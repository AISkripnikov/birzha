(function () {
  const $ = (id) => document.getElementById(id);
  const INFO = {
    USDRUBF: { desc: 'доллар / рубль · вечный', ico: '$', color: '#5ee6b0' },
    CNYRUBF: { desc: 'юань / рубль · вечный', ico: '¥', color: '#ff6b6b' },
    EURRUBF: { desc: 'евро / рубль · вечный', ico: '€', color: '#6fa8ff' },
    GLDRUBF: { desc: 'золото, ₽ за грамм · вечный', ico: 'Au', color: '#ffc24b' },
    IMOEXF: { desc: 'индекс Мосбиржи · вечный', ico: 'IX', color: '#b57bff' },
    SBERF: { desc: 'Сбербанк, 100 акций · вечный', ico: 'S', color: '#3ecf8e' },
    GAZPF: { desc: 'Газпром, 100 акций · вечный', ico: 'G', color: '#4f8cff' },
  };
  const info = (s) => INFO[s] || { desc: '', ico: s[0], color: '#9fb3c8' };
  const store = {
    get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* приватный режим */ } },
  };
  const state = { symbol: store.get('fut_symbol', 'USDRUBF'), tf: +store.get('fut_tf', 30), items: [], data: null, key: '' };
  $('capital').value = store.get('fut_capital', '300000');

  // ---------- формат ----------
  const nf = (d) => new Intl.NumberFormat('ru-RU', { minimumFractionDigits: d, maximumFractionDigits: d });
  const dec = (p) => (p >= 1000 ? 1 : p >= 100 ? 2 : 3);
  const fp = (p) => (p == null || isNaN(p) ? '—' : nf(dec(Math.abs(p))).format(p));
  const rub = (v, sign) => (sign && v > 0 ? '+' : v < 0 ? '−' : '') + nf(0).format(Math.abs(v)) + ' ₽';
  const pct = (v) => (v > 0 ? '+' : v < 0 ? '−' : '') + nf(2).format(Math.abs(v)) + '%';
  const cls = (v) => (v > 0 ? 'pos' : v < 0 ? 'neg' : 'zero');
  const side = (d) => (d > 0 ? 'ЛОНГ' : 'ШОРТ');
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

  async function get(url) {
    const r = await fetch(url, { cache: 'no-store' });
    const j = await r.json().catch(() => ({ error: `сервер ответил ${r.status}` }));
    if (!r.ok || j.error) throw new Error(j.error || `сервер ответил ${r.status}`);
    return j;
  }
  function setStatus(text, kind) { $('statusText').textContent = text; $('status').className = 'pill ' + (kind || ''); }

  // ---------- график ----------
  const chart = LightweightCharts.createChart($('chart'), {
    layout: { background: { color: 'transparent' }, textColor: '#7d8799', fontFamily: 'Inter, system-ui, sans-serif', fontSize: 11 },
    grid: { vertLines: { color: 'rgba(255,255,255,.035)' }, horzLines: { color: 'rgba(255,255,255,.035)' } },
    timeScale: { timeVisible: true, secondsVisible: false, borderColor: '#1f2635', rightOffset: 4 },
    rightPriceScale: { borderColor: '#1f2635', scaleMargins: { top: 0.08, bottom: 0.2 } },
    crosshair: { mode: 0 }, localization: { locale: 'ru-RU' }, autoSize: true,
  });
  const candles = chart.addCandlestickSeries({ upColor: '#20b26c', downColor: '#f6465d', wickUpColor: '#20b26c', wickDownColor: '#f6465d', borderVisible: false });
  const vol = chart.addHistogramSeries({ priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
  chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
  const line = (color, extra) => chart.addLineSeries({ color, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, ...extra });
  const L = {
    fast: line('#ffc24b'), slow: line('#4f8cff', { lineWidth: 2 }),
    hh: line('rgba(32,178,108,.55)', { lineStyle: 2, lineWidth: 1, lineType: 1 }),
    ll: line('rgba(246,70,93,.55)', { lineStyle: 2, lineWidth: 1, lineType: 1 }),
  };
  let priceLines = [];

  function renderOhlc(c) {
    if (!c) { $('ohlc').innerHTML = ''; return; }
    const ch = ((c.close - c.open) / c.open) * 100;
    $('ohlc').innerHTML = `<span>О <b>${fp(c.open)}</b></span><span>М <b>${fp(c.high)}</b></span><span>Н <b>${fp(c.low)}</b></span>` +
      `<span>З <b>${fp(c.close)}</b></span><span class="${cls(ch)}">${pct(ch)}</span>`;
  }
  chart.subscribeCrosshairMove((p) => renderOhlc(p.time ? p.seriesData.get(candles) : state.data?.candles.at(-1)));

  function drawChart(d, fresh) {
    candles.setData(d.candles);
    vol.setData(d.candles.map((c) => ({ time: c.time, value: c.volume, color: c.close >= c.open ? 'rgba(32,178,108,.3)' : 'rgba(246,70,93,.3)' })));
    L.fast.setData(d.ema_fast); L.slow.setData(d.ema_slow); L.hh.setData(d.hh); L.ll.setData(d.ll);
    candles.setMarkers(d.markers.map((m) => m.kind === 'enter'
      ? { time: m.time, position: m.dir > 0 ? 'belowBar' : 'aboveBar', shape: m.dir > 0 ? 'arrowUp' : 'arrowDown', color: m.dir > 0 ? '#20b26c' : '#f6465d', text: m.text }
      : { time: m.time, position: m.dir > 0 ? 'aboveBar' : 'belowBar', shape: 'circle', color: '#c9d1de', text: m.text }));
    priceLines.forEach((l) => candles.removePriceLine(l));
    priceLines = [];
    const st = d.status;
    const pl = (price, color, title, style = 2) => priceLines.push(candles.createPriceLine({ price, color, title, lineStyle: style, lineWidth: 1, axisLabelVisible: true }));
    if (st?.position) {
      pl(st.position.entry, '#c9d1de', 'вход', 0);
      pl(st.position.stop, '#f7a600', 'стоп', 0);
    } else if (st) {
      pl(st.up_level, 'rgba(32,178,108,.9)', 'лонг выше');
      pl(st.dn_level, 'rgba(246,70,93,.9)', 'шорт ниже');
    }
    if (fresh) {
      const n = d.candles.length;
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 140), to: n + 4 });
    }
    renderOhlc(d.candles.at(-1));
  }

  // ---------- лента ----------
  function renderTicker() {
    $('ticker').innerHTML = state.items.map((t) => {
      const i = info(t.symbol);
      return `<button class="tk ${t.symbol === state.symbol ? 'active' : ''}" data-sym="${t.symbol}">
        <span class="tk-ico" style="background:${i.color}">${i.ico}</span>
        <span><div class="tk-sym">${t.symbol}</div><div class="tk-price">${t.error ? 'нет данных' : fp(t.price)}</div></span>
        ${t.error ? '' : `<span class="tk-chg ${cls(t.chg)}">${pct(t.chg)}</span>`}
      </button>`;
    }).join('');
  }
  $('ticker').addEventListener('click', (e) => {
    const b = e.target.closest('[data-sym]');
    if (b && b.dataset.sym !== state.symbol) { state.symbol = b.dataset.sym; store.set('fut_symbol', state.symbol); renderTicker(); refresh(true); }
  });
  document.querySelectorAll('#tf button').forEach((b) => {
    b.classList.toggle('active', +b.dataset.tf === state.tf);
    b.addEventListener('click', () => {
      state.tf = +b.dataset.tf; store.set('fut_tf', state.tf);
      document.querySelectorAll('#tf button').forEach((x) => x.classList.toggle('active', x === b));
      refresh(true);
    });
  });
  let capTimer;
  $('capital').addEventListener('input', () => {
    store.set('fut_capital', $('capital').value);
    clearTimeout(capTimer); capTimer = setTimeout(() => refresh(false), 400);
  });

  // ---------- панели ----------
  function renderHero(d) {
    const i = info(d.symbol), st = d.status, item = state.items.find((x) => x.symbol === d.symbol);
    $('heroIcon').textContent = i.ico; $('heroIcon').style.background = i.color;
    $('heroSym').textContent = d.symbol; $('heroDesc').textContent = i.desc;
    const price = d.candles.at(-1)?.close;
    $('heroPrice').textContent = fp(price);
    if (item && !item.error) { $('heroChg').textContent = pct(item.chg); $('heroChg').className = 'chg ' + cls(item.chg); }
    $('hAtr').textContent = st ? fp(st.atr) : '—';
    $('hPv').textContent = nf(0).format(d.point_value) + ' ₽';
    $('hLast').textContent = st ? st.last_closed.slice(5).replace(' ', ', ') : '—';
    document.title = `${fp(price)} · ${d.symbol} — Birzha`;
  }

  function check(kind, title, text) {
    const ic = kind === 'ok' ? '✓' : kind === 'bad' ? '✕' : '•';
    return `<li><span class="ic ${kind}">${ic}</span><div><b>${title}</b><span>${text}</span></div></li>`;
  }

  function renderSignal(d) {
    const st = d.status, p = d.params;
    const v = $('verdict');
    if (!st) { v.textContent = 'Мало данных'; v.className = 'verdict wait'; $('verdictSub').textContent = 'Нужно больше свечей для индикаторов.'; $('checks').innerHTML = ''; return; }
    if (st.position) {
      v.textContent = `В позиции: ${side(st.position.dir)}`;
      v.className = 'verdict ' + (st.position.dir > 0 ? 'long' : 'short');
      $('verdictSub').innerHTML = `${st.position.qty} контр. с ${st.position.t.slice(11)} по ${fp(st.position.entry)} · сейчас <b class="${cls(st.position.pnl)}">${rub(st.position.pnl, true)}</b>`;
    } else if (st.pending) {
      v.textContent = `Сигнал: ${side(st.pending.dir)}`;
      v.className = 'verdict ' + (st.pending.dir > 0 ? 'long' : 'short');
      $('verdictSub').textContent = `Свеча ${st.pending.t.slice(11)} закрылась пробоем — бот входит сразу после её закрытия.`;
    } else {
      v.textContent = 'Ждать';
      v.className = 'verdict wait';
      $('verdictSub').textContent = 'Условия входа сейчас не выполнены. Уровни пробоя — на графике.';
    }
    const trendTxt = st.trend > 0 ? 'Вверх: цена и EMA20 выше EMA50 — ищем только лонги'
      : st.trend < 0 ? 'Вниз: цена и EMA20 ниже EMA50 — ищем только шорты' : 'Нет чёткого тренда — входов не будет';
    const toUp = (st.up_level - st.price) / st.atr, toDn = (st.price - st.dn_level) / st.atr;
    const brk = st.trend > 0 ? `Лонг, если свеча закроется выше ${fp(st.up_level)} (≈${nf(1).format(Math.max(toUp, 0))} ATR от цены)`
      : st.trend < 0 ? `Шорт, если свеча закроется ниже ${fp(st.dn_level)} (≈${nf(1).format(Math.max(toDn, 0))} ATR от цены)`
        : `Лонг выше ${fp(st.up_level)}, шорт ниже ${fp(st.dn_level)}`;
    const near = Math.min(st.trend > 0 ? toUp : st.trend < 0 ? toDn : 9, 9);
    $('checks').innerHTML = [
      check(st.trend ? 'ok' : 'bad', 'Тренд', trendTxt),
      check(st.trend ? (near < 0.5 ? 'ok' : 'mid') : 'mid', 'Пробой канала ' + p.channel + ' свечей', brk),
      check(st.window ? 'ok' : 'bad', 'Время входа', st.window ? `Окно открыто до ${p.last_entry} МСК` : `Новые входы ${p.start}–${p.last_entry} МСК по будням, закрытие всего в ${p.flat}`),
      check(st.trades_today < st.max_trades ? 'ok' : 'bad', 'Сделок сегодня', `${st.trades_today} из ${st.max_trades} по этому инструменту`),
    ].join('');
  }

  function renderPlan(d) {
    const st = d.status;
    if (!st) { $('plan').innerHTML = ''; return; }
    const pl = st.plan;
    if (pl.qty <= 0) {
      $('plan').innerHTML = `<p class="err-box">Капитала не хватает даже на 1 контракт при риске ${nf(1).format(d.risk.risk_per_trade * 100)}% на сделку.</p>`;
      return;
    }
    $('plan').innerHTML = `
      <div class="plan-grid">
        <div><span>Контрактов</span><b>${pl.qty}</b></div>
        <div><span>Риск при стопе</span><b class="neg">${rub(-pl.risk_rub)}</b></div>
        <div><span>ГО (примерно)</span><b>${rub(pl.margin_rub)}</b></div>
        <div><span>Стоимость позиции</span><b>${rub(pl.notional)}</b></div>
      </div>
      <div class="plan-sides">
        <div class="plan-side long"><b>Лонг: закрытие выше ${fp(st.up_level)}</b>стоп ≈ ${fp(pl.long_stop)} (2×ATR = ${fp(pl.stop_dist)})</div>
        <div class="plan-side short"><b>Шорт: закрытие ниже ${fp(st.dn_level)}</b>стоп ≈ ${fp(pl.short_stop)}</div>
      </div>
      <p class="note">Риск ${nf(1).format(d.risk.risk_per_trade * 100)}% капитала на сделку, ГО — не больше ${nf(0).format(d.risk.max_margin * 100)}% капитала.
      Стоп дальше подтягивается за ценой. Реальное ГО смотрите у брокера.</p>`;
  }

  function renderStats(d) {
    const st = d.status;
    if (!st) { $('kpis').innerHTML = ''; return; }
    const s = st.stats;
    $('statsFrom').textContent = `с ${s.from}, свечи ${d.tf} мин, комиссии учтены`;
    $('kpis').innerHTML = `
      <div><span>Результат</span><b class="${cls(s.pnl)}">${rub(s.pnl, true)}</b></div>
      <div><span>К капиталу</span><b class="${cls(s.return)}">${pct(s.return * 100)}</b></div>
      <div><span>Сделок</span><b>${s.trades}</b></div>
      <div><span>Прибыльных</span><b>${nf(0).format(s.win_rate * 100)}%</b></div>
      <div><span>Profit factor</span><b class="${s.profit_factor == null ? '' : s.profit_factor >= 1.2 ? 'pos' : s.profit_factor < 1 ? 'neg' : ''}">${s.profit_factor == null ? '—' : nf(2).format(s.profit_factor)}</b></div>`;
    const rows = st.trades.map((t) => `<tr>
      <td>${esc(t.entry_t.slice(5))}</td>
      <td><span class="tag ${t.dir > 0 ? 'long' : 'short'}">${side(t.dir)}</span></td>
      <td class="r">${t.qty}</td>
      <td class="r">${fp(t.entry)} → ${fp(t.exit)}</td>
      <td>${esc(t.exit_t.slice(11))} · ${esc(t.reason)}</td>
      <td class="r ${cls(t.pnl)}"><b>${rub(t.pnl, true)}</b></td></tr>`).join('');
    $('trades').querySelector('tbody').innerHTML = rows || '<tr><td colspan="6" class="empty">Сделок на этой истории не было.</td></tr>';
  }

  // ---------- обновление ----------
  let busy = false;
  async function refresh(fresh) {
    if (busy && !fresh) return;
    busy = true;
    const key = `${state.symbol}:${state.tf}`;
    try {
      const d = await get(`/api/state?symbol=${state.symbol}&tf=${state.tf}&capital=${+$('capital').value || 300000}`);
      if (`${state.symbol}:${state.tf}` !== key) return;   // пока грузили, пользователь переключился
      const isNew = fresh || state.key !== key;
      state.data = d; state.key = key;
      drawChart(d, isNew); renderHero(d); renderSignal(d); renderPlan(d); renderStats(d);
      const live = d.source.includes('реальное');
      setStatus(`${d.source} · обновлено ${d.now}`, live ? 'live' : 'delay');
    } catch (e) {
      setStatus('Ошибка: ' + e.message, 'err');
    } finally { busy = false; }
  }
  async function refreshItems() {
    try { const j = await get('/api/instruments'); state.items = j.items; renderTicker(); if (state.data) renderHero(state.data); } catch { /* не критично */ }
  }
  setInterval(() => { $('clock').textContent = new Date().toLocaleTimeString('ru-RU', { timeZone: 'Europe/Moscow' }) + ' МСК'; }, 1000);

  renderTicker();
  refreshItems();
  refresh(true);
  setInterval(() => refresh(false), 10000);
  setInterval(refreshItems, 30000);
})();
