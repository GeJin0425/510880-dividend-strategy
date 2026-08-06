# 510880 GitHub Pages 仪表盘 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把`红利研究/`里已验证的510880 MA250策略数据管线迁移到独立仓库`GeJin0425/510880-dividend-strategy`，每日通过GitHub Actions自动生成JSON并发布为深色终端风交互式仪表盘（GitHub Pages）。

**Architecture:** Python数据管线(`pipeline/`)每次运行抓取510880/511260行情→计算指标/信号/回测→导出`site/data.json`；纯静态前端(`site/`)用Apache ECharts渲染交互图表；GitHub Actions每日定时运行管线并用官方`upload-pages-artifact`+`deploy-pages`直接发布，不将数据提交回git。

**Tech Stack:** Python 3.12 + pandas/numpy/requests，pytest测试；前端纯HTML/CSS/JS + Apache ECharts(CDN)；GitHub Actions + GitHub Pages。

## Global Constraints

- 仓库`GeJin0425/510880-dividend-strategy`，公开(public)可见（已创建）
- 范围仅510880（不含512890、空仓轮动）
- 深色终端配色：背景`#0d1117`、正文`#c9d1d9`、多头/买入`#3fb950`、空头/卖出`#f85149`、强调蓝`#58a6ff`、网格`#21262d`
- 数据展示窗口从`2018-01-01`起（`DISPLAY_START`），与现有matplotlib仪表盘一致
- 每日生成的`data.json`**不提交到git**，只作为Pages部署产物发布
- Cron定时UTC `07:40`（北京15:40）+ 支持`workflow_dispatch`手动触发
- JSON输出中不能出现裸`NaN`（非法JSON token），缺失值必须序列化为`null`
- 页面必须包含免责声明："本页面为个人量化研究记录，不构成投资建议。历史回测结果不代表未来收益。"
- 指标计算逻辑（MA/RSI/MACD/偏离度/M3+买卖信号/回测）与`红利研究/src/visualize_final.py`保持完全一致，不重新设计策略参数
- 每一个Python模块任务必须先写失败的测试再实现（TDD），前端任务用手动浏览器验证清单替代自动化测试

---

### Task 1: 项目骨架 + 依赖 + Ashare数据接口

**Files:**
- Create: `.gitignore`
- Create: `requirements.txt`
- Create: `pipeline/__init__.py`
- Create: `pipeline/Ashare.py`（从`/Users/ge/Desktop/Stock/红利研究/src/Ashare.py`原样复制，第三方代码不改动）
- Create: `README.md`

**Interfaces:**
- Produces: `pipeline.Ashare.get_price(code, end_date='', count=10, frequency='1d', fields=[])` — 返回以`date`为索引、含`open/close/high/low/volume`列的`DataFrame`。后续Task 2直接依赖此函数。

- [ ] **Step 1: 创建 `.gitignore`**

```
.venv/
__pycache__/
*.pyc
site/data.json
.DS_Store
```

- [ ] **Step 2: 创建 `requirements.txt`**

```
pandas>=2.0
numpy>=1.24
requests>=2.31
pytest>=7.4
```

- [ ] **Step 3: 创建Python虚拟环境并安装依赖**

```bash
cd /Users/ge/Desktop/Stock/510880-dividend-strategy
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

- [ ] **Step 4: 复制 Ashare.py**

```bash
mkdir -p pipeline
cp /Users/ge/Desktop/Stock/红利研究/src/Ashare.py pipeline/Ashare.py
touch pipeline/__init__.py
```

- [ ] **Step 5: 创建 README.md**

```markdown
# 510880 红利ETF · MA250策略仪表盘

上证红利ETF(510880)的MA250均值回归策略研究，每日自动更新的公开仪表盘。

**策略摘要**：价格接近MA250时买入，远离MA250时卖出；空仓期配置511260十年国债ETF。2018年至今回测年化约+20%，最大回撤-13.9%，26笔交易全部盈利（历史数据，不代表未来收益）。

- 在线仪表盘：https://gejin0425.github.io/510880-dividend-strategy/
- 每日北京时间15:40自动抓取行情、重新计算指标并发布（GitHub Actions）
- 详细设计文档：[docs/superpowers/specs/2026-08-06-github-pages-dashboard-design.md](docs/superpowers/specs/2026-08-06-github-pages-dashboard-design.md)

## 本地开发

\`\`\`bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pipeline.export        # 生成 site/data.json
python -m http.server 8000 --directory site   # 本地预览
\`\`\`

## 免责声明

本仓库是个人量化研究记录，不构成投资建议。历史回测结果不代表未来收益。
```

- [ ] **Step 6: Commit**

```bash
git add .gitignore requirements.txt pipeline/__init__.py pipeline/Ashare.py README.md
git commit -m "chore: scaffold repo, add Ashare data client and deps"
```

---

### Task 2: `pipeline/fetch.py` — 行情获取 + 前复权

**Files:**
- Create: `pipeline/fetch.py`
- Create: `tests/test_fetch.py`

**Interfaces:**
- Consumes: `pipeline.Ashare.get_price(code, frequency='1d', count=N)`（Task 1）
- Produces:
  - `apply_qfq(df, dividends) -> DataFrame`，输入含`open/close/high/low/volume`列、`DatetimeIndex`的不复权`DataFrame`，输出新增`close_raw/high_raw/low_raw/adjust_factor`列的前复权`DataFrame`（Task 6依赖此列结构）
  - `fetch_510880_qfq(count=3000) -> DataFrame`
  - `fetch_511260_close(count=2500) -> Series`（收盘价序列，索引为日期）

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_fetch.py`：

```python
import pandas as pd

from pipeline.fetch import apply_qfq, fetch_510880_qfq, fetch_511260_close


def test_apply_qfq_single_dividend():
    dates = pd.to_datetime(['2020-01-15', '2020-01-16', '2020-01-17', '2020-01-20'])
    df = pd.DataFrame({
        'open':  [10.0, 10.0, 10.0, 10.2],
        'close': [10.0, 10.0, 10.0, 10.2],
        'high':  [10.1, 10.1, 10.1, 10.3],
        'low':   [9.9, 9.9, 9.9, 10.1],
        'volume': [1000, 1000, 1000, 1000],
    }, index=dates)
    dividends = [('2020-01-17', 0.20)]

    out = apply_qfq(df, dividends)

    assert out.loc['2020-01-17', 'adjust_factor'] == 1.0
    assert out.loc['2020-01-17', 'close'] == 10.0
    assert out.loc['2020-01-20', 'close'] == 10.2

    expected_factor = round((10.0 - 0.20) / 10.0, 6)
    assert out.loc['2020-01-15', 'adjust_factor'] == expected_factor
    assert out.loc['2020-01-15', 'close'] == round(10.0 * expected_factor, 3)

    assert out.loc['2020-01-15', 'close_raw'] == 10.0
    assert out.loc['2020-01-20', 'close_raw'] == 10.2


def test_fetch_510880_qfq_applies_dividends(monkeypatch):
    dates = pd.date_range('2018-01-01', periods=5, freq='D')
    fixture = pd.DataFrame({
        'open': [1.0] * 5, 'close': [1.0] * 5,
        'high': [1.0] * 5, 'low': [1.0] * 5,
        'volume': [100] * 5,
    }, index=dates)

    def fake_get_price(code, frequency='1d', count=10):
        assert code == 'sh510880'
        return fixture

    monkeypatch.setattr('pipeline.fetch.get_price', fake_get_price)
    out = fetch_510880_qfq(count=5)

    assert list(out.columns) == [
        'open', 'close', 'high', 'low', 'volume',
        'close_raw', 'high_raw', 'low_raw', 'adjust_factor',
    ]
    assert len(out) == 5


def test_fetch_511260_close_returns_close_series(monkeypatch):
    dates = pd.date_range('2018-01-01', periods=3, freq='D')
    fixture = pd.DataFrame({
        'open': [2.0, 2.0, 2.0], 'close': [2.1, 2.2, 2.3],
        'high': [2.1] * 3, 'low': [2.0] * 3, 'volume': [10] * 3,
    }, index=dates)

    def fake_get_price(code, frequency='1d', count=10):
        assert code == 'sh511260'
        return fixture

    monkeypatch.setattr('pipeline.fetch.get_price', fake_get_price)
    out = fetch_511260_close(count=3)

    assert out.tolist() == [2.1, 2.2, 2.3]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_fetch.py -v`
Expected: FAIL，报错 `ModuleNotFoundError: No module named 'pipeline.fetch'`

- [ ] **Step 3: 实现 `pipeline/fetch.py`**

```python
import numpy as np
import pandas as pd

from .Ashare import get_price

DIVIDENDS_510880 = [
    ('2026-01-21', 0.1430),
    ('2025-01-21', 0.1420),
    ('2024-01-23', 0.1310),
    ('2023-01-16', 0.1380),
    ('2022-01-17', 0.0860),
    ('2021-01-18', 0.1410),
    ('2020-01-17', 0.1440),
    ('2019-01-16', 0.0980),
    ('2018-01-23', 0.1090),
    ('2017-01-23', 0.0910),
    ('2016-01-20', 0.0500),
    ('2015-01-20', 0.0800),
    ('2014-01-21', 0.0590),
]


def apply_qfq(df, dividends):
    """对不复权日线做前复权调整，返回新增 close_raw/high_raw/low_raw/adjust_factor 列的DataFrame"""
    df = df.sort_index()
    factor = np.ones(len(df))
    for ex_str, div in dividends:
        ex = pd.Timestamp(ex_str)
        mask = df.index < ex
        if mask.any():
            prev_close = df.loc[mask, 'close'].iloc[-1]
            ex_idx = df.index.get_indexer([ex], method='nearest')[0]
            factor[:ex_idx] *= (prev_close - div) / prev_close

    return pd.DataFrame({
        'open': (df['open'].values * factor).round(3),
        'close': (df['close'].values * factor).round(3),
        'high': (df['high'].values * factor).round(3),
        'low': (df['low'].values * factor).round(3),
        'volume': df['volume'].values,
        'close_raw': df['close'].values,
        'high_raw': df['high'].values,
        'low_raw': df['low'].values,
        'adjust_factor': factor.round(6),
    }, index=df.index)


def fetch_510880_qfq(count=3000):
    """拉取510880不复权日线并应用前复权"""
    raw = get_price('sh510880', frequency='1d', count=count)
    return apply_qfq(raw, DIVIDENDS_510880)


def fetch_511260_close(count=2500):
    """拉取511260十年国债ETF收盘价序列（空仓期配置资产）"""
    raw = get_price('sh511260', frequency='1d', count=count)
    return raw['close']
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_fetch.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add pipeline/fetch.py tests/test_fetch.py
git commit -m "feat: add 510880/511260 data fetch with qfq dividend adjustment"
```

---

### Task 3: `pipeline/indicators.py` — MA/RSI/MACD/偏离度

**Files:**
- Create: `pipeline/indicators.py`
- Create: `tests/test_indicators.py`

**Interfaces:**
- Consumes: 任意含`open/close/high/low/volume`列、`DatetimeIndex`的`DataFrame`（如Task 2输出）
- Produces: `add_indicators(df) -> DataFrame`，新增列 `ma10/ma20/ma60/ma250/deviation/ma250_slope/rsi/rsi6/macd/macd_signal/macd_hist`（Task 4、Task 6依赖这些列名）

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_indicators.py`：

```python
import numpy as np
import pandas as pd

from pipeline.indicators import add_indicators


def test_add_indicators_ma_deviation_rsi_macd():
    dates = pd.date_range('2020-01-01', periods=300, freq='D')
    close = pd.Series(np.linspace(10, 20, 300), index=dates)
    df = pd.DataFrame({
        'open': close, 'close': close, 'high': close, 'low': close,
        'volume': 1000,
    }, index=dates)

    out = add_indicators(df)

    assert out['ma10'].iloc[9] == close.iloc[0:10].mean()
    assert out['ma250'].iloc[249] == close.iloc[0:250].mean()
    assert out['deviation'].iloc[-1] > 0  # 持续上涨，收盘价高于MA250
    assert out['rsi'].iloc[-1] > 50       # 持续上涨，RSI偏多头区间
    assert {'macd', 'macd_signal', 'macd_hist'}.issubset(out.columns)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_indicators.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'pipeline.indicators'`

- [ ] **Step 3: 实现 `pipeline/indicators.py`**

```python
def add_indicators(df):
    d = df.copy()
    d['ma10'] = d['close'].rolling(10).mean()
    d['ma20'] = d['close'].rolling(20).mean()
    d['ma60'] = d['close'].rolling(60).mean()
    d['ma250'] = d['close'].rolling(250).mean()
    d['deviation'] = (d['close'] - d['ma250']) / d['ma250'] * 100
    d['ma250_slope'] = (d['ma250'] - d['ma250'].shift(10)) / d['ma250'].shift(10) * 100

    delta = d['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    ag14 = gain.ewm(alpha=1 / 14, min_periods=14).mean()
    al14 = loss.ewm(alpha=1 / 14, min_periods=14).mean()
    d['rsi'] = 100 - 100 / (1 + ag14 / al14)
    ag6 = gain.ewm(alpha=1 / 6, min_periods=6).mean()
    al6 = loss.ewm(alpha=1 / 6, min_periods=6).mean()
    d['rsi6'] = 100 - 100 / (1 + ag6 / al6)

    ema12 = d['close'].ewm(span=12).mean()
    ema26 = d['close'].ewm(span=26).mean()
    d['macd'] = ema12 - ema26
    d['macd_signal'] = d['macd'].ewm(span=9).mean()
    d['macd_hist'] = d['macd'] - d['macd_signal']
    return d
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_indicators.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add pipeline/indicators.py tests/test_indicators.py
git commit -m "feat: add MA/deviation/RSI/MACD indicator calculation"
```

---

### Task 4: `pipeline/strategy.py` — M3+买卖信号状态机

**Files:**
- Create: `pipeline/strategy.py`
- Create: `tests/test_strategy.py`

**Interfaces:**
- Consumes: 含`close/ma10/ma250/ma250_slope/deviation/rsi`列的`DataFrame`（Task 3输出）
- Produces: `PARAMS: dict`；`run_strategy(df, p=PARAMS) -> DataFrame`，新增列`signal`(1=买/-1=卖/0=无操作)、`sell_reason`(str)、`position`(0/1)（Task 5依赖`signal/sell_reason/position`列）

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_strategy.py`：

```python
import pandas as pd

from pipeline.strategy import PARAMS, run_strategy


def _row(close, ma250, rsi, ma10=None, slope=0.1):
    dev = (close - ma250) / ma250 * 100
    return dict(
        close=close, ma250=ma250, deviation=dev, rsi=rsi,
        ma10=ma10 if ma10 is not None else close, ma250_slope=slope,
    )


def test_run_strategy_extreme_buy_then_hard_sell():
    rows = [_row(100, 100, 50) for _ in range(3)]  # 平盘期，above_ma10不成立，不会误触发L3买入
    rows.append(_row(97, 100, 50))    # dev=-3% < b1(-2%) -> L1买入
    rows.append(_row(114, 100, 50))   # dev=14% >= s1(14%) -> 硬上限卖出
    df = pd.DataFrame(rows)

    out = run_strategy(df, p=PARAMS)

    assert out['signal'].iloc[3] == 1
    assert out['signal'].iloc[4] == -1
    assert '硬上限' in out['sell_reason'].iloc[4]
    assert out['position'].iloc[4] == 0
    assert out['position'].iloc[3] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_strategy.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'pipeline.strategy'`

- [ ] **Step 3: 实现 `pipeline/strategy.py`**

```python
import pandas as pd

PARAMS = dict(
    b1=-2.0, b2=0.0, b2r=35.0, b3lo=0.0, b3hi=4.0,
    s1=14.0, s2=7.0, s2r=75.0, s3pk=6.0, s3dp=2.0,
    s4pr=4.0, s4r=65.0, cooldown=10,
)


def run_strategy(df, p=PARAMS):
    d = df.copy()
    d['signal'] = 0
    d['sell_reason'] = ''
    d['position'] = 0
    pos = 0
    last_sell = -999
    ctx = {}

    for i in range(1, len(d)):
        row = d.iloc[i]
        prev = d.iloc[i - 1]
        if pd.isna(row['ma250']) or pd.isna(row['rsi']):
            d.iloc[i, d.columns.get_loc('position')] = pos
            continue

        dev = row['deviation']
        rsi = row['rsi']

        if pos == 0 and (i - last_sell) >= p['cooldown']:
            buy = False
            if dev < p['b1']:
                buy = True
            elif dev < p['b2'] and rsi < p['b2r']:
                buy = True
            else:
                slope = row['ma250_slope'] if not pd.isna(row['ma250_slope']) else 0
                above_ma10 = row['close'] > row['ma10'] if not pd.isna(row['ma10']) else False
                if p['b3lo'] <= dev <= p['b3hi'] and slope > 0 and above_ma10:
                    buy = True
            if buy:
                d.iloc[i, d.columns.get_loc('signal')] = 1
                pos = 1
                ctx = {'entry_price': row['close'], 'max_dev': dev}

        elif pos == 1:
            ctx['max_dev'] = max(ctx.get('max_dev', 0), dev)
            max_dev = ctx['max_dev']
            profit = (row['close'] / ctx.get('entry_price', row['close']) - 1) * 100
            sell = False
            reason = ''

            if dev >= p['s1']:
                sell, reason = True, f'硬上限:{dev:.1f}%'
            elif dev >= p['s2'] and rsi >= p['s2r']:
                sell, reason = True, f'RSI确认:RSI={rsi:.0f},偏离{dev:.1f}%'
            elif max_dev >= p['s3pk'] and dev < max_dev - p['s3dp']:
                sell, reason = True, f'偏离回落:{max_dev:.1f}%→{dev:.1f}%'
            elif profit >= p['s4pr'] and rsi < p['s4r'] and prev['rsi'] >= p['s4r']:
                sell, reason = True, f'RSI下穿{p["s4r"]:.0f}:+{profit:.1f}%'

            if sell:
                d.iloc[i, d.columns.get_loc('signal')] = -1
                d.iloc[i, d.columns.get_loc('sell_reason')] = reason
                pos = 0
                last_sell = i
                ctx = {}

        d.iloc[i, d.columns.get_loc('position')] = pos
    return d
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_strategy.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add pipeline/strategy.py tests/test_strategy.py
git commit -m "feat: port M3+ buy/sell signal state machine"
```

---

### Task 5: `pipeline/backtest.py` — 交易回测引擎

**Files:**
- Create: `pipeline/backtest.py`
- Create: `tests/test_backtest.py`

**Interfaces:**
- Consumes: 含`close/close_raw/signal/sell_reason`列的`DataFrame`（Task 4输出），可选`idle_price: Series`（Task 2的`fetch_511260_close`输出）
- Produces: `backtest(df, idle_price=None, initial=100000, comm=0.001) -> (equity_df, trades_df)`。`equity_df`索引为日期、列`equity`；`trades_df`列包括`date/action/price/shares/price_raw`，SELL行额外含`pnl_pct/hold_days/reason`（Task 6依赖这些列名）

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_backtest.py`：

```python
import pandas as pd
import pytest

from pipeline.backtest import backtest


def test_backtest_single_round_trip_no_idle():
    dates = pd.date_range('2020-01-01', periods=3, freq='D')
    df = pd.DataFrame({
        'close': [10.0, 11.0, 12.0],
        'close_raw': [10.0, 11.0, 12.0],
        'signal': [1, 0, -1],
        'sell_reason': ['', '', '涨够了'],
    }, index=dates)

    eq, tr = backtest(df, idle_price=None, initial=100000, comm=0.0)

    assert len(tr) == 2
    assert tr.iloc[0]['action'] == 'BUY'
    assert tr.iloc[1]['action'] == 'SELL'
    assert tr.iloc[1]['pnl_pct'] == pytest.approx((12.0 / 10.0 - 1) * 100)
    assert eq['equity'].iloc[-1] > 100000
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_backtest.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'pipeline.backtest'`

- [ ] **Step 3: 实现 `pipeline/backtest.py`**

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_backtest.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add pipeline/backtest.py tests/test_backtest.py
git commit -m "feat: add 510880+511260 idle-rotation backtest engine"
```

---

### Task 6: `pipeline/export.py` — 汇总为 `site/data.json`

**Files:**
- Create: `pipeline/export.py`
- Create: `tests/test_export.py`
- Create: `site/`（空目录，`data.json`由脚本运行时生成，不提交）

**Interfaces:**
- Consumes: `fetch_510880_qfq`/`fetch_511260_close`（Task 2）、`add_indicators`（Task 3）、`run_strategy`/`PARAMS`（Task 4）、`backtest`（Task 5）
- Produces: `export(output_path, count_510880=3000, count_511260=2500) -> dict`，写出并返回如下结构的JSON（Task 8/9的`app.js`直接消费这个schema，字段名必须完全一致）：

```
{
  "meta": {
    "annualized_pct": float, "max_drawdown_pct": float, "sharpe": float,
    "win_rate_pct": float, "trade_count": int, "avg_win_pct": float,
    "excess_annualized_pct": float, "buy_hold_annualized_pct": float,
    "holding_pct": float, "updated_at": "ISO8601字符串", "as_of_date": "YYYY-MM-DD"
  },
  "current_status": {
    "holding": bool, "position_asset": "510880"|"511260", "date": "YYYY-MM-DD",
    "price_raw": float, "ma250": float, "deviation_pct": float,
    "rsi14": float, "rsi6": float, "ma250_slope_pct": float,
    "sell_trigger_price_soft": float, "sell_trigger_price_hard": float,
    "buy_trigger_price_cap": float,
    "signal_text": str, "signal_level": "buy"|"sell"|"watch"|"neutral"
  },
  "series": {
    "dates": [str], "close": [float|null], "close_raw": [float|null],
    "ma10": [float|null], "ma20": [float|null], "ma60": [float|null], "ma250": [float|null],
    "deviation": [float|null], "rsi14": [float|null], "rsi6": [float|null],
    "macd": [float|null], "macd_signal": [float|null], "macd_hist": [float|null],
    "equity_strategy": [float|null], "equity_buyhold": [float|null], "drawdown_pct": [float|null]
  },
  "trades": [{"seq": int, "buy_date": str, "sell_date": str|null, "buy_price_raw": float,
              "sell_price_raw": float, "pnl_pct": float, "hold_days": int,
              "sell_reason": str, "open": bool}],
  "sell_reason_breakdown": [{"reason": str, "count": int, "avg_pnl_pct": float, "pct_of_total": float}]
}
```

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_export.py`：

```python
import json

import numpy as np
import pandas as pd

import pipeline.export as export_mod


def _build_fixture():
    dates = pd.date_range('2018-01-01', periods=300, freq='D')
    prices = np.concatenate([
        np.full(260, 100.0),               # 260天平盘，喂饱MA250热身期
        [95.0],                             # 急跌 -> 偏离度<-2% 触发L1买入
        np.linspace(96.0, 118.0, 19),        # 连续拉升
        np.full(20, 118.0),                 # 高位横盘
    ])
    df = pd.DataFrame({
        'open': prices, 'close': prices, 'high': prices, 'low': prices,
        'volume': np.full(300, 1_000_000.0),
        'close_raw': prices, 'high_raw': prices, 'low_raw': prices,
        'adjust_factor': np.ones(300),
    }, index=dates)
    idle = pd.Series(np.full(300, 100.0), index=dates)
    return df, idle


def test_export_end_to_end(tmp_path, monkeypatch):
    fixture_df, fixture_idle = _build_fixture()
    monkeypatch.setattr(export_mod, 'fetch_510880_qfq', lambda count=3000: fixture_df)
    monkeypatch.setattr(export_mod, 'fetch_511260_close', lambda count=2500: fixture_idle)
    # 跳过前250+天MA250热身期，避免展示窗口内出现NaN
    monkeypatch.setattr(export_mod, 'DISPLAY_START', fixture_df.index[255].strftime('%Y-%m-%d'))

    out_path = tmp_path / 'data.json'
    payload = export_mod.export(str(out_path))

    assert out_path.exists()
    reloaded = json.loads(out_path.read_text(encoding='utf-8'))
    assert reloaded == payload

    assert payload['meta']['trade_count'] >= 1
    assert len(payload['trades']) >= 1
    assert payload['trades'][0]['sell_reason']
    assert payload['current_status']['date'] == fixture_df.index[-1].strftime('%Y-%m-%d')
    for key in ('dates', 'close', 'ma250', 'rsi14', 'macd', 'equity_strategy'):
        assert key in payload['series']
        assert len(payload['series'][key]) == len(payload['series']['dates'])
    assert 'NaN' not in out_path.read_text(encoding='utf-8')


def test_build_current_status_sell_signal_triggered():
    dates = pd.date_range('2020-01-01', periods=1)
    df2 = pd.DataFrame({
        'close_raw': [10.7], 'deviation': [7.5], 'rsi': [80.0], 'rsi6': [82.0],
        'ma250': [10.0], 'ma250_slope': [0.3],
    }, index=dates)
    status = export_mod.build_current_status(df2, latest_position=1)
    assert status['holding'] is True
    assert status['signal_level'] == 'sell'
    assert status['signal_text'] == '卖出信号触发!'


def test_build_current_status_idle_buy_triggered():
    dates = pd.date_range('2020-01-01', periods=1)
    df2 = pd.DataFrame({
        'close_raw': [9.7], 'deviation': [-3.0], 'rsi': [30.0], 'rsi6': [28.0],
        'ma250': [10.0], 'ma250_slope': [-0.1],
    }, index=dates)
    status = export_mod.build_current_status(df2, latest_position=0)
    assert status['holding'] is False
    assert status['signal_level'] == 'buy'
    assert status['signal_text'] == '空仓国债 | 极端买入触发!'


def test_build_sell_reason_breakdown_groups_by_tier():
    sells = pd.DataFrame([
        {'reason': '硬上限:15.0%', 'pnl_pct': 8.0},
        {'reason': 'RSI确认:RSI=80,偏离8.0%', 'pnl_pct': 6.0},
        {'reason': 'RSI确认:RSI=76,偏离9.0%', 'pnl_pct': 4.0},
    ])
    breakdown = export_mod.build_sell_reason_breakdown(sells)
    by_reason = {b['reason']: b for b in breakdown}
    assert by_reason['RSI确认']['count'] == 2
    assert by_reason['RSI确认']['avg_pnl_pct'] == 5.0
    assert by_reason['硬上限']['count'] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_export.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'pipeline.export'`

- [ ] **Step 3: 实现 `pipeline/export.py`**

```python
import json
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .backtest import backtest
from .fetch import fetch_510880_qfq, fetch_511260_close
from .indicators import add_indicators
from .strategy import PARAMS, run_strategy

SELL_TIER_ORDER = ['硬上限', 'RSI确认', '偏离回落', 'RSI下穿']
DISPLAY_START = '2018-01-01'


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


def build_current_status(df2, latest_position):
    latest = df2.iloc[-1]
    dev = latest['deviation']
    rsi = latest['rsi']
    ma250_raw = latest['close_raw'] / (1 + dev / 100)
    sell_soft = ma250_raw * 1.07
    sell_hard = ma250_raw * 1.14
    buy_cap = ma250_raw * 1.04

    holding = bool(latest_position == 1)
    if holding:
        if dev >= 7.0 and rsi >= 75:
            signal_text, signal_level = '卖出信号触发!', 'sell'
        elif dev >= 7.0:
            signal_text, signal_level = '持仓510880 | 卖出监控中', 'watch'
        else:
            signal_text, signal_level = '持仓510880 | 持有等待', 'neutral'
    else:
        if dev < -2:
            signal_text, signal_level = '空仓国债 | 极端买入触发!', 'buy'
        elif 0 <= dev <= 4:
            signal_text, signal_level = '空仓国债 | 接近买入区', 'watch'
        else:
            signal_text, signal_level = '空仓国债 | 等待回落', 'neutral'

    return {
        'holding': holding,
        'position_asset': '510880' if holding else '511260',
        'date': df2.index[-1].strftime('%Y-%m-%d'),
        'price_raw': round(float(latest['close_raw']), 3),
        'ma250': round(float(latest['ma250']), 3),
        'deviation_pct': round(float(dev), 1),
        'rsi14': round(float(rsi), 0),
        'rsi6': round(float(latest['rsi6']), 0),
        'ma250_slope_pct': round(float(latest['ma250_slope']), 2),
        'sell_trigger_price_soft': round(float(sell_soft), 3),
        'sell_trigger_price_hard': round(float(sell_hard), 3),
        'buy_trigger_price_cap': round(float(buy_cap), 3),
        'signal_text': signal_text,
        'signal_level': signal_level,
    }


def build_trades(buys, sells, df2):
    trades = []
    for j in range(min(len(buys), len(sells))):
        b, s = buys.iloc[j], sells.iloc[j]
        trades.append({
            'seq': j + 1,
            'buy_date': b['date'].strftime('%Y-%m-%d'),
            'sell_date': s['date'].strftime('%Y-%m-%d'),
            'buy_price_raw': round(float(b['price_raw']), 3),
            'sell_price_raw': round(float(s['price_raw']), 3),
            'pnl_pct': round(float(s['pnl_pct']), 1),
            'hold_days': int(s['hold_days']),
            'sell_reason': s['reason'],
            'open': False,
        })
    if len(buys) > len(sells):
        b = buys.iloc[len(sells)]
        cur_price = df2.iloc[-1]['close']
        cur_pnl = (cur_price / b['price'] - 1) * 100
        trades.append({
            'seq': len(sells) + 1,
            'buy_date': b['date'].strftime('%Y-%m-%d'),
            'sell_date': None,
            'buy_price_raw': round(float(b['price_raw']), 3),
            'sell_price_raw': round(float(df2.iloc[-1]['close_raw']), 3),
            'pnl_pct': round(float(cur_pnl), 1),
            'hold_days': int((df2.index[-1] - b['date']).days),
            'sell_reason': '未平仓（持有中）',
            'open': True,
        })
    return trades


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
        'equity_strategy': _safe_list(eq_aligned, 0),
        'equity_buyhold': _safe_list(bh, 0),
        'drawdown_pct': _safe_list(dd_aligned, 2),
    }


def export(output_path, count_510880=3000, count_511260=2500):
    raw = fetch_510880_qfq(count=count_510880)
    df = add_indicators(raw)
    df_sig = run_strategy(df, PARAMS)

    idle_price = None
    try:
        idle_price = fetch_511260_close(count=count_511260)
    except Exception as e:
        print(f'511260获取失败,继续但不计空仓收益: {e}')

    eq, tr = backtest(df_sig, idle_price=idle_price)

    df2 = df_sig[df_sig.index >= DISPLAY_START].copy()
    eq2 = eq[eq.index >= DISPLAY_START].copy()
    buys = tr[(tr['action'] == 'BUY') & (tr['date'] >= DISPLAY_START)].reset_index(drop=True)
    sells = tr[(tr['action'] == 'SELL') & (tr['date'] >= DISPLAY_START)].reset_index(drop=True)

    stats, dd_series = compute_stats(df2, eq2, sells)
    stats['holding_pct'] = compute_holding_pct(buys, sells, df2)

    beijing_now = datetime.now(timezone(timedelta(hours=8)))

    payload = {
        'meta': {
            **stats,
            'updated_at': beijing_now.isoformat(),
            'as_of_date': df2.index[-1].strftime('%Y-%m-%d'),
        },
        'current_status': build_current_status(df2, df2.iloc[-1]['position']),
        'series': build_series(df2, eq2, dd_series),
        'trades': build_trades(buys, sells, df2),
        'sell_reason_breakdown': build_sell_reason_breakdown(sells),
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


if __name__ == '__main__':
    site_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'site')
    os.makedirs(site_dir, exist_ok=True)
    export(os.path.join(site_dir, 'data.json'))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_export.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
mkdir -p site
git add pipeline/export.py tests/test_export.py
git commit -m "feat: export pipeline results to site/data.json schema"
```

---

### Task 7: `site/index.html` + `site/style.css` — 深色终端主题骨架

**Files:**
- Create: `site/index.html`
- Create: `site/style.css`

**Interfaces:**
- Produces: DOM结构（元素id：`status-dot`, `updated-at`, `kpi-row`, `status-card`, `chart-price`, `chart-deviation`, `chart-rsi`, `chart-macd`, `chart-equity`, `chart-sell-reason`, `trades-table`, `trades-table-body`, `data-error`），Task 8/9的`app.js`通过这些id渲染内容

- [ ] **Step 1: 创建 `site/index.html`**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>510880 红利ETF · MA250策略仪表盘</title>
<link rel="stylesheet" href="style.css">
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
</head>
<body>
  <header class="topbar">
    <span id="status-dot" class="status-dot"></span>
    <h1>510880 红利ETF · MA250策略</h1>
    <span id="updated-at" class="updated-at"></span>
  </header>

  <section class="kpi-row" id="kpi-row"></section>

  <section class="status-card" id="status-card"></section>

  <section class="panel" id="panel-main">
    <h2>价格 &amp; MA250</h2>
    <div class="chart" id="chart-price"></div>
  </section>

  <details class="panel collapsible">
    <summary>偏离度</summary>
    <div class="chart" id="chart-deviation"></div>
  </details>

  <details class="panel collapsible">
    <summary>RSI</summary>
    <div class="chart" id="chart-rsi"></div>
  </details>

  <details class="panel collapsible">
    <summary>MACD</summary>
    <div class="chart" id="chart-macd"></div>
  </details>

  <details class="panel collapsible">
    <summary>策略 vs 买入持有</summary>
    <div class="chart" id="chart-equity"></div>
  </details>

  <details class="panel collapsible">
    <summary>卖出原因分布</summary>
    <div class="chart" id="chart-sell-reason"></div>
  </details>

  <details class="panel collapsible">
    <summary>全部交易明细</summary>
    <table class="trades-table" id="trades-table">
      <thead>
        <tr>
          <th>序号</th><th>买入日期</th><th>卖出日期</th><th>买价</th>
          <th>卖价</th><th>收益%</th><th>持仓天</th><th>卖出原因</th>
        </tr>
      </thead>
      <tbody id="trades-table-body"></tbody>
    </table>
  </details>

  <footer class="footer">
    <p id="data-error" class="data-error" hidden></p>
    <p>数据来源:新浪/腾讯财经(510880/511260日线) | 每日北京时间15:40自动更新</p>
    <p class="disclaimer">本页面为个人量化研究记录,不构成投资建议。历史回测结果不代表未来收益。</p>
  </footer>

  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: 创建 `site/style.css`**

```css
:root {
  --bg: #0d1117;
  --bg-card: #161b22;
  --border: #21262d;
  --text: #c9d1d9;
  --text-dim: #8b949e;
  --green: #3fb950;
  --red: #f85149;
  --blue: #58a6ff;
  --mono: 'SFMono-Regular', Menlo, Consolas, monospace;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  padding: 16px;
}

.topbar { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
.topbar h1 { font-size: 18px; margin: 0; flex: 1; }
.updated-at { font-family: var(--mono); font-size: 12px; color: var(--text-dim); }

.status-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--text-dim); }
.status-dot.holding { background: var(--green); box-shadow: 0 0 6px var(--green); }
.status-dot.idle { background: var(--text-dim); }

.kpi-row { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-bottom: 16px; }
@media (max-width: 800px) { .kpi-row { grid-template-columns: repeat(2, 1fr); } }

.kpi-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 12px; text-align: center; }
.kpi-card .value { font-family: var(--mono); font-size: 20px; font-weight: 700; }
.kpi-card .label { font-size: 11px; color: var(--text-dim); margin-top: 4px; }
.kpi-card .value.pos { color: var(--green); }
.kpi-card .value.neg { color: var(--red); }

.status-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 16px; }
.status-card .signal { font-weight: 700; padding: 8px 12px; border-radius: 6px; display: inline-block; margin-top: 10px; }
.signal.buy { background: var(--green); color: #06210f; }
.signal.sell { background: var(--red); color: #2b0b09; }
.signal.watch { background: #d29922; color: #2b1d02; }
.signal.neutral { background: var(--border); color: var(--text); }

.status-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; font-family: var(--mono); font-size: 13px; }
@media (max-width: 800px) { .status-grid { grid-template-columns: repeat(2, 1fr); } }
.status-grid .k { color: var(--text-dim); }

.panel { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.panel h2, .panel summary { font-size: 14px; margin: 0 0 8px 0; }
.collapsible summary { cursor: pointer; padding: 4px 0; }

.chart { width: 100%; height: 360px; }
#chart-price { height: 480px; }

.trades-table { width: 100%; border-collapse: collapse; font-family: var(--mono); font-size: 12px; }
.trades-table th, .trades-table td { border-bottom: 1px solid var(--border); padding: 6px 8px; text-align: right; }
.trades-table th:first-child, .trades-table td:first-child { text-align: left; }
.trades-table th { color: var(--text-dim); cursor: pointer; user-select: none; }
.trades-table tbody tr.open-row { color: var(--blue); font-weight: 700; }

.footer { color: var(--text-dim); font-size: 12px; margin-top: 24px; line-height: 1.6; }
.disclaimer { color: var(--text-dim); }
.data-error { background: #3d1f1f; color: var(--red); padding: 8px 12px; border-radius: 6px; }

@media (max-width: 800px) {
  .trades-table { display: block; overflow-x: auto; white-space: nowrap; }
}
```

- [ ] **Step 3: 手动验证骨架渲染**

```bash
cd /Users/ge/Desktop/Stock/510880-dividend-strategy
python -m http.server 8000 --directory site
```

打开浏览器访问 `http://localhost:8000`，确认：
- 背景为深色`#0d1117`，无白屏
- 顶部标题、6格KPI占位区域（此时为空，因为还没有`app.js`）、当前状态卡片区域、主图区域、5个可折叠面板（点击summary能展开/收起）都按预期布局出现
- 缩小浏览器窗口到手机宽度（~375px），KPI卡片变成2列，无横向溢出

Run: `pkill -f "http.server 8000"` 关闭本地服务器

- [ ] **Step 4: Commit**

```bash
git add site/index.html site/style.css
git commit -m "feat: add dark-terminal dashboard HTML/CSS skeleton"
```

---

### Task 8: `site/app.js` (第一部分) — 数据加载 + KPI + 状态卡 + 主图

**Files:**
- Create: `site/app.js`
- Modify: 无（`data.json`由Task 6的脚本生成，本任务先手写一份样例文件仅用于本地手动验证，不提交到git）

**Interfaces:**
- Consumes: Task 6定义的JSON schema；Task 7的DOM元素id
- Produces: 全局函数 `main()`, `showDataError(message)`, `renderTopbar(data)`, `fmtSigned(value, suffix)`, `renderKpis(meta)`, `renderStatusCard(status)`, `renderPriceChart(series, trades)`, 常量`DARK_AXIS`, 辅助函数`baseGrid()`（Task 9继续在同一文件追加`renderDeviationChart`等函数，依赖这里定义的`DARK_AXIS`/`baseGrid`/`fmtSigned`）

- [ ] **Step 1: 手写一份样例 `site/data.json.sample`（仅用于本地调试，不是最终产物）**

```bash
cd /Users/ge/Desktop/Stock/510880-dividend-strategy
source .venv/bin/activate
python -c "
import json, sys
sys.path.insert(0, '.')
from tests.test_export import _build_fixture
import pipeline.export as export_mod
fixture_df, fixture_idle = _build_fixture()
export_mod.fetch_510880_qfq = lambda count=3000: fixture_df
export_mod.fetch_511260_close = lambda count=2500: fixture_idle
export_mod.DISPLAY_START = fixture_df.index[255].strftime('%Y-%m-%d')
export_mod.export('site/data.json')
print('样例data.json已生成，仅用于本地调试')
"
```

（这一步只是借用Task 6测试里的fixture快速生成一份可用于调试的`site/data.json`；`site/data.json`已在`.gitignore`里排除，不会被提交）

- [ ] **Step 2: 实现 `site/app.js`（第一部分）**

```js
async function main() {
  let data;
  try {
    const res = await fetch('./data.json', { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    showDataError(`数据加载失败: ${err.message}`);
    return;
  }

  renderTopbar(data);
  renderKpis(data.meta);
  renderStatusCard(data.current_status);
  renderPriceChart(data.series, data.trades);
}

function showDataError(message) {
  const el = document.getElementById('data-error');
  el.textContent = message;
  el.hidden = false;
}

function renderTopbar(data) {
  const dot = document.getElementById('status-dot');
  dot.classList.add(data.current_status.holding ? 'holding' : 'idle');
  document.getElementById('updated-at').textContent =
    `数据日期 ${data.meta.as_of_date} · 更新于 ${data.meta.updated_at.slice(0, 16).replace('T', ' ')}`;
}

function fmtSigned(value, suffix = '%') {
  const sign = value > 0 ? '+' : '';
  return `${sign}${value}${suffix}`;
}

function renderKpis(meta) {
  const cards = [
    { value: fmtSigned(meta.annualized_pct), label: '年化(含分红+国债)', signed: true },
    { value: `${meta.max_drawdown_pct}%`, label: '最大回撤', signed: true },
    { value: meta.sharpe.toFixed(2), label: '夏普比率', signed: false },
    { value: `${meta.win_rate_pct}%`, label: `胜率(${meta.trade_count}笔)`, signed: false },
    { value: fmtSigned(meta.avg_win_pct), label: '平均盈利', signed: true },
    { value: `${meta.holding_pct}%`, label: '持仓占比', signed: false },
  ];
  const row = document.getElementById('kpi-row');
  row.innerHTML = cards.map(c => `
    <div class="kpi-card">
      <div class="value ${c.signed ? (parseFloat(c.value) >= 0 ? 'pos' : 'neg') : ''}">${c.value}</div>
      <div class="label">${c.label}</div>
    </div>
  `).join('');
}

function renderStatusCard(status) {
  const card = document.getElementById('status-card');
  card.innerHTML = `
    <div class="status-grid">
      <div><span class="k">日期</span><br>${status.date}</div>
      <div><span class="k">价格(不复权)</span><br>¥${status.price_raw}</div>
      <div><span class="k">MA250(前复权)</span><br>¥${status.ma250}</div>
      <div><span class="k">偏离度</span><br>${fmtSigned(status.deviation_pct)}</div>
      <div><span class="k">RSI14 / RSI6</span><br>${status.rsi14} / ${status.rsi6}</div>
      <div><span class="k">卖出监控价</span><br>¥${status.sell_trigger_price_soft}</div>
      <div><span class="k">硬卖价</span><br>¥${status.sell_trigger_price_hard}</div>
      <div><span class="k">买入上限价</span><br>¥${status.buy_trigger_price_cap}</div>
    </div>
    <div class="signal ${status.signal_level}">${status.signal_text}</div>
  `;
}

const DARK_AXIS = {
  axisLine: { lineStyle: { color: '#21262d' } },
  axisLabel: { color: '#8b949e' },
  splitLine: { lineStyle: { color: '#161b22' } },
};

function baseGrid() {
  return { left: 56, right: 24, top: 24, bottom: 40 };
}

function renderPriceChart(series, trades) {
  const chart = echarts.init(document.getElementById('chart-price'));
  const buyPoints = trades.map(t => ({
    coord: [t.buy_date, t.buy_price_raw], symbol: 'triangle',
    itemStyle: { color: '#3fb950' },
  }));
  const sellPoints = trades.filter(t => t.sell_date).map(t => ({
    coord: [t.sell_date, t.sell_price_raw], symbol: 'pin',
    itemStyle: { color: '#f85149' },
  }));

  chart.setOption({
    backgroundColor: 'transparent',
    grid: baseGrid(),
    tooltip: { trigger: 'axis', backgroundColor: '#161b22', borderColor: '#21262d', textStyle: { color: '#c9d1d9' } },
    legend: { data: ['收盘价', 'MA10', 'MA20', 'MA60', 'MA250'], textStyle: { color: '#8b949e' }, top: 0 },
    xAxis: { type: 'category', data: series.dates, ...DARK_AXIS },
    yAxis: { type: 'value', scale: true, ...DARK_AXIS },
    dataZoom: [{ type: 'inside' }, { type: 'slider', backgroundColor: '#161b22', fillerColor: 'rgba(88,166,255,0.15)' }],
    series: [
      { name: '收盘价', type: 'line', data: series.close, showSymbol: false, lineStyle: { width: 1.5, color: '#c9d1d9' } },
      { name: 'MA10', type: 'line', data: series.ma10, showSymbol: false, lineStyle: { width: 1, color: '#58a6ff', opacity: 0.5 } },
      { name: 'MA20', type: 'line', data: series.ma20, showSymbol: false, lineStyle: { width: 1, color: '#3fb950', opacity: 0.4 } },
      { name: 'MA60', type: 'line', data: series.ma60, showSymbol: false, lineStyle: { width: 1, color: '#d29922', opacity: 0.4 } },
      {
        name: 'MA250', type: 'line', data: series.ma250, showSymbol: false,
        lineStyle: { width: 2, color: '#f85149', type: 'dashed' },
        markPoint: { symbolSize: 14, data: [...buyPoints, ...sellPoints] },
      },
    ],
  });
  window.addEventListener('resize', () => chart.resize());
}

document.addEventListener('DOMContentLoaded', main);
```

- [ ] **Step 3: 手动验证**

```bash
cd /Users/ge/Desktop/Stock/510880-dividend-strategy
python -m http.server 8000 --directory site
```

打开 `http://localhost:8000`，打开浏览器开发者工具Console，确认：
- 没有JS报错
- 顶部状态点根据`data.json.sample`里`current_status.holding`显示绿色(持仓)或灰色(空仓)
- 6个KPI卡片显示数字（年化/回撤为绿色或红色，其余为默认色）
- 当前状态卡片显示日期/价格/偏离度等字段和一个彩色信号徽章
- 主图显示价格线+4条MA线，可以用底部滑块缩放，图上能看到绿色三角(买入点)和红色标记(卖出点)

Run: `pkill -f "http.server 8000"`

- [ ] **Step 4: Commit**

```bash
git add site/app.js
git commit -m "feat: add data loading, KPI cards, status card and price chart"
```

---

### Task 9: `site/app.js` (第二部分) — 次要图表 + 可排序交易明细表

**Files:**
- Modify: `site/app.js`（追加函数，不改动Task 8已写的部分）

**Interfaces:**
- Consumes: Task 8定义的`DARK_AXIS`/`baseGrid()`/`fmtSigned()`；Task 6的JSON schema
- Produces: `renderDeviationChart(series)`, `renderRsiChart(series)`, `renderMacdChart(series)`, `renderEquityChart(series)`, `renderSellReasonChart(breakdown)`, `renderTradesTable(trades)`；并在`main()`末尾追加对这些函数的调用

- [ ] **Step 1: 在 `main()` 函数末尾追加渲染调用**

把Task 8里的：
```js
  renderPriceChart(data.series, data.trades);
}
```
改为：
```js
  renderPriceChart(data.series, data.trades);
  renderDeviationChart(data.series);
  renderRsiChart(data.series);
  renderMacdChart(data.series);
  renderEquityChart(data.series);
  renderSellReasonChart(data.sell_reason_breakdown);
  renderTradesTable(data.trades);
}
```

- [ ] **Step 2: 在文件末尾（`document.addEventListener('DOMContentLoaded', main);`之前）追加以下函数**

```js
function renderDeviationChart(series) {
  const chart = echarts.init(document.getElementById('chart-deviation'));
  chart.setOption({
    backgroundColor: 'transparent',
    grid: baseGrid(),
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: series.dates, ...DARK_AXIS },
    yAxis: { type: 'value', ...DARK_AXIS },
    dataZoom: [{ type: 'inside' }],
    series: [{
      type: 'bar', data: series.deviation,
      itemStyle: { color: (p) => (p.value >= 7 ? '#f85149' : p.value >= 0 ? '#3fb950' : '#58a6ff') },
    }],
  });
  window.addEventListener('resize', () => chart.resize());
}

function renderRsiChart(series) {
  const chart = echarts.init(document.getElementById('chart-rsi'));
  chart.setOption({
    backgroundColor: 'transparent',
    grid: baseGrid(),
    tooltip: { trigger: 'axis' },
    legend: { data: ['RSI14', 'RSI6'], textStyle: { color: '#8b949e' }, top: 0 },
    xAxis: { type: 'category', data: series.dates, ...DARK_AXIS },
    yAxis: { type: 'value', min: 0, max: 100, ...DARK_AXIS },
    dataZoom: [{ type: 'inside' }],
    series: [
      { name: 'RSI14', type: 'line', data: series.rsi14, showSymbol: false, lineStyle: { color: '#a371f7' } },
      { name: 'RSI6', type: 'line', data: series.rsi6, showSymbol: false, lineStyle: { color: '#d29922', opacity: 0.5 } },
    ],
  });
  window.addEventListener('resize', () => chart.resize());
}

function renderMacdChart(series) {
  const chart = echarts.init(document.getElementById('chart-macd'));
  chart.setOption({
    backgroundColor: 'transparent',
    grid: baseGrid(),
    tooltip: { trigger: 'axis' },
    legend: { data: ['MACD', 'Signal'], textStyle: { color: '#8b949e' }, top: 0 },
    xAxis: { type: 'category', data: series.dates, ...DARK_AXIS },
    yAxis: { type: 'value', ...DARK_AXIS },
    dataZoom: [{ type: 'inside' }],
    series: [
      { name: 'MACD柱', type: 'bar', data: series.macd_hist, itemStyle: { color: (p) => (p.value >= 0 ? '#3fb950' : '#f85149') } },
      { name: 'MACD', type: 'line', data: series.macd, showSymbol: false, lineStyle: { color: '#58a6ff' } },
      { name: 'Signal', type: 'line', data: series.macd_signal, showSymbol: false, lineStyle: { color: '#d29922' } },
    ],
  });
  window.addEventListener('resize', () => chart.resize());
}

function renderEquityChart(series) {
  const chart = echarts.init(document.getElementById('chart-equity'));
  chart.setOption({
    backgroundColor: 'transparent',
    grid: baseGrid(),
    tooltip: { trigger: 'axis' },
    legend: { data: ['MA250策略', '买入持有'], textStyle: { color: '#8b949e' }, top: 0 },
    xAxis: { type: 'category', data: series.dates, ...DARK_AXIS },
    yAxis: { type: 'value', ...DARK_AXIS },
    dataZoom: [{ type: 'inside' }, { type: 'slider' }],
    series: [
      { name: 'MA250策略', type: 'line', data: series.equity_strategy, showSymbol: false, lineStyle: { width: 2, color: '#3fb950' } },
      { name: '买入持有', type: 'line', data: series.equity_buyhold, showSymbol: false, lineStyle: { width: 1, color: '#8b949e', type: 'dashed' } },
    ],
  });
  window.addEventListener('resize', () => chart.resize());
}

function renderSellReasonChart(breakdown) {
  const chart = echarts.init(document.getElementById('chart-sell-reason'));
  chart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 90, right: 40, top: 20, bottom: 30 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: { type: 'value', ...DARK_AXIS },
    yAxis: { type: 'category', data: breakdown.map(b => b.reason), ...DARK_AXIS },
    series: [{
      type: 'bar',
      data: breakdown.map(b => b.count),
      itemStyle: { color: '#f85149' },
      label: {
        show: true, position: 'right', color: '#c9d1d9',
        formatter: (p) => `${breakdown[p.dataIndex].count}笔 · 均${fmtSigned(breakdown[p.dataIndex].avg_pnl_pct)}`,
      },
    }],
  });
  window.addEventListener('resize', () => chart.resize());
}

let currentTrades = [];
let sortState = { key: 'seq', dir: 1 };
const TRADE_COLUMN_KEYS = ['seq', 'buy_date', 'sell_date', 'buy_price_raw', 'sell_price_raw', 'pnl_pct', 'hold_days', 'sell_reason'];

function renderTradesTable(trades) {
  currentTrades = trades;
  document.querySelectorAll('#trades-table th').forEach((th, i) => {
    th.onclick = () => {
      const key = TRADE_COLUMN_KEYS[i];
      sortState.dir = sortState.key === key ? -sortState.dir : 1;
      sortState.key = key;
      drawTradesBody();
    };
  });
  drawTradesBody();
}

function drawTradesBody() {
  const rows = [...currentTrades].sort((a, b) => {
    const av = a[sortState.key];
    const bv = b[sortState.key];
    if (av === null) return 1;
    if (bv === null) return -1;
    if (av < bv) return -1 * sortState.dir;
    if (av > bv) return 1 * sortState.dir;
    return 0;
  });
  const tbody = document.getElementById('trades-table-body');
  tbody.innerHTML = rows.map(t => `
    <tr class="${t.open ? 'open-row' : ''}">
      <td>${t.seq}</td>
      <td>${t.buy_date}</td>
      <td>${t.sell_date ?? '持仓中…'}</td>
      <td>${t.buy_price_raw}</td>
      <td>${t.sell_price_raw}</td>
      <td>${fmtSigned(t.pnl_pct)}</td>
      <td>${t.hold_days}</td>
      <td>${t.sell_reason}</td>
    </tr>
  `).join('');
}
```

- [ ] **Step 3: 手动验证**

```bash
cd /Users/ge/Desktop/Stock/510880-dividend-strategy
python -m http.server 8000 --directory site
```

打开 `http://localhost:8000`，展开全部5个折叠面板，确认：
- 偏离度柱状图、RSI双线图、MACD柱+双线图、策略vs买入持有净值曲线图都正常渲染，无Console报错
- 卖出原因分布是横向条形图（不是饼图），每条右侧显示"N笔 · 均+X.X%"
- 交易明细表显示全部交易行，点击表头（如"收益%"）能按该列排序，再点一次反向排序
- 未平仓的那一行（如果有）文字是蓝色且加粗

Run: `pkill -f "http.server 8000"`

- [ ] **Step 4: Commit**

```bash
git add site/app.js
git commit -m "feat: add deviation/RSI/MACD/equity/sell-reason charts and sortable trades table"
```

---

### Task 10: GitHub Actions 自动化部署工作流

**Files:**
- Create: `.github/workflows/deploy.yml`

**Interfaces:**
- Consumes: `requirements.txt`（Task 1）、`python -m pipeline.export`（Task 6的`if __name__ == '__main__'`入口）、`site/`目录（Task 7-9）
- Produces: 每日定时/手动触发的Pages部署

- [ ] **Step 1: 创建 `.github/workflows/deploy.yml`**

```yaml
name: Deploy dashboard

on:
  schedule:
    - cron: '40 7 * * *'
  workflow_dispatch: {}

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - run: pip install -r requirements.txt

      - run: python -m pipeline.export

      - uses: actions/upload-pages-artifact@v3
        with:
          path: site

      - id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: 本地校验YAML语法**

```bash
cd /Users/ge/Desktop/Stock/510880-dividend-strategy
python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml'))" && echo "YAML语法OK"
```

Expected: `YAML语法OK`（如果本机没有`pyyaml`，先 `pip install pyyaml`）

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add daily GitHub Actions workflow to build and deploy Pages"
```

---

### Task 11: 本地真实数据端到端验证

**Files:**
- 无新文件；验证Task 1-9的完整链路

**Interfaces:**
- Consumes: 全部前序任务

- [ ] **Step 1: 用真实行情跑一次完整管线**

```bash
cd /Users/ge/Desktop/Stock/510880-dividend-strategy
source .venv/bin/activate
python -m pipeline.export
```

Expected: 无异常退出，`site/data.json`被创建/更新，终端没有Python traceback

- [ ] **Step 2: 检查关键数值是否在合理范围**

```bash
python -c "
import json
d = json.load(open('site/data.json'))
print('年化:', d['meta']['annualized_pct'])
print('最大回撤:', d['meta']['max_drawdown_pct'])
print('夏普:', d['meta']['sharpe'])
print('交易笔数:', d['meta']['trade_count'])
print('当前信号:', d['current_status']['signal_text'])
"
```

Expected: 年化在15~25%区间、最大回撤在-10%~-18%区间、交易笔数在20笔以上（与`红利研究/output/510880_dashboard.png`里当前显示的年化+20.4%/回撤-13.9%/26笔量级一致，允许因数据更新到最新交易日而有小幅差异）

- [ ] **Step 3: 本地起服务器，全流程走一遍前端**

```bash
python -m http.server 8000 --directory site
```

打开 `http://localhost:8000`，确认：
- 页面标题、KPI、状态卡片、主图、5个折叠面板、免责声明全部正常显示，无Console报错
- 用浏览器开发者工具切换到手机视口（如iPhone 12, 390×844），确认KPI变2列、图表不溢出、交易表可以横向滑动
- 页脚免责声明文字完整可读

Run: `pkill -f "http.server 8000"`

- [ ] **Step 4: 无需commit（本任务只做验证，不产生新文件变更；`site/data.json`已被`.gitignore`排除）**

---

### Task 12: 推送到GitHub、开启Pages、触发首次部署验证

**Files:**
- 无新文件；操作远程仓库配置

**Interfaces:**
- Consumes: 全部前序任务的commit历史

- [ ] **Step 1: 推送全部commit**

```bash
cd /Users/ge/Desktop/Stock/510880-dividend-strategy
git push origin main
```

Expected: 推送成功，无冲突

- [ ] **Step 2: 开启GitHub Pages（Source=GitHub Actions）**

```bash
gh api repos/GeJin0425/510880-dividend-strategy/pages -X POST -f build_type=workflow
```

Expected: 返回JSON中`build_type`为`"workflow"`（如果Pages已存在会报409，改用 `-X PUT` 更新同样的body）

- [ ] **Step 3: 手动触发一次workflow**

```bash
gh workflow run deploy.yml -R GeJin0425/510880-dividend-strategy
sleep 10
gh run list -R GeJin0425/510880-dividend-strategy --limit 1
```

Expected: 看到一条状态为`in_progress`或`queued`的运行记录

- [ ] **Step 4: 等待运行完成并检查结果**

```bash
gh run watch -R GeJin0425/510880-dividend-strategy
```

Expected: 最终状态为`completed` / `success`。如果失败，用 `gh run view -R GeJin0425/510880-dividend-strategy --log-failed` 查看具体报错（最可能的失败点是新浪/腾讯行情接口对GitHub Actions海外IP不可达——若发生，需要在此任务基础上追加评估更换数据源或改造为可从中国大陆网络触发的方案，这超出本次计划范围，需要另开一次brainstorming）

- [ ] **Step 5: 验证线上页面可访问**

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://gejin0425.github.io/510880-dividend-strategy/
```

Expected: `200`

在浏览器打开 `https://gejin0425.github.io/510880-dividend-strategy/`，确认线上内容与本地Task 11验证时看到的一致（KPI、图表、免责声明都正常显示）。

---

## Self-Review 记录

- **Spec覆盖**：仓库结构(Task1,2,6)、部署方式(Task10,12)、深色终端前端设计(Task7-9)、自动化调度(Task10)、已知风险兜底(Task12 Step4注明runner连通性风险；每日抓取失败保留T-1数据的兜底逻辑体现在`export.py`对511260获取失败的`try/except`——510880本身抓取失败会直接抛异常中断整个workflow，避免用坏数据覆盖已发布的旧`data.json`，这本身就是一种"失败不覆盖"的兜底)、免责声明(Task7)、分红年度维护(沿用`pipeline/fetch.py`里的`DIVIDENDS_510880`常量列表，与现有项目维护方式一致)均有对应任务覆盖。
- **占位符扫描**：全文无TBD/TODO，所有代码块均为可直接运行的完整实现。
- **类型一致性**：`export.py`产出的JSON字段名（`meta.annualized_pct`、`current_status.signal_level`、`series.rsi14`等）与`app.js`里`renderKpis`/`renderStatusCard`/`renderRsiChart`等函数读取的字段名逐一核对一致；`trades[].sell_date`为`null`时前端用`t.sell_date ?? '持仓中…'`处理，与`build_trades`里`'sell_date': None`对应。
