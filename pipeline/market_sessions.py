"""Offline SSE session/freshness guards for daily market-data frames.

XSHG comes from exchange_calendars, rather than a Chinese civil/workday
calendar: weekend make-up workdays are *not* exchange sessions. Its precomputed
holiday coverage is bounded, and this module deliberately fails closed outside
the reviewed 1999--2026 range. Update/review the dependency and these guards when
SSE publishes a new year's calendar; never extrapolate using ordinary weekdays.

2026 calendar sources, checked against exchange_calendars 4.13.2:
https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml
https://www.sse.com.cn/disclosure/announcement/general/c/c_20260915_10832273.shtml
Upstream calendar:
https://github.com/gerrymanoim/exchange_calendars/blob/4.13.2/exchange_calendars/exchange_calendar_xshg.py
"""

from functools import lru_cache

import pandas as pd

SHANGHAI_TZ = "Asia/Shanghai"
CALENDAR_START = pd.Timestamp("1999-01-01")
CALENDAR_END = pd.Timestamp("2026-12-31")

# Weekday closures from SSE's annual notice. Weekends are independently closed,
# including the government's make-up workdays; those are not extra sessions.
SSE_HOLIDAYS_2026 = (
    "2026-01-01", "2026-01-02",
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19",
    "2026-02-20", "2026-02-23", "2026-04-06",
    "2026-05-01", "2026-05-04", "2026-05-05", "2026-06-19",
    "2026-09-25", "2026-10-01", "2026-10-02", "2026-10-05",
    "2026-10-06", "2026-10-07",
)


class CalendarUnavailableError(ValueError):
    """No reviewed SSE calendar is available for the requested date range."""


@lru_cache(maxsize=1)
def _sse_calendar():
    try:
        import exchange_calendars
    except ImportError as exc:
        raise CalendarUnavailableError(
            "SSE calendar unavailable: install the reviewed exchange_calendars "
            "dependency from requirements.txt; refusing a weekday fallback"
        ) from exc

    try:
        calendar = exchange_calendars.get_calendar(
            "XSHG", start=CALENDAR_START, end=CALENDAR_END,
        )
        actual = calendar.sessions_in_range("2026-01-01", "2026-12-31")
        # This weekday construction is an *audit* against the complete official
        # 2026 holiday list, not a fallback calendar for unknown years.
        expected = pd.bdate_range("2026-01-01", "2026-12-31").difference(
            pd.DatetimeIndex(SSE_HOLIDAYS_2026),
        )
        if not actual.equals(expected):
            raise CalendarUnavailableError(
                "SSE calendar disagrees with the verified official 2026 holidays"
            )
        if (calendar.sessions.dayofweek >= 5).any():
            raise CalendarUnavailableError("SSE calendar contains weekend sessions")
        closes = calendar.schedule["close"].dt.tz_convert(SHANGHAI_TZ)
        if not (
            (closes.dt.hour == 15) & (closes.dt.minute == 0)
            & (closes.dt.second == 0) & (closes.dt.microsecond == 0)
            & (closes.dt.nanosecond == 0)
        ).all():
            raise CalendarUnavailableError("SSE calendar has an unreviewed close time")
        return calendar
    except CalendarUnavailableError:
        raise
    except Exception as exc:
        raise CalendarUnavailableError(
            "SSE calendar unavailable or unsupported; refusing a weekday fallback"
        ) from exc


def _session_date(value):
    """Parse a date label without silently discarding an intraday time."""
    if isinstance(value, (int, float)):
        raise TypeError("SSE session date must be a date, not a number")
    try:
        day = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid SSE session date") from exc
    if pd.isna(day):
        raise ValueError("Invalid SSE session date: NaT")
    if day.tzinfo is not None:
        day = day.tz_convert(SHANGHAI_TZ).tz_localize(None)
    if day != day.normalize():
        raise ValueError("SSE session dates must be midnight date labels")
    return day


def _check_calendar_bounds(start, end):
    if start < CALENDAR_START or end > CALENDAR_END:
        raise CalendarUnavailableError(
            f"SSE calendar unsupported for {start:%Y-%m-%d}..{end:%Y-%m-%d}; "
            f"reviewed coverage is {CALENDAR_START:%Y-%m-%d}..{CALENDAR_END:%Y-%m-%d}"
        )


def sse_sessions(start, end):
    """Return timezone-naive Shanghai session dates in an inclusive range.

    Empty holiday/weekend-only ranges are valid. Unknown calendar years raise
    CalendarUnavailableError instead of synthesizing business days.
    """
    start, end = _session_date(start), _session_date(end)
    if start > end:
        raise ValueError("SSE session range start must not be after end")
    _check_calendar_bounds(start, end)
    sessions = _sse_calendar().sessions
    return sessions[(sessions >= start) & (sessions <= end)].copy()


def last_closed_sse_session(now=None):
    """Return the last session closed by ``now`` (15:00 Asia/Shanghai).

    ``now`` defaults to the current Shanghai time. Inject a timezone-aware
    datetime/Timestamp for deterministic tests; naive values are rejected to
    avoid confusing UTC with Shanghai. A session is closed exactly at 15:00.
    """
    current = pd.Timestamp.now(tz=SHANGHAI_TZ) if now is None else pd.Timestamp(now)
    if pd.isna(current) or current.tzinfo is None:
        raise ValueError("now must be a valid timezone-aware timestamp")
    current = current.tz_convert(SHANGHAI_TZ)
    today = current.tz_localize(None).normalize()
    _check_calendar_bounds(today, today)
    calendar = _sse_calendar()
    position = calendar.schedule["close"].searchsorted(
        current.tz_convert("UTC"), side="right",
    ) - 1
    if position < 0:
        raise CalendarUnavailableError("No closed SSE session within reviewed coverage")
    return calendar.sessions[position]


def _date_list(dates):
    preview = ", ".join(day.strftime("%Y-%m-%d") for day in dates[:5])
    return preview + (f" (+{len(dates) - 5} more)" if len(dates) > 5 else "")


def validate_sse_frame(frame, label="market data", *, now=None):
    """Reject unusable daily data and return its required last closed session.

    Validates the entire original index before any alignment/filtering. The
    index must contain unique, increasing midnight session dates and every SSE
    session from its first date through the last closed session. Shanghai-aware
    midnight indexes are also accepted. No rows are dropped, sorted or filled.
    This checks freshness/continuity, not price or volume values.
    """
    if not isinstance(frame, (pd.DataFrame, pd.Series)):
        raise TypeError(f"{label}: expected a pandas market-data frame or series")
    if frame.empty:
        raise ValueError(f"{label}: empty market-data frame")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError(f"{label}: index must be a DatetimeIndex of SSE session dates")
    dates = frame.index
    if dates.hasnans:
        raise ValueError(f"{label}: invalid NaT session date")
    if dates.tz is not None:
        dates = dates.tz_convert(SHANGHAI_TZ).tz_localize(None)
    if not dates.equals(dates.normalize()):
        raise ValueError(f"{label}: intraday timestamps are not daily session dates")
    if dates.has_duplicates:
        duplicates = dates[dates.duplicated()].unique()
        raise ValueError(f"{label}: duplicate session dates: {_date_list(duplicates)}")
    if not dates.is_monotonic_increasing:
        raise ValueError(f"{label}: session dates must be increasing")

    expected_last = last_closed_sse_session(now)
    _check_calendar_bounds(dates.min(), dates.max())
    all_sessions = _sse_calendar().sessions
    non_sessions = dates.difference(all_sessions)
    if len(non_sessions):
        raise ValueError(f"{label}: non-session dates: {_date_list(non_sessions)}")
    future = dates[dates > expected_last]
    if len(future):
        raise ValueError(
            f"{label}: future or not-yet-closed session dates: {_date_list(future)}; "
            f"expected last closed SSE session {expected_last:%Y-%m-%d}"
        )
    if dates[-1] != expected_last:
        raise ValueError(
            f"{label}: stale data ends {dates[-1]:%Y-%m-%d}; "
            f"expected last closed SSE session {expected_last:%Y-%m-%d}"
        )
    missing = sse_sessions(dates[0], expected_last).difference(dates)
    if len(missing):
        raise ValueError(f"{label}: missing trading dates: {_date_list(missing)}")
    return expected_last
