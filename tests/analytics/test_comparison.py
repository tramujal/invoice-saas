from decimal import Decimal

from app.analytics.comparison import compare_periods
from app.analytics.trend_direction import TrendDirection


class TestComparePeriods:
    def test_growth_reports_up_with_all_four_fields(self):
        result = compare_periods(Decimal("150.00"), Decimal("100.00"))
        assert result.current == Decimal("150.00")
        assert result.previous == Decimal("100.00")
        assert result.absolute_difference == Decimal("50.00")
        assert result.percentage_difference == Decimal("50.00")
        assert result.direction == TrendDirection.up

    def test_decline_reports_down(self):
        result = compare_periods(Decimal("50.00"), Decimal("100.00"))
        assert result.absolute_difference == Decimal("-50.00")
        assert result.percentage_difference == Decimal("-50.00")
        assert result.direction == TrendDirection.down

    def test_no_change_reports_flat(self):
        result = compare_periods(Decimal("100.00"), Decimal("100.00"))
        assert result.absolute_difference == Decimal("0.00")
        assert result.percentage_difference == Decimal("0.00")
        assert result.direction == TrendDirection.flat

    def test_zero_previous_baseline_reports_unknown_direction_not_zero_percent(self):
        result = compare_periods(Decimal("100.00"), Decimal("0"))
        assert result.percentage_difference is None
        assert result.direction == TrendDirection.unknown
        # Absolute difference is still meaningful even without a percentage.
        assert result.absolute_difference == Decimal("100.00")

    def test_both_zero(self):
        result = compare_periods(Decimal("0"), Decimal("0"))
        assert result.absolute_difference == Decimal("0.00")
        assert result.percentage_difference is None
        assert result.direction == TrendDirection.unknown

    def test_never_exposes_only_a_percentage(self):
        # Regression guard for this phase's explicit "do not expose only
        # percentages" requirement -- every field must be independently
        # present and correct.
        result = compare_periods(Decimal("300"), Decimal("200"))
        assert result.current == Decimal("300.00")
        assert result.previous == Decimal("200.00")
        assert result.absolute_difference == Decimal("100.00")
        assert result.percentage_difference == Decimal("50.00")
