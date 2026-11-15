"""Список всего, что показывает сайт: фьючерсы, акции Мосбиржи и криптовалюта, плюс загрузчики свечей.

Поля инструмента:
  market       futures | stock | crypto
  secid/asset  код на Мосбирже (asset — для обычных фьючерсов: сайт сам найдёт ближайший контракт)
  point_value  ₽ за 1 пункт цены на 1 контракт/лот (pv_usd — то же в долларах, переводится по курсу)
  margin_rate  ГО как доля стоимости (1 = без плеча: акции и спот платятся полностью)
  long_only    шорт недоступен (акции без маржинальной торговли, спот-крипта)
  qty_step     шаг количества: 1 контракт/лот или доли монеты
"""
import json
import threading
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

import fut_config as cfg

MSK = timezone(timedelta(hours=3))
CRYPTO_SESSION = {"start": "00:00", "last_entry": "23:00", "flat": "23:50", "weekends": True}

MARKETS = {}
for s, v in cfg.INSTRUMENTS.items():   # вечные фьючерсы — те же, что торгует бот
    MARKETS[s] = dict(v, market="futures", secid=s, group="Вечные фьючерсы")
MARKETS["EURRUBF"] = {"market": "futures", "secid": "EURRUBF", "symbol": "EURRUBF@RTSX", "point_value": 1000,
                      "margin_rate": 0.12, "group": "Вечные фьючерсы"}

# обычные (квартальные/месячные) фьючерсы: код контракта ищется автоматически
for asset, name, pv, pv_usd, mr in (
        ("Si", "Si (доллар, 1000 $)", 1, None, 0.10),
        ("CNY", "CNY (юань, 1000 ¥)", 1000, None, 0.10),
        ("BR", "BR (нефть Brent, 10 барр.)", None, 10, 0.15),
        ("NG", "NG (газ, 100 MMBtu)", None, 100, 0.25),
        ("GOLD", "GOLD (золото, 1 унция)", None, 1, 0.12),
        ("MIX", "MIX (индекс Мосбиржи)", 10, None, 0.15)):
    MARKETS[asset] = {"market": "futures", "asset": asset, "point_value": pv, "pv_usd": pv_usd, "margin_rate": mr,
                      "group": "Срочные фьючерсы", "title": name}

for t in ("SBER", "GAZP", "LKOH", "VTBR", "YDEX", "T", "AFLT", "MOEX", "ROSN", "MGNT"):
    MARKETS[t] = {"market": "stock", "secid": t, "symbol": f"{t}@MISX", "point_value": None,  # = лот, узнаём с биржи
                  "margin_rate": 1.0, "long_only": True, "commission": 0.0005, "group": "Акции"}

for c in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "TONUSDT", "XRPUSDT", "DOGEUSDT"):
    MARKETS[c] = {"market": "crypto", "secid": c, "pv_usd": 1, "margin_rate": 1.0, "long_only": True,
                  "qty_step": 0.0001 if c in ("BTCUSDT", "ETHUSDT") else 0.01, "commission": 0.001,
                  "slippage": 0.0005, "session": CRYPTO_SESSION, "group": "Криптовалюта"}

# Где торговать (верификация гражданина РФ). Данные на конец 2026 г. — проверяйте условия сами.
VENUES = {
    "futures": {
        "title": "Срочный рынок Мосбиржи",
        "where": ["Финам", "Т-Инвестиции", "БКС", "Альфа-Инвестиции", "Сбер Инвестиции", "ВТБ"],
        "verify": "паспорт РФ / Госуслуги, лицензия ЦБ, защита брокерского счёта",
        "min": "нужно ГО на 1 контракт (от ~1–15 тыс. ₽) и тест ЦБ на фьючерсы",
    },
    "stock": {
        "title": "Фондовый рынок Мосбиржи",
        "where": ["Финам", "Т-Инвестиции", "БКС", "Альфа-Инвестиции", "Сбер Инвестиции", "ВТБ"],
        "verify": "паспорт РФ / Госуслуги, лицензия ЦБ",
        "min": "1 лот: от сотен рублей (VTBR, AFLT) до тысяч (SBER, LKOH)",
    },
    "crypto": {
        "title": "Криптобиржи (спот)",
        "where": ["Bybit", "HTX", "MEXC", "BingX", "Gate"],
        "verify": "KYC по паспорту РФ — условия меняются, проверьте при регистрации",
        "min": "ордер от ~1–5 USDT; рубли — только через P2P. Нет защиты ЦБ, возможны блокировки",
    },
}

# ---------------------------------------------------------------------------
_meta, _meta_day, _lock = {}, {}, threading.Lock()


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "birzha"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def front_contract(asset):
    """Ближайший неистёкший контракт на Мосбирже: Si → SiZ6 и т.п. Кешируется на день."""
    key = ("front", asset)
    with _lock:
        if _meta_day.get(key) == date.today():
            return _meta[key]
    js = _get("https://iss.moex.com/iss/engines/futures/markets/forts/securities.json?iss.meta=off"
              "&iss.only=securities&securities.columns=SECID,ASSETCODE,LASTTRADEDATE")["securities"]
    today = date.today().isoformat()
    rows = [dict(zip(js["columns"], r)) for r in js["data"]]
    rows = [r for r in rows if r["ASSETCODE"] == asset and (r["LASTTRADEDATE"] or "") > today]
    if not rows:
        raise RuntimeError(f"не найден действующий контракт {asset}")
    secid = min(rows, key=lambda r: r["LASTTRADEDATE"])["SECID"]
    with _lock:
        _meta[key], _meta_day[key] = (secid, min(r["LASTTRADEDATE"] for r in rows)), date.today()
    return _meta[key]


def lot_size(secid):
    key = ("lot", secid)
    if key not in _meta:
        js = _get("https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/"
                  f"{secid}.json?iss.meta=off&iss.only=securities&securities.columns=LOTSIZE")["securities"]
        _meta[key] = int(js["data"][0][0]) if js["data"] else 1
    return _meta[key]


def iss_candles(market, secid, days):
    path = ("engines/futures/markets/forts/securities" if market == "futures"
            else "engines/stock/markets/shares/boards/TQBR/securities")
    frm = (date.today() - timedelta(days=days)).isoformat()
    out, start = [], 0
    while True:
        js = _get(f"https://iss.moex.com/iss/{path}/{secid}/candles.json?interval=10&from={frm}"
                  f"&start={start}&iss.meta=off")["candles"]
        if not js["data"]:
            break
        for row in js["data"]:
            x = dict(zip(js["columns"], row))
            t = x["begin"][:16]
            out.append({"t": t, "date": t[:10], "open": x["open"], "high": x["high"], "low": x["low"],
                        "close": x["close"], "volume": x["volume"]})
        start += len(js["data"])
    return out


def bybit_candles(symbol, days):
    """5-минутные свечи Bybit (спот), время → МСК. Bybit отдаёт до 1000 свечей за запрос, новые первыми."""
    end = int(time.time() * 1000)
    stop = end - days * 86400_000
    rows = {}
    while end > stop:
        js = _get(f"https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol}&interval=5"
                  f"&limit=1000&end={end}")
        lst = js.get("result", {}).get("list", [])
        if not lst:
            break
        for k in lst:
            rows[int(k[0])] = k
        oldest = min(int(k[0]) for k in lst)
        if oldest >= end:
            break
        end = oldest - 1
    out = []
    for ms in sorted(rows):
        if ms < stop:
            continue
        k = rows[ms]
        t = datetime.fromtimestamp(ms / 1000, MSK).strftime("%Y-%m-%d %H:%M")
        out.append({"t": t, "date": t[:10], "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
                    "close": float(k[4]), "volume": float(k[5])})
    return out
