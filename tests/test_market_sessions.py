import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from pipeline import market_sessions
from pipeline.market_sessions import (
    CalendarUnavailableError,
    last_closed_sse_session,
    sse_sessions,
    validate_sse_frame,
)


@pytest.fixture(autouse=True)
def clear_calendar_cache():
    market_sessions._sse_calendar.cache_clear()
    yield
    market_sessions._sse_calendar.cache_clear()


def _frame(dates):
    return pd.DataFrame({"close": 1.0}, index=pd.DatetimeIndex(dates))


@pytest.mark.parametrize("now, expected", [
    ("2026-09-30 14:59:59+08:00", "2026-09-29"),
    ("2026-09-30 15:00:00+08:00", "2026-09-30"),
    ("2026-09-30 07:00:00+00:00", "2026-09-30"),
    ("2026-09-25 17:00:00+08:00", "2026-09-24"),
    ("2026-09-27 17:00:00+08:00", "2026-09-24"),
    ("2026-09-28 14:59:59+08:00", "2026-09-24"),
    ("2026-09-28 15:00:00+08:00", "2026-09-28"),
    ("2026-10-01 09:00:00+08:00", "2026-09-30"),
    ("2026-10-07 17:00:00+08:00", "2026-09-30"),
    ("2026-10-08 14:59:59+08:00", "2026-09-30"),
    ("2026-10-08 15:00:00+08:00", "2026-10-08"),
    ("2026-10-10 17:00:00+08:00", "2026-10-09"),
    ("2026-01-02 17:00:00+08:00", "2025-12-31"),
    ("2026-02-23 17:00:00+08:00", "2026-02-13"),
    ("2026-02-24 15:00:00+08:00", "2026-02-24"),
])
def test_last_closed_session_uses_exchange_holidays_and_shanghai_close(now, expected):
    assert last_closed_sse_session(pd.Timestamp(now)) == pd.Timestamp(expected)


@pytest.mark.parametrize("now", ["2026-10-01", pd.NaT])
def test_last_closed_session_rejects_ambiguous_or_missing_now(now):
    with pytest.raises(ValueError, match="timezone-aware"):
        last_closed_sse_session(now)


def test_calendar_matches_every_day_of_official_2026_schedule():
    # Independent expected closure periods from the SSE annual notice. Include
    # government weekend make-up workdays to prove they remain exchange-closed.
    closures = set()
    for start, end in [
        ("2026-01-01", "2026-01-04"),
        ("2026-02-14", "2026-02-23"),
        ("2026-04-04", "2026-04-06"),
        ("2026-05-01", "2026-05-05"),
        ("2026-06-19", "2026-06-21"),
        ("2026-09-25", "2026-09-27"),
        ("2026-10-01", "2026-10-07"),
    ]:
        closures.update(pd.date_range(start, end))
    closures.update(pd.to_datetime([
        "2026-02-28", "2026-05-09", "2026-09-20", "2026-10-10",
    ]))
    expected = pd.DatetimeIndex([
        day for day in pd.date_range("2026-01-01", "2026-12-31")
        if day.dayofweek < 5 and day not in closures
    ])
    actual = sse_sessions("2026-01-01", "2026-12-31")
    assert actual.equals(expected)
    assert len(actual) == 242
    assert sse_sessions("2026-10-01", "2026-10-07").empty


@pytest.mark.parametrize("start", ["2013-01-04", "2017-08-24"])
def test_complete_historical_etf_frames_pass(start):
    dates = sse_sessions(start, "2026-09-30")
    frame = _frame(dates)
    original = frame.copy(deep=True)
    assert validate_sse_frame(frame, "ETF", now=pd.Timestamp(
        "2026-10-01T00:30:00+08:00",
    )) == pd.Timestamp("2026-09-30")
    pd.testing.assert_frame_equal(frame, original)


def test_historical_holidays_and_makeup_weekends_are_not_sessions():
    assert sse_sessions("2013-01-01", "2013-01-07").tolist() == [
        pd.Timestamp("2013-01-04"), pd.Timestamp("2013-01-07"),
    ]
    assert sse_sessions("2017-09-29", "2017-10-09").tolist() == [
        pd.Timestamp("2017-09-29"), pd.Timestamp("2017-10-09"),
    ]


def test_shanghai_midnight_aware_index_is_accepted():
    frame = _frame(sse_sessions("2026-09-28", "2026-09-30"))
    frame.index = frame.index.tz_localize("Asia/Shanghai")
    validate_sse_frame(frame, now=pd.Timestamp("2026-10-01T00:00:00+08:00"))


@pytest.mark.parametrize("dates, message", [
    ([], "empty"),
    (["2026-09-28", "2026-09-29"], "stale.*2026-09-30"),
    (["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-08"], "future"),
    (["2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30"], "non-session.*2026-09-25"),
    (["2026-09-26", "2026-09-28", "2026-09-29", "2026-09-30"], "non-session.*2026-09-26"),
    (["2026-09-28", "2026-09-29", "2026-09-29", "2026-09-30"], "duplicate"),
    (["2026-09-28", "2026-09-30"], "missing trading dates.*2026-09-29"),
    (["2026-09-29", "2026-09-28", "2026-09-30"], "increasing"),
    (["2026-09-28", None, "2026-09-30"], "NaT"),
    (["2026-09-28 01:00", "2026-09-29", "2026-09-30"], "intraday"),
])
def test_invalid_frames_fail_without_repair(dates, message):
    with pytest.raises(ValueError, match=message):
        validate_sse_frame(_frame(dates), "510880", now=pd.Timestamp(
            "2026-10-01T00:30:00+08:00",
        ))


def test_current_session_row_is_rejected_before_close():
    with pytest.raises(ValueError, match="not-yet-closed.*2026-09-30"):
        validate_sse_frame(
            _frame(["2026-09-29", "2026-09-30"]),
            now=pd.Timestamp("2026-09-30T14:59:59+08:00"),
        )


def test_string_index_cannot_be_silently_interpreted_as_dates():
    frame = pd.DataFrame({"close": [1]}, index=["2026-09-30"])
    with pytest.raises(TypeError, match="DatetimeIndex"):
        validate_sse_frame(frame, now=pd.Timestamp("2026-10-01T00:00:00+08:00"))


@pytest.mark.parametrize("start, end", [
    ("1998-12-31", "1999-01-05"),
    ("2026-12-31", "2027-01-01"),
])
def test_unknown_calendar_ranges_fail_closed(start, end):
    with pytest.raises(CalendarUnavailableError, match="unsupported"):
        sse_sessions(start, end)


def test_future_current_year_fails_even_if_prior_years_are_known():
    with pytest.raises(CalendarUnavailableError, match="unsupported"):
        last_closed_sse_session(pd.Timestamp("2027-01-01T00:00:00+08:00"))


def test_missing_dependency_never_falls_back_to_weekdays(monkeypatch):
    monkeypatch.setitem(sys.modules, "exchange_calendars", None)
    with pytest.raises(CalendarUnavailableError, match="dependency.*weekday fallback"):
        sse_sessions("2026-09-28", "2026-09-30")


def test_incorrect_library_holidays_fail_closed(monkeypatch):
    import exchange_calendars

    real_calendar = exchange_calendars.get_calendar(
        "XSHG", start="1999-01-01", end="2026-12-31",
    )
    incorrect = SimpleNamespace(
        sessions_in_range=lambda start, end: real_calendar.sessions_in_range(
            start, end,
        ).union(pd.DatetimeIndex(["2026-09-25"])),
    )
    monkeypatch.setattr(exchange_calendars, "get_calendar", lambda *a, **kw: incorrect)
    with pytest.raises(CalendarUnavailableError, match="official 2026 holidays"):
        sse_sessions("2026-09-28", "2026-09-30")


def test_unsupported_dependency_calendar_fails_closed(monkeypatch):
    import exchange_calendars

    def unsupported_calendar(*args, **kwargs):
        raise ValueError("XSHG holidays are only recorded through 2025")

    monkeypatch.setattr(exchange_calendars, "get_calendar", unsupported_calendar)
    with pytest.raises(CalendarUnavailableError, match="unsupported.*weekday fallback"):
        sse_sessions("2026-09-28", "2026-09-30")


def test_unreviewed_close_time_fails_closed(monkeypatch):
    import exchange_calendars

    real_calendar = exchange_calendars.get_calendar(
        "XSHG", start="1999-01-01", end="2026-12-31",
    )
    schedule = real_calendar.schedule.copy()
    schedule.loc[pd.Timestamp("2026-09-30"), "close"] += pd.Timedelta(minutes=1)
    incorrect = SimpleNamespace(
        sessions_in_range=real_calendar.sessions_in_range,
        sessions=real_calendar.sessions,
        schedule=schedule,
    )
    monkeypatch.setattr(exchange_calendars, "get_calendar", lambda *a, **kw: incorrect)
    with pytest.raises(CalendarUnavailableError, match="unreviewed close time"):
        last_closed_sse_session(pd.Timestamp("2026-10-01T00:00:00+08:00"))


@pytest.mark.parametrize("start", ["2013-01-04", "2017-08-24"])
def test_historical_interior_gap_is_rejected(start):
    dates = sse_sessions(start, "2026-09-30")
    missing_date = dates[500]
    with pytest.raises(ValueError, match=f"missing trading dates.*{missing_date:%Y-%m-%d}"):
        validate_sse_frame(_frame(dates.delete(500)), now=pd.Timestamp(
            "2026-10-01T00:00:00+08:00",
        ))


@pytest.mark.parametrize("start, end, message", [
    ("2026-09-30", "2026-09-29", "after end"),
    ("2026-09-30 09:30", "2026-09-30", "midnight"),
    (pd.NaT, "2026-09-30", "NaT"),
    (1, "2026-09-30", "number"),
])
def test_invalid_session_ranges_are_rejected(start, end, message):
    with pytest.raises((ValueError, TypeError), match=message):
        sse_sessions(start, end)
