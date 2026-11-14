(function () {
  const API = 'https://data-api.binance.vision/api/v3';
  const WS = 'wss://data-stream.binance.vision/ws';
  const SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT', 'ADAUSDT', 'TONUSDT',
    'AVAXUSDT', 'LINKUSDT', 'DOTUSDT', 'TRXUSDT', 'LTCUSDT', 'NEARUSDT', 'SUIUSDT', 'APTUSDT'];

  const $ = (id) => document.getElementById(id);
  const state = { symbol: 'BTCUSDT', interval: '4h', candles: [], ws: null, lastRender: 0 };

  // ---------- настройки (запоминаем в браузере) ----------
  function load(key, def) { try { return localStorage.getItem(key) ?? def; } catch { return def; } }
  function save(key, val) { try { localStorage.setItem(key, val); } catch { /* приватный режим */ } }

  SYMBOLS.forEach((s) => $('symbol').add(new Option(s.replace('USDT', ' / USDT'), s)));
  state.symbol = load('symbol', 'BTCUSDT');
  state.interval = load('interval', '4h');
  $('symbol').value = state.symbol;
  $('interval').value = state.interval;
  $('deposit').value = load('deposit', '1000');
  $('risk').value = load('risk', '1');

  // ---------- форматирование ----------
  const fmtPrice = (p) => p >= 1000 ? p.toLocaleString('ru-RU', { maximumFractionDigits: 2 })
    : p >= 1 ? p.toFixed(4) : p.toPrecision(4);
  const fmtMoney = (m) => m.toLocaleString('ru-RU', { maximumFractionDigits: 2 }) + ' $';
  const fmtPct = (v) => (v > 0 ? '+' : '') + v.toFixed(2) + '%';
  const cls = (v) => (v > 0 ? 'pos' : v < 0 ? 'neg' : 'zero');

  // ---------- данные ----------
  async function fetchKlines(symbol, interval, limit = 500) {
    const r = await fetch(`${API}/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`);
    if (!r.ok) throw new Error(`Binance ответил ${r.status}`);
    const raw = await r.json();
    return raw.map((k) => ({ time: k[0] / 1000, open: +k[1], high: +k[2], low: +k[3], close: +k[4], volume: +k[5] }));
  }

  // ---------- графики ----------
  const chartOpts = {
    layout: { background: { color: 'transparent' }, textColor: '#8b949e' },
    grid: { vertLines: { color: '#1f262f' }, horzLines: { color: '#1f262f' } },
    timeScale: { timeVisible: true, borderColor: '#2a313c' },
    rightPriceScale: { borderColor: '#2a313c' },
    crosshair: { mode: 0 },
    autoSize: true,
  };
  const chart = LightweightCharts.createChart($('chart'), chartOpts);
  const candleSeries = chart.addCandlestickSeries({
    upColor: '#22c55e', downColor: '#ef4444', wickUpColor: '#22c55e', wickDownColor: '#ef4444', borderVisible: false,
  });
  const line = (color, extra = {}) => chart.addLineSeries({ color, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, ...extra });
  const s = {
    ema20: line('#f0b90b'), ema50: line('#3b82f6'), ema200: line('#a855f7'),
    bbU: line('#8b949e', { lineStyle: 2, lineWidth: 1 }), bbL: line('#8b949e', { lineStyle: 2, lineWidth: 1 }),
  };
  const stopLine = { stop: null, take: null };

  const rsiChart = LightweightCharts.createChart($('rsiChart'), { ...chartOpts, timeScale: { ...chartOpts.timeScale, visible: false } });
  const rsiSeries = rsiChart.addLineSeries({ color: '#f0b90b', lineWidth: 1.5, priceLineVisible: false });
  rsiSeries.createPriceLine({ price: 70, color: '#ef4444', lineStyle: 2, lineWidth: 1, axisLabelVisible: false });
  rsiSeries.createPriceLine({ price: 30, color: '#22c55e', lineStyle: 2, lineWidth: 1, axisLabelVisible: false });
  chart.timeScale().subscribeVisibleLogicalRangeChange((r) => r && rsiChart.timeScale().setVisibleLogicalRange(r));

  const toLine = (arr) => state.candles.map((c, i) => (arr[i] == null ? null : { time: c.time, value: arr[i] })).filter(Boolean);

  // ---------- главный расчёт и отрисовка ----------
  function render(full) {
    const candles = state.candles;
    if (candles.length < 210) return;
    const ind = TA.computeAll(candles);
    const last = candles.length - 1;

    if (full) {
      candleSeries.setData(candles);
      s.ema20.setData(toLine(ind.ema20)); s.ema50.setData(toLine(ind.ema50)); s.ema200.setData(toLine(ind.ema200));
      s.bbU.setData(toLine(ind.bb.upper)); s.bbL.setData(toLine(ind.bb.lower));
      rsiSeries.setData(toLine(ind.rsi));
      candleSeries.setMarkers(historyMarkers(candles, ind));
      renderBacktest(candles, ind);
    } else {
      candleSeries.update(candles[last]);
      for (const [k, arr] of [['ema20', ind.ema20], ['ema50', ind.ema50], ['ema200', ind.ema200], ['bbU', ind.bb.upper], ['bbL', ind.bb.lower]])
        s[k].update({ time: candles[last].time, value: arr[last] });
      rsiSeries.update({ time: candles[last].time, value: ind.rsi[last] });
    }

    const { score, reasons } = TA.scoreAt(candles, ind, last);
    const v = TA.verdict(score);
    $('verdict').textContent = v.label;
    $('verdict').className = 'verdict ' + v.cls;
    const pos = Math.max(0, Math.min(1, (score + TA.MAX_SCORE) / (2 * TA.MAX_SCORE)));
    $('meterFill').style.left = `calc(${pos * 100}% - 2px)`;
    $('price').textContent = `Цена ${fmtPrice(candles[last].close)} USDT · оценка ${score > 0 ? '+' : ''}${score.toFixed(1)} из ±${TA.MAX_SCORE}`;
    $('reasons').innerHTML = reasons.map((r) =>
      `<li><span class="pts ${cls(r.pts)}">${r.pts > 0 ? '+' : ''}${r.pts}</span><span>${r.text}</span></li>`).join('');
    $('chartTitle').textContent = `${state.symbol.replace('USDT', ' / USDT')} · ${$('interval').selectedOptions[0].text}`;

    renderPlan(candles[last].close, ind.atr[last], v, score);
  }

  function historyMarkers(candles, ind) {
    const markers = [];
    let prevDir = 0;
    for (let i = 200; i < candles.length; i++) {
      const { score } = TA.scoreAt(candles, ind, i);
      const dir = score >= 3 ? 1 : score <= -3 ? -1 : 0;
      if (dir !== 0 && dir !== prevDir) {
        markers.push(dir > 0
          ? { time: candles[i].time, position: 'belowBar', color: '#22c55e', shape: 'arrowUp', text: 'BUY' }
          : { time: candles[i].time, position: 'aboveBar', color: '#ef4444', shape: 'arrowDown', text: 'SELL' });
      }
      if (dir !== 0) prevDir = dir;
    }
    return markers;
  }

  function settings() {
    const deposit = Math.max(0, parseFloat($('deposit').value) || 0);
    const riskPct = Math.min(10, Math.max(0.1, parseFloat($('risk').value) || 1));
    return { deposit, riskPct };
  }

  function renderPlan(entry, atrValue, v, score) {
    const { deposit, riskPct } = settings();
    for (const k of ['stop', 'take']) if (stopLine[k]) { candleSeries.removePriceLine(stopLine[k]); stopLine[k] = null; }

    if (v.dir <= 0) {
      $('plan').innerHTML = `<div class="big ${v.dir < 0 ? 'neg' : 'neutral'}">0 $ — не входить</div>
        <div class="note">${v.dir < 0
          ? 'Индикаторы против покупки. Если монета уже есть — подумайте о фиксации или подтяните стоп.'
          : 'Сигнал слабый. Лучше подождать более явной картины, чем гадать.'}</div>`;
      return;
    }
    const strength = score >= 3 ? 1 : 0.5;
    const p = TA.positionPlan({ deposit, riskPct, entry, atrValue, strength });
    stopLine.stop = candleSeries.createPriceLine({ price: p.stop, color: '#ef4444', lineStyle: 1, title: 'стоп' });
    stopLine.take = candleSeries.createPriceLine({ price: p.take, color: '#22c55e', lineStyle: 1, title: 'тейк' });
    $('plan').innerHTML = `
      <div class="big pos">${fmtMoney(p.amount)}</div>
      <div class="note" style="margin-top:0">${((p.amount / deposit) * 100 || 0).toFixed(1)}% депозита · ${p.qty.toPrecision(5)} ${state.symbol.replace('USDT', '')}</div>
      <dl class="kv" style="margin-top:10px">
        <dt>Вход (рынок)</dt><dd>${fmtPrice(entry)}</dd>
        <dt>Стоп-лосс</dt><dd class="neg">${fmtPrice(p.stop)} (−${p.stopPct.toFixed(2)}%)</dd>
        <dt>Тейк-профит</dt><dd class="pos">${fmtPrice(p.take)} (+${p.takePct.toFixed(2)}%)</dd>
        <dt>Потеря при стопе</dt><dd class="neg">−${fmtMoney(p.riskMoney)}</dd>
        <dt>Прибыль при тейке</dt><dd class="pos">+${fmtMoney(p.riskMoney * 2)}</dd>
      </dl>
      <div class="note">Размер рассчитан так, чтобы при срабатывании стопа вы потеряли не больше
        ${(riskPct * strength).toFixed(2)}% депозита${strength < 1 ? ' (половина риска — сигнал не самый сильный)' : ''}.
        Стоп = 1.5×ATR, соотношение прибыль/риск 2:1.${p.capped ? ' Сумма ограничена всем депозитом (без плеча).' : ''}</div>`;
  }

  function renderBacktest(candles, ind) {
    const bt = TA.backtest(candles, ind, { threshold: 3 });
    const days = ((candles.at(-1).time - candles[200].time) / 86400).toFixed(0);
    if (!bt.trades.length) {
      $('backtest').innerHTML = `<div class="note">За последние ~${days} дн. сильных сигналов на покупку не было.</div>`;
      return;
    }
    $('backtest').innerHTML = `
      <dl class="kv">
        <dt>Период</dt><dd>~${days} дн.</dd>
        <dt>Сделок по сигналу «ПОКУПАТЬ»</dt><dd>${bt.trades.length}</dd>
        <dt>Прибыльных</dt><dd>${bt.wins} (${bt.winRate.toFixed(0)}%)</dd>
        <dt>Итог по позиции</dt><dd class="${cls(bt.totalPct)}">${fmtPct(bt.totalPct)}</dd>
      </dl>
      <div class="note">Если бы вы входили по каждому сильному сигналу со стопом и тейком (с комиссией 0.1%).
        При соотношении 2:1 стратегия в плюсе, если прибыльных больше ~34%. Прошлое не гарантирует будущее.</div>`;
  }

  // ---------- живые обновления ----------
  function connectWs() {
    if (state.ws) { state.ws.onclose = null; state.ws.close(); }
    const ws = new WebSocket(`${WS}/${state.symbol.toLowerCase()}@kline_${state.interval}`);
    state.ws = ws;
    ws.onopen = () => setStatus('онлайн · обновляется в реальном времени', 'live');
    ws.onmessage = (e) => {
      const k = JSON.parse(e.data).k;
      const c = { time: k.t / 1000, open: +k.o, high: +k.h, low: +k.l, close: +k.c, volume: +k.v };
      const arr = state.candles;
      if (!arr.length) return;
      if (arr.at(-1).time === c.time) arr[arr.length - 1] = c;
      else if (c.time > arr.at(-1).time) { arr.push(c); arr.shift(); render(true); return; }
      const now = Date.now();
      if (now - state.lastRender > 1000) { state.lastRender = now; render(false); }
    };
    ws.onclose = () => { setStatus('соединение потеряно, переподключаюсь…'); setTimeout(connectWs, 3000); };
  }

  function setStatus(text, kind = '') { $('status').textContent = text; $('status').className = 'status ' + kind; }

  async function loadMain() {
    setStatus('загрузка…');
    try {
      state.candles = await fetchKlines(state.symbol, state.interval, 500);
      render(true);
      chart.timeScale().setVisibleLogicalRange({ from: state.candles.length - 150, to: state.candles.length + 5 });
      connectWs();
    } catch (e) {
      setStatus('Ошибка загрузки: ' + e.message + '. Возможно, Binance недоступен из вашей сети.', 'err');
    }
  }

  // ---------- сканер ----------
  async function scan() {
    const tbody = $('scanTable').querySelector('tbody');
    tbody.innerHTML = `<tr><td colspan="8" class="zero">Сканирую ${SYMBOLS.length} монет…</td></tr>`;
    const { deposit, riskPct } = settings();
    let tickers = {};
    try {
      const r = await fetch(`${API}/ticker/24hr?symbols=${encodeURIComponent(JSON.stringify(SYMBOLS))}`);
      (await r.json()).forEach((t) => (tickers[t.symbol] = +t.priceChangePercent));
    } catch { /* без суточного изменения */ }

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

    const ok = rows.filter(Boolean).sort((a, b) => b.score - a.score);
    tbody.innerHTML = ok.map((r) => `
      <tr data-sym="${r.sym}">
        <td><b>${r.sym.replace('USDT', '')}</b></td>
        <td>${fmtPrice(r.price)}</td>
        <td class="${cls(tickers[r.sym] ?? 0)}">${tickers[r.sym] != null ? fmtPct(tickers[r.sym]) : '—'}</td>
        <td>${r.rsi.toFixed(0)}</td>
        <td class="${cls(r.score)}">${r.score > 0 ? '+' : ''}${r.score.toFixed(1)}</td>
        <td class="${r.v.cls}">${r.v.label}</td>
        <td>${r.plan ? fmtMoney(r.plan.amount) : '—'}</td>
        <td>${r.plan ? `${fmtPrice(r.plan.stop)} / ${fmtPrice(r.plan.take)}` : '—'}</td>
      </tr>`).join('') || `<tr><td colspan="8" class="neg">Не удалось загрузить данные</td></tr>`;
    tbody.querySelectorAll('tr[data-sym]').forEach((tr) => tr.addEventListener('click', () => {
      $('symbol').value = tr.dataset.sym; $('symbol').dispatchEvent(new Event('change'));
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }));
  }

  // ---------- события ----------
  $('symbol').addEventListener('change', (e) => { state.symbol = e.target.value; save('symbol', state.symbol); loadMain(); });
  $('interval').addEventListener('change', (e) => { state.interval = e.target.value; save('interval', state.interval); loadMain(); scan(); });
  for (const id of ['deposit', 'risk']) $(id).addEventListener('input', (e) => { save(id, e.target.value); render(false); });
  $('scanBtn').addEventListener('click', scan);
  setInterval(scan, 5 * 60 * 1000);

  loadMain();
  scan();
})();
