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


def test_backtest_applies_min_commission():
    dates = pd.date_range('2020-01-01', periods=3, freq='D')
    df = pd.DataFrame({
        'close': [10.0, 11.0, 12.0],
        'close_raw': [10.0, 11.0, 12.0],
        'signal': [1, 0, -1],
        'sell_reason': ['', '', '涨够了'],
    }, index=dates)

    eq, tr = backtest(df, idle_price=None, initial=10000, comm=0.0, min_comm=1.0)

    # 买入: 10000 - 1(最低佣金) 可买 900 股, 再扣1元最低佣金
    assert tr.iloc[0]['shares'] == 900
    # 卖出: 剩余现金999 + 900*12 - 1(最低佣金) = 11798
    assert eq['equity'].iloc[-1] == 11798


def test_backtest_can_delay_signal_execution():
    dates = pd.date_range('2020-01-01', periods=4, freq='D')
    df = pd.DataFrame({
        'close': [10.0, 11.0, 12.0, 13.0],
        'close_raw': [10.0, 11.0, 12.0, 13.0],
        'signal': [1, 0, -1, 0],
        'buy_level': ['b2', '', '', ''],
        'sell_reason': ['', '', 'exit', ''],
    }, index=dates)

    _, tr = backtest(df, idle_price=None, initial=100000, comm=0.0, signal_lag=1)

    assert tr.iloc[0]['date'] == dates[1]
    assert tr.iloc[0]['price'] == 11.0
    assert tr.iloc[0]['buy_level'] == 'b2'
    assert tr.iloc[1]['date'] == dates[3]
    assert tr.iloc[1]['reason'] == 'exit'
