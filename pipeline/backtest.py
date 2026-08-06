import pandas as pd


def backtest(df, idle_price=None, initial=100000, comm=0.001):
    """回测引擎: 持仓510880 + 空仓期买入十年国债ETF"""
    capital = initial
    shares = 0
    shares_idle = 0
    trades = []
    equity = []

    for i in range(len(df)):
        sig = df.iloc[i]['signal']
        close = df.iloc[i]['close']
        date = df.index[i]
        idle_close = idle_price.loc[date] if (idle_price is not None and date in idle_price.index) else None

        if sig == 1 and shares == 0:
            if shares_idle > 0 and idle_close:
                capital += shares_idle * idle_close * (1 - comm)
                shares_idle = 0
            s = int((capital * (1 - comm)) / close / 100) * 100
            capital -= s * close * (1 + comm)
            shares = s
            trades.append({
                'date': date, 'action': 'BUY', 'price': close, 'shares': s,
                'price_raw': df.iloc[i]['close_raw'],
            })
        elif sig == -1 and shares > 0:
            capital += shares * close * (1 - comm)
            pnl = (close / trades[-1]['price'] - 1) * 100
            trades.append({
                'date': date, 'action': 'SELL', 'price': close, 'shares': shares,
                'price_raw': df.iloc[i]['close_raw'],
                'pnl_pct': pnl, 'hold_days': (date - trades[-1]['date']).days,
                'reason': df.iloc[i]['sell_reason'],
            })
            shares = 0
            if idle_close and idle_close > 0:
                si = int((capital * (1 - comm)) / idle_close / 100) * 100
                if si > 0:
                    capital -= si * idle_close * (1 + comm)
                    shares_idle = si

        total = capital + (shares * close if shares > 0 else 0)
        if shares_idle > 0 and idle_close:
            total += shares_idle * idle_close
        equity.append({'date': date, 'equity': total})

    return pd.DataFrame(equity).set_index('date'), pd.DataFrame(trades)
