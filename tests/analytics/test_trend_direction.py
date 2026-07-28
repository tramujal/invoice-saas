from decimal import Decimal

from app.analytics.trend_direction import TrendDirection, direction_from_percent


class TestDirectionFromPercent:
    def test_positive_above_threshold_is_up(self):
        assert direction_from_percent(Decimal("5.0")) == TrendDirection.up

    def test_negative_above_threshold_is_down(self):
        assert direction_from_percent(Decimal("-5.0")) == TrendDirection.down

    def test_small_positive_is_flat(self):
        assert direction_from_percent(Decimal("0.5")) == TrendDirection.flat

    def test_small_negative_is_flat(self):
        assert direction_from_percent(Decimal("-0.5")) == TrendDirection.flat

    def test_zero_is_flat(self):
        assert direction_from_percent(Decimal("0")) == TrendDirection.flat

    def test_none_is_unknown_not_flat(self):
        assert direction_from_percent(None) == TrendDirection.unknown

    def test_exactly_at_threshold_is_not_flat(self):
        # abs(value) < threshold is flat; == threshold clears it.
        assert direction_from_percent(Decimal("1")) == TrendDirection.up
        assert direction_from_percent(Decimal("-1")) == TrendDirection.down

    def test_custom_flat_threshold(self):
        assert direction_from_percent(Decimal("3"), flat_threshold=Decimal("5")) == TrendDirection.flat
        assert direction_from_percent(Decimal("6"), flat_threshold=Decimal("5")) == TrendDirection.up
