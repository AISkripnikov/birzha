"""Сайт с живыми свечами и сигналами внутридневной стратегии: фьючерсы, акции Мосбиржи и криптовалюта.

    python fut_web.py        → откроется http://localhost:8010

Данные:
  * Мосбиржа (фьючерсы, акции): с FINAM_TOKEN — свечи Финама в реальном времени,
    без токена — iss.moex.com с задержкой ~15 минут;
  * криптовалюта: публичные свечи Bybit (спот), в реальном времени.
Сайт только показывает данные и сигналы, заявок не отправляет.
"""
import http.server
import json
import os
import sys
import threading
import time
import urllib.parse
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import fut_config as cfg
import markets
from data import aggregate
from fut_strategy import Book, hm, indicators, round_qty, signal
from markets import MARKETS, VENUES

PORT = 8010
HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
MSK = timezone(timedelta(hours=3))
HISTORY_DAYS = 30          # столько дней грузим для графика и статистики
REFRESH_SEC = 10           # не чаще, чем раз в 10 секунд на инструмент
USD_RUB_FALLBACK = 80.0


class Source:
    """Свечи с кешем: полная загрузка один раз, дальше — докачка последних дней."""

    def __init__(self):
        self.api = None
        if os.getenv("FINAM_TOKEN"):
            from finam_api import Finam
            self.api = Finam(os.getenv("FINAM_TOKEN"), os.getenv("FINAM_ACCOUNT_ID"))
        self.moex_name = "Финам · реальное время" if self.api else "Мосбиржа · задержка ~15 мин"
        self.cache, self.stamp, self.locks = {}, {}, {}

    def source_name(self, s):
        return "Bybit · реальное время" if MARKETS[s]["market"] == "crypto" else self.moex_name

    def _load(self, s, days):
        m = MARKETS[s]
        if m["market"] == "crypto":
            return aggregate(markets.bybit_candles(m["secid"], days), 10)
        secid = markets.front_contract(m["asset"])[0] if m.get("asset") else m["secid"]
        if self.api:   # 5-минутки Финама склеиваем в 10-минутки — так же, как история Мосбиржи
            mic = "RTSX" if m["market"] == "futures" else "MISX"
            return aggregate(self.api.candles(f"{secid}@{mic}", "TIME_FRAME_M5", days=days), 10)
        return markets.iss_candles(m["market"], secid, days)

    def bars10(self, s):
        lock = self.locks.setdefault(s, threading.Lock())
        with lock:
            if time.time() - self.stamp.get(s, 0) < REFRESH_SEC and s in self.cache:
                return self.cache[s]
            if s not in self.cache:
                bars = self._load(s, HISTORY_DAYS)
            else:
                merged = {b["t"]: b for b in self.cache[s]}
                merged.update({b["t"]: b for b in self._load(s, 2)})
                bars = [merged[t] for t in sorted(merged)]
            self.cache[s], self.stamp[s] = bars, time.time()
            return bars


SRC = None
POOL = ThreadPoolExecutor(max_workers=8)


def now_msk():
    return datetime.now(MSK)


def epoch(t):
    """'YYYY-MM-DD HH:MM' (МСК) → секунды. Графику отдаём «московское» время как UTC, чтобы ось показывала МСК."""
    return int(datetime.strptime(t, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())


def usd_rub():
    try:
        return SRC.bars10("USDRUBF")[-1]["close"]
    except Exception:
        return USD_RUB_FALLBACK


def runtime(s):
    """Инструмент с посчитанными «₽ за пункт» (лот акции, курс доллара) и кодом контракта."""
    m = dict(MARKETS[s])
    if m["market"] == "stock":
        m["point_value"] = markets.lot_size(m["secid"])
        m["unit"] = f"лот {m['point_value']} шт"
    elif m.get("pv_usd"):
        m["point_value"] = m["pv_usd"] * usd_rub()
    if m["market"] == "crypto":
        m["min_notional_rub"] = 5 * usd_rub()   # минимальный ордер на бирже ~5 USDT
    if m.get("asset"):
        m["contract"], m["expiry"] = markets.front_contract(m["asset"])
    m.setdefault("unit", "монета" if m["market"] == "crypto" else "контракт")
    return m


def params(m, tf):
    return dict(cfg.STRATEGY, timeframe=tf, **{k: v for k, v in m.get("session", {}).items() if k != "weekends"})


def min_capital(m, price, atr_value, p, risk):
    """Сколько нужно капитала, чтобы по правилам риска взять минимальное количество."""
    q = m.get("qty_step", 1)
    if m["market"] == "crypto":
        q = max(q, 5 / max(price, 1e-9))          # минимальный ордер на бирже ~5 USDT
    by_margin = price * m["point_value"] * m["margin_rate"] * q / risk["max_margin"]
    by_risk = p["stop_atr"] * atr_value * m["point_value"] * q / risk["risk_per_trade"]
    return max(by_margin, by_risk)


def closed_bars(s, tf):
    raw = SRC.bars10(s)
    bars = aggregate(raw, tf) if tf != 10 else list(raw)
    limit = (now_msk() - timedelta(minutes=tf)).strftime("%Y-%m-%d %H:%M")
    forming = bars[-1] if bars and bars[-1]["t"] > limit else None
    return bars, (bars[:-1] if forming else bars), forming


def item(s, tf, risk):
    m0 = MARKETS[s]
    base = {"symbol": s, "group": m0["group"], "market": m0["market"], "title": m0.get("title", "")}
    try:
        m = runtime(s)
        bars, closed, _ = closed_bars(s, tf)
        if not bars:
            return dict(base, error="нет данных")
        last = bars[-1]
        prev_day = [b for b in bars if b["date"] < last["date"]]
        ref = prev_day[-1]["close"] if prev_day else bars[0]["open"]
        p = params(m, tf)
        ind = indicators(closed, p) if closed else {"atr": [None]}
        a = ind["atr"][-1] if ind["atr"] else None
        return dict(base, price=last["close"], chg=(last["close"] / ref - 1) * 100, t=last["t"],
                    contract=m.get("contract"), min_capital=min_capital(m, last["close"], a, p, risk) if a else None)
    except Exception as e:
        return dict(base, error=f"{type(e).__name__}: {e}"[:160])


def instruments(tf, risk):
    items = list(POOL.map(lambda s: item(s, tf, risk), MARKETS))
    return {"moex_source": SRC.moex_name, "usd_rub": usd_rub(), "items": items, "venues": VENUES}


def state(s, tf, capital, risk):
    m = runtime(s)
    p = params(m, tf)
    bars, closed, forming = closed_bars(s, tf)
    ind = indicators(closed, p)
    now = now_msk()

    book = Book({s: m}, p, risk, cfg.COSTS, capital)
    markers = []
    for i in range(len(closed)):
        for kind, _, x in book.on_bar(s, closed, ind, i):
            if kind == "ENTER":
                markers.append({"time": epoch(x["t"]), "kind": "enter", "dir": x["dir"], "price": x["entry"],
                                "text": f"{'ЛОНГ' if x['dir'] > 0 else 'ШОРТ'} {x['qty']:g}"})
            elif kind == "EXIT":
                markers.append({"time": epoch(x["exit_t"]), "kind": "exit", "dir": x["dir"], "price": x["exit"],
                                "text": f"{x['pnl']:+,.0f} ₽".replace(",", " ")})

    out = {"symbol": s, "tf": tf, "source": SRC.source_name(s), "now": now.strftime("%H:%M:%S"),
           "market": m["market"], "group": m["group"], "title": m.get("title", ""), "unit": m["unit"],
           "contract": m.get("contract"), "expiry": m.get("expiry"), "long_only": bool(m.get("long_only")),
           "point_value": m["point_value"], "margin_rate": m["margin_rate"], "params": p, "risk": risk,
           "venue": VENUES[m["market"]], "usd_rub": usd_rub(),
           "commission": m.get("commission", cfg.COSTS["commission"]),
           "candles": [{"time": epoch(b["t"]), "open": b["open"], "high": b["high"], "low": b["low"],
                        "close": b["close"], "volume": b["volume"]} for b in bars],
           "forming": bool(forming), "markers": markers}
    line = lambda arr: [{"time": epoch(closed[i]["t"]), "value": v} for i, v in enumerate(arr) if v is not None]
    out["ema_fast"], out["ema_slow"] = line(ind["ema_fast"]), line(ind["ema_slow"])
    out["hh"], out["ll"] = line(ind["hh"]), line(ind["ll"])

    if len(closed) <= max(p["ema_slow"], p["channel"], p["atr_period"]) + 1:
        out["status"] = None
        return out

    i = len(closed) - 1
    c, f, sl, a = closed[i]["close"], ind["ema_fast"][i], ind["ema_slow"][i], ind["atr"][i]
    ch = p["channel"]
    up_level = max(b["high"] for b in closed[i - ch + 1:i + 1])     # уровни для следующей свечи
    dn_level = min(b["low"] for b in closed[i - ch + 1:i + 1])
    trend = 1 if c > sl and f > sl else -1 if c < sl and f < sl else 0
    mins = hm(now.strftime("%H:%M"))
    weekends = m.get("session", {}).get("weekends")
    window = hm(p["start"]) <= mins < hm(p["last_entry"]) and (weekends or now.weekday() < 5)
    price = forming["close"] if forming else c

    pv, mr = m["point_value"], m["margin_rate"]
    stop_dist = p["stop_atr"] * a
    by_risk = capital * risk["risk_per_trade"] / (stop_dist * pv)
    by_margin = capital * risk["max_margin"] / (price * pv * mr)
    qty = round_qty(min(by_risk, by_margin), m.get("qty_step", 1))
    if qty * price * pv < m.get("min_notional_rub", 0):
        qty = 0   # меньше минимального ордера биржи

    pos, pend = book.pos.get(s), book.pending.get(s)
    stats = [t["pnl"] for t in book.trades]
    wins, loss = [x for x in stats if x > 0], [x for x in stats if x <= 0]
    out["status"] = {
        "last_closed": closed[i]["t"], "price": price, "close": c, "ema_fast": f, "ema_slow": sl, "atr": a,
        "trend": trend, "up_level": up_level, "dn_level": dn_level, "window": window,
        "signal_now": signal(closed, ind, i, p),
        "pending": pend and {"dir": pend["dir"], "t": pend["t"]},
        "position": pos and {"dir": pos["dir"], "qty": pos["qty"], "entry": pos["entry"], "stop": pos["stop"],
                             "t": pos["t"], "pnl": pos["dir"] * (price - pos["entry"]) * pos["qty"] * pv},
        "trades_today": book.day_trades.get(s, 0) if book.day == now.date().isoformat() else 0,
        "max_trades": p["max_trades_per_day"],
        "min_capital": min_capital(m, price, a, p, risk),
        "plan": {"qty": qty, "stop_dist": stop_dist, "risk_rub": qty * stop_dist * pv,
                 "margin_rub": qty * price * pv * mr, "notional": qty * price * pv,
                 "fee_rub": qty * price * pv * out["commission"] * 2,
                 "long_stop": up_level - stop_dist, "short_stop": dn_level + stop_dist},
        "stats": {"trades": len(stats), "pnl": sum(stats), "win_rate": len(wins) / len(stats) if stats else 0,
                  "profit_factor": (sum(wins) / -sum(loss)) if loss and sum(loss) else None,
                  "from": closed[0]["date"], "return": book.capital / capital - 1},
        "trades": [dict(t, pnl=round(t["pnl"])) for t in book.trades[-30:]][::-1],
    }
    return out


def risk_from(q):
    r = dict(cfg.RISK)
    try:
        r["risk_per_trade"] = min(max(float(q.get("risk", 1)) / 100, 0.001), 0.05)
    except ValueError:
        r["risk_per_trade"] = 0.01
    return r


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        tf = int(q.get("tf", cfg.STRATEGY["timeframe"])) if q.get("tf", "").isdigit() else cfg.STRATEGY["timeframe"]
        tf = tf if tf in (10, 30, 60) else 30
        try:
            if url.path == "/api/instruments":
                return self._json(instruments(tf, risk_from(q)))
            if url.path == "/api/state":
                s = q.get("symbol", "USDRUBF")
                if s not in MARKETS:
                    return self._json({"error": "неизвестный инструмент"}, 404)
                capital = float(q.get("capital", 2000) or 2000)
                return self._json(state(s, tf, max(capital, 1), risk_from(q)))
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}"}, 502)
        return super().do_GET()

    def log_message(self, *args):
        pass


def main():
    global SRC
    SRC = Source()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Сайт: http://localhost:{PORT}  (Мосбиржа: {SRC.moex_name}; крипта: Bybit; Ctrl+C — остановить)")
    print("Первая загрузка всех инструментов занимает до минуты.")
    if "--no-browser" not in sys.argv:
        webbrowser.open(f"http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
