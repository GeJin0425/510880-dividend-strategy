import pandas as pd


EXECUTION_MODES = {'same_close', 'next_close', 'next_open'}


def backtest(df, idle_price=None, initial=100000, comm=0.001, min_comm=0.0,
             signal_lag=None, execution_mode=None):
    """回测引擎：510880 与空仓期 511260 的逐日事件循环。

    ``next_open`` 在 T 日收盘生成订单，在 T+1 开盘成交，并在同一天收盘
    对持仓估值。价格计算使用前复权序列，交易明细同时记录原始（不复权）报价。
    ``signal_lag`` 仅为兼容旧调用保留；新代码应显式传 ``execution_mode``。
    """
    capital = initial
    shares = 0
    shares_idle = 0
    trades = []
    equity = []

    def fee(notional):
        return max(notional * comm, min_comm)

    if execution_mode is None:
        if signal_lag is None or signal_lag == 0:
            execution_mode = 'same_close'
        elif signal_lag == 1:
            execution_mode = 'next_close'
        else:
            raise ValueError('signal_lag only supports 0 or 1')
    if execution_mode not in EXECUTION_MODES:
        raise ValueError(f'unknown execution_mode: {execution_mode}')

    required = {'close', 'close_raw'}
    if execution_mode == 'next_open':
        required |= {'open', 'open_raw'}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f'510880缺少{execution_mode}成交所需字段: {sorted(missing)}')

    def normalize_idle(price):
        if price is None:
            return None
        if isinstance(price, pd.Series):
            idle = pd.DataFrame({'close': price})
            if execution_mode == 'next_open':
                raise ValueError('next_open模式要求511260提供前复权open与open_raw数据')
        else:
            idle = price.copy()
        needed = {'close'} | ({'open'} if execution_mode == 'next_open' else set())
        absent = needed - set(idle.columns)
        if absent:
            raise ValueError(f'511260缺少{execution_mode}成交所需字段: {sorted(absent)}')
        idle = idle.reindex(df.index)
        missing_dates = idle[list(needed)].isna().any(axis=1)
        if missing_dates.any():
            first = missing_dates[missing_dates].index[0].strftime('%Y-%m-%d')
            raise ValueError(f'510880与511260价格未对齐或缺失，首个缺失日: {first}')
        if (idle[list(needed)] <= 0).any().any():
            raise ValueError('511260价格必须为正数')
        return idle

    idle = normalize_idle(idle_price)

    def quote(row, field, asset):
        value = row[field]
        if pd.isna(value) or value <= 0:
            raise ValueError(f'{asset} {field}价格缺失或无效: {row.name:%Y-%m-%d}')
        return float(value)

    def raw_quote(row, field, fallback):
        return float(row[field]) if field in row and pd.notna(row[field]) else fallback

    pending = None
    last_buy = None

    for i in range(len(df)):
        row = df.iloc[i]
        date = df.index[i]
        close = quote(row, 'close', '510880')
        idle_close = quote(idle.loc[date], 'close', '511260') if idle is not None else None

        # 开盘阶段：只执行上一交易日收盘后已挂出的订单。
        if execution_mode == 'next_open' and pending is not None:
            execution_price = quote(row, 'open', '510880')
            execution_raw = raw_quote(row, 'open_raw', execution_price)
            idle_execution = quote(idle.loc[date], 'open', '511260') if idle is not None else None
            if pending['action'] == 'BUY' and shares == 0:
                if shares_idle > 0:
                    capital += shares_idle * idle_execution - fee(shares_idle * idle_execution)
                    shares_idle = 0
                s = int((capital - fee(capital)) / execution_price / 100) * 100
                capital -= s * execution_price + fee(s * execution_price)
                shares = s
                last_buy = {
                    'date': date, 'price': execution_price, 'price_raw': execution_raw,
                }
                trades.append({
                    'signal_date': pending['signal_date'], 'date': date, 'action': 'BUY',
                    'price': execution_price, 'price_raw': execution_raw,
                    'close_price': close, 'close_price_raw': raw_quote(row, 'close_raw', close),
                    'shares': s, 'buy_level': pending['buy_level'],
                })
            elif pending['action'] == 'SELL' and shares > 0:
                capital += shares * execution_price - fee(shares * execution_price)
                pnl = (execution_price / last_buy['price'] - 1) * 100
                trades.append({
                    'signal_date': pending['signal_date'], 'date': date, 'action': 'SELL',
                    'price': execution_price, 'price_raw': execution_raw,
                    'close_price': close, 'close_price_raw': raw_quote(row, 'close_raw', close),
                    'shares': shares, 'pnl_pct': pnl,
                    'hold_days': (date - last_buy['date']).days, 'reason': pending['reason'],
                })
                shares = 0
                if idle_execution is not None:
                    si = int((capital - fee(capital)) / idle_execution / 100) * 100
                    if si > 0:
                        capital -= si * idle_execution + fee(si * idle_execution)
                        shares_idle = si
            pending = None

        # 收盘阶段：兼容旧口径，或执行 T-1 信号的次日收盘订单。
        if execution_mode in {'same_close', 'next_close'}:
            source_i = i if execution_mode == 'same_close' else i - 1
            source = df.iloc[source_i] if source_i >= 0 else None
            sig = source['signal'] if source_i >= 0 else 0
            if sig == 1 and shares == 0:
                if shares_idle > 0:
                    capital += shares_idle * idle_close - fee(shares_idle * idle_close)
                    shares_idle = 0
                s = int((capital - fee(capital)) / close / 100) * 100
                capital -= s * close + fee(s * close)
                shares = s
                last_buy = {'date': date, 'price': close, 'price_raw': raw_quote(row, 'close_raw', close)}
                trades.append({
                    'signal_date': df.index[source_i], 'date': date, 'action': 'BUY',
                    'price': close, 'price_raw': raw_quote(row, 'close_raw', close),
                    'close_price': close, 'close_price_raw': raw_quote(row, 'close_raw', close),
                    'shares': s, 'buy_level': source.get('buy_level', ''),
                })
            elif sig == -1 and shares > 0:
                capital += shares * close - fee(shares * close)
                pnl = (close / last_buy['price'] - 1) * 100
                trades.append({
                    'signal_date': df.index[source_i], 'date': date, 'action': 'SELL',
                    'price': close, 'price_raw': raw_quote(row, 'close_raw', close),
                    'close_price': close, 'close_price_raw': raw_quote(row, 'close_raw', close),
                    'shares': shares, 'pnl_pct': pnl,
                    'hold_days': (date - last_buy['date']).days,
                    'reason': source.get('sell_reason', ''),
                })
                shares = 0
                if idle_close is not None:
                    si = int((capital - fee(capital)) / idle_close / 100) * 100
                    if si > 0:
                        capital -= si * idle_close + fee(si * idle_close)
                        shares_idle = si

        # 收盘后形成次日开盘订单。最后一个交易日的订单保留为待成交，不虚构成交。
        if execution_mode == 'next_open' and row.get('signal', 0) in (1, -1):
            pending = {
                'action': 'BUY' if row['signal'] == 1 else 'SELL',
                'signal_date': date,
                'buy_level': row.get('buy_level', ''),
                'reason': row.get('sell_reason', ''),
            }

        total = capital + (shares * close if shares > 0 else 0)
        if shares_idle > 0:
            total += shares_idle * idle_close
        equity.append({'date': date, 'equity': total})

    return pd.DataFrame(equity).set_index('date'), pd.DataFrame(trades)
