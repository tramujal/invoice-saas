"""Canonical time-window resolution for the analytics domain.

Every "revenue this month" / "customers in the last 30 days" style
calculation in this codebase used to compute its own boundaries:
app.routers.dashboard had _month_bounds()/_last_n_month_starts(),
app.services.organization_usage had _current_month_start_utc(), and
app.quote_analytics had its own _month_start() -- three independent,
near-identical re-derivations of "the start of the current UTC calendar
month." This module is the one place that logic lives now; every
calculator in app/analytics/calculators/ resolves its window through
resolve_time_window() rather than computing boundaries itself, the same
way every due-date comparison in this app goes through
app.org_time.get_organization_today() instead of each caller computing
"today" independently.

UTC vs organization-local: calendar-month/quarter/year boundaries stay
UTC-based, matching the existing convention app.services.organization_usage
and app.routers.dashboard already established for "this month" -- changing
that now would silently shift every existing revenue-this-month/usage
figure for an organization outside UTC, a behavior change well outside
this phase's scope. "Today" and "yesterday" use the organization's own
local calendar day instead (via app.org_time.get_organization_today),
since those two windows exist specifically to answer "what happened today,
in the timezone this business actually operates in" -- the same reasoning
app.org_time itself documents for due-date comparisons.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING

from app.org_time import get_organization_today

if TYPE_CHECKING:
    from app.models import Organization


class TimeWindowKind(str, Enum):
    today = "today"
    yesterday = "yesterday"
    last_7_days = "last_7_days"
    last_30_days = "last_30_days"
    current_month = "current_month"
    previous_month = "previous_month"
    current_quarter = "current_quarter"
    current_year = "current_year"
    custom = "custom"


@dataclass(frozen=True)
class TimeWindow:
    """A half-open [start, end) UTC-aware range -- `start` is inclusive,
    `end` is exclusive, matching every existing boundary comparison in
    this codebase (e.g. the old app.routers.dashboard's own `created_at >=
    start, created_at < end`). Never inclusive on both ends: a row landing
    exactly on `end` belongs to the NEXT window, not this one, so
    consecutive windows (e.g. current_month followed by the next month)
    never double-count a boundary row.
    """

    kind: TimeWindowKind
    start: datetime
    end: datetime


def _utc_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _add_months(d: date, months: int) -> date:
    """Returns the first of the month `months` away from `d`'s own month
    (positive or negative). The one place month-carry arithmetic happens
    -- replaces the hand-rolled year/month rollover logic that used to be
    duplicated in app.routers.dashboard._month_bounds and
    _last_n_month_starts. Always called with a day=1 date (every caller in
    this module derives `d` from _month_start()/_quarter_start()), so
    there's never a day-of-month overflow to worry about (e.g. Jan 31 - 1
    month has no ambiguity here)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _quarter_start(d: date) -> date:
    quarter_first_month = ((d.month - 1) // 3) * 3 + 1
    return date(d.year, quarter_first_month, 1)


def resolve_time_window(
    kind: TimeWindowKind,
    *,
    organization: "Organization | None" = None,
    now: datetime | None = None,
    custom_start: datetime | None = None,
    custom_end: datetime | None = None,
) -> TimeWindow:
    """The one function every analytics calculator calls to turn a
    TimeWindowKind into concrete [start, end) boundaries.

    `now` is accepted rather than always reading the clock so tests can
    pin it deterministically -- the same pattern
    app.insights.engine.build_insights already uses for its own `now`
    parameter. `organization` is only consulted for today/yesterday (see
    module docstring); every other window ignores it and is UTC-only.
    """
    moment = now or datetime.now(timezone.utc)

    if kind == TimeWindowKind.custom:
        if custom_start is None or custom_end is None:
            raise ValueError(
                "custom_start and custom_end are required for TimeWindowKind.custom"
            )
        if custom_end <= custom_start:
            raise ValueError("custom_end must be after custom_start")
        return TimeWindow(kind=kind, start=custom_start, end=custom_end)

    if kind in (TimeWindowKind.today, TimeWindowKind.yesterday):
        today_local = get_organization_today(organization)
        anchor = today_local if kind == TimeWindowKind.today else today_local - timedelta(days=1)
        start = _utc_midnight(anchor)
        return TimeWindow(kind=kind, start=start, end=start + timedelta(days=1))

    if kind == TimeWindowKind.last_7_days:
        return TimeWindow(kind=kind, start=moment - timedelta(days=7), end=moment)

    if kind == TimeWindowKind.last_30_days:
        return TimeWindow(kind=kind, start=moment - timedelta(days=30), end=moment)

    if kind == TimeWindowKind.current_month:
        start_date = _month_start(moment.date())
        end_date = _add_months(start_date, 1)
        return TimeWindow(kind=kind, start=_utc_midnight(start_date), end=_utc_midnight(end_date))

    if kind == TimeWindowKind.previous_month:
        this_month_start = _month_start(moment.date())
        start_date = _add_months(this_month_start, -1)
        return TimeWindow(
            kind=kind, start=_utc_midnight(start_date), end=_utc_midnight(this_month_start)
        )

    if kind == TimeWindowKind.current_quarter:
        start_date = _quarter_start(moment.date())
        end_date = _add_months(start_date, 3)
        return TimeWindow(kind=kind, start=_utc_midnight(start_date), end=_utc_midnight(end_date))

    if kind == TimeWindowKind.current_year:
        start_date = date(moment.year, 1, 1)
        end_date = date(moment.year + 1, 1, 1)
        return TimeWindow(kind=kind, start=_utc_midnight(start_date), end=_utc_midnight(end_date))

    raise ValueError(f"Unhandled TimeWindowKind: {kind}")


def trailing_month_starts(n: int, *, now: datetime | None = None) -> list[datetime]:
    """Returns n consecutive UTC month-start datetimes, oldest first,
    ending with the current month -- a drop-in replacement for
    app.routers.dashboard._last_n_month_starts (identical signature and
    semantics), used for month-bucketed trend series such as monthly
    revenue, monthly invoice volume, and monthly quote conversions."""
    moment = now or datetime.now(timezone.utc)
    this_month_start = _month_start(moment.date())
    starts = [_add_months(this_month_start, -offset) for offset in range(n)]
    return [_utc_midnight(d) for d in reversed(starts)]


def trailing_quarter_starts(n: int, *, now: datetime | None = None) -> list[datetime]:
    """Same shape and semantics as trailing_month_starts, one quarter at a
    time (each step is 3 months) -- Phase 16C's quarterly evolution
    series. A quarter is exactly 3 calendar months, so this reuses
    _add_months(..., -offset * 3) rather than introducing a second
    month-carry implementation."""
    moment = now or datetime.now(timezone.utc)
    this_quarter_start = _quarter_start(moment.date())
    starts = [_add_months(this_quarter_start, -offset * 3) for offset in range(n)]
    return [_utc_midnight(d) for d in reversed(starts)]


def trailing_year_starts(n: int, *, now: datetime | None = None) -> list[datetime]:
    """Same shape and semantics as trailing_month_starts, one calendar
    year at a time -- Phase 16C's yearly evolution series."""
    moment = now or datetime.now(timezone.utc)
    this_year = moment.year
    return [_utc_midnight(date(this_year - offset, 1, 1)) for offset in range(n - 1, -1, -1)]


# The 5 comparison kinds this phase's period-comparison feature supports
# (see resolve_period_comparison_windows) -- a deliberately narrower list
# than TimeWindowKind's full 9 values: "today"/"yesterday" are too short
# a span for a meaningful period-over-period business comparison, and
# "previous_month"/"custom" are themselves window selections, not a
# comparison request ("current_month" already implies "vs previous_month").
COMPARISON_KINDS = (
    TimeWindowKind.last_7_days,
    TimeWindowKind.last_30_days,
    TimeWindowKind.current_month,
    TimeWindowKind.current_quarter,
    TimeWindowKind.current_year,
)


def resolve_period_comparison_windows(
    kind: TimeWindowKind, *, organization: "Organization | None" = None, now: datetime | None = None
) -> tuple[TimeWindow, TimeWindow]:
    """Returns (current, previous) -- two equal-length, back-to-back,
    non-overlapping windows for one of COMPARISON_KINDS. This is the one
    place "what counts as the *previous* period" is decided for period
    comparisons, the same centralizing role resolve_time_window already
    plays for single windows -- every trend calculator in
    app.analytics.calculators.trends calls this rather than re-deriving a
    previous-period boundary itself.

    Note on the returned `previous` window's own `.kind` field: for
    current_quarter/current_year there is no TimeWindowKind.previous_
    quarter/year (unlike previous_month, which already existed pre-16C)
    -- rather than widen the enum just for an internal label never
    serialized by any response schema (this function's callers only ever
    read `.start`/`.end`), `previous.kind` is simply set to the same
    `kind` passed in, meaning "a window of this kind's length," not "this
    exact named window." """
    if kind not in COMPARISON_KINDS:
        raise ValueError(
            f"{kind} is not a supported period-comparison kind; must be one of "
            f"{[k.value for k in COMPARISON_KINDS]}"
        )

    moment = now or datetime.now(timezone.utc)

    if kind == TimeWindowKind.last_7_days:
        current = resolve_time_window(kind, now=moment)
        previous = TimeWindow(
            kind=kind, start=current.start - timedelta(days=7), end=current.start
        )
        return current, previous

    if kind == TimeWindowKind.last_30_days:
        current = resolve_time_window(kind, now=moment)
        previous = TimeWindow(
            kind=kind, start=current.start - timedelta(days=30), end=current.start
        )
        return current, previous

    if kind == TimeWindowKind.current_month:
        current = resolve_time_window(kind, now=moment)
        previous = resolve_time_window(TimeWindowKind.previous_month, now=moment)
        return current, previous

    if kind == TimeWindowKind.current_quarter:
        current = resolve_time_window(kind, now=moment)
        previous_start = _add_months(current.start.date(), -3)
        previous = TimeWindow(
            kind=kind, start=_utc_midnight(previous_start), end=current.start
        )
        return current, previous

    if kind == TimeWindowKind.current_year:
        current = resolve_time_window(kind, now=moment)
        previous_start = date(current.start.year - 1, 1, 1)
        previous = TimeWindow(kind=kind, start=_utc_midnight(previous_start), end=current.start)
        return current, previous

    raise ValueError(f"Unhandled comparison kind: {kind}")  # pragma: no cover -- guarded above
