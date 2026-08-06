import pandas as pd
import pytest

from pipeline.backtest import backtest


def test_backtest_single_round_trip_no_idle():
    dates = pd.date_range('2020-01-01', periods=3, freq='D')
    df = pd.DataFrame({
        'close': [10.0, 11.0, 12.0],
        'close_raw': [10.0, 11.0, 12.0],
        'signal': [1, 0, -1],
        'sell_reason': ['', '', '涨够了'],
    }, index=dates)

    eq, tr = backtest(df, idle_price=None, initial=100000, comm=0.0)

    assert len(tr) == 2
    assert tr.iloc[0]['action'] == 'BUY'
    assert tr.iloc[1]['action'] == 'SELL'
    assert tr.iloc[1]['pnl_pct'] == pytest.approx((12.0 / 10.0 - 1) * 100)
    assert eq['equity'].iloc[-1] > 100000
