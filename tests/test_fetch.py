import pandas as pd

from pipeline.fetch import apply_qfq, fetch_510880_qfq, fetch_511260_close


def test_apply_qfq_single_dividend():
    dates = pd.to_datetime(['2020-01-15', '2020-01-16', '2020-01-17', '2020-01-20'])
    df = pd.DataFrame({
        'open':  [10.0, 10.0, 10.0, 10.2],
        'close': [10.0, 10.0, 10.0, 10.2],
        'high':  [10.1, 10.1, 10.1, 10.3],
        'low':   [9.9, 9.9, 9.9, 10.1],
        'volume': [1000, 1000, 1000, 1000],
    }, index=dates)
    dividends = [('2020-01-17', 0.20)]

    out = apply_qfq(df, dividends)

    assert out.loc['2020-01-17', 'adjust_factor'] == 1.0
    assert out.loc['2020-01-17', 'close'] == 10.0
    assert out.loc['2020-01-20', 'close'] == 10.2

    expected_factor = round((10.0 - 0.20) / 10.0, 6)
    assert out.loc['2020-01-15', 'adjust_factor'] == expected_factor
    assert out.loc['2020-01-15', 'close'] == round(10.0 * expected_factor, 3)

    assert out.loc['2020-01-15', 'close_raw'] == 10.0
    assert out.loc['2020-01-20', 'close_raw'] == 10.2


def test_fetch_510880_qfq_applies_dividends(monkeypatch):
    dates = pd.date_range('2018-01-01', periods=5, freq='D')
    fixture = pd.DataFrame({
        'open': [1.0] * 5, 'close': [1.0] * 5,
        'high': [1.0] * 5, 'low': [1.0] * 5,
        'volume': [100] * 5,
    }, index=dates)

    def fake_get_price(code, frequency='1d', count=10):
        assert code == 'sh510880'
        return fixture

    monkeypatch.setattr('pipeline.fetch.get_price', fake_get_price)
    out = fetch_510880_qfq(count=5)

    assert list(out.columns) == [
        'open', 'close', 'high', 'low', 'volume',
        'close_raw', 'high_raw', 'low_raw', 'adjust_factor',
    ]
    assert len(out) == 5


def test_fetch_511260_close_returns_qfq_close_series(monkeypatch):
    dates = pd.to_datetime(['2025-09-19', '2025-09-22', '2025-09-23', '2025-09-24'])
    fixture = pd.DataFrame({
        'open': [135.0] * 4, 'close': [135.0, 136.0, 134.0, 134.5],
        'high': [136.0] * 4, 'low': [133.0] * 4, 'volume': [100] * 4,
    }, index=dates)

    def fake_get_price(code, frequency='1d', count=10):
        assert code == 'sh511260'
        return fixture

    monkeypatch.setattr('pipeline.fetch.get_price', fake_get_price)
    monkeypatch.setattr('pipeline.fetch.DIVIDENDS_511260', [('2025-09-23', 1.36)])
    out = fetch_511260_close(count=4)

    # 除息日当天不复权; 除息日前按 (136-1.36)/136 = 0.99 前复权
    assert out.loc['2025-09-23'] == 134.0
    assert out.loc['2025-09-22'] == round(136.0 * 0.99, 3)
    assert out.loc['2025-09-19'] == round(135.0 * 0.99, 3)
