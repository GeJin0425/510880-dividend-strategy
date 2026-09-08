import pandas as pd
import pytest
from pipeline.benchmark_research import benchmark


def test_buy_hold_counts_open_close_gap_and_commission():
    index = pd.date_range('2026-01-01', periods=2)
    stock = pd.DataFrame({'open': [10, 11], 'close': [11, 12]}, index=index)
    bond = pd.DataFrame({'open': [100, 100], 'close': [100, 100]}, index=index)
    eq, details = benchmark(stock, bond, weight=1, frequency='once')
    assert eq.iloc[-1] == pytest.approx(100000 - 99000 - 4.95 + 9900 * 12)
    assert details['fees'] == 4.95


def test_missing_bond_price_fails():
    index = pd.date_range('2026-01-01', periods=2)
    data = pd.DataFrame({'open': [10, 10], 'close': [10, 10]}, index=index)
    with pytest.raises(ValueError, match='Missing benchmark'):
        benchmark(data, data.iloc[:1])


def test_trend_target_uses_previous_close_and_has_no_future_dependency():
    index = pd.date_range('2026-01-01', periods=3)
    data = pd.DataFrame({'open': [10, 10, 20], 'close': [9, 20, 20],
                         'ma250': [10, 10, 10]}, index=index)
    bond = pd.DataFrame({'open': [1]*3, 'close': [1]*3}, index=index)
    full, _ = benchmark(data, bond, weight=0, trend=True)
    prefix, _ = benchmark(data.iloc[:2], bond.iloc[:2], weight=0, trend=True)
    pd.testing.assert_series_equal(prefix, full.iloc[:2])
    assert full.iloc[1] == full.iloc[0]  # Day two rally occurs while still in bonds.
    assert full.iloc[2] < full.iloc[1]  # Next open switch incurs fees, no captured rally.
