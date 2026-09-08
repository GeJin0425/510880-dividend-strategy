import pandas as pd
import pytest
from pipeline.event_engine import simulate


def fixture():
    dates = pd.bdate_range('2026-01-01', periods=5)
    return pd.DataFrame(dict(open=[100, 97, 90, 100, 100], close=[100, 97, 95, 100, 100],
                             open_raw=[100, 97, 90, 100, 100], close_raw=[100, 97, 95, 100, 100],
                             ma250=[100]*5, ma10=[100]*5, deviation=[0, -3, -5, 0, 0],
                             ma250_slope=[0]*5, rsi=[50, 80, 60, 50, 50]), index=dates)


def test_real_fill_changes_s4_and_final_order_is_not_filled():
    data = fixture()
    sig, eq, fills = simulate(data, initial=100000, comm=0, min_comm=0)
    assert sig.signal.iloc[2] == -1
    assert fills.iloc[0].price == 90
    assert fills.iloc[1].date == data.index[3]
    assert eq.shares.iloc[1] == 0
    _, _, pending = simulate(data.iloc[:2])
    assert pending.empty


def test_insufficient_cash_does_not_create_phantom_position_or_fee():
    sig, eq, fills = simulate(fixture(), initial=100, comm=0, min_comm=.5)
    assert fills.empty
    assert not sig.position.any()
    assert (eq.cash == 100).all()


def test_slippage_is_used_by_s4_not_just_deducted_as_fee():
    sig, _, fills = simulate(fixture(), slippage_bps=300)
    assert fills.iloc[0].price == pytest.approx(92.7)
    assert sig.signal.iloc[2] == 0  # 95/92.7 < 3.5%, while 95/90 > 3.5%


def test_future_prices_do_not_change_past_signals_or_equity():
    data = fixture()
    full_sig, full_eq, _ = simulate(data)
    prefix_sig, prefix_eq, _ = simulate(data.iloc[:3])
    pd.testing.assert_series_equal(prefix_sig.signal, full_sig.signal.iloc[:3])
    pd.testing.assert_frame_equal(prefix_eq, full_eq.iloc[:3])


def test_half_entry_reduces_actual_units():
    _, full, _ = simulate(fixture(), comm=0, min_comm=0)
    _, half, _ = simulate(fixture(), allocation='b1_half', comm=0, min_comm=0)
    assert half.shares.iloc[2] < full.shares.iloc[2]
    assert half.cash.iloc[2] > full.cash.iloc[2]
