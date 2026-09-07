import numpy as np
import pandas as pd
import pytest

from pipeline.indicator_research import (
    add_candidate_indicators,
    candidate_rules,
    holding_pct_for_window,
)


def test_candidate_indicators_use_only_available_price_and_volume_history():
    dates = pd.date_range('2020-01-01', periods=300, freq='B')
    close = pd.Series(np.linspace(100, 130, len(dates)), index=dates)
    data = pd.DataFrame({
        'close': close,
        'volume': np.linspace(1_000, 2_000, len(dates)),
        'share_flow_5': np.linspace(-0.01, 0.01, len(dates)),
        'flow_z20': np.linspace(-1, 1, len(dates)),
    }, index=dates)
    benchmark = pd.Series(np.linspace(100, 120, len(dates)), index=dates)

    out = add_candidate_indicators(data, benchmark)

    assert out.loc[dates[-1], 'volatility_ok'] == 1.0
    assert out.loc[dates[-1], 'volume_confirm'] == 1.0
    assert out.loc[dates[-1], 'flow_short_confirm'] == 1.0
    assert out.loc[dates[-1], 'market_above_ma200'] == 1.0
    assert 'relative_strength_60' in out
    assert set(candidate_rules()) >= {'baseline', 'volatility_guard', 'market_ma200_regime'}


def test_holding_pct_replays_position_opened_before_holdout():
    dates = pd.date_range('2020-01-01', periods=4, freq='D')
    trades = pd.DataFrame({
        'date': [dates[0], dates[2]],
        'action': ['BUY', 'SELL'],
    })

    assert holding_pct_for_window(trades, dates[1:]) == pytest.approx(33.3)
