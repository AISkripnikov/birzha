"""Стратегия «Тренд + пробой + фильтр рынка» для акций Мосбиржи (только покупки).

Идея простая и проверенная десятилетиями (семейство «черепашьих» трендовых систем):
  1. Покупаем только бумаги в долгосрочном аптренде: close > EMA200 и EMA50 > EMA200.
  2. Вход — пробой: закрытие выше максимума за 40 прошлых дней.
  3. Не открываем новые позиции, когда рынок в целом падает
     (меньше половины бумаг выше своей EMA200).
  4. Выход — трейлинг-стоп: максимум с момента входа − 3×ATR. Прибыль «бежит», убыток режется.
  5. Размер позиции — по риску: при срабатывании стопа теряется ~1 % капитала.

Свеча (bar) — dict с ключами date, open, high, low, close, volume.
"""


def ema(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def atr(bars, period):
    out = [None] * len(bars)
    if len(bars) <= period:
        return out
    tr = [bars[0]["high"] - bars[0]["low"]]
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    prev = sum(tr[1:period + 1]) / period
    out[period] = prev
    for i in range(period + 1, len(bars)):
        prev = (prev * (period - 1) + tr[i]) / period  # сглаживание Уайлдера
        out[i] = prev
    return out


def indicators(bars, p):
    """Считает все индикаторы для одной бумаги. Возвращает dict списков той же длины."""
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    n = len(bars)
    prior_high = [None] * n
    for i in range(p["breakout"], n):
        prior_high[i] = max(highs[i - p["breakout"]:i])
    mom = [None] * n
    for i in range(p["momentum"], n):
        mom[i] = closes[i] / closes[i - p["momentum"]] - 1
    return {
        "ema_fast": ema(closes, p["ema_fast"]),
        "ema_slow": ema(closes, p["ema_slow"]),
        "atr": atr(bars, p["atr_period"]),
        "prior_high": prior_high,
        "momentum": mom,
    }


def above_slow(bars, ind, i):
    s = ind["ema_slow"][i]
    return s is not None and bars[i]["close"] > s


def entry_signal(bars, ind, i):
    """True, если на закрытии свечи i есть сигнал на покупку."""
    f, s, ph, a = ind["ema_fast"][i], ind["ema_slow"][i], ind["prior_high"][i], ind["atr"][i]
    if None in (f, s, ph, a) or ind["momentum"][i] is None:
        return False
    c = bars[i]["close"]
    return c > s and f > s and c > ph


def trail_stop(prev_stop, highest, atr_value, k):
    """Стоп только поднимается, никогда не опускается."""
    new = highest - k * atr_value
    return new if prev_stop is None else max(prev_stop, new)


def rank_score(ind, i):
    """Чем выше — тем приоритетнее вход: сила тренда, нормированная на волатильность."""
    return ind["momentum"][i] or 0.0


def position_size(equity, cash, price, atr_value, risk, stop_atr, lot=1):
    """Количество штук (кратно лоту) так, чтобы стоп стоил ~risk_per_trade капитала."""
    if price <= 0 or atr_value <= 0:
        return 0
    by_risk = equity * risk["risk_per_trade"] / (stop_atr * atr_value)
    by_cap = equity * risk["max_position"] / price
    by_cash = cash / price
    qty = min(by_risk, by_cap, by_cash)
    return int(qty // lot) * lot
