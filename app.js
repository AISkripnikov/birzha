(function () {
  // ================= Bybit =================
  // Если страница открыта через server.py (http://localhost) — запросы идут через него (обход CORS).
  const API = location.protocol.startsWith('http') ? '/bybit' : 'https://api.bybit.com';
  const WS_URL = 'wss://stream.bybit.com/v5/public/spot';
  const IV = { '15m': '15', '1h': '60', '4h': '240', '1d': 'D' };
  const SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'BNBUSDT', 'DOGEUSDT', 'TONUSDT', 'ADAUSDT',
    'AVAXUSDT', 'LINKUSDT', 'SUIUSDT', 'TRXUSDT', 'DOTUSDT', 'LTCUSDT', 'NEARUSDT', 'APTUSDT'];

  async function api(path) {
    const r = await fetch(API + path);
    if (!r.ok) throw new Error(`Bybit ответил ${r.status}`);
    const j = await r.json();
    if (j.retCode !== 0) throw new Error(j.retMsg || 'ошибка Bybit');
    return j.result;
  }
  const toCandle = (t, o, h, l, c, v) => ({ time: +t / 1000, open: +o, high: +h, low: +l, close: +c, volume: +v });

  async function fetchKlines(symbol, interval, limit = 500) {
    const res = await api(`/v5/market/kline?category=spot&symbol=${symbol}&interval=${IV[interval]}&limit=${limit}`);
    return res.list.map((k) => toCandle(k[0], k[1], k[2], k[3], k[4], k[5])).reverse(); // Bybit отдаёт новые первыми
  }
  async function fetchTickers() {
    const res = await api('/v5/market/tickers?category=spot');
    const out = {};
    for (const t of res.list) if (SYMBOLS.includes(t.symbol)) out[t.symbol] = {
      price: +t.lastPrice, chg: +t.price24hPcnt * 100, high: +t.highPrice24h, low: +t.lowPrice24h, turnover: +t.turnover24h,
    };
    return out;
  }

  // ================= состояние =================
  const $ = (id) => document.getElementById(id);
  const store = {
    get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* приватный режим */ } },
  };
  const state = {
    symbol: SYMBOLS.includes(store.get('symbol')) ? store.get('symbol') : 'BTCUSDT',
    interval: IV[store.get('interval')] ? store.get('interval') : '4h',
    candles: [], tickers: {}, ws: null, lastRender: 0,
  };
  $('deposit').value = store.get('deposit', '1000');
  $('risk').value = store.get('risk', '1');

  // ================= формат =================
  const nf = (d) => new Intl.NumberFormat('ru-RU', { minimumFractionDigits: d, maximumFractionDigits: d });
  const fmtPrice = (p) => p == null || isNaN(p) ? '—' : p >= 1000 ? nf(2).format(p) : p >= 1 ? nf(4).format(p) : nf(Math.min(8, 3 - Math.floor(Math.log10(p)))).format(p);
  const fmtMoney = (m) => nf(2).format(m) + ' $';
  const fmtPct = (v) => (v > 0 ? '+' : v < 0 ? '−' : '') + nf(2).format(Math.abs(v)) + '%';
  const fmtBig = (v) => v >= 1e9 ? nf(2).format(v / 1e9) + ' млрд $' : v >= 1e6 ? nf(1).format(v / 1e6) + ' млн $' : nf(0).format(v) + ' $';
  const cls = (v) => (v > 0 ? 'pos' : v < 0 ? 'neg' : 'zero');
  const base = (s) => s.replace('USDT', '');
  const coinColor = (s) => { let h = 0; for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) % 360; return `hsl(${h} 75% 62%)`; };
  const COLORS = { BTC: '#f7931a', ETH: '#8c9eff', SOL: '#9b6bff', XRP: '#9fb3c8', BNB: '#f3ba2f', DOGE: '#d9b44a', TON: '#3aa7ff', ADA: '#4f7dff',
    AVAX: '#ff5a5f', LINK: '#4a7dff', SUI: '#6fbcf0', TRX: '#ff4d4f', DOT: '#ff4fa3', LTC: '#b8c2d1', NEAR: '#5ee6b0', APT: '#4fd1c5' };
  const abbr = (s) => (base(s).length <= 3 ? base(s) : base(s)[0]);
  const icon = (s, cl) => `<span class="${cl}" style="background:${COLORS[base(s)] || coinColor(s)}">${abbr(s)}</span>`;

  function setStatus(text, kind = '') { $('statusText').textContent = text; $('status').className = 'pill ' + kind; }

  // ================= лента монет =================
  function renderTicker() {
    $('ticker').innerHTML = SYMBOLS.map((s) => {
      const t = state.tickers[s];
      return `<button class="tk ${s === state.symbol ? 'active' : ''}" data-sym="${s}">
        ${icon(s, 'tk-ico')}
        <span><div class="tk-sym">${base(s)}</div><div class="tk-price">${t ? fmtPrice(t.price) : '…'}</div></span>
        <span class="tk-chg ${t ? cls(t.chg) : ''}">${t ? fmtPct(t.chg) : ''}</span>
      </button>`;
    }).join('');
  }
  $('ticker').addEventListener('click', (e) => {
    const b = e.target.closest('[data-sym]');
    if (b) selectSymbol(b.dataset.sym);
  });

  function renderHero(livePrice) {
    const t = state.tickers[state.symbol];
    $('heroIcon').style.background = COLORS[base(state.symbol)] || coinColor(state.symbol);
    $('heroIcon').textContent = abbr(state.symbol);
    $('heroSym').textContent = base(state.symbol);
    const price = livePrice ?? t?.price;
    $('heroPrice').textContent = fmtPrice(price);
    if (t) {
      $('heroChg').textContent = fmtPct(t.chg);
      $('heroChg').className = 'chg ' + cls(t.chg);
      $('heroHigh').textContent = fmtPrice(t.high);
      $('heroLow').textContent = fmtPrice(t.low);
      $('heroVol').textContent = fmtBig(t.turnover);
    }
    document.title = `${fmtPrice(price)} · ${base(state.symbol)} — Birzha`;
  }

  async function refreshTickers() {
    try { state.tickers = await fetchTickers(); renderTicker(); renderHero(state.candles.at(-1)?.close); } catch { /* не критично */ }
  }

  // ================= графики =================
  const chartOpts = {
    layout: { background: { color: 'transparent' }, textColor: '#7d8799', fontFamily: 'Inter, system-ui, sans-serif', fontSize: 11 },
    grid: { vertLines: { color: 'rgba(255,255,255,.035)' }, horzLines: { color: 'rgba(255,255,255,.035)' } },
    timeScale: { timeVisible: true, borderColor: '#1f2635', rightOffset: 6 },
    rightPriceScale: { borderColor: '#1f2635' },
    crosshair: { mode: 0, vertLine: { color: '#3a4458', labelBackgroundColor: '#2a3346' }, horzLine: { color: '#3a4458', labelBackgroundColor: '#2a3346' } },
    localization: { locale: 'ru-RU' },
    autoSize: true,
  };
  const chart = LightweightCharts.createChart($('chart'), { ...chartOpts, rightPriceScale: { ...chartOpts.rightPriceScale, scaleMargins: { top: 0.12, bottom: 0.2 } } });
  const candleSeries = chart.addCandlestickSeries({
    upColor: '#20b26c', downColor: '#f6465d', wickUpColor: '#20b26c', wickDownColor: '#f6465d', borderVisible: false,
  });
  const volSeries = chart.addHistogramSeries({ priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
  chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
  const line = (color, extra = {}) => chart.addLineSeries({ color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, ...extra });
  const S = {
    ema20: line('#ffc24b', { lineWidth: 1.5 }), ema50: line('#4f8cff', { lineWidth: 1.5 }), ema200: line('#b57bff', { lineWidth: 1.5 }),
    bbU: line('rgba(140,150,170,.55)', { lineStyle: 2, lineWidth: 1 }), bbL: line('rgba(140,150,170,.55)', { lineStyle: 2, lineWidth: 1 }),
  };
  const planLines = [];

  const rsiChart = LightweightCharts.createChart($('rsiChart'), { ...chartOpts, timeScale: { ...chartOpts.timeScale, visible: false }, handleScroll: false, handleScale: false });
  const rsiSeries = rsiChart.addLineSeries({ color: '#ffc24b', lineWidth: 1.5, priceLineVisible: false });
  rsiSeries.createPriceLine({ price: 70, color: 'rgba(246,70,93,.6)', lineStyle: 2, lineWidth: 1, axisLabelVisible: false });
  rsiSeries.createPriceLine({ price: 30, color: 'rgba(32,178,108,.6)', lineStyle: 2, lineWidth: 1, axisLabelVisible: false });
  chart.timeScale().subscribeVisibleLogicalRangeChange((r) => r && rsiChart.timeScale().setVisibleLogicalRange(r));

  const toLine = (arr) => state.candles.map((c, i) => (arr[i] == null ? null : { time: c.time, value: arr[i] })).filter(Boolean);
  const volBar = (c) => ({ time: c.time, value: c.volume, color: c.close >= c.open ? 'rgba(32,178,108,.35)' : 'rgba(246,70,93,.35)' });

  function renderOhlc(c) {
    if (!c) return;
    const ch = ((c.close - c.open) / c.open) * 100;
    $('ohlc').innerHTML = `<span>О <b>${fmtPrice(c.open)}</b></span><span>М <b>${fmtPrice(c.high)}</b></span>
      <span>Н <b>${fmtPrice(c.low)}</b></span><span>З <b>${fmtPrice(c.close)}</b></span><span class="${cls(ch)}">${fmtPct(ch)}</span>`;
  }
  chart.subscribeCrosshairMove((p) => renderOhlc(p.time ? p.seriesData.get(candleSeries) : state.candles.at(-1)));

  // ================= главный расчёт =================
  function render(full) {
    const candles = state.candles;
    if (candles.length < 210) return;
    const ind = TA.computeAll(candles);
    const i = candles.length - 1, c = candles[i];

    if (full) {
      candleSeries.setData(candles);
      volSeries.setData(candles.map(volBar));
      S.ema20.setData(toLine(ind.ema20)); S.ema50.setData(toLine(ind.ema50)); S.ema200.setData(toLine(ind.ema200));
      S.bbU.setData(toLine(ind.bb.upper)); S.bbL.setData(toLine(ind.bb.lower));
      rsiSeries.setData(toLine(ind.rsi));
      candleSeries.setMarkers(historyMarkers(candles, ind));
      renderBacktest(candles, ind);
    } else {
      candleSeries.update(c);
      volSeries.update(volBar(c));
      for (const [k, arr] of [['ema20', ind.ema20], ['ema50', ind.ema50], ['ema200', ind.ema200], ['bbU', ind.bb.upper], ['bbL', ind.bb.lower]])
        S[k].update({ time: c.time, value: arr[i] });
      rsiSeries.update({ time: c.time, value: ind.rsi[i] });
    }
    renderOhlc(c);
    renderHero(c.close);

    const { score, reasons } = TA.scoreAt(candles, ind, i);
    const v = TA.verdict(score);
    const k = Math.max(-1, Math.min(1, score / TA.MAX_SCORE));
    $('needle').style.transform = `rotate(${k * 90}deg)`;
    $('verdict').textContent = v.label;
    $('verdict').className = 'verdict ' + v.cls;
    $('score').textContent = `оценка ${score > 0 ? '+' : ''}${score.toFixed(1)} из ±${TA.MAX_SCORE}`;
    $('reasons').innerHTML = reasons.map((r) =>
      `<li><span class="pts ${cls(r.pts)}">${r.pts > 0 ? '+' : ''}${r.pts}</span><span>${r.text}</span></li>`).join('');

    renderPlan(c.close, ind.atr[i], v, score);
  }

  function historyMarkers(candles, ind) {
    const markers = [];
    let prev = 0;
    for (let i = 200; i < candles.length; i++) {
      const { score } = TA.scoreAt(candles, ind, i);
      const dir = score >= 3 ? 1 : score <= -3 ? -1 : 0;
      if (dir && dir !== prev) markers.push(dir > 0
        ? { time: candles[i].time, position: 'belowBar', color: '#20b26c', shape: 'arrowUp', text: 'BUY' }
        : { time: candles[i].time, position: 'aboveBar', color: '#f6465d', shape: 'arrowDown', text: 'SELL' });
      if (dir) prev = dir;
    }
    return markers;
  }

  function settings() {
    return {
      deposit: Math.max(0, parseFloat($('deposit').value) || 0),
      riskPct: Math.min(10, Math.max(0.1, parseFloat($('risk').value) || 1)),
    };
  }

  function renderPlan(entry, atrValue, v, score) {
    const { deposit, riskPct } = settings();
    while (planLines.length) candleSeries.removePriceLine(planLines.pop());

    if (v.dir <= 0) {
      const sell = v.dir < 0;
      $('plan').innerHTML = `<div class="skip ${sell ? 'sell-bg' : 'neutral-bg'}">
        <div><b class="${sell ? 'neg' : 'neutral'}">0 $ — не входить</b>
        <p>${sell ? 'Индикаторы против покупки. Если монета уже есть — подумайте о фиксации прибыли или подтяните стоп.'
                  : 'Сигнал слабый. Лучше дождаться явной картины, чем гадать.'}</p></div></div>`;
      return;
    }
    const strength = score >= 3 ? 1 : 0.5;
    const p = TA.positionPlan({ deposit, riskPct, entry, atrValue, strength });
    planLines.push(
      candleSeries.createPriceLine({ price: p.stop, color: '#f6465d', lineStyle: 2, lineWidth: 1, title: 'стоп' }),
      candleSeries.createPriceLine({ price: p.take, color: '#20b26c', lineStyle: 2, lineWidth: 1, title: 'тейк' }),
    );
    $('plan').innerHTML = `
      <div class="amount pos">${fmtMoney(p.amount)}</div>
      <div class="amount-sub">${nf(1).format(deposit ? (p.amount / deposit) * 100 : 0)}% депозита · ${p.qty.toPrecision(5)} ${base(state.symbol)}</div>
      <div class="ladder"><div class="l-risk"></div><div class="l-gain"></div></div>
      <div class="ladder-marks">
        <div><span class="neg">Стоп</span><b>${fmtPrice(p.stop)}</b><span class="neg">−${nf(2).format(p.stopPct)}%</span></div>
        <div><span class="muted">Вход</span><b>${fmtPrice(entry)}</b></div>
        <div><span class="pos">Тейк</span><b>${fmtPrice(p.take)}</b><span class="pos">+${nf(2).format(p.takePct)}%</span></div>
      </div>
      <dl class="kv">
        <dt>Потеря, если сработает стоп</dt><dd class="neg">−${fmtMoney(p.riskMoney)}</dd>
        <dt>Прибыль, если сработает тейк</dt><dd class="pos">+${fmtMoney(p.riskMoney * 2)}</dd>
      </dl>
      <div class="note">Сумма подобрана так, чтобы при стопе потерять не больше ${nf(2).format(riskPct * strength)}% депозита${strength < 1 ? ' — половина риска, сигнал не самый сильный' : ''}.
        Стоп = 1,5×ATR, прибыль/риск 2:1.${p.capped ? ' Сумма ограничена депозитом (без плеча).' : ''}</div>`;
  }

  function renderBacktest(candles, ind) {
    const bt = TA.backtest(candles, ind, { threshold: 3 });
    const days = Math.round((candles.at(-1).time - candles[200].time) / 86400);
    if (!bt.trades.length) {
      $('backtest').innerHTML = `<p class="muted" style="margin:0">За последние ~${days} дн. сильных сигналов на покупку не было.</p>`;
      return;
    }
    $('backtest').innerHTML = `
      <div class="bt-top"><span class="bt-big ${cls(bt.totalPct)}">${fmtPct(bt.totalPct)}</span><span class="muted">за ~${days} дн.</span></div>
      <div class="bar" title="Доля прибыльных сделок"><div style="width:${bt.winRate}%"></div></div>
      <dl class="kv">
        <dt>Сделок по сигналу «ПОКУПАТЬ»</dt><dd>${bt.trades.length}</dd>
        <dt>Прибыльных</dt><dd>${bt.wins} из ${bt.trades.length} (${bt.winRate.toFixed(0)}%)</dd>
      </dl>
      <div class="note">Что было бы, если входить по каждому сильному сигналу со стопом и тейком (комиссия 0,1%).
        При 2:1 стратегия в плюсе, если прибыльных больше ~34%. Прошлое не гарантирует будущее.</div>`;
  }

  // ================= живые обновления =================
  function connectWs() {
    if (state.ws) { state.ws.onclose = null; state.ws.close(); }
    clearInterval(state.ping);
    const ws = new WebSocket(WS_URL);
    state.ws = ws;
    ws.onopen = () => {
      ws.send(JSON.stringify({ op: 'subscribe', args: [`kline.${IV[state.interval]}.${state.symbol}`] }));
      state.ping = setInterval(() => ws.readyState === 1 && ws.send('{"op":"ping"}'), 20000);
      setStatus('онлайн · Bybit в реальном времени', 'live');
    };
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (!m.topic || !m.data) return;
      for (const k of m.data) onCandle(toCandle(k.start, k.open, k.high, k.low, k.close, k.volume));
    };
    ws.onclose = () => { clearInterval(state.ping); setStatus('соединение потеряно, переподключаюсь…'); setTimeout(connectWs, 3000); };
  }

  function onCandle(c) {
    const arr = state.candles;
    if (!arr.length) return;
    if (arr.at(-1).time === c.time) arr[arr.length - 1] = c;
    else if (c.time > arr.at(-1).time) { arr.push(c); arr.shift(); render(true); return; }
    else return;
    const now = Date.now();
    if (now - state.lastRender > 1000) { state.lastRender = now; render(false); }
  }

  async function loadMain() {
    setStatus('загрузка…');
    renderTicker();
    renderHero();
    document.querySelectorAll('#tf button').forEach((b) => b.classList.toggle('active', b.dataset.tf === state.interval));
    try {
      state.candles = await fetchKlines(state.symbol, state.interval, 500);
      render(true);
      chart.timeScale().setVisibleLogicalRange({ from: state.candles.length - 140, to: state.candles.length + 6 });
      connectWs();
    } catch (e) {
      const hint = location.protocol === 'file:' ? ' Запустите через start.bat / server.py.' : ' Проверьте, что server.py запущен и Bybit доступен.';
      setStatus(`Ошибка загрузки: ${e.message}.${hint}`, 'err');
    }
  }

  function selectSymbol(sym) {
    if (sym === state.symbol) return;
    state.symbol = sym; store.set('symbol', sym);
    loadMain();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // ================= сканер =================
  async function scan() {
    const tbody = $('scanTable').querySelector('tbody');
    $('scanBtn').classList.add('spin');
    if (!tbody.children.length) tbody.innerHTML = `<tr class="skeleton"><td colspan="8">Сканирую ${SYMBOLS.length} монет…</td></tr>`;
    const { deposit, riskPct } = settings();

    const rows = await Promise.all(SYMBOLS.map(async (sym) => {
      try {
        const candles = await fetchKlines(sym, state.interval, 300);
        const ind = TA.computeAll(candles);
        const i = candles.length - 1;
        const { score } = TA.scoreAt(candles, ind, i);
        const v = TA.verdict(score);
        const plan = v.dir > 0 ? TA.positionPlan({ deposit, riskPct, entry: candles[i].close, atrValue: ind.atr[i], strength: score >= 3 ? 1 : 0.5 }) : null;
        return { sym, price: candles[i].close, rsi: ind.rsi[i], score, v, plan };
      } catch { return null; }
    }));
    $('scanBtn').classList.remove('spin');

    const ok = rows.filter(Boolean).sort((a, b) => b.score - a.score);
    tbody.innerHTML = ok.map((r) => {
      const t = state.tickers[r.sym];
      const w = Math.min(50, (Math.abs(r.score) / TA.MAX_SCORE) * 50);
      const bar = r.score >= 0 ? `left:50%;width:${w}%;background:var(--green)` : `right:50%;width:${w}%;background:var(--red)`;
      return `<tr data-sym="${r.sym}">
        <td><div class="sc-coin">${icon(r.sym, 'sc-ico')}${base(r.sym)}</div></td>
        <td class="r">${fmtPrice(r.price)}</td>
        <td class="r ${t ? cls(t.chg) : ''}">${t ? fmtPct(t.chg) : '—'}</td>
        <td class="r ${r.rsi < 30 ? 'pos' : r.rsi > 70 ? 'neg' : ''}">${r.rsi.toFixed(0)}</td>
        <td><span class="sbar"><i style="${bar}"></i></span><span class="${cls(r.score)}">${r.score > 0 ? '+' : ''}${r.score.toFixed(1)}</span></td>
        <td><span class="badge ${r.v.cls}">${r.v.label}</span></td>
        <td class="r">${r.plan ? `<b class="pos">${fmtMoney(r.plan.amount)}</b>` : '<span class="muted">—</span>'}</td>
        <td class="r">${r.plan ? `<span class="neg">${fmtPrice(r.plan.stop)}</span> / <span class="pos">${fmtPrice(r.plan.take)}</span>` : '<span class="muted">—</span>'}</td>
      </tr>`;
    }).join('') || `<tr class="skeleton"><td colspan="8" class="neg">Не удалось загрузить данные с Bybit</td></tr>`;
  }
  $('scanTable').addEventListener('click', (e) => { const tr = e.target.closest('tr[data-sym]'); if (tr) selectSymbol(tr.dataset.sym); });

  // ================= события =================
  $('tf').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-tf]');
    if (!b || b.dataset.tf === state.interval) return;
    state.interval = b.dataset.tf; store.set('interval', state.interval);
    loadMain(); scan();
  });
  for (const id of ['deposit', 'risk']) $(id).addEventListener('input', (e) => { store.set(id, e.target.value); render(false); });
  $('scanBtn').addEventListener('click', scan);

  setInterval(refreshTickers, 15000);
  setInterval(scan, 5 * 60 * 1000);
  loadMain();
  refreshTickers().then(scan);
})();
