const FONT_SANS = '"Fira Sans","PingFang SC","Hiragino Sans GB","Microsoft YaHei",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif';
const FONT_MONO = '"Fira Code","SFMono-Regular",Menlo,Consolas,monospace';
const THEME_KEY = '510880-theme';
const STALENESS_THRESHOLD_DAYS = 4;

const state = {
  data: null,
  themeChoice: 'auto',
  activeRanges: { price: 'all', returns: 'all' },
};

const charts = [];
let currentTrades = [];
let sortState = { key: 'seq', dir: 1 };
const TRADE_COLUMN_KEYS = ['seq', 'buy_date', 'sell_date', 'buy_price_raw', 'sell_price_raw', 'pnl_pct', 'hold_days', 'sell_reason'];

async function main() {
  initTheme();
  showSkeleton();

  try {
    const res = await fetch('./data.json', { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data || !data.series || !Array.isArray(data.series.dates) || data.series.dates.length === 0) {
      throw new Error('数据为空');
    }
    state.data = data;
    renderAll(data);
    checkStaleness(data.meta.as_of_date);
    initCollapsibleResize();
  } catch (err) {
    showLoadError(err);
  }
}

function initTheme() {
  let stored = 'auto';
  try { stored = localStorage.getItem(THEME_KEY) || 'auto'; } catch (_) {}
  state.themeChoice = ['auto', 'light', 'dark'].includes(stored) ? stored : 'auto';

  document.querySelectorAll('.theme-btn').forEach((btn) => {
    btn.addEventListener('click', () => applyTheme(btn.dataset.themeChoice));
  });

  const media = window.matchMedia('(prefers-color-scheme: light)');
  const onSystemChange = () => {
    if (state.themeChoice === 'auto') applyTheme('auto');
  };
  if (media.addEventListener) media.addEventListener('change', onSystemChange);
  else if (media.addListener) media.addListener(onSystemChange);

  applyTheme(state.themeChoice);
}

function systemTheme() {
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function applyTheme(choice) {
  state.themeChoice = choice;
  const effective = choice === 'light' || (choice === 'auto' && systemTheme() === 'light') ? 'light' : 'dark';
  document.documentElement.dataset.theme = effective;
  document.documentElement.dataset.themeChoice = choice;

  const themeMeta = document.querySelector('meta[name="theme-color"]');
  if (themeMeta) themeMeta.setAttribute('content', effective === 'light' ? '#F5F7FB' : '#0B1220');

  document.querySelectorAll('.theme-btn').forEach((btn) => {
    const active = btn.dataset.themeChoice === choice;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-pressed', String(active));
  });

  charts.forEach((entry) => entry.refresh());

  try { localStorage.setItem(THEME_KEY, choice); } catch (_) {}
}

function reducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function palette() {
  const light = document.documentElement.dataset.theme === 'light';
  return light ? {
    text: '#101828',
    dim: '#55657B',
    axis: '#94A3B8',
    split: 'rgba(15,23,42,0.08)',
    tooltipBg: '#FFFFFF',
    tooltipBorder: '#E2E8F0',
    price: '#1E293B',
    ma10: '#2563EB',
    ma20: '#047857',
    ma60: '#B45309',
    ma250: '#DC2626',
    up: '#047857',
    down: '#DC2626',
    warn: '#B45309',
    purple: '#7C3AED',
    accent: '#2563EB',
  } : {
    text: '#c9d1d9',
    dim: '#8b949e',
    axis: '#21262d',
    split: '#161b22',
    tooltipBg: '#161b22',
    tooltipBorder: '#21262d',
    price: '#c9d1d9',
    ma10: '#58a6ff',
    ma20: '#3fb950',
    ma60: '#d29922',
    ma250: '#f85149',
    up: '#3fb950',
    down: '#f85149',
    warn: '#d29922',
    purple: '#a371f7',
    accent: '#58a6ff',
  };
}

function chartBase(p) {
  return {
    backgroundColor: 'transparent',
    animation: !reducedMotion(),
    animationDuration: 380,
    animationEasing: 'cubicOut',
    textStyle: { fontFamily: FONT_SANS, color: p.text },
    aria: { enabled: true, decal: { show: true } },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.tooltipBg,
      borderColor: p.tooltipBorder,
      borderWidth: 1,
      textStyle: { color: p.text, fontSize: 12, fontFamily: FONT_SANS },
      axisPointer: { lineStyle: { color: p.axis, type: 'dashed' } },
      padding: [8, 12],
      extraCssText: 'border-radius:10px;box-shadow:0 8px 24px rgba(2,6,23,0.25);',
    },
  };
}

function chartAxis(p) {
  return {
    axisLine: { lineStyle: { color: p.axis } },
    axisLabel: { color: p.dim },
    splitLine: { lineStyle: { color: p.split } },
  };
}

function chartGrid(p) {
  return { left: 10, right: 16, top: 36, bottom: 8, containLabel: true };
}

function registerChart(id, build) {
  const el = document.getElementById(id);
  const instance = echarts.init(el);
  const entry = {
    instance,
    refresh: () => instance.setOption(build(), { notMerge: true }),
  };
  charts.push(entry);
  entry.refresh();
  return entry;
}

function showSkeleton() {
  const kpi = document.getElementById('kpi-row');
  kpi.innerHTML = Array.from({ length: 6 }, () => `
    <div class="kpi-card">
      <div class="sk-line sk-w-40 sk-h-24"></div>
      <div class="sk-line sk-w-64" style="margin:10px auto 0"></div>
    </div>
  `).join('');

  document.getElementById('status-card').innerHTML = `
    <div class="sk-line sk-w-56 sk-h-24"></div>
    <div class="sk-grid">
      ${Array.from({ length: 9 }, () => '<div class="sk-line sk-w-64"></div>').join('')}
    </div>
  `;
}

function showLoadError(err) {
  document.getElementById('kpi-row').innerHTML = '';
  document.getElementById('status-card').innerHTML = '';

  const dot = document.getElementById('status-dot');
  dot.classList.remove('holding', 'idle', 'stale');
  dot.classList.add('error');
  dot.setAttribute('aria-label', '策略状态:加载失败');

  const banner = document.getElementById('banner');
  banner.hidden = false;
  banner.className = 'banner error';
  banner.innerHTML = `数据加载失败:${escapeHtml(err.message)} <button type="button" class="retry-btn">重新加载</button>`;
  banner.querySelector('.retry-btn').addEventListener('click', () => location.reload());
}

function showBanner(message, kind = 'warning') {
  const banner = document.getElementById('banner');
  banner.hidden = false;
  banner.className = `banner ${kind}`;
  banner.textContent = message;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));
}

function checkStaleness(asOfDate) {
  const asOf = new Date(`${asOfDate}T00:00:00`);
  if (isNaN(asOf.getTime())) return;
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - asOf.getTime()) / (1000 * 60 * 60 * 24));
  if (diffDays <= STALENESS_THRESHOLD_DAYS) return;

  const dot = document.getElementById('status-dot');
  dot.classList.add('stale');
  dot.setAttribute('aria-label', `数据已 ${diffDays} 天未更新`);
  document.getElementById('updated-at').classList.add('stale');
  showBanner(`数据已 ${diffDays} 天未更新,当前显示的可能不是最新信号(数据日期:${asOfDate})`);
}

function renderAll(data) {
  renderTopbar(data);
  renderKpis(data.meta);
  renderStatusCard(data.current_status);
  renderPriceChart(data);
  renderReturnsPanel(data);
  renderDeviationChart(data.series);
  renderRsiChart(data.series);
  renderMacdChart(data.series);
  renderEquityChart(data.series);
  renderDrawdownChart(data.series);
  renderSellReasonChart(data.sell_reason_breakdown);
  renderTradesTable(data.trades);
}

function renderTopbar(data) {
  const dot = document.getElementById('status-dot');
  dot.classList.remove('error', 'stale');
  dot.classList.toggle('holding', !!data.current_status.holding);
  dot.classList.toggle('idle', !data.current_status.holding);
  dot.setAttribute('aria-label', data.current_status.holding ? '策略状态:持仓510880' : '策略状态:空仓国债');

  const updated = document.getElementById('updated-at');
  updated.classList.remove('stale');
  updated.textContent = `数据日期 ${data.meta.as_of_date} · 更新于 ${data.meta.updated_at.slice(0, 16).replace('T', ' ')}`;
}

function fmtSigned(value, suffix = '%') {
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  const sign = num > 0 ? '+' : '';
  return `${sign}${num}${suffix}`;
}

function toneOf(value) {
  return value > 0 ? 'pos' : value < 0 ? 'neg' : '';
}

function renderKpis(meta) {
  const cards = [
    { value: fmtSigned(meta.annualized_pct), label: '年化(含分红+国债·万0.5)', signed: true },
    { value: `${meta.max_drawdown_pct}%`, label: '最大回撤', signed: true },
    { value: meta.sharpe.toFixed(2), label: '夏普比率', signed: false },
    { value: `${meta.win_rate_pct}%`, label: `胜率(${meta.trade_count}笔)`, signed: false },
    { value: fmtSigned(meta.avg_win_pct), label: '平均盈利', signed: true },
    { value: `${meta.holding_pct}%`, label: '持仓占比', signed: false },
  ];

  const row = document.getElementById('kpi-row');
  row.innerHTML = cards.map((c) => `
    <div class="kpi-card">
      <div class="value ${c.signed ? toneOf(parseFloat(c.value)) : ''}">${c.value}</div>
      <div class="label">${c.label}</div>
    </div>
  `).join('');
}

function renderStatusCard(status) {
  const card = document.getElementById('status-card');
  card.innerHTML = `
    <div class="status-grid">
      <div><span class="k">日期</span>${status.date}</div>
      <div><span class="k">价格(不复权)</span>¥${status.price_raw}</div>
      <div><span class="k">MA250(前复权)</span>¥${status.ma250}</div>
      <div><span class="k">偏离度</span>${fmtSigned(status.deviation_pct)}</div>
      <div><span class="k">RSI14 / RSI6</span>${status.rsi14} / ${status.rsi6}</div>
      <div><span class="k">MA250斜率</span>${fmtSigned(status.ma250_slope_pct)}</div>
      <div><span class="k">卖出监控价</span>¥${status.sell_trigger_price_soft}</div>
      <div><span class="k">硬卖价</span>¥${status.sell_trigger_price_hard}</div>
      <div><span class="k">买入上限价</span>¥${status.buy_trigger_price_cap}</div>
    </div>
    <div class="signal ${status.signal_level}" role="status">${status.signal_text}</div>
  `;
}

function isoYearsAgo(dateStr, years) {
  const [y, m, d] = dateStr.split('-').map(Number);
  return new Date(Date.UTC(y - years, m - 1, d)).toISOString().slice(0, 10);
}

function startIndexForRange(allDates, range) {
  const lastDate = allDates[allDates.length - 1] ?? '';
  if (!lastDate) return 0;
  let startDate;
  if (range === 'ytd') startDate = `${lastDate.slice(0, 4)}-01-01`;
  else if (range === '1y') startDate = isoYearsAgo(lastDate, 1);
  else if (range === '3y') startDate = isoYearsAgo(lastDate, 3);
  else if (range === '5y') startDate = isoYearsAgo(lastDate, 5);
  else return 0;
  const idx = allDates.findIndex((d) => d >= startDate);
  return idx === -1 ? 0 : idx;
}

function setRangeButtons(containerId, range) {
  document.querySelectorAll(`#${containerId} .range-btn`).forEach((btn) => {
    const active = btn.dataset.range === range;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-pressed', String(active));
  });
}

function renderPriceChart(data) {
  const series = data.series;
  const trades = data.trades;
  const allDates = series.dates;

  function buildOption() {
    const p = palette();
    const start = startIndexForRange(allDates, state.activeRanges.price);
    const dates = allDates.slice(start);
    const firstDate = dates[0] ?? '';

    const buyPoints = trades
      .filter((t) => t.buy_date >= firstDate)
      .map((t) => ({
        coord: [t.buy_date, t.buy_price],
        value: t.buy_date,
        symbol: 'triangle',
        symbolSize: 13,
        itemStyle: { color: p.up },
        label: { show: true, formatter: '买', position: 'top', color: p.up, fontSize: 10, fontWeight: 600, backgroundColor: p.tooltipBg, borderColor: p.up, borderWidth: 1, padding: [1, 4], borderRadius: 4 },
      }));
    const sellPoints = trades
      .filter((t) => t.sell_date && t.sell_date >= firstDate)
      .map((t) => ({
        coord: [t.sell_date, t.sell_price],
        value: t.sell_date,
        symbol: 'pin',
        symbolSize: 14,
        itemStyle: { color: p.down },
        label: { show: true, formatter: '卖', position: 'top', color: p.down, fontSize: 10, fontWeight: 600, backgroundColor: p.tooltipBg, borderColor: p.down, borderWidth: 1, padding: [1, 4], borderRadius: 4 },
      }));

    return {
      ...chartBase(p),
      grid: chartGrid(p),
      legend: {
        data: ['收盘价', 'MA10', 'MA20', 'MA60', 'MA250'],
        textStyle: { color: p.dim },
        top: 0,
        itemWidth: 16,
        itemHeight: 8,
      },
      xAxis: { type: 'category', data: dates, boundaryGap: false, ...chartAxis(p) },
      yAxis: { type: 'value', scale: true, ...chartAxis(p) },
      dataZoom: [{
        type: 'slider',
        backgroundColor: 'transparent',
        borderColor: 'transparent',
        fillerColor: 'rgba(88,166,255,0.15)',
        handleStyle: { color: '#8b949e' },
        textStyle: { color: p.dim },
        height: 18,
        bottom: 4,
      }],
      series: [
        { name: '收盘价', type: 'line', data: series.close.slice(start), showSymbol: false, lineStyle: { width: 1.5, color: p.price }, emphasis: { focus: 'series' } },
        { name: 'MA10', type: 'line', data: series.ma10.slice(start), showSymbol: false, lineStyle: { width: 1, color: p.ma10, opacity: 0.5 }, emphasis: { focus: 'series' } },
        { name: 'MA20', type: 'line', data: series.ma20.slice(start), showSymbol: false, lineStyle: { width: 1, color: p.ma20, opacity: 0.4 }, emphasis: { focus: 'series' } },
        { name: 'MA60', type: 'line', data: series.ma60.slice(start), showSymbol: false, lineStyle: { width: 1, color: p.ma60, opacity: 0.4 }, emphasis: { focus: 'series' } },
        {
          name: 'MA250', type: 'line', data: series.ma250.slice(start), showSymbol: false,
          lineStyle: { width: 2, color: p.ma250, type: 'dashed' },
          emphasis: { focus: 'series' },
          markPoint: { data: [...buyPoints, ...sellPoints] },
        },
      ],
    };
  }

  const entry = registerChart('chart-price', buildOption);
  document.querySelectorAll('#chart-price-ranges .range-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.activeRanges.price = btn.dataset.range;
      setRangeButtons('chart-price-ranges', btn.dataset.range);
      entry.refresh();
    });
  });

  const latest = allDates[allDates.length - 1];
  const idx = allDates.length - 1;
  document.getElementById('chart-price-summary').textContent =
    `价格与MA250走势图。最新交易日${latest},收盘价${series.close[idx]},MA250为${series.ma250[idx]},偏离度${series.deviation[idx]}%。`;
}

function renderReturnsPanel(data) {
  const series = data.series;
  const trades = data.trades;
  const allDates = series.dates;
  const tableBody = document.getElementById('returns-table-body');

  function buildChartOption() {
    const p = palette();
    const start = startIndexForRange(allDates, state.activeRanges.returns);
    const dates = allDates.slice(start);
    const eq = series.equity_strategy.slice(start);
    const bh = series.equity_buyhold.slice(start);
    const eq0 = eq[0];
    const bh0 = bh[0];
    const toReturn = (arr, base) => arr.map((v) => (v === null || v === undefined ? null : (v / base - 1) * 100));

    return {
      ...chartBase(p),
      grid: chartGrid(p),
      legend: { data: ['MA250策略', '无脑持有510880'], textStyle: { color: p.dim }, top: 0, itemWidth: 16, itemHeight: 8 },
      xAxis: { type: 'category', data: dates, boundaryGap: false, ...chartAxis(p) },
      yAxis: {
        type: 'value', scale: true, ...chartAxis(p),
        axisLabel: { color: p.dim, formatter: '{value}%' },
      },
      series: [
        {
          name: 'MA250策略', type: 'line', data: toReturn(eq, eq0), showSymbol: false,
          lineStyle: { width: 2, color: p.up },
          areaStyle: { color: p.up, opacity: 0.08 },
          emphasis: { focus: 'series' },
        },
        {
          name: '无脑持有510880', type: 'line', data: toReturn(bh, bh0), showSymbol: false,
          lineStyle: { width: 1.5, color: p.dim, type: 'dashed' },
          emphasis: { focus: 'series' },
        },
      ],
    };
  }

  function periodRows(start) {
    const dates = series.dates;
    const startDate = dates[start];
    const endDate = dates[dates.length - 1];
    const eq = series.equity_strategy.slice(start);
    const bh = series.equity_buyhold.slice(start);

    const stratRet = (eq[eq.length - 1] / eq[0] - 1) * 100;
    const bhRet = (bh[bh.length - 1] / bh[0] - 1) * 100;
    const excess = stratRet - bhRet;

    const years = (Date.parse(endDate) - Date.parse(startDate)) / (365.25 * 24 * 3600 * 1000);
    const annualized = years > 0 ? (Math.pow(eq[eq.length - 1] / eq[0], 1 / years) - 1) * 100 : null;

    let peak = eq[0];
    let maxDd = 0;
    for (const v of eq) {
      if (v > peak) peak = v;
      const dd = (v - peak) / peak * 100;
      if (dd < maxDd) maxDd = dd;
    }

    const inPeriod = trades.filter((t) => t.buy_date >= startDate);
    const closed = inPeriod.filter((t) => t.sell_date);
    const winRate = closed.length ? closed.filter((t) => t.pnl_pct > 0).length / closed.length * 100 : null;

    return [
      { label: '区间起点', value: startDate },
      { label: '区间终点', value: endDate },
      { label: 'MA250策略收益', value: fmtSigned(stratRet.toFixed(1)), tone: toneOf(stratRet) },
      { label: '买入持有收益', value: fmtSigned(bhRet.toFixed(1)), tone: toneOf(bhRet) },
      { label: '超额收益', value: fmtSigned(excess.toFixed(1)), tone: toneOf(excess) },
      { label: '策略年化', value: annualized === null ? 'N/A' : fmtSigned(annualized.toFixed(1)), tone: annualized === null ? '' : toneOf(annualized) },
      { label: '最大回撤(策略)', value: fmtSigned(maxDd.toFixed(1)), tone: toneOf(maxDd) },
      { label: '交易笔数', value: `${inPeriod.length}笔` },
      { label: '胜率', value: winRate === null ? 'N/A' : `${winRate.toFixed(0)}%` },
    ];
  }

  function applyRange(range) {
    const start = startIndexForRange(allDates, range);
    state.activeRanges.returns = range;
    entry.refresh();
    tableBody.innerHTML = periodRows(start).map((row) => `
      <tr>
        <td>${row.label}</td>
        <td${row.tone ? ` class="${row.tone}"` : ''}>${row.value}</td>
      </tr>
    `).join('');
    setRangeButtons('returns-ranges', range);
  }

  const entry = registerChart('chart-returns', buildChartOption);
  document.querySelectorAll('#returns-ranges .range-btn').forEach((btn) => {
    btn.addEventListener('click', () => applyRange(btn.dataset.range));
  });
  applyRange('all');

  const last = allDates[allDates.length - 1];
  const eqFinal = series.equity_strategy[series.equity_strategy.length - 1];
  const bhFinal = series.equity_buyhold[series.equity_buyhold.length - 1];
  document.getElementById('chart-returns-summary').textContent =
    `区间收益对比图。截至${last},策略净值${Math.round(eqFinal)}元,买入持有净值${Math.round(bhFinal)}元。`;
}

function renderDeviationChart(series) {
  function buildOption() {
    const p = palette();
    return {
      ...chartBase(p),
      grid: chartGrid(p),
      legend: { data: ['偏离度'], textStyle: { color: p.dim }, top: 0, itemWidth: 16, itemHeight: 8 },
      xAxis: { type: 'category', data: series.dates, ...chartAxis(p) },
      yAxis: { type: 'value', ...chartAxis(p), axisLabel: { color: p.dim, formatter: '{value}%' } },
      dataZoom: [{ type: 'inside' }],
      series: [{
        name: '偏离度',
        type: 'bar',
        data: series.deviation,
        barMaxWidth: 4,
        itemStyle: { color: (point) => (point.value >= 7 ? p.down : point.value >= 0 ? p.up : p.accent) },
        markLine: {
          symbol: 'none',
          label: { position: 'insideEndTop', fontSize: 10 },
          data: [
            { yAxis: 7, name: '卖出监控', lineStyle: { color: p.down, type: 'dashed' }, label: { formatter: '+7 卖出监控', color: p.down } },
            { yAxis: -2, name: '买入区', lineStyle: { color: p.up, type: 'dashed' }, label: { formatter: '-2 买入区', color: p.up } },
            { yAxis: 0, lineStyle: { color: p.axis }, label: { show: false } },
          ],
        },
      }],
    };
  }
  registerChart('chart-deviation', buildOption);
  const lastIdx = series.dates.length - 1;
  document.getElementById('chart-deviation-summary').textContent =
    `偏离度柱状图,阈值线标注+7%卖出监控区与-2%买入区。最新偏离度${series.deviation[lastIdx]}%。`;
}

function renderRsiChart(series) {
  function buildOption() {
    const p = palette();
    return {
      ...chartBase(p),
      grid: chartGrid(p),
      legend: { data: ['RSI14', 'RSI6'], textStyle: { color: p.dim }, top: 0, itemWidth: 16, itemHeight: 8 },
      xAxis: { type: 'category', data: series.dates, ...chartAxis(p) },
      yAxis: { type: 'value', min: 0, max: 100, ...chartAxis(p) },
      dataZoom: [{ type: 'inside' }],
      series: [
        {
          name: 'RSI14', type: 'line', data: series.rsi14, showSymbol: false,
          lineStyle: { width: 1.5, color: p.purple },
          markLine: {
            symbol: 'none',
            label: { position: 'insideEndTop', fontSize: 10 },
            data: [
              { yAxis: 75, name: '卖出确认', lineStyle: { color: p.down, type: 'dashed' }, label: { formatter: '75 卖出确认', color: p.down } },
              { yAxis: 30, name: '超卖区', lineStyle: { color: p.up, type: 'dashed' }, label: { formatter: '30 超卖区', color: p.up } },
            ],
          },
        },
        { name: 'RSI6', type: 'line', data: series.rsi6, showSymbol: false, lineStyle: { width: 1.5, color: p.warn, opacity: 0.65 } },
      ],
    };
  }
  registerChart('chart-rsi', buildOption);
  const lastIdx = series.dates.length - 1;
  document.getElementById('chart-rsi-summary').textContent =
    `RSI走势图,标注75卖出确认线与30超卖线。最新RSI14为${series.rsi14[lastIdx]},RSI6为${series.rsi6[lastIdx]}。`;
}

function renderMacdChart(series) {
  function buildOption() {
    const p = palette();
    return {
      ...chartBase(p),
      grid: chartGrid(p),
      legend: { data: ['MACD柱', 'MACD', 'Signal'], textStyle: { color: p.dim }, top: 0, itemWidth: 16, itemHeight: 8 },
      xAxis: { type: 'category', data: series.dates, ...chartAxis(p) },
      yAxis: { type: 'value', ...chartAxis(p) },
      dataZoom: [{ type: 'inside' }],
      series: [
        { name: 'MACD柱', type: 'bar', data: series.macd_hist, barMaxWidth: 4, itemStyle: { color: (point) => (point.value >= 0 ? p.up : p.down) } },
        { name: 'MACD', type: 'line', data: series.macd, showSymbol: false, lineStyle: { width: 1.5, color: p.accent } },
        { name: 'Signal', type: 'line', data: series.macd_signal, showSymbol: false, lineStyle: { width: 1.5, color: p.warn, opacity: 0.75 } },
      ],
    };
  }
  registerChart('chart-macd', buildOption);
}

function renderEquityChart(series) {
  function buildOption() {
    const p = palette();
    return {
      ...chartBase(p),
      grid: chartGrid(p),
      legend: { data: ['MA250策略', '买入持有'], textStyle: { color: p.dim }, top: 0, itemWidth: 16, itemHeight: 8 },
      xAxis: { type: 'category', data: series.dates, ...chartAxis(p) },
      yAxis: { type: 'value', ...chartAxis(p) },
      dataZoom: [{ type: 'inside' }, { type: 'slider', backgroundColor: 'transparent', borderColor: 'transparent', fillerColor: 'rgba(88,166,255,0.15)', handleStyle: { color: '#8b949e' }, textStyle: { color: p.dim }, height: 18, bottom: 4 }],
      series: [
        { name: 'MA250策略', type: 'line', data: series.equity_strategy, showSymbol: false, lineStyle: { width: 2, color: p.up } },
        { name: '买入持有', type: 'line', data: series.equity_buyhold, showSymbol: false, lineStyle: { width: 1.5, color: p.dim, type: 'dashed' } },
      ],
    };
  }
  registerChart('chart-equity', buildOption);
  const lastIdx = series.dates.length - 1;
  document.getElementById('chart-equity-summary').textContent =
    `策略与买入持有净值对比。截至${series.dates[lastIdx]},策略净值${Math.round(series.equity_strategy[lastIdx])}元,买入持有净值${Math.round(series.equity_buyhold[lastIdx])}元。`;
}

function renderDrawdownChart(series) {
  function buildOption() {
    const p = palette();
    return {
      ...chartBase(p),
      grid: chartGrid(p),
      legend: { data: ['策略回撤'], textStyle: { color: p.dim }, top: 0, itemWidth: 16, itemHeight: 8 },
      xAxis: { type: 'category', data: series.dates, ...chartAxis(p) },
      yAxis: { type: 'value', max: 0, ...chartAxis(p), axisLabel: { color: p.dim, formatter: '{value}%' } },
      dataZoom: [{ type: 'inside' }],
      series: [{
        name: '策略回撤',
        type: 'line',
        data: series.drawdown_pct,
        showSymbol: false,
        lineStyle: { width: 1.5, color: p.down },
        areaStyle: { color: p.down, opacity: 0.12 },
      }],
    };
  }
  registerChart('chart-drawdown', buildOption);
  const lastIdx = series.dates.length - 1;
  document.getElementById('chart-drawdown-summary').textContent =
    `策略回撤曲线,最新回撤${series.drawdown_pct[lastIdx]}%。`;
}

function renderSellReasonChart(breakdown) {
  function buildOption() {
    const p = palette();
    return {
      ...chartBase(p),
      grid: { left: 10, right: 110, top: 10, bottom: 8, containLabel: true },
      xAxis: { type: 'value', ...chartAxis(p), axisLabel: { color: p.dim, formatter: '{value}笔' } },
      yAxis: { type: 'category', data: breakdown.map((b) => b.reason), ...chartAxis(p) },
      series: [{
        type: 'bar',
        data: breakdown.map((b) => b.count),
        barMaxWidth: 22,
        itemStyle: { color: p.down, borderRadius: [0, 6, 6, 0] },
        label: {
          show: true,
          position: 'right',
          color: p.text,
          fontFamily: FONT_MONO,
          fontSize: 12,
          formatter: (point) => {
            const item = breakdown[point.dataIndex];
            return `${item.count}笔 · ${item.pct_of_total}% · 均${fmtSigned(item.avg_pnl_pct)}`;
          },
        },
      }],
    };
  }
  registerChart('chart-sell-reason', buildOption);
  const total = breakdown.reduce((sum, b) => sum + b.count, 0);
  document.getElementById('chart-sell-reason-summary').textContent =
    `卖出原因分布,共${total}笔已平仓交易。`;
}

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

  document.querySelectorAll('#trades-table th').forEach((th, i) => {
    const key = TRADE_COLUMN_KEYS[i];
    const sort = key === sortState.key ? (sortState.dir === 1 ? 'ascending' : 'descending') : 'none';
    th.setAttribute('aria-sort', sort);
  });

  const tbody = document.getElementById('trades-table-body');
  tbody.innerHTML = rows.map((t) => `
    <tr class="${t.open ? 'open-row' : ''}">
      <td>${t.seq}</td>
      <td>${t.buy_date}</td>
      <td>${t.sell_date ?? '持仓中…'}</td>
      <td>${t.buy_price_raw}</td>
      <td>${t.sell_price_raw}</td>
      <td class="${t.open ? '' : toneOf(t.pnl_pct)}">${fmtSigned(t.pnl_pct)}</td>
      <td>${t.hold_days}</td>
      <td>${t.sell_reason}</td>
    </tr>
  `).join('');
}

function initCollapsibleResize() {
  document.querySelectorAll('details.collapsible').forEach((details) => {
    details.addEventListener('toggle', () => charts.forEach((entry) => entry.instance.resize()));
  });
}

document.addEventListener('DOMContentLoaded', main);
