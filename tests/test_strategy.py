import pandas as pd

from pipeline.strategy import PARAMS, run_strategy


def _row(close, ma250, rsi, ma10=None, slope=0.1):
    dev = (close - ma250) / ma250 * 100
    return dict(
        close=close, ma250=ma250, deviation=dev, rsi=rsi,
        ma10=ma10 if ma10 is not None else close, ma250_slope=slope,
    )


def test_run_strategy_extreme_buy_then_hard_sell():
    rows = [_row(100, 100, 50) for _ in range(3)]  # 平盘期，above_ma10不成立，不会误触发L3买入
    rows.append(_row(97, 100, 50))    # dev=-3% < b1(-2%) -> L1买入
    rows.append(_row(118, 100, 50))   # dev=18% >= s1(16%) -> 硬上限卖出
    df = pd.DataFrame(rows)

    out = run_strategy(df, p=PARAMS)

    assert out['signal'].iloc[3] == 1
    assert out['buy_level'].iloc[3] == 'b1'
    assert out['signal'].iloc[4] == -1
    assert '硬上限' in out['sell_reason'].iloc[4]
    assert out['position'].iloc[4] == 0
    assert out['position'].iloc[3] == 1


def test_flow_rule_can_veto_but_not_create_an_entry():
    rows = [_row(100, 100, 50) for _ in range(3)]
    rows.append({**_row(97, 100, 50), 'share_flow_20': -0.01})
    rows.append({**_row(97, 100, 50), 'share_flow_20': 0.01})
    df = pd.DataFrame(rows)

    out = run_strategy(df, p=PARAMS, flow_rule={'share_flow_20': 0.0})

    assert out['signal'].iloc[3] == 0
    assert out['signal'].iloc[4] == 1


def test_next_open_s4pr_uses_actual_open_entry_price():
    rows = [_row(100, 100, 50) for _ in range(3)]
    rows.append({**_row(97, 100, 80), 'open': 97})  # T 日收盘买入信号
    rows.append({**_row(95, 100, 60), 'open': 90})  # T+1 跳空低开成交，收盘盈利并RSI下穿
    df = pd.DataFrame(rows)
    df['open'] = df['open'].fillna(df['close'])

    out = run_strategy(df, p=PARAMS, execution_mode='next_open')

    assert out['signal'].iloc[3] == 1
    assert out['signal'].iloc[4] == -1
    assert 'RSI下穿' in out['sell_reason'].iloc[4]
