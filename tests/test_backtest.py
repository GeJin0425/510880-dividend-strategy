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


def test_next_open_executes_after_signal_and_marks_to_close():
    dates = pd.date_range('2020-01-01', periods=3, freq='D')
    df = pd.DataFrame({
        'open': [10.0, 8.0, 12.0], 'open_raw': [100.0, 80.0, 120.0],
        'close': [10.0, 10.0, 12.0], 'close_raw': [100.0, 100.0, 120.0],
        'signal': [1, 0, 0], 'buy_level': ['b1', '', ''],
        'sell_reason': ['', '', ''],
    }, index=dates)

    eq, tr = backtest(df, initial=10_000, comm=0, execution_mode='next_open')

    buy = tr.iloc[0]
    assert buy['signal_date'] == dates[0]
    assert buy['date'] == dates[1]
    assert buy['price'] == 8.0
    assert buy['price_raw'] == 80.0
    assert buy['close_price'] == 10.0
    assert eq.loc[dates[1], 'equity'] == 12_400  # 开盘买入后按当日收盘估值


def test_next_open_uses_actual_entry_for_gap_sell_and_switches_idle():
    dates = pd.date_range('2020-01-01', periods=4, freq='D')
    df = pd.DataFrame({
        'open': [10.0, 10.0, 15.0, 15.0], 'open_raw': [10.0, 10.0, 15.0, 15.0],
        'close': [10.0, 12.0, 15.0, 15.0], 'close_raw': [10.0, 12.0, 15.0, 15.0],
        'signal': [1, -1, 0, 0], 'buy_level': ['b1', '', '', ''],
        'sell_reason': ['', 'exit', '', ''],
    }, index=dates)
    idle = pd.DataFrame({
        'open': [100.0, 100.0, 100.0, 100.0],
        'close': [100.0, 100.0, 110.0, 110.0],
    }, index=dates)

    eq, tr = backtest(df, idle_price=idle, initial=10_000, comm=0, execution_mode='next_open')

    sell = tr.iloc[1]
    assert sell['signal_date'] == dates[1]
    assert sell['date'] == dates[2]
    assert sell['price'] == 15.0
    assert sell['pnl_pct'] == pytest.approx(50.0)  # 入场为实际开盘10，而非前日信号收盘
    assert eq.loc[dates[2], 'equity'] == 16_000  # 卖510880后，511260从开盘100估至收盘110


def test_next_open_keeps_last_day_signal_pending_and_rejects_missing_idle_prices():
    dates = pd.date_range('2020-01-01', periods=2, freq='D')
    df = pd.DataFrame({
        'open': [10.0, 10.0], 'open_raw': [10.0, 10.0],
        'close': [10.0, 10.0], 'close_raw': [10.0, 10.0],
        'signal': [0, 1], 'buy_level': ['', 'b2'], 'sell_reason': ['', ''],
    }, index=dates)
    eq, tr = backtest(df, initial=10_000, comm=0, execution_mode='next_open')
    assert tr.empty
    assert (eq['equity'] == 10_000).all()

    idle = pd.DataFrame({'open': [100.0], 'close': [100.0]}, index=dates[:1])
    with pytest.raises(ValueError, match='未对齐或缺失'):
        backtest(df, idle_price=idle, initial=10_000, comm=0, execution_mode='next_open')
