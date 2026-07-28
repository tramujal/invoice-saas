from decimal import Decimal

from app.analytics.forecast import (
    ForecastMethod,
    forecast_linear_trend,
    forecast_next_period,
    forecast_simple_moving_average,
    forecast_weighted_moving_average,
)


class TestSimpleMovingAverage:
    def test_averages_the_last_window_values(self):
        history = [Decimal("100"), Decimal("120"), Decimal("140")]
        result = forecast_simple_moving_average(history, window=3)
        assert result.available is True
        assert result.method == ForecastMethod.simple_moving_average
        assert result.forecast_value == Decimal("120.00")
        assert result.inputs == history
        assert result.window_size == 3

    def test_uses_fewer_than_window_when_history_is_shorter(self):
        history = [Decimal("100"), Decimal("200")]
        result = forecast_simple_moving_average(history, window=3)
        assert result.available is True
        assert result.forecast_value == Decimal("150.00")
        assert result.window_size == 2

    def test_only_uses_the_trailing_window_slice(self):
        history = [Decimal("0"), Decimal("100"), Decimal("120"), Decimal("140")]
        result = forecast_simple_moving_average(history, window=3)
        assert result.inputs == [Decimal("100"), Decimal("120"), Decimal("140")]
        assert result.forecast_value == Decimal("120.00")

    def test_unavailable_with_fewer_than_two_points(self):
        result = forecast_simple_moving_average([Decimal("100")])
        assert result.available is False
        assert result.forecast_value is None
        assert result.method is None
        assert result.reason is not None

    def test_unavailable_with_empty_history(self):
        result = forecast_simple_moving_average([])
        assert result.available is False
        assert result.inputs == []


class TestWeightedMovingAverage:
    def test_weights_recent_periods_more_heavily(self):
        # weights 1,2,3 -> (100*1 + 120*2 + 140*3) / 6 = (100+240+420)/6 = 126.666...
        history = [Decimal("100"), Decimal("120"), Decimal("140")]
        result = forecast_weighted_moving_average(history, window=3)
        assert result.available is True
        assert result.method == ForecastMethod.weighted_moving_average
        assert result.forecast_value == Decimal("126.67")

    def test_differs_from_simple_average_when_trend_exists(self):
        history = [Decimal("100"), Decimal("120"), Decimal("140")]
        sma = forecast_simple_moving_average(history, window=3)
        wma = forecast_weighted_moving_average(history, window=3)
        assert wma.forecast_value > sma.forecast_value  # weights the rising trend more

    def test_unavailable_with_fewer_than_two_points(self):
        result = forecast_weighted_moving_average([Decimal("50")])
        assert result.available is False


class TestLinearTrend:
    def test_fits_an_exact_line_through_two_points(self):
        # y = 100 + 20x -> next point (x=2) should be 140
        history = [Decimal("100"), Decimal("120")]
        result = forecast_linear_trend(history)
        assert result.available is True
        assert result.method == ForecastMethod.linear_trend
        assert result.forecast_value == Decimal("140.00")
        assert result.window_size is None
        assert result.inputs == history

    def test_fits_a_perfect_linear_series(self):
        # y = 100 + 10x for x=0..3 -> next point (x=4) is 140
        history = [Decimal("100"), Decimal("110"), Decimal("120"), Decimal("130")]
        result = forecast_linear_trend(history)
        assert result.forecast_value == Decimal("140.00")

    def test_flat_history_forecasts_the_same_value(self):
        history = [Decimal("100"), Decimal("100"), Decimal("100")]
        result = forecast_linear_trend(history)
        assert result.forecast_value == Decimal("100.00")

    def test_unavailable_with_fewer_than_two_points(self):
        result = forecast_linear_trend([Decimal("100")])
        assert result.available is False

    def test_uses_full_history_not_a_window(self):
        history = [Decimal(str(v)) for v in range(1, 11)]  # 1..10, y = x+1
        result = forecast_linear_trend(history)
        assert result.inputs == history
        assert result.window_size is None


class TestForecastNextPeriodDispatch:
    def test_dispatches_to_simple_moving_average_by_default(self):
        history = [Decimal("100"), Decimal("120"), Decimal("140")]
        result = forecast_next_period(history)
        assert result.method == ForecastMethod.simple_moving_average

    def test_dispatches_to_weighted_moving_average(self):
        history = [Decimal("100"), Decimal("120"), Decimal("140")]
        result = forecast_next_period(history, method=ForecastMethod.weighted_moving_average)
        assert result.method == ForecastMethod.weighted_moving_average

    def test_dispatches_to_linear_trend(self):
        history = [Decimal("100"), Decimal("120"), Decimal("140")]
        result = forecast_next_period(history, method=ForecastMethod.linear_trend)
        assert result.method == ForecastMethod.linear_trend
