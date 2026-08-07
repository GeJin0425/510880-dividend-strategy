"""
510880 MA250策略参数网格搜索 / OFAT扫描

用法:
    python -m pipeline.tune fetch               # 抓数据缓存为 CSV
    python -m pipeline.tune sweep --params s1   # 单个参数扫描 (逗号分隔可多参数)
    python -m pipeline.tune refine              # 围绕当前最优做联合精修
    python -m pipeline.tune validate --best "..."  # 样本内/外验证一组参数

数据只抓一次缓存到 tuning_results/data_cache.csv, 后续扫描离线进行。
指标口径与 export.py 完全一致 (2018-01-01 起, 含511260空仓收益, 佣金0.1%)。
"""
import argparse
import copy
import csv
import json
import os
import sys
import time

import numpy as np
import pandas as pd

from .backtest import backtest
from .export import compute_holding_pct, compute_stats
from .fetch import fetch_510880_qfq, fetch_511260_close
from .indicators import add_indicators
from .strategy import PARAMS, run_strategy

DISPLAY_START = '2018-01-01'
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tuning_results')
CACHE = os.path.join(OUT_DIR, 'data_cache.csv')
IDLE_CACHE = os.path.join(OUT_DIR, 'idle_cache.csv')


def load_data(refresh=False):
    if not refresh and os.path.exists(CACHE) and os.path.exists(IDLE_CACHE):
        df = pd.read_csv(CACHE, parse_dates=['date']).set_index('date')
        idle = pd.read_csv(IDLE_CACHE, parse_dates=['date']).set_index('date')['close']
        print(f'[load] 从缓存读取 {len(df)} 行 ({df.index[0].date()} -> {df.index[-1].date()})')
        return df, idle

    os.makedirs(OUT_DIR, exist_ok=True)
    raw = fetch_510880_qfq(count=3000)
    raw.index.name = 'date'
    df = add_indicators(raw)
    try:
        idle = fetch_511260_close(count=2500)
    except Exception as e:
        print(f'[warn] 511260 抓取失败: {e}')
        idle = pd.Series(dtype=float)
    idle.index.name = 'date'
    df.reset_index().to_csv(CACHE, index=False)
    idle.reset_index().to_csv(IDLE_CACHE, index=False)
    print(f'[fetch] 已缓存 {len(df)} 行, 511260 {len(idle)} 行')
    return df, idle


def evaluate(p, df, idle, start=DISPLAY_START):
    """与线上完全一致的单参数组合评估。返回指标 dict 或 None(无可平仓交易)"""
    df_sig = run_strategy(df, p)
    try:
        eq, tr = backtest(df_sig, idle_price=idle)
    except Exception:
        return None
    df2 = df_sig[df_sig.index >= start]
    eq2 = eq[eq.index >= start]
    buys = tr[(tr['action'] == 'BUY') & (tr['date'] >= start)].reset_index(drop=True)
    sells = tr[(tr['action'] == 'SELL') & (tr['date'] >= start)].reset_index(drop=True)
    if len(sells) == 0:
        return None
    try:
        stats, _ = compute_stats(df2, eq2, sells)
    except Exception:
        return None
    stats['holding_pct'] = compute_holding_pct(buys, sells, df2)
    stats['n_trades'] = stats.pop('trade_count')
    return stats


def short(p):
    return ','.join(f'{k}={v:g}' for k, v in p.items())


def sweep(params_to_sweep, fixed, df, idle, tag, eval_win=None):
    """对指定参数逐个扫描(其他固定), 输出 CSV + 控制台表格。eval_win=(start,end) 时只在窗口内评估"""
    rows = []
    for pname, values in params_to_sweep.items():
        for v in values:
            p = copy.deepcopy(fixed)
            p[pname] = v
            if eval_win:
                r = evaluate_range(p, df, idle, *eval_win)
            else:
                r = evaluate(p, df, idle)
            if r is None:
                continue
            r['param'] = pname
            r['value'] = v
            r['params'] = short(p)
            rows.append(r)
    out = pd.DataFrame(rows)
    if len(out) == 0:
        print('[sweep] 无有效结果')
        return []
    path = os.path.join(OUT_DIR, f'sweep_{tag}.csv')
    out.to_csv(path, index=False)
    best = out.loc[out['annualized_pct'].idxmax()]

    disp = out[['param', 'value', 'annualized_pct', 'max_drawdown_pct', 'sharpe',
                'win_rate_pct', 'n_trades', 'avg_win_pct', 'holding_pct']]
    with pd.option_context('display.max_rows', None, 'display.width', 200):
        print(f'\n===== SWEEP [{tag}] =====  {len(out)} evals')
        print(disp.sort_values('annualized_pct', ascending=False).to_string(index=False))
    print(f'\n[best] {best["param"]}={best["value"]:g}  ann={best["annualized_pct"]:.1f}%  '
          f'maxDD={best["max_drawdown_pct"]:.1f}%  sharpe={best["sharpe"]:.2f}  '
          f'win={best["win_rate_pct"]:.0f}%  trades={best["n_trades"]}')
    print(f'[saved] {path}')
    return rows


def cmd_fetch():
    load_data(refresh=True)
    print('done')


def cmd_sweep(args, df, idle):
    names = [s.strip() for s in args.params.split(',')]
    ALLOWED = set(PARAMS.keys())
    bad = [n for n in names if n not in ALLOWED]
    if bad:
        sys.exit(f'未知参数: {bad}. 可选: {sorted(ALLOWED)}')

    fixed = dict(PARAMS)
    if args.fixed:
        for kv in args.fixed.split(','):
            k, v = kv.split('=')
            if k.strip() not in ALLOWED:
                sys.exit(f'未知参数: {k.strip()}')
            fixed[k.strip()] = float(v)
    sweep_grid = {}
    for n in names:
        lo, hi = args.range  # (lo, hi)
        steps = args.steps
        sweep_grid[n] = [round(lo + (hi - lo) * i / (steps - 1), 2) for i in range(steps)]
    win = {'train': ('2018-01-01', '2022-12-31'), 'test': ('2023-01-01', '2026-12-31'),
           'full': None}.get(args.window)
    sweep(sweep_grid, fixed, df, idle, tag='custom_' + '_'.join(names) + f'_{args.window}', eval_win=win)


def cmd_refine(args, df, idle):
    """围绕基线 PARAMS 对全部数值参数做小步长联合扫描(笛卡尔积太大时逐步放缩)"""
    delta = dict(args.delta) if args.delta else dict(b1=0.5, b2=0.5, b2r=5, b3hi=1, s1=1, s2=1,
                                                     s2r=5, s3pk=1, s3dp=0.5, s4pr=1, s4r=5)
    grid = {}
    for k, v in PARAMS.items():
        if k in delta and isinstance(v, (int, float)):
            d = delta[k]
            grid[k] = [round(v + d, 2), round(v, 2), round(v - d, 2)]
    rows = sweep(grid, dict(PARAMS), df, idle, tag='refine')


def cmd_validate(args, df, idle):
    """样本内/外验证: 训练 2018-2022, 测试 2023-2026"""
    p = dict(PARAMS)
    if args.best:
        for kv in args.best.split(','):
            k, v = kv.split('=')
            p[k.strip()] = float(v)
    print(f'\n===== VALIDATE =====  {short(p)}\n')
    baseline = dict(PARAMS)
    labels = [('基线', baseline)] if args.best else []
    labels.append(('候选', p))
    for label, params in labels:
        print(f'--- {label}: {short(params)}')
        for name in ['全样本', '训练 2018-2022', '测试 2023-2026']:
            if name == '训练 2018-2022':
                r = evaluate_range(params, df, idle, '2018-01-01', '2022-12-31')
            else:
                r = evaluate(params, df, idle, start='2018-01-01' if name == '全样本' else '2023-01-01')
            if r is None:
                print(f'  {name}: 无可平仓交易')
                continue
            print(f'  {name}: ann={r["annualized_pct"]:.1f}%  maxDD={r["max_drawdown_pct"]:.1f}%  '
                  f'sharpe={r["sharpe"]:.2f}  win={r["win_rate_pct"]:.0f}%  '
                  f'trades={r["n_trades"]}  avg={r["avg_win_pct"]:.1f}%  hold={r["holding_pct"]:.0f}%')


def evaluate_range(params, df, idle, start, end):
    """在 [start, end] 区间内评估(交易必须在该区间内开平仓)"""
    df_sig = run_strategy(df, params)
    eq, tr = backtest(df_sig, idle_price=idle)
    df2 = df_sig[(df_sig.index >= start) & (df_sig.index <= end)]
    eq2 = eq[(eq.index >= start) & (eq.index <= end)]
    buys = tr[(tr['action'] == 'BUY') & (tr['date'] >= start) & (tr['date'] <= end)]
    sells = tr[(tr['action'] == 'SELL') & (tr['date'] >= start) & (tr['date'] <= end)]
    if len(sells) == 0:
        return None
    stats, _ = compute_stats(df2, eq2, sells)
    stats['holding_pct'] = compute_holding_pct(buys, sells, df2)
    stats['n_trades'] = stats.pop('trade_count')
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    f = sub.add_parser('fetch')
    f.set_defaults(fn=cmd_fetch)

    s = sub.add_parser('sweep')
    s.add_argument('--params', required=True, help='逗号分隔参数名, 如 s1,s2')
    s.add_argument('--range', nargs=2, type=float, required=True, help='扫描范围 lo hi')
    s.add_argument('--steps', type=int, default=7)
    s.add_argument('--fixed', default=None, help='非扫描参数覆盖, 形如 "s2=5,s4pr=3.5"')
    s.add_argument('--window', choices=['full', 'train', 'test'], default='full',
                   help='评估窗口: full=2018起全样本, train=2018-2022, test=2023-2026')
    s.set_defaults(fn=cmd_sweep)

    r = sub.add_parser('refine')
    r.add_argument('--delta', nargs='*', default=None,
                   help='形如 s1=1 s2=1 的步长覆盖')
    r.set_defaults(fn=cmd_refine)

    v = sub.add_parser('validate')
    v.add_argument('--best', default=None, help='候选参数, 形如 "s1=12,s2=7"')
    v.set_defaults(fn=cmd_validate)

    args = ap.parse_args()
    if args.cmd == 'fetch':
        args.fn()
    else:
        df, idle = load_data()
        args.fn(args, df, idle)


if __name__ == '__main__':
    main()
