import json

import numpy as np
import pandas as pd

import pipeline.export as export_mod


def _build_fixture():
    # 总长度需 >= export.py 的 400 条最小史长哨兵检查（见 export() 里的截断保护）
    dates = pd.date_range('2018-01-01', periods=410, freq='D')
    prices = np.concatenate([
        np.full(300, 100.0),               # 平盘，喂饱MA250与资金流热身期
        [95.0],                             # 急跌 -> 偏离度<-2% 触发L1买入
        np.linspace(96.0, 118.0, 19),        # 连续拉升
        np.full(90, 118.0),                 # 高位横盘
    ])
    df = pd.DataFrame({
        'open': prices, 'close': prices, 'high': prices, 'low': prices,
        'volume': np.full(410, 1_000_000.0),
        'close_raw': prices, 'high_raw': prices, 'low_raw': prices,
        'adjust_factor': np.ones(410),
    }, index=dates)
    idle = pd.Series(np.full(410, 100.0), index=dates)
    shares = np.exp(np.arange(410) * 0.0005 + np.sin(np.arange(410) / 11) * 0.01)
    scale = pd.DataFrame({'scale_yi': shares * prices}, index=dates)
    return df, idle, scale


def test_export_end_to_end(tmp_path, monkeypatch):
    fixture_df, fixture_idle, fixture_scale = _build_fixture()
    monkeypatch.setattr(export_mod, 'fetch_510880_qfq', lambda count=3000: fixture_df)
    monkeypatch.setattr(export_mod, 'fetch_511260_close', lambda count=2500: fixture_idle)
    monkeypatch.setattr(export_mod, 'fetch_sse_scale_history', lambda fund_code='510880': fixture_scale)
    # 跳过前250+天MA250热身期，避免展示窗口内出现NaN
    monkeypatch.setattr(export_mod, 'DISPLAY_START', fixture_df.index[255].strftime('%Y-%m-%d'))

    out_path = tmp_path / 'data.json'
    payload = export_mod.export(str(out_path))

    assert out_path.exists()
    reloaded = json.loads(out_path.read_text(encoding='utf-8'))
    assert reloaded == payload

    assert payload['meta']['trade_count'] >= 1
    assert len(payload['trades']) >= 1
    assert payload['trades'][0]['sell_reason']
    assert payload['current_status']['date'] == fixture_df.index[-1].strftime('%Y-%m-%d')
    for key in ('dates', 'close', 'ma250', 'rsi14', 'macd', 'equity_strategy'):
        assert key in payload['series']
        assert len(payload['series'][key]) == len(payload['series']['dates'])
    assert 'NaN' not in out_path.read_text(encoding='utf-8')


def test_build_current_status_sell_signal_triggered():
    dates = pd.date_range('2020-01-01', periods=1)
    df2 = pd.DataFrame({
        'close_raw': [10.7], 'deviation': [7.5], 'rsi': [80.0], 'rsi6': [82.0],
        'ma250': [10.0], 'ma250_slope': [0.3], 'signal': [-1],
        'sell_reason': ['RSI确认'], 'share_flow_5': [0.01],
        'share_flow_20': [0.02], 'flow_z20': [0.5],
    }, index=dates)
    status = export_mod.build_current_status(df2, latest_position=1)
    assert status['holding'] is True
    assert status['signal_level'] == 'sell'
    assert '卖出信号触发' in status['signal_text']
    assert '下一交易日执行' in status['signal_text']


def test_build_current_status_idle_buy_triggered():
    dates = pd.date_range('2020-01-01', periods=1)
    df2 = pd.DataFrame({
        'close_raw': [9.7], 'deviation': [-3.0], 'rsi': [30.0], 'rsi6': [28.0],
        'ma250': [10.0], 'ma250_slope': [-0.1], 'signal': [1],
        'buy_level': ['b1'], 'share_flow_5': [-0.01],
        'share_flow_20': [-0.02], 'flow_z20': [-0.5],
    }, index=dates)
    status = export_mod.build_current_status(df2, latest_position=0)
    assert status['holding'] is False
    assert status['signal_level'] == 'buy'
    assert status['signal_text'] == 'b1信号触发 | 下一交易日执行'


def test_build_sell_reason_breakdown_groups_by_tier():
    sells = pd.DataFrame([
        {'reason': '硬上限:15.0%', 'pnl_pct': 8.0},
        {'reason': 'RSI确认:RSI=80,偏离8.0%', 'pnl_pct': 6.0},
        {'reason': 'RSI确认:RSI=76,偏离9.0%', 'pnl_pct': 4.0},
    ])
    breakdown = export_mod.build_sell_reason_breakdown(sells)
    by_reason = {b['reason']: b for b in breakdown}
    assert by_reason['RSI确认']['count'] == 2
    assert by_reason['RSI确认']['avg_pnl_pct'] == 5.0
    assert by_reason['硬上限']['count'] == 1
