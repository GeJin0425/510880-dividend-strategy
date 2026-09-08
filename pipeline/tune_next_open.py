"""在当前 next-open + flow_z20 生产口径下调优 510880 参数。

使用策略审计冻结快照，避免调参过程中重新抓取数据。训练区间为 2022--2024，
2025 年以后只作样本外验证；参数搜索结果不自动替换生产参数。
"""

import argparse
import json
import random
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

from .event_engine import simulate
from .export import FLOW_RULE, FEE_MIN, FEE_RATE, compute_holding_pct, compute_stats
from .strategy import PARAMS


SNAPSHOT_PATH = Path('tuning_results/audit/snapshot.pkl')
OUTPUT_PATH = Path('docs/research/510880-next-open-tuning-results.json')
TRAIN_WINDOWS = {
    'train_full': ('2022-01-28', '2024-12-31'),
    'train_early': ('2022-01-28', '2023-12-31'),
    'train_late': ('2023-01-01', '2024-12-31'),
}
VALIDATION_WINDOWS = {
    'test_2025_plus': ('2025-01-01', None),
    'full_snapshot': ('2022-01-28', None),
}
RANGES = {
    'b1': [-2.5, -2.0, -1.67, -1.5, -1.0, -0.5],
    'b2': [0.0, 0.5, 1.0, 1.5, 2.0, 2.5],
    'b2r': [28.0, 30.0, 31.67, 35.0, 40.0, 45.0, 50.0],
    'b3hi': [3.0, 4.0, 5.0, 6.0],
    's1': [10.0, 12.0, 14.0, 16.0],
    's2': [4.0, 5.0, 6.0, 7.0],
    's2r': [70.0, 75.0, 77.5, 80.0, 85.0],
    's3pk': [4.0, 5.0, 6.0, 7.0, 8.0],
    's3dp': [1.5, 2.0, 2.33, 2.5, 3.0],
    's4pr': [3.0, 3.5, 4.0, 4.5, 5.0],
    's4r': [60.0, 65.0, 67.5, 70.0],
    'cooldown': [5, 8, 10, 12, 15],
}

_DATA = None
_IDLE = None


def _valid(params):
    return params['b1'] < params['b2'] and params['s1'] > params['s2']


def _random_params(rng):
    params = {key: rng.choice(values) for key, values in RANGES.items()}
    params['b3lo'] = 0.0
    if params['b1'] >= params['b2']:
        params['b1'] = min(params['b1'], params['b2'] - 0.5)
    if params['s1'] <= params['s2']:
        params['s1'] = params['s2'] + 2.0
    return params


def _load_snapshot(path=SNAPSHOT_PATH):
    saved = pd.read_pickle(path)
    data = saved['data'].copy()
    idle = saved['idle'].copy()
    if data.empty or idle.empty:
        raise ValueError('调参快照为空')
    return data, idle


def _init_worker(data, idle):
    global _DATA, _IDLE
    _DATA, _IDLE = data, idle


def _evaluate(params, start, end=None):
    data = _DATA.loc[start:end]
    signals, equity, fills = simulate(
        data, _IDLE, params=params, flow_rule=FLOW_RULE,
        comm=FEE_RATE, min_comm=FEE_MIN,
    )
    sells = fills[fills['action'] == 'SELL']
    if len(sells) < 2:
        return None
    stats, _ = compute_stats(signals, equity, sells)
    buys = fills[fills['action'].isin(['BUY', 'ADD'])]
    stats.update({
        'closed_trades': int(len(sells)),
        'holding_pct': compute_holding_pct(buys, sells, data),
    })
    return stats


def _evaluate_full(params):
    return {'params': params, 'train_full': _evaluate(params, *TRAIN_WINDOWS['train_full'])}


def _evaluate_windows(params):
    return {
        'params': params,
        'train': {name: _evaluate(params, start, end)
                  for name, (start, end) in TRAIN_WINDOWS.items()},
        'validation': {name: _evaluate(params, start, end)
                       for name, (start, end) in VALIDATION_WINDOWS.items()},
    }


def _score(row):
    values = [row['train'][name] for name in TRAIN_WINDOWS]
    if any(item is None or item['closed_trades'] < 2 for item in values):
        return -1e9
    mean_ann = sum(item['annualized_pct'] for item in values) / len(values)
    worst_ann = min(item['annualized_pct'] for item in values)
    mean_sharpe = sum(item['sharpe'] for item in values) / len(values)
    worst_dd = min(item['max_drawdown_pct'] for item in values)
    # 同时奖励训练期收益和跨阶段稳定性，避免只追逐2024单一年份。
    return (
        0.55 * mean_ann + 0.25 * worst_ann + 1.5 * mean_sharpe
        - 0.20 * max(0.0, -worst_dd - 8.0)
    )


def run_search(n=1000, workers=8, seed=42, refine_top=100, snapshot_path=SNAPSHOT_PATH):
    data, idle = _load_snapshot(snapshot_path)
    global _DATA, _IDLE
    _DATA, _IDLE = data, idle
    rng = random.Random(seed)
    candidates = [dict(PARAMS)]
    while len(candidates) < n:
        candidate = _random_params(rng)
        if _valid(candidate):
            candidates.append(candidate)

    with ProcessPoolExecutor(
        max_workers=workers, initializer=_init_worker, initargs=(data, idle),
    ) as pool:
        rough = list(pool.map(_evaluate_full, candidates, chunksize=8))
        rough = [row for row in rough if row['train_full'] is not None]
        rough.sort(key=lambda row: row['train_full']['annualized_pct'], reverse=True)
        shortlist = [row['params'] for row in rough[:refine_top]]
        if PARAMS not in shortlist:
            shortlist.append(dict(PARAMS))
        rows = list(pool.map(_evaluate_windows, shortlist, chunksize=4))

    for row in rows:
        row['score'] = _score(row)
    rows.sort(key=lambda row: row['score'], reverse=True)

    baseline = next(row for row in rows if row['params'] == PARAMS)
    for row in [baseline] + rows[:20]:
        row.setdefault('validation', _evaluate_windows(row['params'])['validation'])
    return {
        'method': '当前next_open成交引擎 + flow_z20入口过滤；训练期稳健评分，2025+仅验证',
        'snapshot': str(snapshot_path),
        'snapshot_end': str(data.index[-1].date()),
        'seed': seed,
        'candidate_count': n,
        'refine_top': refine_top,
        'train_windows': TRAIN_WINDOWS,
        'validation_windows': VALIDATION_WINDOWS,
        'baseline': baseline,
        'top_candidates': rows[:20],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--n', type=int, default=1000)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--refine-top', type=int, default=100)
    parser.add_argument('--snapshot', type=Path, default=SNAPSHOT_PATH)
    parser.add_argument('--output', type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    payload = run_search(args.n, args.workers, args.seed, args.refine_top, args.snapshot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    for rank, row in enumerate(payload['top_candidates'][:10], 1):
        train = row['train']['train_full']
        test = row['validation']['test_2025_plus']
        print(
            f'{rank:2d} score={row["score"]:.2f} '
            f'train={train["annualized_pct"]:.2f}% '
            f'test={test["annualized_pct"]:.2f}% '
            f'params={row["params"]}'
        )


if __name__ == '__main__':
    main()
