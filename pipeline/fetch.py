import numpy as np
import pandas as pd

from .Ashare import get_price

DIVIDENDS_510880 = [
    ('2026-01-21', 0.1430),
    ('2025-01-21', 0.1420),
    ('2024-01-23', 0.1310),
    ('2023-01-16', 0.1380),
    ('2022-01-17', 0.0860),
    ('2021-01-18', 0.1410),
    ('2020-01-17', 0.1440),
    ('2019-01-16', 0.0980),
    ('2018-01-23', 0.1090),
    ('2017-01-23', 0.0910),
    ('2016-01-20', 0.0500),
    ('2015-01-20', 0.0800),
    ('2014-01-21', 0.0590),
]

# 511260十年国债ETF历次(除息日, 每份分红金额)记录。
# 该ETF 2017年成立, 2025年9月起才开始现金分红。
DIVIDENDS_511260 = [
    ('2025-09-23', 1.3600),
    ('2025-12-26', 0.8330),
    ('2026-03-25', 0.6711),
    ('2026-06-25', 1.2686),
    # Fund announcement 2026-09-15: 12.747 CNY per 10 units; ex-date Sep 18.
    # https://money.finance.sina.com.cn/fund/go.php/vAkFundInfo_JJGKXX/q/5553065.phtml
    ('2026-09-18', 1.2747),
]


def apply_qfq(df, dividends):
    """对不复权日线做前复权调整，并保留可与券商报价核对的原始 OHLC。"""
    if df.attrs.get('price_basis') != 'raw':
        raise ValueError('apply_qfq requires explicitly raw OHLC; adjusted/unknown input is unsafe')
    if df.empty or not isinstance(df.index, pd.DatetimeIndex) or not df.index.is_unique:
        raise ValueError('raw OHLC must have nonempty unique datetime dates')
    df = df.sort_index()
    if not np.isfinite(df[['open', 'close', 'high', 'low', 'volume']].to_numpy()).all():
        raise ValueError('raw OHLCV must be finite')
    if (df[['open', 'close', 'high', 'low']] <= 0).any().any():
        raise ValueError('raw OHLC must be positive')
    factor = np.ones(len(df))
    applied = []
    seen = set()
    for ex_str, div in dividends:
        ex = pd.Timestamp(ex_str)
        if ex in seen or not np.isfinite(div) or div <= 0:
            raise ValueError('dividends must have unique dates and positive finite amounts')
        seen.add(ex)
        # No future dividend is applied to an earlier historical snapshot.
        if ex > df.index[-1] or ex <= df.index[0]:
            continue
        mask = df.index < ex
        if mask.any():
            if ex not in df.index:
                raise ValueError(f'missing ex-dividend price session: {ex:%Y-%m-%d}')
            prev_close = df.loc[mask, 'close'].iloc[-1]
            if div >= prev_close:
                raise ValueError(f'dividend is not below previous raw close: {ex:%Y-%m-%d}')
            factor[mask] *= (prev_close - div) / prev_close
            applied.append({'ex_date': ex_str, 'cash_per_unit': float(div)})

    result = pd.DataFrame({
        'open': (df['open'].values * factor).round(3),
        'close': (df['close'].values * factor).round(3),
        'high': (df['high'].values * factor).round(3),
        'low': (df['low'].values * factor).round(3),
        'volume': df['volume'].values,
        'open_raw': df['open'].values,
        'close_raw': df['close'].values,
        'high_raw': df['high'].values,
        'low_raw': df['low'].values,
        'adjust_factor': factor.round(6),
    }, index=df.index)
    result.attrs.update(df.attrs)
    result.attrs.update(price_basis='qfq', raw_price_basis='raw',
                        adjustment_method='cash_dividend_ratio', dividends_applied=applied)
    return result


def fetch_510880_qfq(count=3000):
    """拉取510880不复权日线并应用前复权"""
    raw = get_price('sh510880', frequency='1d', count=count)
    return apply_qfq(raw, DIVIDENDS_510880)


def fetch_511260_close(count=2500):
    """拉取511260十年国债ETF前复权收盘价序列（空仓期配置资产, 含现金分红）"""
    return fetch_511260_qfq(count=count)['close']


def fetch_511260_qfq(count=2500):
    """拉取511260前复权 OHLC；开盘价用于与510880同步的次日开盘调仓。"""
    raw = get_price('sh511260', frequency='1d', count=count)
    return apply_qfq(raw, DIVIDENDS_511260)
