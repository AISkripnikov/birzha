"""Внутридневная стратегия «Пробой канала по тренду» для фьючерсов (лонг и шорт).

Правила (свечи 30 минут по умолчанию, только основная сессия 10:00–18:50 МСК):
  * Направление: лонг — только если close > EMA50 и EMA20 > EMA50; шорт — зеркально.
  * Вход: закрытие свечи выше максимума (ниже минимума) 12 предыдущих свечей → вход на открытии следующей.
  * Стоп: 2×ATR от цены входа, дальше тянется за лучшей ценой (трейлинг), никогда не отодвигается назад.
  * Не больше 2 сделок в день на инструмент, новых входов после 17:30, все позиции закрываются до 18:40.
  * Дневной лимит убытка: −2 % капитала — до конца дня не торгуем.
  * Размер: при срабатывании стопа теряем ~0,5 % капитала, суммарное ГО — не больше 50 % капитала.

Book — «торговая книга»: одна и та же логика используется в бэктесте и в боте,
поэтому бумажная торговля ведёт себя так же, как проверка на истории.
"""
from strategy import atr, ema


def hm(s):
    return int(s[:2]) * 60 + int(s[3:5])


def bar_minutes(bar):
    return hm(bar["t"][11:16])


def indicators(bars, p):
    closes = [b["close"] for b in bars]
    n, ch = len(bars), p["channel"]
    hh, ll = [None] * n, [None] * n
    for i in range(ch, n):
        hh[i] = max(b["high"] for b in bars[i - ch:i])
        ll[i] = min(b["low"] for b in bars[i - ch:i])
    return {"ema_fast": ema(closes, p["ema_fast"]), "ema_slow": ema(closes, p["ema_slow"]),
            "atr": atr(bars, p["atr_period"]), "hh": hh, "ll": ll}


def signal(bars, ind, i, p):
    """+1 — лонг, −1 — шорт, 0 — ничего. Считается по ЗАКРЫТОЙ свече i."""
    f, s, h, l, a = (ind[k][i] for k in ("ema_fast", "ema_slow", "hh", "ll", "atr"))
    if None in (f, s, h, l, a):
        return 0
    end = bar_minutes(bars[i]) + p["timeframe"]
    if bar_minutes(bars[i]) < hm(p["start"]) or end > hm(p["last_entry"]):
        return 0
    c = bars[i]["close"]
    if c > s and f > s and c > h:
        return 1
    if c < s and f < s and c < l:
        return -1
    return 0


class Book:
    """Позиции, сделки и капитал. Свечи подаются по одной: on_bar(тикер, bars, ind, i)."""

    def __init__(self, instruments, p, risk, costs, capital):
        self.inst, self.p, self.risk, self.costs = instruments, p, risk, costs
        self.capital = capital          # реализованный капитал (фьючерсы: деньги не тратятся на покупку)
        self.pos, self.pending, self.trades = {}, {}, []
        self.day, self.day_start, self.day_trades = None, capital, {}
        self.last_close = {}

    # --- служебное ----------------------------------------------------------
    def equity(self):
        return self.capital + sum(self._upnl(s, self.last_close.get(s, p["entry"])) for s, p in self.pos.items())

    def _upnl(self, s, price):
        p = self.pos[s]
        return p["dir"] * (price - p["entry"]) * p["qty"] * self.inst[s]["point_value"]

    def _cost(self, s, price, qty):
        return price * self.inst[s]["point_value"] * qty * self.costs["commission"]

    def _margin(self, s, price, qty):
        return price * self.inst[s]["point_value"] * self.inst[s]["margin_rate"] * qty

    def contracts(self, s, price, atr_value):
        pv = self.inst[s]["point_value"]
        eq = self.equity()
        by_risk = eq * self.risk["risk_per_trade"] / (self.p["stop_atr"] * atr_value * pv)
        used = sum(self._margin(x, q["entry"], q["qty"]) for x, q in self.pos.items())
        by_margin = (eq * self.risk["max_margin"] - used) / max(self._margin(s, price, 1), 1e-9)
        return max(int(min(by_risk, by_margin)), 0)

    def _close(self, s, price, t, reason):
        p = self.pos.pop(s)
        slip = price * self.costs["slippage"] * p["dir"]
        price -= slip
        pnl = p["dir"] * (price - p["entry"]) * p["qty"] * self.inst[s]["point_value"] - self._cost(s, price, p["qty"])
        self.capital += pnl
        tr = {"symbol": s, "dir": p["dir"], "qty": p["qty"], "entry_t": p["t"], "exit_t": t,
              "entry": p["entry"], "exit": price, "pnl": pnl, "reason": reason}
        self.trades.append(tr)
        return tr

    # --- главный шаг ---------------------------------------------------------
    def on_bar(self, s, bars, ind, i):
        """Обрабатывает свечу i. Возвращает список событий для отчёта/бота."""
        b, p, ev = bars[i], self.p, []
        if b["date"] != self.day:
            self.day, self.day_start, self.day_trades = b["date"], self.equity(), {}
        self.last_close[s] = b["close"]

        # 1) вход по открытию (сигнал был на прошлой свече того же дня)
        sig = self.pending.pop(s, None)
        if sig and sig["date"] == b["date"] and s not in self.pos and bar_minutes(b) + p["timeframe"] <= hm(p["flat"]):
            price = b["open"] * (1 + self.costs["slippage"] * sig["dir"])
            qty = sig.get("qty") or self.contracts(s, price, sig["atr"])
            if qty > 0:
                stop = sig.get("stop") or price - sig["dir"] * p["stop_atr"] * sig["atr"]
                self.capital -= self._cost(s, price, qty)
                self.pos[s] = {"dir": sig["dir"], "qty": qty, "entry": price, "t": b["t"], "stop": stop,
                               "best": price, "risk": abs(price - stop)}
                self.day_trades[s] = self.day_trades.get(s, 0) + 1
                ev.append(("ENTER", s, dict(self.pos[s])))

        # 2) сопровождение позиции
        if s in self.pos:
            q = self.pos[s]
            d = q["dir"]
            end_of_day = bar_minutes(b) + p["timeframe"] > hm(p["flat"]) or b["date"] != q["t"][:10]
            tp = q["entry"] + d * p["take_r"] * q["risk"] if p["take_r"] else None
            if end_of_day:
                ev.append(("EXIT", s, self._close(s, b["open"], b["t"], "конец дня")))
            elif (d > 0 and b["low"] <= q["stop"]) or (d < 0 and b["high"] >= q["stop"]):
                px = min(b["open"], q["stop"]) if d > 0 else max(b["open"], q["stop"])
                ev.append(("EXIT", s, self._close(s, px, b["t"], "стоп")))
            elif tp and ((d > 0 and b["high"] >= tp) or (d < 0 and b["low"] <= tp)):
                px = max(b["open"], tp) if d > 0 else min(b["open"], tp)
                ev.append(("EXIT", s, self._close(s, px, b["t"], "тейк")))
            elif ind["atr"][i]:
                q["best"] = max(q["best"], b["high"]) if d > 0 else min(q["best"], b["low"])
                new = q["best"] - d * p["stop_atr"] * ind["atr"][i]
                if (d > 0 and new > q["stop"]) or (d < 0 and new < q["stop"]):
                    q["stop"] = new
                    ev.append(("TRAIL", s, dict(q)))

        # 3) новый сигнал по закрытию свечи
        if s not in self.pos and self.day_trades.get(s, 0) < p["max_trades_per_day"] \
                and self.equity() > self.day_start * (1 - self.risk["daily_loss_limit"]):
            d = signal(bars, ind, i, p)
            if d:
                self.pending[s] = {"dir": d, "atr": ind["atr"][i], "date": b["date"], "t": b["t"],
                                   "close": b["close"]}
                ev.append(("SIGNAL", s, self.pending[s]))
        return ev
