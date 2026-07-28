from decimal import Decimal

from app.analytics.primitives import growth_percent, quantize_money


class TestQuantizeMoney:
    def test_rounds_to_two_decimal_places(self):
        # Decimal's default context rounds half-to-even (banker's
        # rounding), so 10.005 -> 10.00 (0 is already even) -- these two
        # cases are unambiguous either way, avoiding that edge entirely.
        assert quantize_money(Decimal("10.006")) == Decimal("10.01")
        assert quantize_money(Decimal("10")) == Decimal("10.00")


class TestGrowthPercent:
    def test_positive_growth(self):
        assert growth_percent(Decimal("150"), Decimal("100")) == Decimal("50.00")

    def test_negative_growth(self):
        assert growth_percent(Decimal("50"), Decimal("100")) == Decimal("-50.00")

    def test_no_change(self):
        assert growth_percent(Decimal("100"), Decimal("100")) == Decimal("0.00")

    def test_zero_previous_baseline_returns_none(self):
        assert growth_percent(Decimal("100"), Decimal("0")) is None

    def test_negative_previous_baseline_returns_none(self):
        assert growth_percent(Decimal("100"), Decimal("-5")) is None
