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

  checkStaleness(data.meta.as_of_date);

  renderTopbar(data);
  renderKpis(data.meta);
  renderStatusCard(data.current_status);
  renderPriceChart(data.series, data.trades);
  renderDeviationChart(data.series);
  renderRsiChart(data.series);
  renderMacdChart(data.series);
  renderEquityChart(data.series);
  renderSellReasonChart(data.sell_reason_breakdown);
  renderTradesTable(data.trades);
}

function showDataError(message) {
  const el = document.getElementById('data-error');
  el.textContent = message;
  el.hidden = false;
}

const STALENESS_THRESHOLD_DAYS = 4;

function checkStaleness(asOfDate) {
  const asOf = new Date(`${asOfDate}T00:00:00`);
  if (isNaN(asOf.getTime())) return;
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - asOf.getTime()) / (1000 * 60 * 60 * 24));
  if (diffDays > STALENESS_THRESHOLD_DAYS) {
    showDataError(`数据已 ${diffDays} 天未更新,当前显示的可能不是最新信号(数据日期: ${asOfDate})`);
  }
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
    coord: [t.buy_date, t.buy_price], symbol: 'triangle',
    itemStyle: { color: '#3fb950' },
  }));
  const sellPoints = trades.filter(t => t.sell_date).map(t => ({
    coord: [t.sell_date, t.sell_price], symbol: 'pin',
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

document.addEventListener('DOMContentLoaded', main);
