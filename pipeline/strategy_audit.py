"""Frozen-input audit; historical diagnostics, not an out-of-sample claim.

python -m pipeline.strategy_audit --refresh downloads a new snapshot.
python -m pipeline.strategy_audit replays the saved local snapshot offline.
"""
import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

from .indicator_research import load_live_data, holding_pct_for_window
from .strategy import PARAMS, run_strategy
from .backtest import backtest
from .export import FLOW_RULE, FEE_RATE, FEE_MIN, compute_stats
from .event_engine import simulate


def run(data, idle, disabled=(), delay=0, extra_cost=0, params=None):
    d = data.copy()
    if delay:
        d['flow_z20'] = d['flow_z20'].shift(delay)
    signals, eq, trades = simulate(d, idle, params=params or PARAMS, flow_rule=FLOW_RULE,
                                   disabled_rules=disabled, comm=FEE_RATE + extra_cost,
                                   min_comm=FEE_MIN)
    sells = trades[trades.action == 'SELL']
    stats, _ = compute_stats(signals, eq, sells)
    stats['holding_pct'] = holding_pct_for_window(trades, d.index)
    stats['total_return_pct'] = round((eq.equity.iloc[-1] / 100000 - 1) * 100, 2)
    annual = eq.equity.groupby(eq.index.year).agg(['first', 'last'])
    # Calendar return includes the first day's return from the preceding year.
    starts = annual['last'].shift(1).fillna(100000)
    stats['calendar_returns_pct'] = ((annual['last'] / starts - 1) * 100).round(2).to_dict()
    return stats, trades


def excursions(data, trades):
    result, entry = [], None
    for _, event in trades.iterrows():
        if event.action == 'BUY':
            entry = event
        elif entry is not None:
            # On exit day exposure ends at open: its intraday low/high is excluded.
            held = data.loc[(data.index >= entry.date) & (data.index < event.date)]
            worst = min(held.low.min(), event.price) / entry.price - 1
            best = max(held.high.max(), event.price) / entry.price - 1
            result.append(dict(buy_date=str(entry.date.date()), sell_date=str(event.date.date()),
                               level=entry.buy_level, reason=event.reason,
                               pnl_pct=round(event.pnl_pct, 2), mae_pct=round(worst * 100, 2),
                               mfe_pct=round(best * 100, 2), hold_days=int(event.hold_days),
                               underwater_closes=int((held.close < entry.price).sum())))
            entry = None
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    folder = Path('tuning_results/audit')
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = folder / 'snapshot.pkl'
    if args.refresh or not snapshot.exists():
        data, idle = load_live_data()
        pd.to_pickle(dict(data=data, idle=idle, fetched_at=datetime.now(timezone.utc).isoformat()), snapshot)
    saved = pd.read_pickle(snapshot)  # Only the locally generated snapshot is supported.
    data, idle = saved['data'], saved['idle']
    results = {}
    results['baseline'], trades = run(data, idle)
    for rule in ['b1', 'b2', 'b3', 's1', 's2', 's3', 's4']:
        results['without_' + rule], _ = run(data, idle, disabled=(rule,))
    for delay in [1, 2]:
        results[f'flow_delay_{delay}'], _ = run(data, idle, delay=delay)
    for bps in [5, 10, 20]:
        results[f'extra_cost_{bps}bps_per_leg'], _ = run(data, idle, extra_cost=bps / 10000)
    rounded = {**PARAMS, 'b1': -1.5, 'b2r': 30, 's2r': 75, 's3dp': 2.5, 's4r': 65}
    results['rounded_parameters'], _ = run(data, idle, params=rounded)
    idle = idle.copy()
    idle['trend_ok'] = idle.close > idle.close.rolling(60).mean()
    event_results = {}
    for name, options in [('full', {}), ('b1_half', {'allocation': 'b1_half'}),
                          ('b1_half_confirm', {'allocation': 'b1_half_confirm'}),
                          ('high_vol_half', {'allocation': 'high_vol_half'}),
                          ('bond_ma60_guard', {'idle_guard': True}),
                          ('slippage_5bps', {'slippage_bps': 5}),
                          ('slippage_10bps', {'slippage_bps': 10}),
                          ('slippage_20bps', {'slippage_bps': 20})]:
        sig, eq, fills = simulate(data, idle, flow_rule=FLOW_RULE, **options)
        stats, _ = compute_stats(sig, eq, fills[fills.action == 'SELL'])
        stats['holding_pct'] = round((eq.shares > 0).mean() * 100, 1)
        stats['add_count'] = int((fills.action == 'ADD').sum())
        event_results[name] = stats
        if name == 'full':
            old_signals = run_strategy(data, PARAMS, FLOW_RULE, 'next_open')
            old_eq, old_fills = backtest(old_signals, idle, comm=FEE_RATE, min_comm=FEE_MIN,
                                         execution_mode='next_open')
            pd.testing.assert_series_equal(sig.signal, old_signals.signal)
            pd.testing.assert_series_equal(fills.date, old_fills.date)
            stats['max_equity_difference_vs_legacy'] = float((eq.equity - old_eq.equity).abs().max())
    output = dict(fetched_at=saved['fetched_at'], snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                  start=str(data.index[0].date()), end=str(data.index[-1].date()),
                  results=results, event_results=event_results, trades=excursions(data, trades))
    Path('docs/research/strategy-audit-results.json').write_text(
        json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
