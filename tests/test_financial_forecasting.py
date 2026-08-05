"""Phase 24.2 -- deterministic revenue forecasting.

Covers: forecast model correctness (models.py), rolling-origin backtesting
and model selection, confidence classification, scenario analysis,
currency separation, permission/tenant-isolation enforcement, the plan
capability's SOFT gate (200 + plan_restricted=True, never a 403 -- see
app.financial_intelligence.forecasting's own module docstring), and
insufficient-data honesty. No AI recommendations -- that module doesn't
exist yet in this phase, deliberately.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.financial_intelligence import backtesting, confidence, forecasting, models
from app.schemas import CurrencyCode, InvoiceLineItemCreate
from tests.factories import make_customer, make_invoice, make_org_with_owner_on_plan, mark_invoice_paid


def _fi_org(db, **overrides):
    defaults = dict(advanced_financial_analytics_enabled=True, revenue_forecasting_enabled=True)
    defaults.update(overrides)
    return make_org_with_owner_on_plan(db, **defaults)


_SAFE_FUTURE_DUE_DATE = date.today() + timedelta(days=3650)


def _backdate(db, obj, *, created_at: datetime) -> None:
    obj.created_at = created_at
    db.commit()
    db.refresh(obj)


def _invoice_in_month(db, org, user, *, year: int, month: int, amount: Decimal, customer=None):
    inv = make_invoice(
        db,
        org,
        user,
        customer=customer,
        due_date=_SAFE_FUTURE_DUE_DATE,
        line_items=[InvoiceLineItemCreate(description="x", quantity=Decimal("1"), unit_price=amount)],
    )
    _backdate(db, inv, created_at=datetime(year, month, 15, tzinfo=timezone.utc))
    return inv


def _build_monthly_history(db, org, user, *, now: datetime, months: int, start_amount: Decimal, step: Decimal):
    """Creates one invoice per month, `months` months trailing up to (and
    including) `now`'s calendar month, in strictly increasing amounts --
    a synthetic series with an obvious linear trend, so backtesting.py's
    model selection has a clear, assertable winner."""
    year, month = now.year, now.month
    invoices = []
    for offset in range(months - 1, -1, -1):
        m = month - offset
        y = year
        while m <= 0:
            m += 12
            y -= 1
        amount = start_amount + step * Decimal(months - 1 - offset)
        invoices.append(_invoice_in_month(db, org, user, year=y, month=m, amount=amount))
    return invoices


# --- Pure model math (no DB) ------------------------------------------------


def test_linear_trend_extrapolates_a_perfect_line():
    history = [Decimal(str(1000 + 100 * i)) for i in range(6)]  # 1000..1500
    forecast = models.linear_trend(history, steps=3)
    assert forecast.available
    assert forecast.values == [Decimal("1600.00"), Decimal("1700.00"), Decimal("1800.00")]


def test_rolling_average_is_flat_and_uses_last_window():
    history = [Decimal("100"), Decimal("200"), Decimal("300"), Decimal("900")]
    forecast = models.rolling_average(history, steps=2, window=3)
    # avg(200, 300, 900) = 466.67, repeated for both future steps.
    assert forecast.values == [Decimal("466.67"), Decimal("466.67")]


def test_weighted_moving_average_weighs_recent_periods_more():
    history = [Decimal("100"), Decimal("200"), Decimal("300")]
    forecast = models.weighted_moving_average(history, steps=1, window=3)
    # weights 1,2,3 -> (100*1 + 200*2 + 300*3) / 6 = 233.33
    assert forecast.values == [Decimal("233.33")]


def test_seasonal_naive_repeats_the_same_calendar_month_last_season():
    history = [Decimal(str(i)) for i in range(13)]  # 13 months: 0..12 (the MIN_HISTORY floor)
    forecast = models.seasonal_naive(history, steps=2)
    # step 1 = the value 12 months before it (history[1] = 1);
    # step 2 = history[2] = 2.
    assert forecast.values == [Decimal("1.00"), Decimal("2.00")]


def test_models_report_unavailable_below_their_own_history_floor():
    assert not models.linear_trend([Decimal("1")], steps=1).available
    assert not models.seasonal_naive([Decimal(str(i)) for i in range(11)], steps=1).available
    assert models.seasonal_naive([Decimal(str(i)) for i in range(13)], steps=1).available


# --- Backtesting / model selection ------------------------------------------


def test_select_best_model_picks_linear_trend_for_a_clean_linear_series():
    history = [Decimal(str(1000 + 50 * i)) for i in range(14)]
    method, evaluations = backtesting.select_best_model(history)
    assert method == models.ForecastModelName.linear_trend
    selected = next(e for e in evaluations if e.method == method)
    assert selected.wape == Decimal("0.00")
    assert selected.mae == Decimal("0.00")
    assert selected.directional_accuracy_percent == Decimal("100.00")
    # Every candidate is represented, even the losers -- full transparency.
    assert {e.method for e in evaluations} == set(models.ForecastModelName)


def test_select_best_model_returns_none_with_too_little_history():
    method, evaluations = backtesting.select_best_model([Decimal("100")])
    assert method is None
    assert all(not e.eligible for e in evaluations)


def test_mape_is_none_when_any_actual_is_zero():
    # A history with a real zero-revenue month among the folds' actuals.
    history = [Decimal("100"), Decimal("100"), Decimal("0"), Decimal("100")]
    evaluation = backtesting._evaluate_one_model(models.ForecastModelName.rolling_average, history)
    assert evaluation.mape is None
    # WAPE stays computable (denominator is the SUM of actuals, not each one).
    assert evaluation.wape is not None


# --- Confidence --------------------------------------------------------------


def test_confidence_insufficient_below_minimum_sample():
    assert confidence.classify_confidence(2, Decimal("5")) == confidence.ConfidenceLevel.insufficient_data


def test_confidence_low_with_small_sample_even_with_perfect_backtest():
    assert confidence.classify_confidence(4, Decimal("0")) == confidence.ConfidenceLevel.low


def test_confidence_high_requires_both_large_sample_and_low_error():
    assert confidence.classify_confidence(12, Decimal("10")) == confidence.ConfidenceLevel.high
    # Large sample but poor backtest accuracy never reaches "high."
    assert confidence.classify_confidence(24, Decimal("50")) == confidence.ConfidenceLevel.low


def test_confidence_interval_widens_with_horizon():
    near_lower, near_upper = confidence.confidence_interval(Decimal("1000"), wape=Decimal("10"), steps_ahead=1)
    far_lower, far_upper = confidence.confidence_interval(Decimal("1000"), wape=Decimal("10"), steps_ahead=9)
    assert (far_upper - far_lower) > (near_upper - near_lower)


def test_confidence_interval_never_goes_negative():
    lower, _ = confidence.confidence_interval(Decimal("10"), wape=Decimal("90"), steps_ahead=12)
    assert lower >= Decimal("0")


# --- Revenue forecast section (DB-backed) -----------------------------------


def test_revenue_forecast_insufficient_data_for_a_brand_new_organization(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    response = forecasting.build_revenue_forecast_section(db_session, org.organization.id, now=now)
    assert response.plan_restricted is False
    assert response.results == []  # no currency has any invoiced history at all


def test_revenue_forecast_returns_horizons_for_an_established_organization(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    _build_monthly_history(
        db_session, org.organization, org.user, now=now, months=14, start_amount=Decimal("1000"), step=Decimal("50")
    )

    response = forecasting.build_revenue_forecast_section(db_session, org.organization.id, now=now)
    assert len(response.results) == 1
    result = response.results[0]
    assert result.currency_code == "USD"
    assert result.status == "ok"
    assert result.model is not None
    assert result.confidence != confidence.ConfidenceLevel.insufficient_data
    horizon_days_present = {h.horizon_days for h in result.horizons}
    assert horizon_days_present == {30, 90, 180, 365}  # 14 months -> 365d horizon included
    for h in result.horizons:
        assert h.lower_bound <= h.forecast_value <= h.upper_bound


def test_revenue_forecast_omits_365d_horizon_without_enough_history(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    _build_monthly_history(
        db_session, org.organization, org.user, now=now, months=5, start_amount=Decimal("500"), step=Decimal("10")
    )

    response = forecasting.build_revenue_forecast_section(db_session, org.organization.id, now=now)
    result = response.results[0]
    assert 365 not in {h.horizon_days for h in result.horizons}
    assert {30, 90, 180} <= {h.horizon_days for h in result.horizons}


def test_revenue_forecast_currencies_are_never_mixed(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    _build_monthly_history(
        db_session, org.organization, org.user, now=now, months=6, start_amount=Decimal("1000"), step=Decimal("20")
    )
    # A single EUR invoice -- too little history for a real forecast, but
    # must appear as its OWN insufficient_data currency entry, never
    # merged into USD's numbers.
    eur_invoice = make_invoice(
        db_session,
        org.organization,
        org.user,
        currency_code=CurrencyCode.EUR,
        line_items=[InvoiceLineItemCreate(description="x", quantity=Decimal("1"), unit_price=Decimal("300"))],
    )
    _backdate(db_session, eur_invoice, created_at=now)

    response = forecasting.build_revenue_forecast_section(db_session, org.organization.id, now=now)
    by_code = {r.currency_code: r for r in response.results}
    assert set(by_code) == {"USD", "EUR"}
    assert by_code["USD"].status == "ok"
    assert by_code["EUR"].status == "insufficient_data"
    assert by_code["EUR"].horizons == []


def test_revenue_forecast_soft_gates_when_plan_lacks_forecasting(db_session):
    org = _fi_org(db_session, revenue_forecasting_enabled=False)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    _build_monthly_history(
        db_session, org.organization, org.user, now=now, months=6, start_amount=Decimal("100"), step=Decimal("5")
    )
    response = forecasting.build_revenue_forecast_section(db_session, org.organization.id, now=now)
    assert response.plan_restricted is True
    assert response.results == []  # never fabricates numbers behind a denied plan


# --- Expected collections ----------------------------------------------------


def test_collections_forecast_known_component_reflects_open_invoices(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    today_local = date(2026, 3, 15)
    inv = make_invoice(
        db_session,
        org.organization,
        org.user,
        due_date=_SAFE_FUTURE_DUE_DATE,
        line_items=[InvoiceLineItemCreate(description="x", quantity=Decimal("1"), unit_price=Decimal("500"))],
    )
    _backdate(db_session, inv, created_at=now)
    inv.due_date = today_local + timedelta(days=10)
    db_session.commit()

    response = forecasting.build_collections_forecast_section(db_session, org.organization.id, now=now)
    usd = next(r for r in response.results if r.currency_code == "USD")
    horizon_30 = next(h for h in usd.horizons if h.horizon_days == 30)
    assert horizon_30.known_amount == Decimal("500.00")
    assert horizon_30.total_expected >= horizon_30.known_amount


def test_collections_forecast_falls_back_to_org_average_without_customer_history(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    today_local = date(2026, 3, 15)
    customer = make_customer(db_session, org.organization)

    # Establish an ORG-WIDE payment-delay history (5+ observations, none
    # for this specific customer) so compute_payment_delay_stats(customer_id=...)
    # is honestly unavailable and the org-wide average is used instead.
    for i in range(5):
        paid = make_invoice(
            db_session,
            org.organization,
            org.user,
            line_items=[InvoiceLineItemCreate(description="x", quantity=Decimal("1"), unit_price=Decimal("50"))],
        )
        _backdate(db_session, paid, created_at=now - timedelta(days=60))
        paid.due_date = date(2026, 1, 1)
        db_session.commit()
        mark_invoice_paid(db_session, paid, paid_at=datetime(2026, 1, 21, tzinfo=timezone.utc))  # 20 days late

    overdue = make_invoice(
        db_session,
        org.organization,
        org.user,
        customer=customer,
        due_date=_SAFE_FUTURE_DUE_DATE,
        line_items=[InvoiceLineItemCreate(description="x", quantity=Decimal("1"), unit_price=Decimal("400"))],
    )
    _backdate(db_session, overdue, created_at=now - timedelta(days=40))
    overdue.due_date = today_local - timedelta(days=10)  # 10 days overdue already
    db_session.commit()

    response = forecasting.build_collections_forecast_section(db_session, org.organization.id, now=now)
    usd = next(r for r in response.results if r.currency_code == "USD")
    # Expected date = due_date(-10d) + org avg delay(~20d) = +10d from today
    # -> falls inside the 30-day horizon.
    horizon_30 = next(h for h in usd.horizons if h.horizon_days == 30)
    assert horizon_30.known_amount >= Decimal("400.00")


# --- Monthly projection ------------------------------------------------------


def test_monthly_projection_returns_requested_number_of_points_per_currency(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    _build_monthly_history(
        db_session, org.organization, org.user, now=now, months=6, start_amount=Decimal("100"), step=Decimal("10")
    )
    response = forecasting.build_monthly_projection_section(db_session, org.organization.id, now=now, months=4)
    assert response.months == 4
    usd_points = [p for p in response.points if p.currency_code == "USD"]
    assert len(usd_points) == 4
    assert usd_points[0].month == "2026-04"
    assert usd_points[-1].month == "2026-07"


# --- Forecast accuracy / methods --------------------------------------------


def test_forecast_accuracy_lists_every_model_and_flags_the_selected_one(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    _build_monthly_history(
        db_session, org.organization, org.user, now=now, months=14, start_amount=Decimal("1000"), step=Decimal("50")
    )
    response = forecasting.build_forecast_accuracy_section(db_session, org.organization.id, now=now)
    result = response.results[0]
    assert {e.method for e in result.evaluations} == set(models.ForecastModelName)
    selected_entries = [e for e in result.evaluations if e.selected]
    assert len(selected_entries) == 1
    assert selected_entries[0].method == result.selected_model


def test_forecast_methods_lists_all_four_candidates_with_their_floor(db_session):
    org = _fi_org(db_session)
    response = forecasting.build_forecast_methods_section(db_session, org.organization.id)
    assert {m.method for m in response.methods} == set(models.ForecastModelName)
    # The reported minimum is MIN_HISTORY + 1: backtesting's rolling-origin
    # loop needs one real month STRICTLY BEYOND the model's own fit floor
    # to produce a single validated fold -- see
    # forecasting._min_observations_for_selection's own docstring.
    seasonal = next(m for m in response.methods if m.method == models.ForecastModelName.seasonal_naive)
    assert seasonal.minimum_observations_required == 14
    linear = next(m for m in response.methods if m.method == models.ForecastModelName.linear_trend)
    assert linear.minimum_observations_required == 3


# --- Anomalies ----------------------------------------------------------------


def test_anomaly_flags_a_sharp_revenue_drop(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    _invoice_in_month(db_session, org.organization, org.user, year=2026, month=2, amount=Decimal("1000"))
    _invoice_in_month(db_session, org.organization, org.user, year=2026, month=3, amount=Decimal("200"))  # -80%

    response = forecasting.build_anomalies_section(db_session, org.organization.id, now=now)
    drop_flags = [f for f in response.flags if f.rule == "revenue_drop"]
    assert len(drop_flags) == 1
    assert drop_flags[0].severity == "high"
    assert drop_flags[0].currency_code == "USD"


def test_anomaly_flags_customer_concentration(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    whale = make_customer(db_session, org.organization, name="Whale Co", email="whale@example.com")
    small = make_customer(db_session, org.organization, name="Small Co", email="small@example.com")
    _invoice_in_month(db_session, org.organization, org.user, year=2026, month=1, amount=Decimal("9000"), customer=whale)
    _invoice_in_month(db_session, org.organization, org.user, year=2026, month=1, amount=Decimal("100"), customer=small)

    response = forecasting.build_anomalies_section(db_session, org.organization.id, now=now)
    concentration_flags = [f for f in response.flags if f.rule == "customer_concentration"]
    assert len(concentration_flags) == 1
    assert "Whale Co" in concentration_flags[0].evidence


def test_anomalies_soft_gate_when_plan_lacks_forecasting(db_session):
    org = _fi_org(db_session, revenue_forecasting_enabled=False)
    response = forecasting.build_anomalies_section(db_session, org.organization.id)
    assert response.plan_restricted is True
    assert response.flags == []


# --- Scenario analysis --------------------------------------------------------


def test_optimistic_scenario_forecasts_higher_revenue_than_conservative(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    _build_monthly_history(
        db_session, org.organization, org.user, now=now, months=8, start_amount=Decimal("1000"), step=Decimal("20")
    )

    base = forecasting.evaluate_scenario(db_session, org.organization.id, scenario="base", now=now)
    optimistic = forecasting.evaluate_scenario(db_session, org.organization.id, scenario="optimistic", now=now)
    conservative = forecasting.evaluate_scenario(db_session, org.organization.id, scenario="conservative", now=now)

    def revenue_90d(response):
        result = next(r for r in response.results if r.currency_code == "USD")
        return next(h.forecast_value for h in result.revenue_horizons if h.horizon_days == 90)

    assert revenue_90d(optimistic) > revenue_90d(base) > revenue_90d(conservative)


def test_scenario_never_mutates_stored_invoices(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    _build_monthly_history(
        db_session, org.organization, org.user, now=now, months=6, start_amount=Decimal("500"), step=Decimal("10")
    )
    from app.models import Invoice

    before_count = db_session.query(Invoice).count()
    before_total = sum((inv.total for inv in db_session.query(Invoice).all()), Decimal("0"))

    forecasting.evaluate_scenario(db_session, org.organization.id, scenario="optimistic", now=now)

    after_count = db_session.query(Invoice).count()
    after_total = sum((inv.total for inv in db_session.query(Invoice).all()), Decimal("0"))
    assert after_count == before_count
    assert after_total == before_total


def test_scenario_accepts_custom_assumption_overrides(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    _build_monthly_history(
        db_session, org.organization, org.user, now=now, months=6, start_amount=Decimal("500"), step=Decimal("10")
    )
    custom = forecasting.ScenarioAssumptions(invoice_growth_percent=Decimal("50"))
    response = forecasting.evaluate_scenario(
        db_session, org.organization.id, scenario="base", assumptions=custom, now=now
    )
    assert response.assumptions_used.invoice_growth_percent == Decimal("50")


# --- HTTP layer: permissions, tenant isolation, plan soft-gating -------------


def test_forecast_endpoint_requires_authentication(client, db_session):
    org = _fi_org(db_session, email="fc-auth@example.com")
    response = client.get(f"/organizations/{org.organization.id}/financial-intelligence/forecast/revenue")
    assert response.status_code == 401


def test_forecast_endpoint_rejects_foreign_user(client, db_session):
    org_a = _fi_org(db_session, email="fc-tenant-a@example.com")
    org_b = _fi_org(db_session, email="fc-tenant-b@example.com")
    response = client.get(
        f"/organizations/{org_a.organization.id}/financial-intelligence/forecast/revenue",
        headers=org_b.auth_headers,
    )
    assert response.status_code == 403


def test_forecast_endpoint_soft_gates_never_returns_403_for_plan(client, db_session):
    org = _fi_org(db_session, revenue_forecasting_enabled=False, email="fc-noplan@example.com")
    response = client.get(
        f"/organizations/{org.organization.id}/financial-intelligence/forecast/revenue",
        headers=org.auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["plan_restricted"] is True
    assert body["results"] == []


def test_all_forecast_endpoints_reachable_and_return_200(client, db_session):
    org = _fi_org(db_session, email="fc-endpoints@example.com")
    make_invoice(db_session, org.organization, org.user)

    for path in (
        "forecast/revenue",
        "forecast/collections",
        "forecast/monthly-projection",
        "forecast/summary",
        "forecast/accuracy",
        "forecast/methods",
        "forecast/anomalies",
    ):
        response = client.get(
            f"/organizations/{org.organization.id}/financial-intelligence/{path}", headers=org.auth_headers
        )
        assert response.status_code == 200, f"{path} -> {response.status_code}: {response.text}"

    scenario_response = client.post(
        f"/organizations/{org.organization.id}/financial-intelligence/forecast/scenario",
        json={"scenario": "optimistic"},
        headers=org.auth_headers,
    )
    assert scenario_response.status_code == 200


def test_forecast_tenant_isolation_never_crosses_organizations(client, db_session):
    org_a = _fi_org(db_session, email="fc-iso-a@example.com")
    org_b = _fi_org(db_session, email="fc-iso-b@example.com")
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    _build_monthly_history(
        db_session, org_a.organization, org_a.user, now=now, months=14, start_amount=Decimal("9000"), step=Decimal("100")
    )

    response = client.get(
        f"/organizations/{org_b.organization.id}/financial-intelligence/forecast/revenue",
        headers=org_b.auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["results"] == []  # org_b has no invoices of its own
