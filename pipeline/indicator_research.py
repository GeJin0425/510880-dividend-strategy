"""Reproducible, non-production tests for candidate strategy indicators.

The module deliberately evaluates a small, pre-declared indicator set against
the production T+1-open engine.  It is not an optimizer: all candidates are
binary guards on b2/b3, while b1 remains an unconditional deep-value entry.
"""

import math

import numpy as np
import pandas as pd

from .Ashare import get_price
from .backtest import backtest
from .export import EXECUTION_MODE, FEE_MIN, FEE_RATE, FLOW_RULE, compute_stats
from .fetch import fetch_510880_qfq, fetch_511260_qfq
from .indicators import add_indicators
from .share_flow import add_share_flow_indicators, derive_shares_from_scale, fetch_sse_scale_history
from .strategy import PARAMS, run_strategy


DISPLAY_START = pd.Timestamp('2022-01-01')
BENCHMARK_CODE = 'sh000300'


def _binary(condition):
    """Represent a known-at-close Boolean as 1.0 / NaN for existing flow guards."""
    return pd.Series(np.where(condition, 1.0, np.nan), index=condition.index)


def add_candidate_indicators(data, benchmark_close):
    """Add only close-known candidate features; no forward return is used."""
    d = data.copy()
    returns = d['close'].pct_change()
    d['realized_vol_20'] = returns.rolling(20).std(ddof=0) * math.sqrt(252)
    # Current-day close is permitted: the decision is made after that close.
    d['volatility_rank_60'] = d['realized_vol_20'].rolling(60).rank(pct=True)
    d['volatility_ok'] = _binary(d['volatility_rank_60'] <= 0.80)

    log_volume = np.log(d['volume'].where(d['volume'] > 0))
    volume_mean = log_volume.rolling(20).mean()
    volume_std = log_volume.rolling(20).std(ddof=0).replace(0, np.nan)
    d['volume_z20'] = (log_volume - volume_mean) / volume_std
    d['volume_confirm'] = _binary(d['volume_z20'] >= 0)

    d['flow_short_confirm'] = _binary(d['share_flow_5'] >= 0)
    d['return_20'] = d['close'].pct_change(20)
    # Price weakness despite non-negative 20-day share flow is a pre-declared
    # mean-reversion hypothesis, not a future-return label.
    d['flow_price_divergence'] = _binary(
        (d['return_20'] <= 0) & (d['flow_z20'] >= 0)
    )

    benchmark = pd.Series(benchmark_close, name='benchmark_close').reindex(d.index)
    benchmark_ma200 = benchmark.rolling(200).mean()
    d['market_above_ma200'] = _binary(benchmark > benchmark_ma200)
    d['relative_return_60'] = d['close'].pct_change(60) - benchmark.pct_change(60)
    d['relative_strength_60'] = _binary(d['relative_return_60'] >= 0)
    return d


def candidate_rules():
    """One-at-a-time guards, all applied only to b2/b3 on top of production flow."""
    apply_to = {'b2', 'b3'}

    def rule(**extra):
        return {**FLOW_RULE, '_apply_to': apply_to, **extra}

    return {
        'baseline': FLOW_RULE,
        'volatility_guard': rule(volatility_ok=1.0),
        'volume_confirmation': rule(volume_confirm=1.0),
        'short_flow_confirmation': rule(flow_short_confirm=1.0),
        'flow_price_divergence': rule(flow_price_divergence=1.0),
        'market_ma200_regime': rule(market_above_ma200=1.0),
        'relative_strength_60': rule(relative_strength_60=1.0),
    }


def holding_pct_for_window(trades, dates):
    """Calculate exposure without mis-pairing an entry before the window.

    A holdout may begin while a position is already open, so filtering buys and
    sells independently before subtracting dates can produce nonsensical
    negative holding time. Replay all executions, then average only the window.
    """
    grouped = {date: group for date, group in trades.groupby('date')}
    window_dates = set(dates)
    timeline = sorted(set(grouped) | window_dates)
    holding = 0
    values = []
    for date in timeline:
        if date in grouped:
            for action in grouped[date]['action']:
                holding = int(action == 'BUY')
        if date in window_dates:
            values.append(holding)
    return round(float(np.mean(values) * 100), 1) if values else 0.0


def evaluate(data, idle, rule, start=DISPLAY_START):
    """Run one candidate with exactly the production execution/fee convention."""
    signaled = run_strategy(
        data, PARAMS, flow_rule=rule, execution_mode=EXECUTION_MODE,
    )
    equity, trades = backtest(
        signaled, idle_price=idle, comm=FEE_RATE, min_comm=FEE_MIN,
        execution_mode=EXECUTION_MODE,
    )
    d = signaled[signaled.index >= start]
    eq = equity[equity.index >= start]
    sells = trades[(trades['action'] == 'SELL') & (trades['date'] >= start)]
    if len(d) < 2 or sells.empty:
        return None
    stats, _ = compute_stats(d, eq, sells)
    stats['holding_pct'] = holding_pct_for_window(trades, d.index)
    return stats


def idle_asset_diagnostics(idle, start=DISPLAY_START):
    """Describe 511260 as an asset; it is not assumed to be cash-equivalent."""
    close = idle.loc[idle.index >= start, 'close'].dropna()
    returns = close.pct_change().dropna()
    years = (close.index[-1] - close.index[0]).days / 365.25
    equity = close / close.iloc[0]
    return {
        'annualized_pct': round(float((equity.iloc[-1] ** (1 / years) - 1) * 100), 1),
        'max_drawdown_pct': round(float(((equity / equity.cummax() - 1) * 100).min()), 1),
        'annualized_vol_pct': round(float(returns.std(ddof=0) * math.sqrt(252) * 100), 1),
    }


def load_live_data(count=3000):
    """Fetch the same source data as production plus a broad-market benchmark."""
    raw = fetch_510880_qfq(count=count)
    scale = fetch_sse_scale_history('510880')
    data = add_indicators(raw).join(scale, how='inner')
    data['shares'] = derive_shares_from_scale(data['scale_yi'], data['close_raw'])
    data = add_share_flow_indicators(data)
    flow_start = data['flow_z20'].first_valid_index()
    if flow_start is None:
        raise ValueError('insufficient share-flow history')
    benchmark = get_price(BENCHMARK_CODE, frequency='1d', count=count)['close']
    data = add_candidate_indicators(data, benchmark)
    return data.loc[data.index >= flow_start], fetch_511260_qfq(count=count)


def main():
    data, idle = load_live_data()
    rows = []
    windows = {
        'full': DISPLAY_START,
        # Previously inspected history is a segment, not untouched holdout data.
        'historical_2024_plus': pd.Timestamp('2024-01-01'),
    }
    for window, start in windows.items():
        for name, rule in candidate_rules().items():
            result = evaluate(data, idle, rule, start=start)
            if result:
                rows.append({'window': window, 'candidate': name, **result})
    print(pd.DataFrame(rows).to_string(index=False))
    print('\n511260 diagnostics:', idle_asset_diagnostics(idle))
    print(f'\nResearch range: {data.index.min():%Y-%m-%d}..{data.index.max():%Y-%m-%d}')


if __name__ == '__main__':
    main()
