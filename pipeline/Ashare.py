# ruff: noqa: N999  # Preserve the upstream Ashare import path
"""Sina-first quotes with a Tencent fallback and a raw-OHLC contract.

Adapted from https://github.com/mpquant/Ashare. Neither provider is allowed to
return adjusted prices: dividend adjustment belongs exclusively to fetch.py.
"""
import numpy as np
import pandas as pd
import requests

SINA_URL = 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
TENCENT_DAY_URL = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
TENCENT_MIN_URL = 'https://ifzq.gtimg.cn/appstock/app/kline/mkline'
REQUEST_TIMEOUT = 20
OHLC = ['open', 'close', 'high', 'low']


def _date_string(value):
    return pd.Timestamp(value).strftime('%Y-%m-%d') if value else ''


def _raw_frame(rows, columns, *, provider, code, frequency, endpoint, count,
               end_date='', volume_multiplier=1):
    if not rows:
        raise ValueError(f'{provider}: empty quote response')
    frame = pd.DataFrame(rows, columns=columns)
    date_column = columns[0]
    frame[date_column] = pd.to_datetime(frame[date_column], errors='raise')
    frame = frame.set_index(date_column)
    frame.index.name = ''
    frame = frame[['open', 'close', 'high', 'low', 'volume']].astype(float)
    if not frame.index.is_unique:
        raise ValueError(f'{provider}: duplicate quote dates')
    frame = frame.sort_index()
    if end_date:
        frame = frame.loc[frame.index <= pd.Timestamp(end_date)]
    frame = frame.tail(count).copy()
    if frame.empty or not np.isfinite(frame.to_numpy()).all():
        raise ValueError(f'{provider}: empty or non-finite OHLCV')
    if (frame[OHLC] <= 0).any().any() or (frame['volume'] < 0).any():
        raise ValueError(f'{provider}: invalid OHLCV')
    if ((frame['low'] > frame[OHLC].min(axis=1)) |
            (frame['high'] < frame[OHLC].max(axis=1))).any():
        raise ValueError(f'{provider}: inconsistent OHLC bounds')
    frame['volume'] *= volume_multiplier
    frame.attrs.update(
        price_basis='raw', provider=provider, symbol=code, frequency=frequency,
        endpoint=endpoint, volume_unit='shares', requested_count=count,
        returned_count=len(frame), source_start_date=frame.index[0].strftime('%Y-%m-%d'),
        as_of_date=frame.index[-1].strftime('%Y-%m-%d'),
    )
    return frame


def get_price_day_tx(code, end_date='', count=10, frequency='1d'):
    """Request unadjusted Tencent OHLCV; reject qfq-only responses.

    Tencent's daily volume is in 100-share lots; normalize to shares.
    """
    unit = {'1d': 'day', '1w': 'week', '1M': 'month'}[frequency]
    end = _date_string(end_date)
    response = requests.get(
        TENCENT_DAY_URL, params={'param': f'{code},{unit},,{end},{count},'},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get('code', 0) != 0:
        raise ValueError(f'Tencent: {payload.get("msg", "quote request failed")}')
    stock = payload['data'][code]
    if unit not in stock:
        raise ValueError(f'Tencent: raw {unit} missing; adjusted response is unsafe')
    return _raw_frame(
        stock[unit], ['time', 'open', 'close', 'high', 'low', 'volume'],
        provider='Tencent', code=code, frequency=frequency, endpoint=TENCENT_DAY_URL,
        count=count, end_date=end, volume_multiplier=100,
    )


def get_price_min_tx(code, end_date=None, count=10, frequency='1m'):
    minutes = int(frequency[:-1])
    response = requests.get(
        TENCENT_MIN_URL, params={'param': f'{code},m{minutes},,{count}'},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    rows = response.json()['data'][code]['m' + str(minutes)]
    return _raw_frame(
        rows, ['time', 'open', 'close', 'high', 'low', 'volume', 'n1', 'n2'],
        provider='Tencent', code=code, frequency=frequency, endpoint=TENCENT_MIN_URL,
        count=count, end_date=_date_string(end_date), volume_multiplier=100,
    )


def get_price_sina(code, end_date='', count=10, frequency='60m'):
    scale = {'1d': 240, '1w': 1200, '1M': 7200}.get(frequency)
    if scale is None:
        scale = int(frequency[:-1])
    end = _date_string(end_date)
    requested = count
    if end and frequency in {'1d', '1w', '1M'}:
        unit = {'1d': 1, '1w': 4, '1M': 29}[frequency]
        days = (pd.Timestamp.now(tz='Asia/Shanghai').date() - pd.Timestamp(end).date()).days
        requested += max(0, days // unit)
    response = requests.get(
        SINA_URL, params={'symbol': code, 'scale': scale, 'ma': 5, 'datalen': requested},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return _raw_frame(
        response.json(), ['day', 'open', 'high', 'low', 'close', 'volume'],
        provider='Sina', code=code, frequency=frequency, endpoint=SINA_URL,
        count=count, end_date=end,
    )


def get_price(code, end_date='', count=10, frequency='1d', fields=None):
    """Return raw quotes, including provider and price-basis provenance in attrs."""
    if count < 1:
        raise ValueError('count must be positive')
    xcode = code.replace('.XSHG', '').replace('.XSHE', '')
    xcode = 'sh' + xcode if 'XSHG' in code else 'sz' + xcode if 'XSHE' in code else code
    if frequency == '1m':
        return get_price_min_tx(xcode, end_date=end_date, count=count, frequency=frequency)
    if frequency not in {'1d', '1w', '1M', '5m', '15m', '30m', '60m'}:
        raise ValueError(f'unsupported frequency: {frequency}')
    try:
        return get_price_sina(xcode, end_date=end_date, count=count, frequency=frequency)
    except (requests.RequestException, ValueError, KeyError, TypeError) as primary_error:
        fallback = get_price_day_tx if frequency in {'1d', '1w', '1M'} else get_price_min_tx
        frame = fallback(xcode, end_date=end_date, count=count, frequency=frequency)
        frame.attrs['fallback_from'] = 'Sina'
        frame.attrs['fallback_reason'] = type(primary_error).__name__
        return frame
