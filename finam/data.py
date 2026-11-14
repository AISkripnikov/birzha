"""Загрузка дневных свечей с кешем в CSV.

Для бэктеста нужна длинная история (лет 8–10), а Финам отдаёт дневки на ~5 лет назад
неудобными кусками и только с токеном. Поэтому историю берём из бесплатного публичного
API Мосбиржи (ISS) — токен не нужен. Для бота подходят и данные Финама.
"""
import csv
import json
import os
import urllib.request
from datetime import date

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
ISS = ("https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/"
       "{sec}/candles.json?interval=24&from={frm}&till={till}&start={start}&iss.meta=off")


def moex_bars(ticker, frm="2014-01-01", till=None):
    till = till or date.today().isoformat()
    out, start = [], 0
    while True:
        url = ISS.format(sec=ticker, frm=frm, till=till, start=start)
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "birzha"}),
                                    timeout=30) as r:
            js = json.loads(r.read())["candles"]
        cols, rows = js["columns"], js["data"]
        if not rows:
            break
        for row in rows:
            x = dict(zip(cols, row))
            out.append({"date": x["begin"][:10], "open": x["open"], "high": x["high"],
                        "low": x["low"], "close": x["close"], "volume": x["volume"]})
        start += len(rows)
    return adjust_splits(out)


def adjust_splits(bars, threshold=0.45):
    """Сплиты (например, GMKN 1:100 в 2024) ломают индикаторы: правим историю назад.

    Считаем сплитом ночной разрыв, когда цена изменилась больше чем в ~2,2 раза.
    Дивидендные гэпы (обычно 5–15 %) не трогаем.
    """
    for i in range(len(bars) - 1, 0, -1):
        ratio = bars[i]["open"] / bars[i - 1]["close"]
        if ratio < threshold or ratio > 1 / threshold:
            k = round(ratio) if ratio > 1 else 1 / round(1 / ratio)
            for b in bars[:i]:
                for f in ("open", "high", "low", "close"):
                    b[f] *= k
                b["volume"] /= k
    return bars


def save_csv(path, bars):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close", "volume"])
        w.writeheader()
        w.writerows(bars)


def load_csv(path):
    with open(path, newline="") as f:
        return [{"date": r["date"], **{k: float(r[k]) for k in ("open", "high", "low", "close", "volume")}}
                for r in csv.DictReader(f)]


def history(ticker, frm="2014-01-01", refresh=False):
    """История с Мосбиржи, закешированная в finam/cache/ТИКЕР.csv."""
    path = os.path.join(CACHE, f"{ticker}.csv")
    if os.path.exists(path) and not refresh:
        return load_csv(path)
    bars = moex_bars(ticker, frm)
    save_csv(path, bars)
    return bars


# --- внутридневные свечи фьючерсов -------------------------------------------
ISS_FUT = ("https://iss.moex.com/iss/engines/futures/markets/forts/securities/"
           "{sec}/candles.json?interval={iv}&from={frm}&till={till}&start={start}&iss.meta=off")


def moex_futures_candles(secid, frm, till=None, interval=10):
    """Свечи фьючерса с Мосбиржи (interval: 1, 10 или 60 минут). Время — МСК, начало свечи.
    Без подписки на данные ISS отдаёт их с задержкой ~15 минут — для бэктеста это не важно."""
    till = till or date.today().isoformat()
    out, start = [], 0
    while True:
        url = ISS_FUT.format(sec=secid, iv=interval, frm=frm, till=till, start=start)
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "birzha"}),
                                    timeout=30) as r:
            js = json.loads(r.read())["candles"]
        rows = js["data"]
        if not rows:
            break
        for row in rows:
            x = dict(zip(js["columns"], row))
            t = x["begin"][:16]
            out.append({"t": t, "date": t[:10], "open": x["open"], "high": x["high"],
                        "low": x["low"], "close": x["close"], "volume": x["volume"]})
        start += len(rows)
    return out


def aggregate(bars, minutes):
    """Склеивает мелкие свечи в крупные (например, 10-минутные → 30-минутные) внутри одного дня."""
    out, cur, key = [], None, None
    for b in bars:
        hh, mm = int(b["t"][11:13]), int(b["t"][14:16])
        m = (hh * 60 + mm) // minutes * minutes
        k = (b["date"], m)
        if k != key:
            if cur:
                out.append(cur)
            key = k
            cur = dict(b, t=f"{b['date']} {m // 60:02d}:{m % 60:02d}")
        else:
            cur["high"] = max(cur["high"], b["high"])
            cur["low"] = min(cur["low"], b["low"])
            cur["close"] = b["close"]
            cur["volume"] += b["volume"]
    if cur:
        out.append(cur)
    return out


def save_csv_t(path, bars):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["t", "open", "high", "low", "close", "volume"])
        w.writeheader()
        w.writerows({k: b[k] for k in ("t", "open", "high", "low", "close", "volume")} for b in bars)


def load_csv_t(path):
    with open(path, newline="") as f:
        return [{"t": r["t"], "date": r["t"][:10],
                 **{k: float(r[k]) for k in ("open", "high", "low", "close", "volume")}}
                for r in csv.DictReader(f)]


def futures_history(secid, frm="2024-01-01", refresh=False):
    """10-минутная история фьючерса с Мосбиржи, кеш в finam/cache/fut_SECID_10m.csv."""
    path = os.path.join(CACHE, f"fut_{secid}_10m.csv")
    if os.path.exists(path) and not refresh:
        return load_csv_t(path)
    bars = moex_futures_candles(secid, frm)
    save_csv_t(path, bars)
    return bars
