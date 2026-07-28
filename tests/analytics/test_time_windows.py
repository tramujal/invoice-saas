"""app.analytics.time_windows -- the one place window boundaries are
computed. Every test here is pure (no db_session needed) except the
today/yesterday cases, which need an Organization row for
get_organization_today's timezone lookup.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.analytics.time_windows import (
    COMPARISON_KINDS,
    TimeWindowKind,
    resolve_period_comparison_windows,
    resolve_time_window,
    trailing_month_starts,
    trailing_quarter_starts,
    trailing_year_starts,
)
from tests.factories import make_organization


class TestResolveTimeWindow:
    def test_today_is_org_local_midnight_to_midnight(self, db_session):
        # today/yesterday resolve through app.org_time.get_organization_today,
        # which always reads the real system clock (no `now` override
        # exists there) -- so `now=` has no effect on this branch, and
        # these assertions are built from the real clock rather than a
        # pinned literal, matching that constraint honestly instead of
        # pretending the window can be pinned when it can't.
        org = make_organization(db_session, name="Today Org")
        window = resolve_time_window(TimeWindowKind.today, organization=org)
        assert window.end - window.start == timedelta(days=1)
        assert window.start.time() == datetime.min.time()

    def test_yesterday_is_one_day_before_today(self, db_session):
        org = make_organization(db_session, name="Yesterday Org")
        today_window = resolve_time_window(TimeWindowKind.today, organization=org)
        yesterday_window = resolve_time_window(TimeWindowKind.yesterday, organization=org)
        assert yesterday_window.end == today_window.start
        assert yesterday_window.start == today_window.start - timedelta(days=1)

    def test_last_7_days_is_a_rolling_window_ending_now(self):
        now = datetime(2026, 3, 15, 10, 30, tzinfo=timezone.utc)
        window = resolve_time_window(TimeWindowKind.last_7_days, now=now)
        assert window.end == now
        assert window.start == now - timedelta(days=7)

    def test_last_30_days_is_a_rolling_window_ending_now(self):
        now = datetime(2026, 3, 15, 10, 30, tzinfo=timezone.utc)
        window = resolve_time_window(TimeWindowKind.last_30_days, now=now)
        assert window.end == now
        assert window.start == now - timedelta(days=30)

    def test_current_month_spans_the_whole_calendar_month(self):
        now = datetime(2026, 3, 15, tzinfo=timezone.utc)
        window = resolve_time_window(TimeWindowKind.current_month, now=now)
        assert window.start == datetime(2026, 3, 1, tzinfo=timezone.utc)
        assert window.end == datetime(2026, 4, 1, tzinfo=timezone.utc)

    def test_current_month_handles_december_to_january_rollover(self):
        now = datetime(2026, 12, 15, tzinfo=timezone.utc)
        window = resolve_time_window(TimeWindowKind.current_month, now=now)
        assert window.start == datetime(2026, 12, 1, tzinfo=timezone.utc)
        assert window.end == datetime(2027, 1, 1, tzinfo=timezone.utc)

    def test_previous_month_is_the_full_prior_calendar_month(self):
        now = datetime(2026, 3, 15, tzinfo=timezone.utc)
        window = resolve_time_window(TimeWindowKind.previous_month, now=now)
        assert window.start == datetime(2026, 2, 1, tzinfo=timezone.utc)
        assert window.end == datetime(2026, 3, 1, tzinfo=timezone.utc)

    def test_previous_month_handles_january_to_december_rollback(self):
        now = datetime(2026, 1, 15, tzinfo=timezone.utc)
        window = resolve_time_window(TimeWindowKind.previous_month, now=now)
        assert window.start == datetime(2025, 12, 1, tzinfo=timezone.utc)
        assert window.end == datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_current_quarter_spans_three_months(self):
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)  # Q2: Apr-Jun
        window = resolve_time_window(TimeWindowKind.current_quarter, now=now)
        assert window.start == datetime(2026, 4, 1, tzinfo=timezone.utc)
        assert window.end == datetime(2026, 7, 1, tzinfo=timezone.utc)

    def test_current_quarter_handles_q4_year_rollover(self):
        now = datetime(2026, 11, 1, tzinfo=timezone.utc)  # Q4: Oct-Dec
        window = resolve_time_window(TimeWindowKind.current_quarter, now=now)
        assert window.start == datetime(2026, 10, 1, tzinfo=timezone.utc)
        assert window.end == datetime(2027, 1, 1, tzinfo=timezone.utc)

    def test_current_year_spans_the_whole_calendar_year(self):
        now = datetime(2026, 7, 4, tzinfo=timezone.utc)
        window = resolve_time_window(TimeWindowKind.current_year, now=now)
        assert window.start == datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert window.end == datetime(2027, 1, 1, tzinfo=timezone.utc)

    def test_custom_window_uses_the_given_bounds(self):
        start = datetime(2026, 1, 5, tzinfo=timezone.utc)
        end = datetime(2026, 1, 20, tzinfo=timezone.utc)
        window = resolve_time_window(TimeWindowKind.custom, custom_start=start, custom_end=end)
        assert window.start == start
        assert window.end == end

    def test_custom_window_requires_both_bounds(self):
        with pytest.raises(ValueError):
            resolve_time_window(TimeWindowKind.custom, custom_start=datetime.now(timezone.utc))

    def test_custom_window_rejects_end_before_start(self):
        start = datetime(2026, 1, 20, tzinfo=timezone.utc)
        end = datetime(2026, 1, 5, tzinfo=timezone.utc)
        with pytest.raises(ValueError):
            resolve_time_window(TimeWindowKind.custom, custom_start=start, custom_end=end)


class TestTrailingMonthStarts:
    def test_returns_n_months_oldest_first_ending_with_current(self):
        now = datetime(2026, 3, 15, tzinfo=timezone.utc)
        starts = trailing_month_starts(3, now=now)
        assert starts == [
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 2, 1, tzinfo=timezone.utc),
            datetime(2026, 3, 1, tzinfo=timezone.utc),
        ]

    def test_handles_year_rollover(self):
        now = datetime(2026, 2, 1, tzinfo=timezone.utc)
        starts = trailing_month_starts(4, now=now)
        assert starts == [
            datetime(2025, 11, 1, tzinfo=timezone.utc),
            datetime(2025, 12, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 2, 1, tzinfo=timezone.utc),
        ]


class TestTrailingQuarterStarts:
    def test_returns_n_quarters_oldest_first_ending_with_current(self):
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)  # Q3
        starts = trailing_quarter_starts(3, now=now)
        assert starts == [
            datetime(2026, 1, 1, tzinfo=timezone.utc),  # Q1
            datetime(2026, 4, 1, tzinfo=timezone.utc),  # Q2
            datetime(2026, 7, 1, tzinfo=timezone.utc),  # Q3
        ]

    def test_handles_year_rollover(self):
        now = datetime(2026, 2, 1, tzinfo=timezone.utc)  # Q1 2026
        starts = trailing_quarter_starts(2, now=now)
        assert starts == [
            datetime(2025, 10, 1, tzinfo=timezone.utc),  # Q4 2025
            datetime(2026, 1, 1, tzinfo=timezone.utc),  # Q1 2026
        ]


class TestTrailingYearStarts:
    def test_returns_n_years_oldest_first_ending_with_current(self):
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        starts = trailing_year_starts(3, now=now)
        assert starts == [
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        ]


class TestResolvePeriodComparisonWindows:
    def test_current_month_vs_previous_month(self):
        now = datetime(2026, 3, 15, tzinfo=timezone.utc)
        current, previous = resolve_period_comparison_windows(TimeWindowKind.current_month, now=now)
        assert current.start == datetime(2026, 3, 1, tzinfo=timezone.utc)
        assert current.end == datetime(2026, 4, 1, tzinfo=timezone.utc)
        assert previous.start == datetime(2026, 2, 1, tzinfo=timezone.utc)
        assert previous.end == datetime(2026, 3, 1, tzinfo=timezone.utc)

    def test_current_quarter_vs_previous_quarter(self):
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)  # Q2
        current, previous = resolve_period_comparison_windows(TimeWindowKind.current_quarter, now=now)
        assert current.start == datetime(2026, 4, 1, tzinfo=timezone.utc)
        assert current.end == datetime(2026, 7, 1, tzinfo=timezone.utc)
        assert previous.start == datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert previous.end == datetime(2026, 4, 1, tzinfo=timezone.utc)

    def test_current_year_vs_previous_year(self):
        now = datetime(2026, 7, 4, tzinfo=timezone.utc)
        current, previous = resolve_period_comparison_windows(TimeWindowKind.current_year, now=now)
        assert current.start == datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert current.end == datetime(2027, 1, 1, tzinfo=timezone.utc)
        assert previous.start == datetime(2025, 1, 1, tzinfo=timezone.utc)
        assert previous.end == datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_last_7_days_vs_previous_7_days(self):
        now = datetime(2026, 3, 15, 10, tzinfo=timezone.utc)
        current, previous = resolve_period_comparison_windows(TimeWindowKind.last_7_days, now=now)
        assert current.end == now
        assert current.start == now - timedelta(days=7)
        assert previous.end == current.start
        assert previous.start == now - timedelta(days=14)

    def test_last_30_days_vs_previous_30_days(self):
        now = datetime(2026, 3, 15, 10, tzinfo=timezone.utc)
        current, previous = resolve_period_comparison_windows(TimeWindowKind.last_30_days, now=now)
        assert current.end == now
        assert current.start == now - timedelta(days=30)
        assert previous.end == current.start
        assert previous.start == now - timedelta(days=60)

    def test_windows_never_overlap(self):
        now = datetime(2026, 3, 15, tzinfo=timezone.utc)
        for kind in COMPARISON_KINDS:
            current, previous = resolve_period_comparison_windows(kind, now=now)
            assert previous.end == current.start

    def test_rejects_unsupported_kind(self):
        now = datetime(2026, 3, 15, tzinfo=timezone.utc)
        with pytest.raises(ValueError):
            resolve_period_comparison_windows(TimeWindowKind.today, now=now)
        with pytest.raises(ValueError):
            resolve_period_comparison_windows(TimeWindowKind.previous_month, now=now)
        with pytest.raises(ValueError):
            resolve_period_comparison_windows(TimeWindowKind.custom, now=now)
