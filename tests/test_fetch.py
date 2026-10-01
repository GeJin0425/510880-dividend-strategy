import numpy as np
import pandas as pd
import pytest
import requests

import pipeline.Ashare as ashare
from pipeline.fetch import (
    DIVIDENDS_510880,
    DIVIDENDS_511260,
    apply_qfq,
    fetch_510880_qfq,
    fetch_511260_close,
    fetch_511260_qfq,
)


def test_apply_qfq_single_dividend():
    dates = pd.to_datetime(['2020-01-15', '2020-01-16', '2020-01-17', '2020-01-20'])
    df = pd.DataFrame({
        'open':  [10.0, 10.0, 10.0, 10.2],
        'close': [10.0, 10.0, 10.0, 10.2],
        'high':  [10.1, 10.1, 10.1, 10.3],
        'low':   [9.9, 9.9, 9.9, 10.1],
        'volume': [1000, 1000, 1000, 1000],
    }, index=dates)
    df.attrs['price_basis'] = 'raw'
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

    fixture.attrs['price_basis'] = 'raw'

    def fake_get_price(code, frequency='1d', count=10):
        assert code == 'sh510880'
        return fixture

    monkeypatch.setattr('pipeline.fetch.get_price', fake_get_price)
    out = fetch_510880_qfq(count=5)

    assert list(out.columns) == [
        'open', 'close', 'high', 'low', 'volume',
        'open_raw', 'close_raw', 'high_raw', 'low_raw', 'adjust_factor',
    ]
    assert len(out) == 5


def test_fetch_511260_close_returns_qfq_close_series(monkeypatch):
    dates = pd.to_datetime(['2025-09-19', '2025-09-22', '2025-09-23', '2025-09-24'])
    fixture = pd.DataFrame({
        'open': [135.0] * 4, 'close': [135.0, 136.0, 134.0, 134.5],
        'high': [136.0] * 4, 'low': [133.0] * 4, 'volume': [100] * 4,
    }, index=dates)

    fixture.attrs['price_basis'] = 'raw'

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


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


@pytest.mark.parametrize('code,ex_date,cash', [
    ('sh510880', date, cash) for date, cash in DIVIDENDS_510880
] + [
    ('sh511260', date, cash) for date, cash in DIVIDENDS_511260
])
def test_forced_tencent_fallback_has_same_raw_and_once_adjusted_prices(monkeypatch, code, ex_date, cash):
    ex = pd.Timestamp(ex_date)
    dates = [ex - pd.Timedelta(days=1), ex, ex + pd.Timedelta(days=1)]
    previous = 10.0 if code == 'sh510880' else 136.0
    close = [previous, previous - cash, previous - cash + .1]
    rows = [{'day': date.strftime('%Y-%m-%d'), 'open': price, 'close': price,
             'high': price + .1, 'low': price - .1, 'volume': 10000}
            for date, price in zip(dates, close)]

    def primary(url, params, timeout):
        assert timeout > 0
        assert params['symbol'] == code
        return _Response(rows)

    monkeypatch.setattr(ashare.requests, 'get', primary)
    sina = ashare.get_price(code, count=3)

    def fallback(url, params, timeout):
        if url == ashare.SINA_URL:
            raise requests.ConnectionError('force fallback')
        assert url == ashare.TENCENT_DAY_URL
        assert params['param'] == f'{code},day,,,3,'  # no qfq/hfq request
        return _Response({'code': 0, 'data': {code: {'day': [
            [row['day'], row['open'], row['close'], row['high'], row['low'], 100]
            for row in rows
        ]}}})

    monkeypatch.setattr(ashare.requests, 'get', fallback)
    raw = ashare.get_price(code, count=3)
    pd.testing.assert_frame_equal(raw, sina, check_names=False)
    assert raw.attrs['provider'] == 'Tencent'
    assert raw.attrs['price_basis'] == 'raw'
    assert raw.attrs['fallback_from'] == 'Sina'
    monkeypatch.setattr('pipeline.fetch.get_price', lambda *args, **kwargs: raw)
    monkeypatch.setattr('pipeline.fetch.DIVIDENDS_510880', [(ex_date, cash)])
    monkeypatch.setattr('pipeline.fetch.DIVIDENDS_511260', [(ex_date, cash)])
    adjusted = fetch_510880_qfq(3) if code == 'sh510880' else fetch_511260_qfq(3)
    reference = apply_qfq(sina, [(ex_date, cash)])
    pd.testing.assert_frame_equal(adjusted, reference, check_names=False)
    for column in ashare.OHLC:
        np.testing.assert_array_equal(adjusted[column + '_raw'], raw[column])
    assert adjusted.iloc[0]['close'] == round(previous - cash, 3)
    assert adjusted.loc[ex, 'close'] == round(previous - cash, 3)
    assert adjusted.attrs['price_basis'] == 'qfq'
    assert adjusted.attrs['raw_price_basis'] == 'raw'


def test_tencent_rejects_adjusted_only_payload(monkeypatch):
    monkeypatch.setattr(ashare.requests, 'get', lambda *args, **kwargs: _Response({
        'code': 0, 'data': {'sh511260': {'qfqday': [
            ['2026-09-17', 134., 134., 135., 133., 100.],
        ]}},
    }))
    with pytest.raises(ValueError, match='raw day missing'):
        ashare.get_price_day_tx('sh511260')


@pytest.mark.parametrize('basis', [None, 'qfq', 'hfq'])
def test_adjustment_requires_raw_contract(basis):
    frame = _raw_fixture(['2026-09-17', '2026-09-18'])
    if basis is None:
        frame.attrs.clear()
    else:
        frame.attrs['price_basis'] = basis
    with pytest.raises(ValueError, match='explicitly raw'):
        apply_qfq(frame, [('2026-09-18', 1.2747)])


def _raw_fixture(dates):
    frame = pd.DataFrame({
        'open': 136., 'close': 136., 'high': 136.1, 'low': 135.9, 'volume': 10000.,
    }, index=pd.to_datetime(dates))
    frame.attrs['price_basis'] = 'raw'
    return frame


def test_future_dividend_does_not_adjust_earlier_snapshot():
    raw = _raw_fixture(['2026-09-16', '2026-09-17'])
    adjusted = apply_qfq(raw, [('2026-09-18', 1.2747)])
    assert (adjusted.adjust_factor == 1).all()
    np.testing.assert_array_equal(adjusted.close, raw.close)


def test_missing_ex_session_rejected_instead_of_nearest_date():
    raw = _raw_fixture(['2026-09-17', '2026-09-21'])
    with pytest.raises(ValueError, match='missing ex-dividend price session'):
        apply_qfq(raw, [('2026-09-18', 1.2747)])


def test_dividend_amount_and_exact_adjustment_factor():
    assert ('2026-09-18', 1.2747) in DIVIDENDS_511260
    raw = _raw_fixture(['2026-09-17', '2026-09-18'])
    result = apply_qfq(raw, [('2026-09-18', 1.2747)])
    assert result.adjust_factor.iloc[0] == round((136. - 1.2747) / 136., 6)
    assert result.adjust_factor.iloc[1] == 1
    with pytest.raises(ValueError, match='explicitly raw'):
        apply_qfq(result, [('2026-09-18', 1.2747)])
