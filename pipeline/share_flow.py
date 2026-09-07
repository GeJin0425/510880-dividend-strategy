"""ETF share-flow features derived from end-of-day shares outstanding.

The factor must only be used from the next trading session because exchange
share data is published after the corresponding close.
"""

import numpy as np
import pandas as pd
import requests


SSE_QUERY_URL = "https://query.sse.com.cn/commonQuery.do"
SSE_HEADERS = {
    "Referer": "https://etf.sse.com.cn/",
    "User-Agent": "Mozilla/5.0 (compatible; 510880-research/1.0)",
}


def fetch_sse_scale_history(fund_code="510880", timeout=20, session=requests):
    """Fetch the exchange's historical CNY scale series for one SSE ETF."""
    params = {
        "isPagination": "true",
        "pageHelp.pageSize": "10000",
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.cacheSize": "1",
        "pageHelp.endPage": "1",
        "sqlId": "COMMON_JJZWZ_JJLB_JJXQ_JJGM_CKLSGM_L",
        "FUND_CODE": fund_code,
    }
    response = session.get(SSE_QUERY_URL, params=params, headers=SSE_HEADERS, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("result") or payload.get("pageHelp", {}).get("data", [])
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["scale_yi"], index=pd.DatetimeIndex([], name="date"))
    frame["date"] = pd.to_datetime(frame["TRADE_DATE"], errors="coerce")
    frame["scale_yi"] = pd.to_numeric(frame["SCALE"], errors="coerce")
    return frame.dropna(subset=["date"]).set_index("date")[["scale_yi"]].sort_index()


def add_share_flow_indicators(df, share_col="shares", z_window=252):
    """Add 5/20-day log share flows and the rolling z-score of 20-day flow.

    ``df[share_col]`` must contain strictly positive shares outstanding. Missing
    observations are preserved; they are not forward-filled here because the
    caller should decide whether a missing date is a holiday or a failed fetch.
    """
    if share_col not in df.columns:
        raise KeyError(f"missing share column: {share_col}")
    if z_window < 2:
        raise ValueError("z_window must be at least 2")

    d = df.copy()
    shares = pd.to_numeric(d[share_col], errors="coerce")
    shares = shares.where(shares > 0)
    log_shares = np.log(shares)

    d["share_flow_5"] = log_shares.diff(5)
    d["share_flow_20"] = log_shares.diff(20)
    rolling_mean = d["share_flow_20"].rolling(z_window).mean()
    rolling_std = d["share_flow_20"].rolling(z_window).std(ddof=0)
    # Numerically constant windows can leave a tiny non-zero float on some
    # pandas/numpy versions; treat them as zero variance consistently.
    rolling_std = rolling_std.mask(rolling_std.abs() < 1e-12)
    d["flow_z20"] = (d["share_flow_20"] - rolling_mean) / rolling_std
    return d


def derive_shares_from_scale(scale_yi, raw_close):
    """Derive shares outstanding in 100-million units from scale and price.

    SSE's historical ``SCALE`` field is in CNY 100 million and is calculated
    using the closing price. Dividing by the unadjusted close therefore returns
    shares in 100-million units. Exact exchange ``TOT_VOL`` data is preferable
    whenever it is available.
    """
    scale = pd.to_numeric(scale_yi, errors="coerce")
    close = pd.to_numeric(raw_close, errors="coerce").where(lambda x: x > 0)
    return scale / close
