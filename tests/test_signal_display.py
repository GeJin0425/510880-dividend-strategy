import pandas as pd
from pipeline.export import build_signals, build_trades


def test_pending_signal_does_not_require_a_fill():
    dates = pd.date_range('2026-01-01', periods=2)
    data = pd.DataFrame({'close': [10, 11], 'signal': [0, -1],
                         'sell_reason': ['', 'exit']}, index=dates)
    assert build_signals(data) == [dict(date='2026-01-02', action='SELL', close=11.,
                                      reason='exit', pending=True)]


def test_open_trade_export_uses_latest_valuation():
    dates = pd.date_range('2026-01-01', periods=3)
    prices = pd.DataFrame({'close': [10, 12, 13], 'close_raw': [20, 24, 26]}, index=dates)
    buys = pd.DataFrame([dict(signal_date=dates[0], date=dates[1], price=11,
                             price_raw=22, close_price=12, close_price_raw=24)])
    result = build_trades(buys, pd.DataFrame(), prices)[0]
    assert result['sell_close_price_raw'] == 26
    assert result['buy_signal_close_price'] == 10
    assert result['open'] is True
