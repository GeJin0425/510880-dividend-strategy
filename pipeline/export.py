import json
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .backtest import backtest
from .event_engine import simulate
from .fetch import fetch_510880_qfq, fetch_511260_qfq
from .indicators import add_indicators
from .share_flow import add_share_flow_indicators, derive_shares_from_scale, fetch_sse_scale_history
from .strategy import PARAMS, run_strategy

SELL_TIER_ORDER = ['硬上限', 'RSI确认', '偏离回落', 'RSI下穿']
DISPLAY_START = '2018-01-01'
FLOW_RULE = {'_apply_to': {'b2', 'b3'}, 'flow_z20': 0.0}
EXECUTION_MODE = 'next_open'

# 真实交易费率: 佣金万0.5(0.005%), 单笔最低0.5元, ETF免印花税
FEE_RATE = 0.00005
FEE_MIN = 0.5


def _safe_list(series, ndigits=None):
    s = series.round(ndigits) if ndigits is not None else series
    return [None if pd.isna(v) else float(v) for v in s]


def compute_stats(df2, eq2, sells):
    first_equity = eq2['equity'].iloc[0]
    final = eq2['equity'].iloc[-1]
    years = (eq2.index[-1] - eq2.index[0]).days / 365.25
    ann = ((final / first_equity) ** (1 / years) - 1) * 100
    dd_series = (eq2['equity'] - eq2['equity'].cummax()) / eq2['equity'].cummax() * 100
    max_dd = dd_series.min()
    dr = eq2['equity'].pct_change().dropna()
    sharpe = (dr.mean() * 252 - 0.02) / (dr.std() * np.sqrt(252))
    n_trades = len(sells)
    win_rate = (sells['pnl_pct'] > 0).mean() * 100 if n_trades > 0 else 0.0
    avg_pnl = sells['pnl_pct'].mean() if n_trades > 0 else 0.0
    bh_ret = (df2.iloc[-1]['close'] / df2.iloc[0]['close'] - 1) * 100
    bh_ann = ((1 + bh_ret / 100) ** (1 / years) - 1) * 100
    stats = {
        'annualized_pct': round(float(ann), 1),
        'max_drawdown_pct': round(float(max_dd), 1),
        'sharpe': round(float(sharpe), 2),
        'win_rate_pct': round(float(win_rate), 0),
        'trade_count': int(n_trades),
        'avg_win_pct': round(float(avg_pnl), 1),
        'excess_annualized_pct': round(float(ann - bh_ann), 1),
        'buy_hold_annualized_pct': round(float(bh_ann), 1),
    }
    return stats, dd_series


def compute_holding_pct(buys, sells, df2):
    hold_days = (df2.index[-1] - df2.index[0]).days
    if hold_days <= 0:
        return 0.0
    in_pos_days = 0
    for j in range(min(len(buys), len(sells))):
        in_pos_days += (sells.iloc[j]['date'] - buys.iloc[j]['date']).days
    return round(in_pos_days / hold_days * 100, 0)


def build_current_status(df2, latest_position, p=PARAMS, position_asset=None):
    latest = df2.iloc[-1]
    dev = latest['deviation']
    rsi = latest['rsi']
    ma250_raw = latest['close_raw'] / (1 + dev / 100)
    sell_soft = ma250_raw * (1 + p['s2'] / 100)
    sell_hard = ma250_raw * (1 + p['s1'] / 100)
    buy_cap = ma250_raw * (1 + p['b3hi'] / 100)

    holding = bool(latest_position == 1)
    position_asset = position_asset or ('510880' if holding else '511260')
    latest_signal = int(latest.get('signal', 0))
    if latest_signal == 1:
        buy_level = latest.get('buy_level', '') or '买入'
        signal_text, signal_level = f'{buy_level}收盘信号触发 | 将于下一交易日开盘执行', 'buy'
    elif latest_signal == -1:
        reason = latest.get('sell_reason', '')
        signal_text, signal_level = f'卖出收盘信号触发 | 将于下一交易日开盘执行 | {reason}', 'sell'
    elif holding:
        signal_text, signal_level = '持仓510880 | 持有等待', 'neutral'
    else:
        signal_text, signal_level = ('持有现金 | 等待买入信号' if position_asset == 'cash'
                                    else '空仓国债 | 等待买入信号'), 'neutral'

    return {
        'holding': holding,
        'position_asset': position_asset,
        'date': df2.index[-1].strftime('%Y-%m-%d'),
        'price_raw': round(float(latest['close_raw']), 3),
        'ma250': round(float(latest['ma250']), 3),
        'deviation_pct': round(float(dev), 1),
        'rsi14': round(float(rsi), 0),
        'rsi6': round(float(latest['rsi6']), 0),
        'ma250_slope_pct': round(float(latest['ma250_slope']), 2),
        'share_flow_5_pct': round(float(latest['share_flow_5']) * 100, 2),
        'share_flow_20_pct': round(float(latest['share_flow_20']) * 100, 2),
        'flow_z20': round(float(latest['flow_z20']), 2),
        'sell_trigger_price_soft': round(float(sell_soft), 3),
        'sell_trigger_price_hard': round(float(sell_hard), 3),
        'buy_trigger_price_cap': round(float(buy_cap), 3),
        'signal_text': signal_text,
        'signal_level': signal_level,
    }


def build_trades(buys, sells, prices):
    """Build execution records plus close-price coordinates for signal markers."""
    def signal_close(event):
        signal_row = prices.loc[event['signal_date']]
        return (
            round(float(signal_row['close']), 3),
            round(float(signal_row['close_raw']), 3),
        )

    trades = []
    for j in range(min(len(buys), len(sells))):
        b, s = buys.iloc[j], sells.iloc[j]
        buy_signal_close, buy_signal_close_raw = signal_close(b)
        sell_signal_close, sell_signal_close_raw = signal_close(s)
        trades.append({
            'seq': j + 1,
            'buy_signal_date': b['signal_date'].strftime('%Y-%m-%d'),
            'buy_date': b['date'].strftime('%Y-%m-%d'),
            'buy_level': b.get('buy_level', ''),
            'sell_signal_date': s['signal_date'].strftime('%Y-%m-%d'),
            'sell_date': s['date'].strftime('%Y-%m-%d'),
            'buy_price': round(float(b['price']), 3),
            'sell_price': round(float(s['price']), 3),
            'buy_price_raw': round(float(b['price_raw']), 3),
            'sell_price_raw': round(float(s['price_raw']), 3),
            'buy_signal_close_price': buy_signal_close,
            'sell_signal_close_price': sell_signal_close,
            'buy_signal_close_price_raw': buy_signal_close_raw,
            'sell_signal_close_price_raw': sell_signal_close_raw,
            'buy_close_price': round(float(b['close_price']), 3),
            'sell_close_price': round(float(s['close_price']), 3),
            'buy_close_price_raw': round(float(b['close_price_raw']), 3),
            'sell_close_price_raw': round(float(s['close_price_raw']), 3),
            'pnl_pct': round(float(s['pnl_pct']), 1),
            'hold_days': int(s['hold_days']),
            'sell_reason': s['reason'],
            'open': False,
        })
    if len(buys) > len(sells):
        b = buys.iloc[len(sells)]
        buy_signal_close, buy_signal_close_raw = signal_close(b)
        cur_price = prices.iloc[-1]['close']
        cur_pnl = (cur_price / b['price'] - 1) * 100
        trades.append({
            'seq': len(sells) + 1,
            'buy_signal_date': b['signal_date'].strftime('%Y-%m-%d'),
            'buy_date': b['date'].strftime('%Y-%m-%d'),
            'buy_level': b.get('buy_level', ''),
            'sell_date': None,
            'buy_price': round(float(b['price']), 3),
            'sell_price': round(float(cur_price), 3),
            'buy_price_raw': round(float(b['price_raw']), 3),
            'sell_price_raw': round(float(prices.iloc[-1]['close_raw']), 3),
            'buy_signal_close_price': buy_signal_close,
            'sell_signal_close_price': round(float(cur_price), 3),
            'buy_signal_close_price_raw': buy_signal_close_raw,
            'sell_signal_close_price_raw': round(float(prices.iloc[-1]['close_raw']), 3),
            'buy_close_price': round(float(b['close_price']), 3),
            'sell_close_price': round(float(cur_price), 3),
            'buy_close_price_raw': round(float(b['close_price_raw']), 3),
            'sell_close_price_raw': round(float(prices.iloc[-1]['close_raw']), 3),
            'pnl_pct': round(float(cur_pnl), 1),
            'hold_days': int((prices.index[-1] - b['date']).days),
            'sell_reason': '未平仓（持有中）',
            'open': True,
        })
    return trades


def build_signals(df):
    """Close-known markers, including orders that have not executed yet."""
    return [dict(date=date.strftime('%Y-%m-%d'), action='BUY' if row['signal'] == 1 else 'SELL',
                 close=float(row['close']), reason=row.get('buy_level', '') if row['signal'] == 1
                 else row.get('sell_reason', ''), pending=i == len(df) - 1)
            for i, (date, row) in enumerate(df.iterrows()) if row['signal'] in (1, -1)]


def build_sell_reason_breakdown(sells):
    reason_map = {}
    reason_pnl = {}
    for _, s in sells.iterrows():
        for key in SELL_TIER_ORDER:
            if key in s['reason']:
                reason_map[key] = reason_map.get(key, 0) + 1
                reason_pnl.setdefault(key, []).append(s['pnl_pct'])
                break
    total = sum(reason_map.values())
    return [
        {
            'reason': k,
            'count': v,
            'avg_pnl_pct': round(float(np.mean(reason_pnl[k])), 1),
            'pct_of_total': round(v / total * 100, 0) if total else 0.0,
        }
        for k, v in reason_map.items()
    ]


def build_series(df2, eq2, dd_series):
    bh = 100000 * df2['close'] / df2.iloc[0]['close']
    eq_aligned = eq2['equity'].reindex(df2.index)
    dd_aligned = dd_series.reindex(df2.index)
    return {
        'dates': [d.strftime('%Y-%m-%d') for d in df2.index],
        'close': _safe_list(df2['close'], 3),
        'close_raw': _safe_list(df2['close_raw'], 3),
        'ma10': _safe_list(df2['ma10'], 3),
        'ma20': _safe_list(df2['ma20'], 3),
        'ma60': _safe_list(df2['ma60'], 3),
        'ma250': _safe_list(df2['ma250'], 3),
        'deviation': _safe_list(df2['deviation'], 2),
        'rsi14': _safe_list(df2['rsi'], 1),
        'rsi6': _safe_list(df2['rsi6'], 1),
        'macd': _safe_list(df2['macd'], 4),
        'macd_signal': _safe_list(df2['macd_signal'], 4),
        'macd_hist': _safe_list(df2['macd_hist'], 4),
        'share_flow_5_pct': _safe_list(df2['share_flow_5'] * 100, 2),
        'share_flow_20_pct': _safe_list(df2['share_flow_20'] * 100, 2),
        'flow_z20': _safe_list(df2['flow_z20'], 2),
        'equity_strategy': _safe_list(eq_aligned, 0),
        'equity_buyhold': _safe_list(bh, 0),
        'drawdown_pct': _safe_list(dd_aligned, 2),
    }


def export(output_path, count_510880=3000, count_511260=2500):
    raw = fetch_510880_qfq(count=count_510880)
    if len(raw) < 400:
        raise ValueError(
            f'510880数据只拉到{len(raw)}条,远少于预期,可能是接口返回被截断'
        )
    scale = fetch_sse_scale_history('510880')
    if len(scale) < 300:
        raise ValueError(f'510880规模数据只有{len(scale)}条，无法可靠计算资金流标准分')
    # Preserve price sessions. Missing scale must not skip a real execution day.
    df = add_indicators(raw).join(scale, how='left')
    first_scale = df['scale_yi'].first_valid_index()
    if first_scale is None or df.loc[first_scale:, 'scale_yi'].isna().any():
        raise ValueError('份额规模数据缺失或晚于行情更新，不能删除交易日后发布；请稍后重试')
    df['shares'] = derive_shares_from_scale(df['scale_yi'], df['close_raw'])
    df = add_share_flow_indicators(df)
    flow_start = df['flow_z20'].first_valid_index()
    if flow_start is None:
        raise ValueError('510880规模历史不足，无法计算flow_z20')
    df = df[df.index >= flow_start].copy()
    idle_price = fetch_511260_qfq(count=count_511260)
    df_sig, eq, tr = simulate(
        df, idle_price, params=PARAMS, flow_rule=FLOW_RULE, comm=FEE_RATE, min_comm=FEE_MIN,
    )

    display_start = max(pd.Timestamp(DISPLAY_START), pd.Timestamp(flow_start))
    df2 = df_sig[df_sig.index >= display_start].copy()
    eq2 = eq[eq.index >= display_start].copy()
    buys = tr[(tr['action'] == 'BUY') & (tr['date'] >= display_start)].reset_index(drop=True)
    sells = tr[(tr['action'] == 'SELL') & (tr['date'] >= display_start)].reset_index(drop=True)

    stats, dd_series = compute_stats(df2, eq2, sells)
    stats['holding_pct'] = compute_holding_pct(buys, sells, df2)

    beijing_now = datetime.now(timezone(timedelta(hours=8)))

    payload = {
        'meta': {
            **stats,
            'fee_rate': FEE_RATE,
            'min_fee': FEE_MIN,
            'strategy_version': 'flow_z20_on_b2_b3',
            'execution_mode': EXECUTION_MODE,
            'flow_data_source': 'SSE scale / raw close',
            'updated_at': beijing_now.isoformat(),
            'as_of_date': df2.index[-1].strftime('%Y-%m-%d'),
        },
        'current_status': build_current_status(
            df2,
            int(df2.iloc[-1]['position']),
            position_asset='510880' if eq.iloc[-1]['shares'] > 0 else
                           ('511260' if eq.iloc[-1]['idle_shares'] > 0 else 'cash'),
        ),
        'series': build_series(df2, eq2, dd_series),
        'signals': build_signals(df2),
        'trades': build_trades(buys, sells, df_sig),
        'sell_reason_breakdown': build_sell_reason_breakdown(sells),
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, allow_nan=False)
    return payload


if __name__ == '__main__':
    site_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'site')
    os.makedirs(site_dir, exist_ok=True)
    export(os.path.join(site_dir, 'data.json'))
