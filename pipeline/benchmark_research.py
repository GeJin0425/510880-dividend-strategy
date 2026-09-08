"""Fixed benchmarks and historical-window tests. No parameter selection.

Frozen audit snapshot is required. --fetch-history caches longer Sina raw bars;
subsequent runs are offline. Outputs include input hashes and exact date windows.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .Ashare import get_price_sina
from .fetch import apply_qfq, DIVIDENDS_510880
from .indicators import add_indicators
from .event_engine import simulate
from .export import FLOW_RULE, FEE_RATE, FEE_MIN


def metrics(eq, initial=100000):
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    returns = eq.pct_change().dropna()
    dd = eq / eq.cummax().clip(lower=initial) - 1
    ann = (eq.iloc[-1] / initial) ** (1 / years) - 1
    std = returns.std()
    return dict(annualized_pct=round(float(ann * 100), 2),
                total_return_pct=round(float((eq.iloc[-1] / initial - 1) * 100), 2),
                max_drawdown_pct=round(float(dd.min() * 100), 2),
                sharpe=round(float((returns.mean() * 252 - .02) / (std * np.sqrt(252))), 2)
                if std > 0 else None, final_equity=round(float(eq.iloc[-1]), 2))


def benchmark(data, idle, weight=.5, frequency='monthly', trend=False):
    """100-unit lots, next open, both legs commissioned; no leverage.

    Calendar targets are known beforehand. Trend targets use yesterday's close.
    First allocation occurs at the first observed open. Residuals remain cash.
    """
    frames = [data, idle.reindex(data.index)]
    for frame in frames:
        values = frame[['open', 'close']].to_numpy()
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError('Missing benchmark prices')
    if not 0 <= weight <= 1:
        raise ValueError('weight outside 0..1')
    shares, cash, equity, costs, turnover = [0, 0], 100000., [], 0., 0.
    old_period, old_target = None, None

    def fee(amount):
        return max(amount * FEE_RATE, FEE_MIN) if amount else 0.

    for i, date in enumerate(data.index):
        opens = [frame.loc[date, 'open'] for frame in frames]
        closes = [frame.loc[date, 'close'] for frame in frames]
        target = float(data.iloc[i - 1]['close'] > data.iloc[i - 1]['ma250']) if trend and i else weight
        period = (date.year, (date.month - 1) // 3) if frequency == 'quarterly' else (date.year, date.month)
        rebalance = (target != old_target) if trend else (i == 0 or (frequency != 'once' and period != old_period))
        if rebalance:
            nav = cash + sum(s * p for s, p in zip(shares, opens))
            desired = [int(nav * w / p / 100) * 100 for w, p in zip([target, 1 - target], opens)]
            for j in range(2):
                units = max(0, shares[j] - desired[j])
                amount = units * opens[j]
                cash += amount - fee(amount)
                shares[j] -= units
                costs += fee(amount)
                turnover += amount
            for j in range(2):
                units = max(0, desired[j] - shares[j])
                while units and units * opens[j] + fee(units * opens[j]) > cash + 1e-9:
                    units -= 100
                amount = units * opens[j]
                cash -= amount + fee(amount)
                shares[j] += units
                costs += fee(amount)
                turnover += amount
        equity.append(cash + sum(s * p for s, p in zip(shares, closes)))
        old_period, old_target = period, target
    return pd.Series(equity, index=data.index), dict(fees=round(costs, 2), turnover=round(turnover, 2))


def strategy(data, idle, flow=FLOW_RULE, disabled=()):
    _, eq, trades = simulate(data, idle, flow_rule=flow, disabled_rules=disabled)
    return {**metrics(eq.equity), 'closed_trades': int((trades.action == 'SELL').sum()),
            'open_position': bool(eq.shares.iloc[-1] > 0)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fetch-history', action='store_true')
    parser.add_argument('--fetch-transfer', action='store_true')
    args = parser.parse_args()
    snapshot = Path('tuning_results/audit/snapshot.pkl')
    saved = pd.read_pickle(snapshot)
    data, idle = saved['data'], saved['idle']
    results = dict(strategy_with_bonds=strategy(data, idle), strategy_with_cash=strategy(data, None),
                   no_flow_with_bonds=strategy(data, idle, flow=None),
                   only_b1_with_bonds=strategy(data, idle, disabled=('b2', 'b3')))
    for name, kwargs in [('buy_hold_510880', dict(weight=1, frequency='once')),
                         ('buy_hold_511260', dict(weight=0, frequency='once')),
                         ('50_50_monthly', dict(weight=.5)),
                         ('50_50_quarterly', dict(weight=.5, frequency='quarterly')),
                         ('54_46_monthly_descriptive', dict(weight=.54)),
                         ('ma250_trend', dict(weight=0, trend=True))]:
        eq, fees = benchmark(data, idle, **kwargs)
        results[name] = {**metrics(eq), **fees}
    history_path = Path('tuning_results/audit/510880_raw_history.pkl')
    if args.fetch_history:
        get_price_sina('sh510880', frequency='1d', count=3000).to_pickle(history_path)
    history_results = {}
    if history_path.exists():
        raw = pd.read_pickle(history_path)
        adjusted = add_indicators(apply_qfq(raw, DIVIDENDS_510880))
        for start, end in [('2016-01-01', '2017-12-31'), ('2018-01-01', '2021-12-31'),
                           ('2022-01-28', '2023-12-31'), ('2024-01-01', '2026-09-07')]:
            window = adjusted.loc[start:end]
            if len(window) < 100 or window.iloc[0][['ma250', 'rsi']].isna().any():
                history_results[start] = {'status': 'insufficient warmup'}
                continue
            constant = window[['open', 'close']].copy() * 0 + 1
            eq, _ = benchmark(window, constant, weight=1, frequency='once')
            history_results[start] = dict(start=str(window.index[0].date()), end=str(window.index[-1].date()),
                                         core_no_flow_cash=strategy(window, None, flow=None),
                                         buy_hold=metrics(eq))
    transfer = {}
    for code in ['sh000922', 'sz399324']:
        path = Path(f'tuning_results/audit/{code}_price_index.pkl')
        if args.fetch_transfer:
            get_price_sina(code, frequency='1d', count=3000).to_pickle(path)
        if not path.exists():
            transfer[code] = {'status': 'not downloaded'}
            continue
        raw = pd.read_pickle(path)
        # Synthetic price-index units; not a fund return or a total-return index.
        frame = raw.copy()
        frame[['open', 'high', 'low', 'close']] /= raw.close.iloc[0] / 10
        frame['open_raw'], frame['close_raw'] = frame.open, frame.close
        window = add_indicators(frame).loc['2022-01-28':'2026-09-07']
        if len(window) < 500 or window.iloc[0].ma250 != window.iloc[0].ma250:
            transfer[code] = {'status': 'insufficient history'}
            continue
        cash_asset = window[['open', 'close']] * 0 + 1
        eq, _ = benchmark(window, cash_asset, weight=1, frequency='once')
        transfer[code] = dict(start=str(window.index[0].date()), end=str(window.index[-1].date()),
                              sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                              core_no_flow_cash=strategy(window, None, flow=None),
                              buy_hold_price_index=metrics(eq))
    output = dict(start=str(data.index[0].date()), end=str(data.index[-1].date()),
                  audit_snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                  history_sha256=hashlib.sha256(history_path.read_bytes()).hexdigest() if history_path.exists() else None,
                  benchmarks=results, historical_windows=history_results, price_index_transfer=transfer)
    Path('docs/research/benchmark-results.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
