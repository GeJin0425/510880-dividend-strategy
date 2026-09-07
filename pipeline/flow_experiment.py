"""Offline experiment for adding ETF share-flow factors to the 510880 strategy.

The input files are deliberately explicit so a research run is reproducible and
does not silently refetch changing data. The SSE scale response is joined to
unadjusted prices to recover shares outstanding; exact TOT_VOL history should
replace it if that data is archived in the future.
"""

import argparse
import json

import numpy as np
import pandas as pd

from .backtest import backtest
from .export import EXECUTION_MODE, FEE_MIN, FEE_RATE, compute_stats
from .fetch import DIVIDENDS_510880, DIVIDENDS_511260, apply_qfq
from .indicators import add_indicators
from .share_flow import add_share_flow_indicators, derive_shares_from_scale
from .strategy import PARAMS, run_strategy


VARIANTS = {
    "base": None,
    "flow_veto_z-1": {"flow_z20": -1.0},
    "flow20_positive": {"share_flow_20": 0.0},
    "flow_z_positive": {"flow_z20": 0.0},
    "flow5_and_20_positive": {"share_flow_5": 0.0, "share_flow_20": 0.0},
    "trend_guard": {"ma250_slope": 0.0},
    "momentum252_guard": {"momentum_252": 0.0},
    "flow20_plus_trend": {"share_flow_20": 0.0, "ma250_slope": 0.0},
    "flow_z_on_b3": {"_apply_to": {"b3"}, "flow_z20": 0.0},
    "flow_z-0.5_on_b2_b3": {"_apply_to": {"b2", "b3"}, "flow_z20": -0.5},
    "flow_z_on_b2_b3": {"_apply_to": {"b2", "b3"}, "flow_z20": 0.0},
    "flow_z+0.5_on_b2_b3": {"_apply_to": {"b2", "b3"}, "flow_z20": 0.5},
    "flow_z+1_on_b2_b3": {"_apply_to": {"b2", "b3"}, "flow_z20": 1.0},
    "flow_z_on_b2": {"_apply_to": {"b2"}, "flow_z20": 0.0},
    "flow20_on_b3": {"_apply_to": {"b3"}, "share_flow_20": 0.0},
}


def _load_price(path, dividends):
    frame = pd.DataFrame(json.load(open(path, encoding="utf-8")))
    frame.index = pd.to_datetime(frame.pop("day"))
    for column in ["open", "close", "high", "low", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return apply_qfq(frame[["open", "close", "high", "low", "volume"]], dividends)


def load_research_data(scale_path, price_path, idle_path):
    scale_json = json.load(open(scale_path, encoding="utf-8"))
    rows = scale_json.get("result") or scale_json["pageHelp"]["data"]
    scale = pd.DataFrame(rows)
    scale.index = pd.to_datetime(scale["TRADE_DATE"])
    scale["scale_yi"] = pd.to_numeric(scale["SCALE"], errors="coerce")

    price = _load_price(price_path, DIVIDENDS_510880)
    data = add_indicators(price).join(scale[["scale_yi"]], how="inner")
    data["shares"] = derive_shares_from_scale(data["scale_yi"], data["close_raw"])
    data = add_share_flow_indicators(data)
    data["momentum_252"] = data["close"] / data["close"].shift(252) - 1
    idle = _load_price(idle_path, DIVIDENDS_511260)
    return data.sort_index(), idle.sort_index()


def evaluate(data, idle, flow_rule, start, end=None, execution_mode=EXECUTION_MODE):
    research = data[data.index >= start]
    if end:
        research = research[research.index <= end]
    # Reset strategy and portfolio state at each window boundary. Indicators
    # were calculated on the full warm-up history before this slice.
    signaled = run_strategy(
        research, PARAMS, flow_rule=flow_rule, execution_mode=execution_mode,
    )
    equity, trades = backtest(
        signaled,
        idle_price=idle,
        comm=FEE_RATE,
        min_comm=FEE_MIN,
        execution_mode=execution_mode,
    )
    d = signaled
    eq = equity.reindex(d.index).dropna()
    sells = trades[(trades["action"] == "SELL") & (trades["date"] >= start)]
    buys = trades[(trades["action"] == "BUY") & (trades["date"] >= start)]
    if end:
        sells = sells[sells["date"] <= end]
        buys = buys[buys["date"] <= end]
    if len(eq) < 2 or len(sells) == 0:
        return None
    stats, _ = compute_stats(d, eq, sells)
    actual_position = pd.Series(0, index=signaled.index, dtype=int)
    holding = 0
    tx_by_date = {date: group for date, group in trades.groupby("date")}
    for date in actual_position.index:
        if date in tx_by_date:
            for action in tx_by_date[date]["action"]:
                holding = 1 if action == "BUY" else 0
        actual_position.loc[date] = holding
    stats["holding_pct"] = round(float(actual_position.reindex(d.index).mean() * 100), 1)
    return stats


def run_matrix(data, idle):
    common_start = data["flow_z20"].first_valid_index()
    if common_start is None:
        raise ValueError("not enough history to calculate flow_z20")
    split = pd.Timestamp("2024-01-01")
    windows = [
        ("full", common_start, None),
        ("early_2022_2023", common_start, split - pd.Timedelta(days=1)),
        ("holdout_2024_plus", split, None),
    ]
    rows = []
    for variant, rule in VARIANTS.items():
        for window, start, end in windows:
            result = evaluate(data, idle, rule, start, end)
            if result:
                rows.append({"variant": variant, "window": window, **result})

    # 保留旧口径仅作差异参考，不能作为实盘执行绩效。
    same_close = evaluate(data, idle, None, common_start, execution_mode='same_close')
    if same_close:
        rows.append({"variant": "base_same_close_reference", "window": "full", **same_close})
    return pd.DataFrame(rows), common_start


def factor_diagnostics(data, start):
    d = data[data.index >= start].copy()
    for horizon in [20, 60]:
        d[f"future_{horizon}"] = d["close"].shift(-horizon) / d["close"] - 1
    rows = []
    for factor in ["share_flow_5", "share_flow_20", "flow_z20", "ma250_slope", "momentum_252"]:
        for horizon in [20, 60]:
            pair = d[[factor, f"future_{horizon}"]].dropna()
            rows.append({
                "factor": factor,
                "horizon": horizon,
                "spearman": pair.corr(method="spearman").iloc[0, 1],
                "observations": len(pair),
            })
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", required=True)
    parser.add_argument("--price", required=True)
    parser.add_argument("--idle", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    data, idle = load_research_data(args.scale, args.price, args.idle)
    matrix, start = run_matrix(data, idle)
    diagnostics = factor_diagnostics(data, start)
    matrix.to_csv(args.output, index=False)
    diagnostics.to_csv(args.output.replace(".csv", "_diagnostics.csv"), index=False)
    print(f"data={data.index.min().date()}..{data.index.max().date()} common_start={start.date()}")
    print(matrix.to_string(index=False))
    print("\nFactor diagnostics")
    print(diagnostics.to_string(index=False))


if __name__ == "__main__":
    main()
