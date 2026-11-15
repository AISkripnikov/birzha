(function () {
  const $ = (id) => document.getElementById(id);
  const INFO = {
    USDRUBF: ['доллар / рубль · вечный', '$', '#5ee6b0'], CNYRUBF: ['юань / рубль · вечный', '¥', '#ff6b6b'],
    EURRUBF: ['евро / рубль · вечный', '€', '#6fa8ff'], GLDRUBF: ['золото, ₽ за грамм · вечный', 'Au', '#ffc24b'],
    IMOEXF: ['индекс Мосбиржи · вечный', 'IX', '#b57bff'], SBERF: ['Сбербанк, 100 акций · вечный', 'S', '#3ecf8e'],
    GAZPF: ['Газпром, 100 акций · вечный', 'G', '#4f8cff'],
    Si: ['доллар, 1000 $', 'Si', '#5ee6b0'], CNY: ['юань, 1000 ¥', 'CR', '#ff6b6b'], BR: ['нефть Brent, 10 баррелей', 'BR', '#c9a96e'],
    NG: ['природный газ, 100 MMBtu', 'NG', '#7fd0ff'], GOLD: ['золото, 1 унция', 'GD', '#ffc24b'], MIX: ['индекс Мосбиржи', 'MX', '#b57bff'],
    SBER: ['Сбербанк', 'SB', '#3ecf8e'], GAZP: ['Газпром', 'GZ', '#4f8cff'], LKOH: ['Лукойл', 'LK', '#ff5a5f'],
    VTBR: ['ВТБ', 'VT', '#3a7bff'], YDEX: ['Яндекс', 'Я', '#ffcc00'], T: ['Т-Технологии', 'T', '#ffdd2d'],
    AFLT: ['Аэрофлот', 'AF', '#5b8def'], MOEX: ['Московская биржа', 'MX', '#e04f5f'], ROSN: ['Роснефть', 'RN', '#ffb547'],
    MGNT: ['Магнит', 'MG', '#ff4f6d'],
    BTCUSDT: ['Bitcoin', '₿', '#f7931a'], ETHUSDT: ['Ethereum', 'Ξ', '#8c9eff'], SOLUSDT: ['Solana', 'SOL', '#9b6bff'],
    TONUSDT: ['Toncoin', 'TON', '#3aa7ff'], XRPUSDT: ['XRP', 'XRP', '#9fb3c8'], DOGEUSDT: ['Dogecoin', 'Ð', '#d9b44a'],
  };
  const info = (s) => { const i = INFO[s] || ['', s.slice(0, 2), '#9fb3c8']; return { desc: i[0], ico: i[1], color: i[2] }; };
  const store = {
    get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* приватный режим */ } },
  };
  const state = {
    symbol: store.get('w_symbol', 'CNYRUBF'), tf: +store.get('w_tf', 30), group: store.get('w_group', 'all'),
    fitOnly: store.get('w_fit', '0') === '1', items: [], venues: null, data: null, key: '',
  };
  $('capital').value = store.get('w_capital', '2000');
  $('risk').value = store.get('w_risk', '1');
  $('fitOnly').checked = state.fitOnly;
  const capital = () => Math.max(+$('capital').value || 2000, 1);
  const riskPct = () => Math.min(Math.max(+$('risk').value || 1, 0.1), 5);

  // ---------- формат ----------
  const nf = (d) => new Intl.NumberFormat('ru-RU', { minimumFractionDigits: d, maximumFractionDigits: d });
  const dec = (p) => (p >= 1000 ? 1 : p >= 100 ? 2 : p >= 1 ? 3 : 5);
  const fp = (p) => (p == null || isNaN(p) ? '—' : nf(dec(Math.abs(p))).format(p));
  const rub = (v, sign) => (v == null ? '—' : (sign && v > 0 ? '+' : v < 0 ? '−' : '') + nf(0).format(Math.abs(v)) + ' ₽');
  const pct = (v) => (Math.abs(v) < 0.005 ? '' : v > 0 ? '+' : '−') + nf(2).format(Math.abs(v)) + '%';
  const qtyf = (q) => (q >= 1 && Number.isInteger(q) ? String(q) : nf(4).format(q));
  const cls = (v) => (Math.abs(v) < 0.005 ? 'zero' : v > 0 ? 'pos' : 'neg');
  const side = (d) => (d > 0 ? 'ЛОНГ' : 'ШОРТ');
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
  const compact = (v) => (v >= 1e6 ? nf(1).format(v / 1e6) + ' млн ₽' : v >= 1e4 ? nf(0).format(v / 1e3) + ' тыс ₽' : nf(0).format(v) + ' ₽');

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
    crosshair: { mode: 0 }, localization: { locale: 'ru-RU', priceFormatter: (p) => fp(p) }, autoSize: true,
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
      if (!d.long_only) pl(st.dn_level, 'rgba(246,70,93,.9)', 'шорт ниже');
    }
    if (fresh) {
      const n = d.candles.length;
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 140), to: n + 4 });
    }
    renderOhlc(d.candles.at(-1));
  }

  // ---------- лента и фильтры ----------
  const fits = (t) => t.min_capital != null && t.min_capital <= capital();
  function visibleItems() {
    return state.items.filter((t) => (state.group === 'all' || t.market === state.group) && (!state.fitOnly || fits(t)));
  }
  function renderTicker() {
    let lastGroup = '';
    const items = visibleItems();
    const html = items.map((t) => {
      const i = info(t.symbol);
      const head = t.group !== lastGroup ? `<span class="tk-group">${esc(t.group)}</span>` : '';
      lastGroup = t.group;
      const min = t.error ? '' : t.min_capital == null ? '' : `<span class="tk-min ${fits(t) ? 'ok' : 'no'}" title="Минимальный капитал по правилам риска">от ${compact(t.min_capital)}</span>`;
      return `${head}<button class="tk ${t.symbol === state.symbol ? 'active' : ''} ${t.error ? 'dim' : ''}" data-sym="${t.symbol}" title="${esc(t.error || i.desc)}">
        <span class="tk-ico" style="background:${i.color}">${esc(i.ico)}</span>
        <span><div class="tk-sym">${esc(t.contract || t.symbol)}</div><div class="tk-price">${t.error ? 'нет данных' : fp(t.price)}</div></span>
        ${t.error ? '' : `<span class="tk-chg ${cls(t.chg)}">${pct(t.chg)}</span>`}${min}
      </button>`;
    }).join('');
    $('ticker').innerHTML = html || `<span class="muted small" style="padding:10px 4px">${state.items.length ? 'Под этот капитал и риск ничего не подходит — увеличьте риск или капитал.' : 'Загружаю инструменты… первый раз до минуты.'}</span>`;
    const ok = state.items.filter(fits).length;
    $('fitInfo').textContent = state.items.length ? `по правилам риска на ${rub(capital())} доступно: ${ok} из ${state.items.length}` : '';
  }
  function pick(sym) {
    if (sym === state.symbol) return;
    state.symbol = sym; store.set('w_symbol', sym); renderTicker(); refresh(true);
  }
  $('ticker').addEventListener('click', (e) => { const b = e.target.closest('[data-sym]'); if (b) pick(b.dataset.sym); });
  document.addEventListener('click', (e) => { const b = e.target.closest('.chip[data-sym]'); if (b) pick(b.dataset.sym); });

  function segInit(id, attr, cur, onPick) {
    document.querySelectorAll(`#${id} button`).forEach((b) => {
      b.classList.toggle('active', b.dataset[attr] === String(cur));
      b.addEventListener('click', () => {
        document.querySelectorAll(`#${id} button`).forEach((x) => x.classList.toggle('active', x === b));
        onPick(b.dataset[attr]);
      });
    });
  }
  segInit('tf', 'tf', state.tf, (v) => { state.tf = +v; store.set('w_tf', v); refresh(true); refreshItems(); });
  segInit('groups', 'g', state.group, (v) => { state.group = v; store.set('w_group', v); renderTicker(); });
  $('fitOnly').addEventListener('change', () => { state.fitOnly = $('fitOnly').checked; store.set('w_fit', state.fitOnly ? '1' : '0'); renderTicker(); });
  let tmr;
  const onMoney = () => {
    store.set('w_capital', $('capital').value); store.set('w_risk', $('risk').value);
    renderTicker();
    clearTimeout(tmr); tmr = setTimeout(() => { refresh(false); refreshItems(); }, 500);
  };
  $('capital').addEventListener('input', onMoney);
  $('risk').addEventListener('input', onMoney);

  // ---------- панели ----------
  function renderHero(d) {
    const i = info(d.symbol), st = d.status, item = state.items.find((x) => x.symbol === d.symbol);
    $('heroIcon').textContent = i.ico; $('heroIcon').style.background = i.color;
    $('heroSym').textContent = d.contract || d.symbol;
    $('heroDesc').textContent = [i.desc, d.expiry ? `до ${d.expiry.split('-').reverse().join('.')}` : ''].filter(Boolean).join(' · ');
    const price = d.candles.at(-1)?.close;
    $('heroPrice').textContent = fp(price) + (d.market === 'crypto' ? ' $' : '');
    if (item && !item.error) { $('heroChg').textContent = pct(item.chg); $('heroChg').className = 'chg ' + cls(item.chg); }
    $('hAtr').textContent = st ? fp(st.atr) : '—';
    $('hPvLbl').textContent = d.market === 'stock' ? 'Лот' : d.market === 'crypto' ? 'Курс $' : '₽ за пункт';
    $('hPv').textContent = d.market === 'stock' ? `${d.point_value} шт` : d.market === 'crypto' ? `${nf(2).format(d.usd_rub)} ₽` : nf(d.point_value >= 100 ? 0 : 2).format(d.point_value) + ' ₽';
    $('hMin').textContent = st ? `от ${compact(st.min_capital)}` : '—';
    $('hMin').className = st ? (st.min_capital <= capital() ? 'pos' : 'neg') : '';
    $('hLast').textContent = st ? st.last_closed.slice(5).replace(' ', ', ') : '—';
    document.title = `${fp(price)} · ${d.contract || d.symbol} — Birzha`;
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
      $('verdictSub').innerHTML = `${qtyf(st.position.qty)} × ${esc(d.unit)} с ${st.position.t.slice(11)} по ${fp(st.position.entry)} · сейчас <b class="${cls(st.position.pnl)}">${rub(st.position.pnl, true)}</b>`;
    } else if (st.pending) {
      v.textContent = `Сигнал: ${side(st.pending.dir)}`;
      v.className = 'verdict ' + (st.pending.dir > 0 ? 'long' : 'short');
      $('verdictSub').textContent = `Свеча ${st.pending.t.slice(11)} закрылась пробоем — вход сразу после её закрытия.`;
    } else {
      v.textContent = 'Ждать';
      v.className = 'verdict wait';
      $('verdictSub').textContent = 'Условия входа сейчас не выполнены. Уровни пробоя — на графике.';
    }
    const lo = d.long_only;
    const trendTxt = st.trend > 0 ? 'Вверх: цена и EMA20 выше EMA50 — ищем лонги'
      : st.trend < 0 ? (lo ? 'Вниз — здесь только покупки, поэтому ждём' : 'Вниз: цена и EMA20 ниже EMA50 — ищем шорты') : 'Нет чёткого тренда — входов не будет';
    const toUp = (st.up_level - st.price) / st.atr, toDn = (st.price - st.dn_level) / st.atr;
    const brk = st.trend > 0 ? `Лонг, если свеча закроется выше ${fp(st.up_level)} (≈${nf(1).format(Math.max(toUp, 0))} ATR от цены)`
      : st.trend < 0 && !lo ? `Шорт, если свеча закроется ниже ${fp(st.dn_level)} (≈${nf(1).format(Math.max(toDn, 0))} ATR от цены)`
        : lo ? `Лонг выше ${fp(st.up_level)} после разворота тренда вверх` : `Лонг выше ${fp(st.up_level)}, шорт ниже ${fp(st.dn_level)}`;
    const near = Math.min(st.trend > 0 ? toUp : st.trend < 0 && !lo ? toDn : 9, 9);
    const trendOk = st.trend > 0 || (st.trend < 0 && !lo);
    const win = d.market === 'crypto' ? `Крипта торгуется круглосуточно; входы до ${p.last_entry}, закрытие в ${p.flat} МСК`
      : st.window ? `Окно открыто до ${p.last_entry} МСК` : `Новые входы ${p.start}–${p.last_entry} МСК по будням, закрытие всего в ${p.flat}`;
    $('checks').innerHTML = [
      check(trendOk ? 'ok' : 'bad', 'Тренд', trendTxt),
      check(trendOk ? (near < 0.5 ? 'ok' : 'mid') : 'mid', 'Пробой канала ' + p.channel + ' свечей', brk),
      check(st.window ? 'ok' : 'bad', 'Время входа', win),
      check(st.trades_today < st.max_trades ? 'ok' : 'bad', 'Сделок сегодня', `${st.trades_today} из ${st.max_trades} по этому инструменту`),
      lo ? check('mid', 'Только покупки', d.market === 'crypto' ? 'Спот: шорт без маржи невозможен' : 'Акции без маржи: шорт недоступен') : '',
    ].join('');
  }

  function suggestions() {
    const ok = state.items.filter((t) => fits(t) && t.symbol !== state.symbol).sort((a, b) => a.min_capital - b.min_capital).slice(0, 8);
    if (!ok.length) return '<p class="note">Под этот капитал по правилам риска сейчас ничего не подходит.</p>';
    return `<div class="chips">${ok.map((t) => `<button class="chip" data-sym="${t.symbol}">${esc(t.contract || t.symbol)} · от ${compact(t.min_capital)}</button>`).join('')}</div>`;
  }

  function renderPlan(d) {
    const st = d.status;
    if (!st) { $('plan').innerHTML = ''; return; }
    const pl = st.plan, unit = esc(d.unit);
    if (pl.qty <= 0) {
      $('plan').innerHTML = `<div class="hint"><b>Не хватает: нужно от ${rub(st.min_capital)}</b>
        При риске ${nf(1).format(riskPct())}% на сделку и стопе 2×ATR даже минимальная позиция (1 ${unit}) рискует больше,
        чем позволяют правила, или не хватает ГО/денег на покупку. Не повышайте риск ради входа — выберите то, что по карману:
        ${suggestions()}</div>`;
      return;
    }
    const usd = d.market === 'crypto' ? ` (≈${nf(2).format(pl.notional / d.usd_rub)} $)` : '';
    $('plan').innerHTML = `
      <div class="plan-grid">
        <div><span>Количество</span><b>${qtyf(pl.qty)}</b> <span>${unit}</span></div>
        <div><span>Риск при стопе</span><b class="neg">${rub(-pl.risk_rub)}</b></div>
        <div><span>${d.margin_rate < 1 ? 'ГО (примерно)' : 'Нужно денег'}</span><b>${rub(pl.margin_rub)}</b></div>
        <div><span>Комиссия туда-обратно</span><b>${rub(pl.fee_rub)}</b></div>
      </div>
      <div class="plan-sides">
        <div class="plan-side long"><b>Лонг: закрытие выше ${fp(st.up_level)}</b>стоп ≈ ${fp(pl.long_stop)} (2×ATR = ${fp(pl.stop_dist)}) · позиция ${rub(pl.notional)}${usd}</div>
        ${d.long_only ? '' : `<div class="plan-side short"><b>Шорт: закрытие ниже ${fp(st.dn_level)}</b>стоп ≈ ${fp(pl.short_stop)}</div>`}
      </div>
      <p class="note">Риск ${nf(1).format(riskPct())}% капитала на сделку, в позициях — не больше ${nf(0).format(d.risk.max_margin * 100)}% капитала.
      ${pl.fee_rub > pl.risk_rub * 0.2 ? '<b class="neg">Комиссия больше 20% риска — на таком объёме сделки невыгодны.</b>' : 'Стоп дальше подтягивается за ценой.'}</p>`;
  }

  function renderStats(d) {
    const st = d.status;
    if (!st) { $('kpis').innerHTML = ''; return; }
    const s = st.stats;
    $('statsFrom').textContent = `с ${s.from}, свечи ${d.tf} мин, капитал ${rub(capital())}, комиссии учтены`;
    $('kpis').innerHTML = `
      <div><span>Результат</span><b class="${cls(s.pnl)}">${rub(s.pnl, true)}</b></div>
      <div><span>К капиталу</span><b class="${cls(s.return)}">${pct(s.return * 100)}</b></div>
      <div><span>Сделок</span><b>${s.trades}</b></div>
      <div><span>Прибыльных</span><b>${nf(0).format(s.win_rate * 100)}%</b></div>
      <div><span>Profit factor</span><b class="${s.profit_factor == null ? '' : s.profit_factor >= 1.2 ? 'pos' : s.profit_factor < 1 ? 'neg' : ''}">${s.profit_factor == null ? '—' : nf(2).format(s.profit_factor)}</b></div>`;
    const rows = st.trades.map((t) => `<tr>
      <td>${esc(t.entry_t.slice(5))}</td>
      <td><span class="tag ${t.dir > 0 ? 'long' : 'short'}">${side(t.dir)}</span></td>
      <td class="r">${qtyf(t.qty)}</td>
      <td class="r">${fp(t.entry)} → ${fp(t.exit)}</td>
      <td>${esc(t.exit_t.slice(11))} · ${esc(t.reason)}</td>
      <td class="r ${cls(t.pnl)}"><b>${rub(t.pnl, true)}</b></td></tr>`).join('');
    $('trades').querySelector('tbody').innerHTML = rows ||
      `<tr><td colspan="6" class="empty">${s.trades === 0 && st.plan.qty <= 0 ? 'Сделок нет: под этот капитал позиция не проходит по правилам риска.' : 'Сделок на этой истории не было.'}</td></tr>`;
  }

  function renderVenues(d) {
    if (!state.venues) return;
    const cur = d?.market;
    $('venues').innerHTML = Object.entries(state.venues).map(([k, v]) => `
      <div class="venue ${k === cur ? 'active' : ''}">
        <h3>${esc(v.title)}</h3>
        <div class="names">${v.where.map((n) => `<span>${esc(n)}</span>`).join('')}</div>
        <p><b>Верификация:</b> ${esc(v.verify)}</p>
        <p><b>Порог входа:</b> ${esc(v.min)}</p>
      </div>`).join('');
    const c = capital();
    $('smallCap').innerHTML = `<h3>Если у вас ${rub(c)}</h3>
      <ol>
        ${c < 20000 ? `<li>Для фьючерсов этого мало: ГО одного контракта — от ~1–15 тыс. ₽, и при риске 1% стоп на 1 контракт почти всегда больше ${rub(c * 0.01)}. Начните с бумажной торговли на сайте.</li>` : ''}
        <li>Акции: 1 лот VTBR, AFLT, GAZP и др. стоит сотни рублей. Можно учиться на реальных, но маленьких сделках. Включите «Только по карману».</li>
        <li>Крипта на споте: ордер от ~5 USDT, но рубли заводятся только через P2P, а защиты ЦБ нет.</li>
        <li>Правило: на одну сделку рискуйте не больше 1–2% (${rub(c * 0.01)}–${rub(c * 0.02)}). Деньги на маленьком счёте теряются быстрее всего из-за повышенного риска и комиссий.</li>
      </ol>`;
  }

  // ---------- обновление ----------
  let busy = false;
  async function refresh(fresh) {
    if (busy && !fresh) return;
    busy = true;
    const key = `${state.symbol}:${state.tf}`;
    try {
      const d = await get(`/api/state?symbol=${encodeURIComponent(state.symbol)}&tf=${state.tf}&capital=${capital()}&risk=${riskPct()}`);
      if (`${state.symbol}:${state.tf}` !== key) return;   // пока грузили, пользователь переключился
      const isNew = fresh || state.key !== key;
      state.data = d; state.key = key;
      drawChart(d, isNew); renderHero(d); renderSignal(d); renderPlan(d); renderStats(d); renderVenues(d);
      const live = d.source.includes('реальное');
      setStatus(`${d.source} · обновлено ${d.now}`, live ? 'live' : 'delay');
    } catch (e) {
      setStatus(`${state.symbol}: ${e.message}`, 'err');
    } finally { busy = false; }
  }
  async function refreshItems() {
    try {
      const j = await get(`/api/instruments?tf=${state.tf}&risk=${riskPct()}`);
      state.items = j.items; state.venues = j.venues;
      renderTicker(); renderVenues(state.data);
      if (state.data) { renderHero(state.data); renderPlan(state.data); }
    } catch { /* не критично */ }
  }
  const tick = () => { $('clock').textContent = new Date().toLocaleTimeString('ru-RU', { timeZone: 'Europe/Moscow' }) + ' МСК'; };
  tick(); setInterval(tick, 1000);

  renderTicker();
  refreshItems();
  refresh(true);
  setInterval(() => refresh(false), 10000);
  setInterval(refreshItems, 60000);
})();
