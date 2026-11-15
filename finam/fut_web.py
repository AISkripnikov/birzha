"""Сайт с живыми свечами и сигналами внутридневной стратегии по фьючерсам.

    python fut_web.py        → откроется http://localhost:8010

Данные:
  * есть FINAM_TOKEN — свечи Финама в реальном времени;
  * нет токена — свечи Мосбиржи (iss.moex.com) с задержкой ~15 минут.
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
from datetime import date, datetime, timedelta, timezone

import fut_config as cfg
from data import aggregate, moex_futures_candles
from fut_strategy import Book, hm, indicators, signal

PORT = 8010
HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
MSK = timezone(timedelta(hours=3))
HISTORY_DAYS = 30          # столько дней грузим для графика и статистики
REFRESH_SEC = 10           # не чаще, чем раз в 10 секунд на инструмент


class Source:
    """Свечи по инструментам с кешем: полная загрузка один раз, дальше — докачка последних дней."""

    def __init__(self):
        self.api = None
        if os.getenv("FINAM_TOKEN"):
            from finam_api import Finam
            self.api = Finam(os.getenv("FINAM_TOKEN"), os.getenv("FINAM_ACCOUNT_ID"))
        self.name = "Финам · реальное время" if self.api else "Мосбиржа · задержка ~15 мин"
        self.cache, self.stamp, self.locks = {}, {}, {}

    def _load(self, s, days):
        if self.api:   # 5-минутки Финама склеиваем в 10-минутки — так же, как история Мосбиржи
            return aggregate(self.api.candles(cfg.INSTRUMENTS[s]["symbol"], "TIME_FRAME_M5", days=days), 10)
        return moex_futures_candles(s, (date.today() - timedelta(days=days)).isoformat())

    def bars10(self, s):
        lock = self.locks.setdefault(s, threading.Lock())
        with lock:
            if time.time() - self.stamp.get(s, 0) < REFRESH_SEC and s in self.cache:
                return self.cache[s]
            if s not in self.cache:
                bars = self._load(s, HISTORY_DAYS)
            else:
                fresh = self._load(s, 2)
                merged = {b["t"]: b for b in self.cache[s]}
                merged.update({b["t"]: b for b in fresh})
                bars = [merged[t] for t in sorted(merged)]
            self.cache[s], self.stamp[s] = bars, time.time()
            return bars


SRC = None


def now_msk():
    return datetime.now(MSK)


def epoch(t):
    """'YYYY-MM-DD HH:MM' (МСК) → секунды. Графику отдаём «московское» время как UTC, чтобы ось показывала МСК."""
    return int(datetime.strptime(t, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())


def instruments():
    out = []
    for s, v in cfg.INSTRUMENTS.items():
        try:
            bars = SRC.bars10(s)
        except Exception as e:
            out.append({"symbol": s, "error": str(e)})
            continue
        if not bars:
            out.append({"symbol": s, "error": "нет данных"})
            continue
        last = bars[-1]
        prev_day = [b for b in bars if b["date"] < last["date"]]
        ref = prev_day[-1]["close"] if prev_day else bars[0]["open"]
        out.append({"symbol": s, "price": last["close"], "chg": (last["close"] / ref - 1) * 100, "t": last["t"]})
    return out


def state(s, tf, capital):
    p = dict(cfg.STRATEGY, timeframe=tf)
    inst = cfg.INSTRUMENTS[s]
    raw = SRC.bars10(s)
    bars = aggregate(raw, tf) if tf != 10 else list(raw)
    now = now_msk()
    # последняя свеча может быть ещё не закрыта — стратегия смотрит только на закрытые
    limit = (now - timedelta(minutes=tf)).strftime("%Y-%m-%d %H:%M")
    forming = bars[-1] if bars and bars[-1]["t"] > limit else None
    closed = bars[:-1] if forming else bars
    ind = indicators(closed, p)

    book = Book({s: inst}, p, cfg.RISK, cfg.COSTS, capital)
    markers = []
    for i in range(len(closed)):
        for kind, _, x in book.on_bar(s, closed, ind, i):
            if kind == "ENTER":
                markers.append({"time": epoch(x["t"]), "kind": "enter", "dir": x["dir"], "price": x["entry"],
                                "text": f"{'ЛОНГ' if x['dir'] > 0 else 'ШОРТ'} {x['qty']}"})
            elif kind == "EXIT":
                markers.append({"time": epoch(x["exit_t"]), "kind": "exit", "dir": x["dir"], "price": x["exit"],
                                "text": f"{x['pnl']:+,.0f} ₽".replace(",", " ")})

    out = {"symbol": s, "tf": tf, "source": SRC.name, "now": now.strftime("%H:%M:%S"),
           "point_value": inst["point_value"], "params": p, "risk": cfg.RISK,
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
    window = hm(p["start"]) <= mins < hm(p["last_entry"]) and now.weekday() < 5
    price = forming["close"] if forming else c

    pv, mr = inst["point_value"], inst["margin_rate"]
    stop_dist = p["stop_atr"] * a
    by_risk = capital * cfg.RISK["risk_per_trade"] / (stop_dist * pv)
    by_margin = capital * cfg.RISK["max_margin"] / (price * pv * mr)
    qty = max(int(min(by_risk, by_margin)), 0)

    pos = book.pos.get(s)
    pend = book.pending.get(s)
    stats = [t["pnl"] for t in book.trades]
    wins = [x for x in stats if x > 0]
    loss = [x for x in stats if x <= 0]
    out["status"] = {
        "last_closed": closed[i]["t"], "price": price, "close": c, "ema_fast": f, "ema_slow": sl, "atr": a,
        "trend": trend, "up_level": up_level, "dn_level": dn_level, "window": window,
        "signal_now": signal(closed, ind, i, p),
        "pending": pend and {"dir": pend["dir"], "t": pend["t"]},
        "position": pos and {"dir": pos["dir"], "qty": pos["qty"], "entry": pos["entry"], "stop": pos["stop"],
                             "t": pos["t"], "pnl": pos["dir"] * (price - pos["entry"]) * pos["qty"] * pv},
        "trades_today": book.day_trades.get(s, 0) if book.day == now.date().isoformat() else 0, "max_trades": p["max_trades_per_day"],
        "plan": {"qty": qty, "stop_dist": stop_dist, "risk_rub": qty * stop_dist * pv,
                 "margin_rub": qty * price * pv * mr, "notional": qty * price * pv,
                 "long_stop": up_level - stop_dist, "short_stop": dn_level + stop_dist},
        "stats": {"trades": len(stats), "pnl": sum(stats), "win_rate": len(wins) / len(stats) if stats else 0,
                  "profit_factor": (sum(wins) / -sum(loss)) if loss and sum(loss) else None,
                  "from": closed[0]["date"], "return": book.capital / capital - 1},
        "trades": [dict(t, pnl=round(t["pnl"])) for t in book.trades[-30:]][::-1],
    }
    return out


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
        try:
            if url.path == "/api/instruments":
                return self._json({"source": SRC.name, "items": instruments()})
            if url.path == "/api/state":
                s = q.get("symbol", next(iter(cfg.INSTRUMENTS)))
                if s not in cfg.INSTRUMENTS:
                    return self._json({"error": "неизвестный инструмент"}, 404)
                tf = int(q.get("tf", cfg.STRATEGY["timeframe"]))
                if tf not in (10, 30, 60):
                    tf = 30
                return self._json(state(s, tf, float(q.get("capital", 300000)) or 300000))
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}"}, 502)
        return super().do_GET()

    def log_message(self, *args):
        pass


def main():
    global SRC
    SRC = Source()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Сайт фьючерсов: http://localhost:{PORT}  (данные: {SRC.name}; Ctrl+C — остановить)")
    if "--no-browser" not in sys.argv:
        webbrowser.open(f"http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
