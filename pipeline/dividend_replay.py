"""Offline, controlled dividend-impact replay from captured raw JSON inputs.

Uses identical prices, SSE scale, strategy parameters, fees and execution engine
in both runs; only the 2026-09-18 511260 dividend is toggled. This is a historical
replay of the captured source snapshot, not a raw-share cash-dividend ledger or
proof of the source used in an older deployed artifact.
"""
import argparse
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from . import export as dashboard
from .Ashare import SINA_URL, _raw_frame
from .fetch import DIVIDENDS_510880, DIVIDENDS_511260, apply_qfq

DIVIDEND = ('2026-09-18', 1.2747)


def replay(input_dir, output_dir, *, now, production_path=None):
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    frames, inputs = {}, {}
    for code in ['sh510880', 'sh511260']:
        path = input_dir / f'{code}-raw-sina.json'
        content = path.read_bytes()
        rows = json.loads(content)
        frames[code] = _raw_frame(
            rows, ['day', 'open', 'high', 'low', 'close', 'volume'],
            provider='Sina captured snapshot', code=code, frequency='1d', endpoint=SINA_URL,
            count=len(rows),
        )
        inputs[path.name] = {'sha256': hashlib.sha256(content).hexdigest(), 'rows': len(rows)}
    scale_path = input_dir / '510880-scale-sse.json'
    content = scale_path.read_bytes()
    payload = json.loads(content)
    rows = payload.get('result') or payload.get('pageHelp', {}).get('data', [])
    scale = pd.DataFrame(rows)
    scale['date'] = pd.to_datetime(scale['TRADE_DATE'])
    scale['scale_yi'] = pd.to_numeric(scale['SCALE'], errors='raise')
    scale = scale.set_index('date')[['scale_yi']].sort_index()
    inputs[scale_path.name] = {'sha256': hashlib.sha256(content).hexdigest(), 'rows': len(scale)}
    equity = apply_qfq(frames['sh510880'], DIVIDENDS_510880)
    before_dividends = [event for event in DIVIDENDS_511260 if event != DIVIDEND]
    results, curves, fills = {}, {}, {}
    original_simulate = dashboard.simulate
    for label, dividends in [('before', before_dividends), ('after', DIVIDENDS_511260)]:
        idle = apply_qfq(frames['sh511260'], dividends)
        def capture_simulation(*args, _label=label, **kwargs):
            result = original_simulate(*args, **kwargs)
            curves[_label] = result[1].copy()
            fills[_label] = result[2].copy()
            return result

        with patch.object(dashboard, 'fetch_510880_qfq', return_value=equity), \
                patch.object(dashboard, 'fetch_511260_qfq', return_value=idle), \
                patch.object(dashboard, 'fetch_sse_scale_history', return_value=scale), \
                patch.object(dashboard, 'simulate', side_effect=capture_simulation):
            results[label] = dashboard.export(output_dir / f'{label}.json', now=now)
        curves[label].to_csv(output_dir / f'equity-{label}.csv')
        fills[label].to_csv(output_dir / f'fills-{label}.csv', index=False)
    before, after = results['before'], results['after']
    old_equity, new_equity = before['series']['equity_strategy'], after['series']['equity_strategy']
    dates = before['series']['dates']
    changed = [date for date, old, new in zip(dates, old_equity, new_equity) if old != new]
    raw_bonds = frames['sh511260']
    previous = raw_bonds.loc[raw_bonds.index < pd.Timestamp(DIVIDEND[0]), 'close'].iloc[-1]
    curve_delta = curves['after']['equity'] - curves['before']['equity']
    pre_delta = curve_delta.loc[curve_delta.index < pd.Timestamp(DIVIDEND[0])]
    comparison = {
        'kind': 'controlled_real_history_replay',
        'only_toggled_input': {'asset': '511260', 'ex_date': DIVIDEND[0], 'cash_per_unit': DIVIDEND[1]},
        'inputs': inputs,
        'as_of_date': before['meta']['as_of_date'],
        'start_date': dates[0], 'sessions': len(dates),
        'previous_raw_bond_close': float(previous),
        'new_dividend_factor': float((previous - DIVIDEND[1]) / previous),
        # Display records omit share quantities, so equality is not fill equality.
        'exported_trade_records_identical': before['trades'] == after['trades'],
        'simulation_fills_identical': fills['before'].equals(fills['after']),
        'fill_count_before': len(fills['before']), 'fill_count_after': len(fills['after']),
        'changed_equity_fill_sizes': int((fills['before']['shares'] != fills['after']['shares']).sum()),
        'signals_identical': before['signals'] == after['signals'],
        'final_equity_before_rounded_cny': old_equity[-1],
        'final_equity_after_rounded_cny': new_equity[-1],
        'final_equity_delta_rounded_cny': new_equity[-1] - old_equity[-1],
        'final_equity_before_cny': float(curves['before']['equity'].iloc[-1]),
        'final_equity_after_cny': float(curves['after']['equity'].iloc[-1]),
        'final_equity_delta_cny': float(curves['after']['equity'].iloc[-1] - curves['before']['equity'].iloc[-1]),
        'dividend_date_equity': {
            label: float(curves[label].loc[DIVIDEND[0], 'equity']) if DIVIDEND[0] in curves[label].index
            else None for label in ['before', 'after']
        },
        'changed_rounded_equity_sessions': len(changed),
        'first_changed_rounded_equity_date': changed[0] if changed else None,
        'pre_ex_date_equity_drift_cny': {
            'changed_sessions': int((pre_delta.abs() > 1e-8).sum()),
            'min': float(pre_delta.min()), 'max': float(pre_delta.max()),
            'last_pre_ex_delta': float(pre_delta.iloc[-1]),
        },
        'ex_date_delta_widening_cny': float(curve_delta.loc[DIVIDEND[0]] - pre_delta.iloc[-1])
            if DIVIDEND[0] in curve_delta.index else None,
        'stats_before': {key: before['meta'][key] for key in ['annualized_pct', 'max_drawdown_pct', 'sharpe']},
        'stats_after': {key: after['meta'][key] for key in ['annualized_pct', 'max_drawdown_pct', 'sharpe']},
        'limits': [
            'Captured Sina raw inputs do not establish which provider produced an older deployment.',
            'Equity export rounds to whole CNY and performance statistics are rounded.',
            'Existing adjusted-unit 100-unit lot convention is preserved; this is not a cash-dividend ledger.',
        ],
    }
    if production_path is not None:
        production_content = Path(production_path).read_bytes()
        production = json.loads(production_content)
        comparison['observed_artifact_baseline_check'] = {
            'sha256': hashlib.sha256(production_content).hexdigest(),
            'all_exported_series_identical': production['series'] == before['series'],
            'signals_identical': production['signals'] == before['signals'],
            'trades_identical': production['trades'] == before['trades'],
        }
    with (output_dir / 'comparison.json').open('w', encoding='utf-8') as file:
        json.dump(comparison, file, ensure_ascii=False, indent=2, allow_nan=False)
    return comparison


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_dir')
    parser.add_argument('output_dir')
    parser.add_argument('--now', required=True, help='Timezone-aware snapshot validation time')
    parser.add_argument('--production', help='Optional observed data.json to compare with baseline')
    args = parser.parse_args()
    print(json.dumps(replay(args.input_dir, args.output_dir, now=pd.Timestamp(args.now),
                            production_path=args.production), indent=2))
