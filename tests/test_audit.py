import pandas as pd
from pipeline.strategy import run_strategy
from pipeline.strategy_audit import excursions


def test_ablation_disables_selected_entry_without_falling_through():
    df = pd.DataFrame(dict(close=[100, 97, 97], open=[100, 97, 97],
                           ma250=[100]*3, deviation=[0, -3, -3], rsi=[50]*3,
                           ma10=[100]*3, ma250_slope=[0]*3))
    assert run_strategy(df).signal.iloc[1] == 1
    assert run_strategy(df, disabled_rules=('b1',)).signal.sum() == 0


def test_excursion_excludes_exit_day_intraday_prices():
    dates = pd.date_range('2026-01-01', periods=3)
    data = pd.DataFrame(dict(low=[9, 8, 1], high=[11, 12, 100], close=[10, 9, 50]), index=dates)
    trades = pd.DataFrame([dict(action='BUY', date=dates[0], price=10, buy_level='b1'),
                           dict(action='SELL', date=dates[2], price=11, pnl_pct=10,
                                hold_days=2, reason='exit')])
    trade = excursions(data, trades)[0]
    assert trade['mae_pct'] == -20
    assert trade['mfe_pct'] == 20
    assert trade['underwater_closes'] == 1
