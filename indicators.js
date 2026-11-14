(function () {
// Технические индикаторы и анализ свечей.
// Все функции принимают массивы чисел и возвращают массив той же длины
// (значения до "прогрева" индикатора = null).

function sma(values, period) {
  const out = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

function ema(values, period) {
  const out = new Array(values.length).fill(null);
  if (values.length < period) return out;
  const k = 2 / (period + 1);
  let prev = values.slice(0, period).reduce((a, b) => a + b, 0) / period;
  out[period - 1] = prev;
  for (let i = period; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

function rsi(values, period = 14) {
  const out = new Array(values.length).fill(null);
  if (values.length <= period) return out;
  let gain = 0, loss = 0;
  for (let i = 1; i <= period; i++) {
    const d = values[i] - values[i - 1];
    if (d >= 0) gain += d; else loss -= d;
  }
  gain /= period; loss /= period;
  out[period] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  for (let i = period + 1; i < values.length; i++) {
    const d = values[i] - values[i - 1];
    gain = (gain * (period - 1) + Math.max(d, 0)) / period;
    loss = (loss * (period - 1) + Math.max(-d, 0)) / period;
    out[i] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  }
  return out;
}

function macd(values, fast = 12, slow = 26, signal = 9) {
  const ef = ema(values, fast);
  const es = ema(values, slow);
  const line = values.map((_, i) => (ef[i] != null && es[i] != null ? ef[i] - es[i] : null));
  const start = line.findIndex((v) => v != null);
  const sig = new Array(values.length).fill(null);
  if (start >= 0) {
    const tail = ema(line.slice(start), signal);
    tail.forEach((v, j) => (sig[start + j] = v));
  }
  const hist = line.map((v, i) => (v != null && sig[i] != null ? v - sig[i] : null));
  return { line, signal: sig, hist };
}

function bollinger(values, period = 20, mult = 2) {
  const mid = sma(values, period);
  const upper = new Array(values.length).fill(null);
  const lower = new Array(values.length).fill(null);
  for (let i = period - 1; i < values.length; i++) {
    let s = 0;
    for (let j = i - period + 1; j <= i; j++) s += (values[j] - mid[i]) ** 2;
    const sd = Math.sqrt(s / period);
    upper[i] = mid[i] + mult * sd;
    lower[i] = mid[i] - mult * sd;
  }
  return { mid, upper, lower };
}

function atr(candles, period = 14) {
  const tr = candles.map((c, i) =>
    i === 0
      ? c.high - c.low
      : Math.max(c.high - c.low, Math.abs(c.high - candles[i - 1].close), Math.abs(c.low - candles[i - 1].close))
  );
  const out = new Array(candles.length).fill(null);
  if (candles.length < period) return out;
  let prev = tr.slice(0, period).reduce((a, b) => a + b, 0) / period;
  out[period - 1] = prev;
  for (let i = period; i < candles.length; i++) {
    prev = (prev * (period - 1) + tr[i]) / period;
    out[i] = prev;
  }
  return out;
}

// Свечные паттерны на свече i. Возвращает [{name, dir}] где dir = +1 бычий, -1 медвежий.
function candlePatterns(candles, i) {
  const res = [];
  if (i < 1) return res;
  const c = candles[i], p = candles[i - 1];
  const body = Math.abs(c.close - c.open);
  const range = c.high - c.low || 1e-12;
  const upper = c.high - Math.max(c.open, c.close);
  const lower = Math.min(c.open, c.close) - c.low;
  const bull = c.close > c.open, pBull = p.close > p.open;

  if (bull && !pBull && c.close >= p.open && c.open <= p.close && body > Math.abs(p.close - p.open))
    res.push({ name: 'Бычье поглощение', dir: 1 });
  if (!bull && pBull && c.open >= p.close && c.close <= p.open && body > Math.abs(p.close - p.open))
    res.push({ name: 'Медвежье поглощение', dir: -1 });
  if (lower >= 2 * body && upper <= body * 0.5 && body / range < 0.35 && i >= 3 && candles[i - 3].close > c.close)
    res.push({ name: 'Молот (после снижения)', dir: 1 });
  if (upper >= 2 * body && lower <= body * 0.5 && body / range < 0.35 && i >= 3 && candles[i - 3].close < c.close)
    res.push({ name: 'Падающая звезда (после роста)', dir: -1 });
  if (body / range < 0.08) res.push({ name: 'Доджи (неопределённость)', dir: 0 });
  return res;
}

// Считает все индикаторы для массива свечей.
function computeAll(candles) {
  const close = candles.map((c) => c.close);
  const vol = candles.map((c) => c.volume);
  return {
    ema20: ema(close, 20),
    ema50: ema(close, 50),
    ema200: ema(close, 200),
    rsi: rsi(close, 14),
    macd: macd(close),
    bb: bollinger(close, 20, 2),
    atr: atr(candles, 14),
    volSma: sma(vol, 20),
  };
}

// Оценка сигнала на свече i. Возвращает score (от -N до +N) и список причин.
function scoreAt(candles, ind, i) {
  const reasons = [];
  let score = 0;
  const add = (pts, text) => { score += pts; reasons.push({ pts, text }); };
  const c = candles[i];

  // 1. Тренд
  if (ind.ema50[i] != null && ind.ema200[i] != null) {
    if (ind.ema50[i] > ind.ema200[i]) add(1, 'Восходящий тренд: EMA50 выше EMA200');
    else add(-1, 'Нисходящий тренд: EMA50 ниже EMA200');
  }
  if (ind.ema20[i] != null) {
    if (c.close > ind.ema20[i]) add(0.5, 'Цена выше EMA20 (краткосрочно сильная)');
    else add(-0.5, 'Цена ниже EMA20 (краткосрочно слабая)');
  }

  // 2. RSI
  const r = ind.rsi[i];
  if (r != null) {
    if (r < 30) add(1.5, `RSI ${r.toFixed(0)} — перепроданность`);
    else if (r > 70) add(-1.5, `RSI ${r.toFixed(0)} — перекупленность`);
    else if (r > 50) add(0.5, `RSI ${r.toFixed(0)} — перевес покупателей`);
    else add(-0.5, `RSI ${r.toFixed(0)} — перевес продавцов`);
  }

  // 3. MACD
  const h = ind.macd.hist[i], hp = ind.macd.hist[i - 1];
  if (h != null && hp != null) {
    if (hp <= 0 && h > 0) add(1.5, 'MACD пересёк сигнальную линию вверх');
    else if (hp >= 0 && h < 0) add(-1.5, 'MACD пересёк сигнальную линию вниз');
    else if (h > 0) add(h > hp ? 0.5 : 0.25, 'MACD выше сигнальной');
    else add(h < hp ? -0.5 : -0.25, 'MACD ниже сигнальной');
  }

  // 4. Боллинджер
  if (ind.bb.lower[i] != null) {
    if (c.close < ind.bb.lower[i]) add(1, 'Цена под нижней полосой Боллинджера (возможен отскок)');
    else if (c.close > ind.bb.upper[i]) add(-1, 'Цена над верхней полосой Боллинджера (возможен откат)');
  }

  // 5. Свечные паттерны с подтверждением объёмом
  const highVol = ind.volSma[i] != null && c.volume > ind.volSma[i] * 1.3;
  for (const p of candlePatterns(candles, i)) {
    if (p.dir === 0) { reasons.push({ pts: 0, text: p.name }); continue; }
    add(p.dir * (highVol ? 1.5 : 1), p.name + (highVol ? ' на повышенном объёме' : ''));
  }

  return { score, reasons };
}

const MAX_SCORE = 7;

function verdict(score) {
  if (score >= 3) return { label: 'ПОКУПАТЬ', cls: 'buy-strong', dir: 1 };
  if (score >= 1.5) return { label: 'Скорее покупать', cls: 'buy', dir: 1 };
  if (score <= -3) return { label: 'ПРОДАВАТЬ / не входить', cls: 'sell-strong', dir: -1 };
  if (score <= -1.5) return { label: 'Скорее продавать', cls: 'sell', dir: -1 };
  return { label: 'Ждать', cls: 'neutral', dir: 0 };
}

// Размер позиции по риску: теряем не более risk% депозита, если сработает стоп.
function positionPlan({ deposit, riskPct, entry, atrValue, stopAtr = 1.5, rr = 2, strength = 1 }) {
  const stop = entry - stopAtr * atrValue;
  const take = entry + stopAtr * atrValue * rr;
  const riskMoney = deposit * (riskPct / 100) * strength;
  const perUnitRisk = entry - stop;
  let qty = perUnitRisk > 0 ? riskMoney / perUnitRisk : 0;
  let amount = qty * entry;
  let capped = false;
  if (amount > deposit) { amount = deposit; qty = amount / entry; capped = true; }
  return { stop, take, qty, amount, riskMoney: qty * perUnitRisk, capped, stopPct: ((entry - stop) / entry) * 100, takePct: ((take - entry) / entry) * 100 };
}

// Простой бэктест: вход в лонг при score >= threshold, выход по стопу/тейку.
function backtest(candles, ind, { threshold = 3, stopAtr = 1.5, rr = 2, feePct = 0.1 } = {}) {
  const trades = [];
  let i = 200;
  while (i < candles.length - 1) {
    const { score } = scoreAt(candles, ind, i);
    if (score >= threshold && ind.atr[i]) {
      const entry = candles[i + 1].open; // вход на открытии следующей свечи
      const stop = entry - stopAtr * ind.atr[i];
      const take = entry + stopAtr * ind.atr[i] * rr;
      let exit = null, j = i + 1;
      for (; j < candles.length; j++) {
        if (candles[j].low <= stop) { exit = stop; break; }       // консервативно: стоп проверяем первым
        if (candles[j].high >= take) { exit = take; break; }
      }
      if (exit == null) break; // сделка ещё открыта
      const ret = (exit / entry - 1) * 100 - feePct * 2;
      trades.push({ time: candles[i + 1].time, ret });
      i = j + 1;
    } else i++;
  }
  const wins = trades.filter((t) => t.ret > 0).length;
  const total = trades.reduce((acc, t) => acc * (1 + t.ret / 100), 1);
  return { trades, wins, winRate: trades.length ? (wins / trades.length) * 100 : 0, totalPct: (total - 1) * 100 };
}

window.TA = { sma, ema, rsi, macd, bollinger, atr, candlePatterns, computeAll, scoreAt, verdict, positionPlan, backtest, MAX_SCORE };
})();
