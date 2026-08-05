"""Phase 24.2 -- rolling-origin backtesting and model selection.

"Rolling-origin" (a.k.a. walk-forward) validation: for each candidate
model, repeatedly train on a growing prefix of the real historical
series and score its ONE-STEP-AHEAD prediction against the real next
month that immediately follows -- a model is never evaluated against an
observation it was also fitted on, per this phase's own "never evaluate
on the same observations used for fitting" requirement. This is the
standard way to validate a time-series model without a held-out future
that doesn't exist yet.

Scoring is deliberately done at horizon=1 regardless of which horizon a
caller ultimately wants a forecast for (30/90/180/365 days): a model's
RELATIVE ranking against the other three candidates is a property of how
well it fits this organization's own revenue pattern, not of how far
forecasting.py later extrapolates it, and evaluating at horizon=1 uses
the maximum number of real historical folds available (evaluating at,
say, horizon=6 would need 6x the history just to get a single fold).
"""

from dataclasses import dataclass
from decimal import Decimal

from app.financial_intelligence.models import MIN_HISTORY, ForecastModelName, forecast_with

PERCENT_QUANTIZE = Decimal("0.01")


def _sign(value: Decimal) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


@dataclass(frozen=True)
class ModelEvaluation:
    """Every metric a caller needs to both pick a winner AND show its
    work (the "Forecast Accuracy" / "Model Explanation" frontend
    sections) -- never just a bare "this one is best" verdict.

    `eligible=False` means this model's own MIN_HISTORY floor isn't met
    yet (see app.financial_intelligence.models); `fold_count=0` means the
    floor IS met but there still isn't one extra real observation beyond
    it to validate against -- both are honestly reported, never silently
    skipped."""

    method: ForecastModelName
    eligible: bool
    fold_count: int
    mae: Decimal | None
    wape: Decimal | None
    mape: Decimal | None
    directional_accuracy_percent: Decimal | None


def _evaluate_one_model(method: ForecastModelName, history: list[Decimal]) -> ModelEvaluation:
    min_train = MIN_HISTORY[method.value]
    if len(history) < min_train:
        return ModelEvaluation(
            method=method,
            eligible=False,
            fold_count=0,
            mae=None,
            wape=None,
            mape=None,
            directional_accuracy_percent=None,
        )

    actuals: list[Decimal] = []
    predicteds: list[Decimal] = []
    directional_matches = 0
    directional_folds = 0

    for origin in range(min_train, len(history)):
        train = history[:origin]
        actual = history[origin]
        predicted = forecast_with(method, train, steps=1).values[0]
        actuals.append(actual)
        predicteds.append(predicted)

        prior = train[-1]
        actual_direction = _sign(actual - prior)
        predicted_direction = _sign(predicted - prior)
        if actual_direction != 0:
            # A flat actual (no real change from the prior month) carries
            # no directional signal to grade a prediction against --
            # excluded from the denominator rather than counted as either
            # a hit or a miss.
            directional_folds += 1
            if actual_direction == predicted_direction:
                directional_matches += 1

    fold_count = len(actuals)
    if fold_count == 0:
        return ModelEvaluation(
            method=method, eligible=True, fold_count=0, mae=None, wape=None, mape=None,
            directional_accuracy_percent=None,
        )

    errors = [abs(a - p) for a, p in zip(actuals, predicteds)]
    mae = (sum(errors, Decimal("0")) / Decimal(fold_count)).quantize(PERCENT_QUANTIZE)

    actual_sum = sum((abs(a) for a in actuals), Decimal("0"))
    wape = (
        (sum(errors, Decimal("0")) / actual_sum * 100).quantize(PERCENT_QUANTIZE)
        if actual_sum > 0
        else None
    )

    # MAPE only when every single actual in this fold set is nonzero --
    # per this phase's own "MAPE only when denominator is safe"
    # requirement, never approximated with a fudge-factor denominator.
    mape = None
    if all(a != 0 for a in actuals):
        percent_errors = [abs(a - p) / abs(a) for a, p in zip(actuals, predicteds)]
        mape = (sum(percent_errors, Decimal("0")) / Decimal(fold_count) * 100).quantize(PERCENT_QUANTIZE)

    directional_accuracy = (
        (Decimal(directional_matches) / Decimal(directional_folds) * 100).quantize(PERCENT_QUANTIZE)
        if directional_folds > 0
        else None
    )

    return ModelEvaluation(
        method=method,
        eligible=True,
        fold_count=fold_count,
        mae=mae,
        wape=wape,
        mape=mape,
        directional_accuracy_percent=directional_accuracy,
    )


def evaluate_all_models(history: list[Decimal]) -> list[ModelEvaluation]:
    """Every candidate model's evaluation, eligible or not -- the full
    transparency list for the Forecast Accuracy / Model Explanation
    sections (a user should be able to see not just which model won, but
    why the other three weren't chosen, or weren't even in the running)."""
    return [_evaluate_one_model(method, history) for method in ForecastModelName]


def select_best_model(history: list[Decimal]) -> tuple[ForecastModelName | None, list[ModelEvaluation]]:
    """Evaluates every candidate and returns the winner: the eligible
    model with at least one real backtested fold, lowest WAPE (the
    primary metric -- scale-independent, so it compares fairly across
    organizations of very different revenue sizes), ties broken by MAE.
    Returns (None, evaluations) when no candidate has enough history to
    be validated at all -- forecasting.py treats that as insufficient_data
    for the whole currency, never silently picking an unvalidated model."""
    evaluations = evaluate_all_models(history)
    candidates = [e for e in evaluations if e.eligible and e.fold_count > 0]
    if not candidates:
        return None, evaluations

    def sort_key(e: ModelEvaluation) -> tuple[Decimal, Decimal]:
        wape = e.wape if e.wape is not None else Decimal("Infinity")
        mae = e.mae if e.mae is not None else Decimal("Infinity")
        return (wape, mae)

    best = min(candidates, key=sort_key)
    return best.method, evaluations
