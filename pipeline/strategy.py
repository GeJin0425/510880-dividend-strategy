import pandas as pd

PARAMS = dict(
    b1=-2.5, b2=1.0, b2r=30.0, b3lo=0.0, b3hi=5.0,
    s1=16.0, s2=4.0, s2r=75.0, s3pk=6.0, s3dp=2.5,
    s4pr=4.5, s4r=67.5, cooldown=12,
)

PARAMS_VERSION = 'next_open_candidate_a'


def close_decision(row, prev, holding, entry_price, max_dev, cooled_down,
                   p=PARAMS, flow_rule=None, disabled_rules=()):
    """Pure close-time decision driven by filled position, not assumed orders."""
    if pd.isna(row['ma250']) or pd.isna(row['rsi']):
        return 0, '', max_dev
    dev, rsi = row['deviation'], row['rsi']
    if not holding:
        if not cooled_down:
            return 0, '', max_dev
        level = ''
        if dev < p['b1']:
            level = 'b1'
        elif dev < p['b2'] and rsi < p['b2r']:
            level = 'b2'
        elif p['b3lo'] <= dev <= p['b3hi'] and row['ma250_slope'] > 0 and row['close'] > row['ma10']:
            level = 'b3'
        if level and level not in disabled_rules and _flow_allows_entry(row, flow_rule, level):
            return 1, level, dev
        return 0, '', max_dev
    max_dev = max(max_dev, dev)
    profit = (row['close'] / entry_price - 1) * 100
    reason = ''
    if 's1' not in disabled_rules and dev >= p['s1']:
        reason = f'硬上限:{dev:.1f}%'
    elif 's2' not in disabled_rules and dev >= p['s2'] and rsi >= p['s2r']:
        reason = f'RSI确认:RSI={rsi:.0f},偏离{dev:.1f}%'
    elif 's3' not in disabled_rules and max_dev >= p['s3pk'] and dev < max_dev - p['s3dp']:
        reason = f'偏离回落:{max_dev:.1f}%→{dev:.1f}%'
    elif 's4' not in disabled_rules and profit >= p['s4pr'] and rsi < p['s4r'] <= prev['rsi']:
        reason = f'RSI下穿{p["s4r"]:.0f}:+{profit:.1f}%'
    return (-1 if reason else 0), reason, max_dev


def _flow_allows_entry(row, flow_rule, buy_level):
    """Return whether an otherwise-valid entry passes an optional flow rule."""
    if not flow_rule:
        return True
    apply_to = flow_rule.get('_apply_to')
    if apply_to and buy_level not in apply_to:
        return True
    for column, minimum in flow_rule.items():
        if column.startswith('_'):
            continue
        value = row.get(column)
        if pd.isna(value) or value < minimum:
            return False
    return True


def run_strategy(df, p=PARAMS, flow_rule=None, execution_mode='same_close', disabled_rules=()):
    """在逐日循环中形成信号，并在 ``next_open`` 时按真实开盘入场价管理仓位。"""
    if execution_mode not in {'same_close', 'next_open'}:
        raise ValueError(f'unsupported execution_mode: {execution_mode}')
    if execution_mode == 'next_open' and 'open' not in df:
        raise ValueError('next_open模式需要前复权open列')
    d = df.copy()
    d['signal'] = 0
    d['buy_level'] = ''
    d['sell_reason'] = ''
    d['position'] = 0
    d['pending_action'] = ''
    pos = 0
    last_sell = -999
    ctx = {}
    pending = None

    for i in range(1, len(d)):
        row = d.iloc[i]
        prev = d.iloc[i - 1]

        # T-1 收盘信号在今天开盘成交；之后才可使用今天收盘指标产生新信号。
        if execution_mode == 'next_open' and pending is not None:
            if pending['action'] == 'BUY':
                pos = 1
                ctx = {'entry_price': row['open'], 'max_dev': pending['deviation']}
            else:
                pos = 0
                last_sell = i
                ctx = {}
            pending = None
        if pd.isna(row['ma250']) or pd.isna(row['rsi']):
            d.iloc[i, d.columns.get_loc('position')] = pos
            continue

        dev = row['deviation']
        rsi = row['rsi']

        if pending is None and pos == 0 and (i - last_sell) >= p['cooldown']:
            buy = False
            buy_level = ''
            if dev < p['b1']:
                buy = True
                buy_level = 'b1'
            elif dev < p['b2'] and rsi < p['b2r']:
                buy = True
                buy_level = 'b2'
            else:
                slope = row['ma250_slope'] if not pd.isna(row['ma250_slope']) else 0
                above_ma10 = row['close'] > row['ma10'] if not pd.isna(row['ma10']) else False
                if p['b3lo'] <= dev <= p['b3hi'] and slope > 0 and above_ma10:
                    buy = True
                    buy_level = 'b3'
            if buy and buy_level not in disabled_rules and _flow_allows_entry(row, flow_rule, buy_level):
                d.iloc[i, d.columns.get_loc('signal')] = 1
                d.iloc[i, d.columns.get_loc('buy_level')] = buy_level
                if execution_mode == 'next_open':
                    pending = {'action': 'BUY', 'deviation': dev}
                    d.iloc[i, d.columns.get_loc('pending_action')] = 'BUY'
                else:
                    pos = 1
                    ctx = {'entry_price': row['close'], 'max_dev': dev}

        elif pending is None and pos == 1:
            ctx['max_dev'] = max(ctx.get('max_dev', 0), dev)
            max_dev = ctx['max_dev']
            profit = (row['close'] / ctx.get('entry_price', row['close']) - 1) * 100
            sell = False
            reason = ''

            if 's1' not in disabled_rules and dev >= p['s1']:
                sell, reason = True, f'硬上限:{dev:.1f}%'
            elif 's2' not in disabled_rules and dev >= p['s2'] and rsi >= p['s2r']:
                sell, reason = True, f'RSI确认:RSI={rsi:.0f},偏离{dev:.1f}%'
            elif 's3' not in disabled_rules and max_dev >= p['s3pk'] and dev < max_dev - p['s3dp']:
                sell, reason = True, f'偏离回落:{max_dev:.1f}%→{dev:.1f}%'
            elif 's4' not in disabled_rules and profit >= p['s4pr'] and rsi < p['s4r'] and prev['rsi'] >= p['s4r']:
                sell, reason = True, f'RSI下穿{p["s4r"]:.0f}:+{profit:.1f}%'

            if sell:
                d.iloc[i, d.columns.get_loc('signal')] = -1
                d.iloc[i, d.columns.get_loc('sell_reason')] = reason
                if execution_mode == 'next_open':
                    pending = {'action': 'SELL'}
                    d.iloc[i, d.columns.get_loc('pending_action')] = 'SELL'
                else:
                    pos = 0
                    last_sell = i
                    ctx = {}

        d.iloc[i, d.columns.get_loc('position')] = pos
    return d
