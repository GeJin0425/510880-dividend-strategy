import json

import numpy as np
import pandas as pd

from pipeline.dividend_replay import replay
from pipeline.fetch import DIVIDENDS_511260
from pipeline.market_sessions import sse_sessions


def test_offline_replay_uses_identical_inputs_and_only_toggles_dividend(tmp_path):
    # Synthetic source-shaped fixture, not claimed real historical evidence.
    inputs, outputs = tmp_path / 'inputs', tmp_path / 'outputs'
    inputs.mkdir()
    dates = sse_sessions('2024-01-02', '2026-09-30')[-500:]
    equity = np.r_[np.full(300, 100.), 95., np.linspace(96., 118., 19), np.full(180, 118.)]
    bond = np.full(500, 136.)
    for date, cash in DIVIDENDS_511260:
        bond[dates >= pd.Timestamp(date)] -= cash
    for code, prices in [('sh510880', equity), ('sh511260', bond)]:
        rows = [{'day': date.strftime('%Y-%m-%d'), 'open': float(price), 'close': float(price),
                 'high': float(price + .1), 'low': float(price - .1), 'volume': 10000.}
                for date, price in zip(dates, prices)]
        (inputs / f'{code}-raw-sina.json').write_text(json.dumps(rows))
    shares = np.exp(np.arange(500) * .0005 + np.sin(np.arange(500) / 11) * .01)
    rows = [{'TRADE_DATE': date.strftime('%Y-%m-%d'), 'SCALE': str(scale)}
            for date, scale in zip(dates, shares * equity)]
    (inputs / '510880-scale-sse.json').write_text(json.dumps({'result': rows}))
    input_bytes = {path.name: path.read_bytes() for path in inputs.iterdir()}
    result = replay(inputs, outputs, now=pd.Timestamp('2026-10-01T01:00:00Z'))
    before, after = [json.loads((outputs / f'{label}.json').read_text()) for label in ['before', 'after']]
    assert {path.name: path.read_bytes() for path in inputs.iterdir()} == input_bytes
    assert result['only_toggled_input']['cash_per_unit'] == 1.2747
    assert result['signals_identical'] and result['exported_trade_records_identical']
    assert before['series']['close'] == after['series']['close']
    assert before['meta']['parameter_set'] == after['meta']['parameter_set'] == 'next_open_candidate_a'
    assert result['final_equity_after_cny'] > result['final_equity_before_cny']
    for label in ['before', 'after']:
        assert (outputs / f'equity-{label}.csv').exists()
    production = tmp_path / 'production.json'
    production.write_text(json.dumps(before))
    repeated = replay(inputs, outputs, now=pd.Timestamp('2026-10-01T01:00:00Z'), production_path=production)
    check = repeated['observed_artifact_baseline_check']
    assert check['all_exported_series_identical'] and check['signals_identical'] and check['trades_identical']
