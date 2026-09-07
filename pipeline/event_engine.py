"""Fill-driven, next-open portfolio simulation for strategy and allocation research.

Uses adjusted units like the historical engine (not a raw-share dividend ledger).
Initial cash and 100-unit lots intentionally preserve the old baseline convention.
"""
import numpy as np
import pandas as pd

from .strategy import PARAMS, close_decision


def simulate(data, idle=None, *, params=PARAMS, flow_rule=None, disabled_rules=(),
             initial=100000, comm=0.00005, min_comm=0.5, slippage_bps=0,
             allocation='full', idle_guard=False):
    if allocation not in {'full', 'b1_half', 'high_vol_half', 'b1_half_confirm'}:
        raise ValueError('unknown allocation')
    if initial <= 0 or comm < 0 or min_comm < 0 or not 0 <= slippage_bps < 10000:
        raise ValueError('invalid portfolio inputs')
    required = ['open', 'close', 'open_raw', 'close_raw']
    for asset, frame in [('510880', data), ('511260', idle)]:
        if frame is None:
            continue
        if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
            raise ValueError(f'{asset}: dates must be unique and increasing')
        prices = frame.reindex(data.index)[required]
        if not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any().any():
            raise ValueError(f'{asset}: missing or invalid aligned OHLC')
    if data.empty:
        raise ValueError('empty history')
    d = data.copy()
    d['signal'], d['buy_level'], d['sell_reason'] = 0, '', ''
    d['position'], d['pending_action'] = 0, ''
    cash, shares, bonds = float(initial), 0, 0
    entry, entry_date, max_dev = 0., None, 0.
    pending, last_sell, added, partial_entry = None, -999, False, False
    fills, curve = [], []
    slip = slippage_bps / 10000
    bond_target = False  # Preserve initial-cash baseline until first equity exit.

    def fee(amount):
        return max(amount * comm, min_comm) if amount else 0.

    def size(budget, price):
        units = max(0, int(budget / price / 100) * 100)
        while units and units * price + fee(units * price) > budget + 1e-9:
            units -= 100
        return units

    def bond_fill(row, buy):
        nonlocal cash, bonds
        price = row['open'] * (1 + slip if buy else 1 - slip)
        units = size(cash, price) if buy else bonds
        if units:
            cash += -(units * price + fee(units * price)) if buy else units * price - fee(units * price)
            bonds += units if buy else -units

    for i, (date, row) in enumerate(data.iterrows()):
        bond = idle.loc[date] if idle is not None else None
        if pending is not None:
            action = pending['action']
            if action in {'BUY', 'ADD'}:
                if bonds:
                    bond_fill(bond, False)
                price = row.open * (1 + slip)
                units = size(cash * pending['fraction'], price)
                if units:
                    old = shares
                    shares += units
                    cash -= units * price + fee(units * price)
                    entry = (entry * old + units * price) / shares
                    if not old:
                        entry_date, max_dev = date, pending['dev']
                        added = False
                        partial_entry = pending['fraction'] < 1
                    else:
                        added = True
                    fills.append(dict(date=date, signal_date=pending['date'], action=action,
                                      price=price, price_raw=row.open_raw * (1 + slip), shares=units,
                                      close_price=row.close, close_price_raw=row.close_raw,
                                      buy_level=pending['reason']))
            elif shares:
                price = row.open * (1 - slip)
                cash += shares * price - fee(shares * price)
                fills.append(dict(date=date, signal_date=pending['date'], action='SELL', price=price,
                                  price_raw=row.open_raw * (1 - slip), shares=shares,
                                  close_price=row.close, close_price_raw=row.close_raw,
                                  pnl_pct=(price / entry - 1) * 100,
                                  hold_days=(date - entry_date).days, reason=pending['reason']))
                shares, entry, last_sell = 0, 0., i
                bond_target = True
            pending = None
        if bond is not None and not shares:
            if idle_guard:
                # Yesterday's close-time bond regime is executable at today's open.
                allow_bond = i > 0 and bool(idle.loc[data.index[i - 1]].get('trend_ok', False))
            else:
                allow_bond = True
            if bonds and not allow_bond:
                bond_fill(bond, False)
            elif not bonds and bond_target and allow_bond:
                bond_fill(bond, True)
        if i:
            sig, reason, max_dev = close_decision(
                row, data.iloc[i - 1], shares > 0, entry, max_dev,
                i - last_sell >= params['cooldown'], params, flow_rule, disabled_rules)
            action = 'BUY' if sig == 1 else 'SELL'
            fraction = 1.
            if sig == 1 and ((allocation in {'b1_half', 'b1_half_confirm'} and reason == 'b1') or
                             (allocation == 'high_vol_half' and row.get('volatility_rank_60', 0) > .8)):
                fraction = .5
            if sig:
                d.loc[date, 'signal'] = sig
                d.loc[date, 'buy_level' if sig == 1 else 'sell_reason'] = reason
            elif allocation == 'b1_half_confirm' and shares and partial_entry and not added and row.close > row.ma10:
                action, sig, reason = 'ADD', 2, 'MA10确认加仓'
            if sig:
                pending = dict(action=action, date=date, reason=reason, fraction=fraction, dev=row.deviation)
                d.loc[date, 'pending_action'] = action
        d.loc[date, 'position'] = int(shares > 0)
        total = cash + shares * row.close + (bonds * bond.close if bonds else 0)
        curve.append(dict(date=date, equity=total, cash=cash, shares=shares, idle_shares=bonds))
    columns = ['date', 'signal_date', 'action', 'price', 'price_raw', 'shares', 'close_price',
               'close_price_raw', 'buy_level', 'pnl_pct', 'hold_days', 'reason']
    return d, pd.DataFrame(curve).set_index('date'), pd.DataFrame(fills, columns=columns)
