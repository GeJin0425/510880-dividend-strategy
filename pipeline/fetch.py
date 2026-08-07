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
]


def apply_qfq(df, dividends):
    """对不复权日线做前复权调整，返回新增 close_raw/high_raw/low_raw/adjust_factor 列的DataFrame"""
    df = df.sort_index()
    factor = np.ones(len(df))
    for ex_str, div in dividends:
        ex = pd.Timestamp(ex_str)
        mask = df.index < ex
        if mask.any():
            prev_close = df.loc[mask, 'close'].iloc[-1]
            ex_idx = df.index.get_indexer([ex], method='nearest')[0]
            factor[:ex_idx] *= (prev_close - div) / prev_close

    return pd.DataFrame({
        'open': (df['open'].values * factor).round(3),
        'close': (df['close'].values * factor).round(3),
        'high': (df['high'].values * factor).round(3),
        'low': (df['low'].values * factor).round(3),
        'volume': df['volume'].values,
        'close_raw': df['close'].values,
        'high_raw': df['high'].values,
        'low_raw': df['low'].values,
        'adjust_factor': factor.round(6),
    }, index=df.index)


def fetch_510880_qfq(count=3000):
    """拉取510880不复权日线并应用前复权"""
    raw = get_price('sh510880', frequency='1d', count=count)
    return apply_qfq(raw, DIVIDENDS_510880)


def fetch_511260_close(count=2500):
    """拉取511260十年国债ETF前复权收盘价序列（空仓期配置资产, 含现金分红）"""
    raw = get_price('sh511260', frequency='1d', count=count)
    return apply_qfq(raw, DIVIDENDS_511260)['close']
