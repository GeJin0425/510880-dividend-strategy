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
