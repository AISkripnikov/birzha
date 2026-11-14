"""Бот: раз в день считает сигналы и (по желанию) торгует через Финам.

Запускайте один раз в день после закрытия основной сессии (после 19:00 МСК),
например через Планировщик заданий Windows или cron.

    python bot.py                 # бумажная торговля: виртуальный счёт в paper_state.json
    python bot.py --capital 300000
    python bot.py --live          # РЕАЛЬНЫЕ заявки на счёт Финама (спросит подтверждение)

Переменные окружения:
    FINAM_TOKEN       — API-токен из личного кабинета Финама (для --live; без него данные берутся с Мосбиржи)
    FINAM_ACCOUNT_ID  — номер торгового счёта (для --live)
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID — по желанию: присылать отчёт в Telegram
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

import config
from data import moex_bars
from engine import breadth, candidates, prepare
from strategy import position_size, trail_stop

HERE = os.path.dirname(os.path.abspath(__file__))
MSK = timezone(timedelta(hours=3))


def rub(x):
    return f"{x:,.0f} ₽".replace(",", " ")


def load_state(path, capital):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"cash": capital, "positions": {}, "history": []}


def save_state(path, state):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_data(api):
    """Дневные свечи по всем бумагам. Незакрытый сегодняшний день отбрасываем."""
    now = datetime.now(MSK)
    today_open = now.hour < 19
    frm = (date.today() - timedelta(days=700)).isoformat()
    data = {}
    for t in config.UNIVERSE:
        try:
            bars = api.bars(f"{t}@{config.MIC}", days=700) if api else moex_bars(t, frm)
        except Exception as e:
            print(f"  {t}: ошибка загрузки — {e}", file=sys.stderr)
            continue
        if bars and today_open and bars[-1]["date"] == now.date().isoformat():
            bars = bars[:-1]
        if bars:
            data[t] = bars
    return data


def telegram(text):
    tok, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return
    try:
        body = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", body, timeout=15)
    except Exception as e:
        print(f"Telegram: не удалось отправить ({e})", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="реальные заявки через Finam Trade API")
    ap.add_argument("--yes", action="store_true", help="не спрашивать подтверждение (для планировщика)")
    ap.add_argument("--capital", type=float, default=1_000_000, help="стартовый капитал бумажного счёта")
    ap.add_argument("--state", default=os.path.join(HERE, "paper_state.json"))
    a = ap.parse_args()
    p, risk, k = config.STRATEGY, config.RISK, config.STRATEGY["stop_atr"]

    api = None
    if os.getenv("FINAM_TOKEN"):
        from finam_api import Finam
        api = Finam(os.getenv("FINAM_TOKEN"), os.getenv("FINAM_ACCOUNT_ID"))
    if a.live:
        if not (api and api.account_id):
            sys.exit("Для --live задайте FINAM_TOKEN и FINAM_ACCOUNT_ID.")
        if not a.yes and input("Будут отправлены РЕАЛЬНЫЕ заявки. Введите ДА: ").strip().upper() != "ДА":
            sys.exit("Отменено.")
        a.state = os.path.join(HERE, "live_state.json")

    print("Загружаю свечи…")
    data = load_data(api)
    if not data:
        sys.exit("Нет данных.")
    prep = prepare(data, p)
    d = max(b[-1]["date"] for b in data.values())
    br = breadth(prep, d)
    state = load_state(a.state, a.capital)
    report = [f"📊 Сигналы на закрытие {d}",
              f"Рынок: {br * 100:.0f}% бумаг выше EMA200 — "
              + ("покупки разрешены" if br >= p["breadth_min"] else "новые покупки ЗАПРЕЩЕНЫ (рынок слабый)")]

    # --- текущие позиции ---------------------------------------------------
    if a.live:
        acc = api.account()
        held = {s.split("@")[0]: v["qty"] for s, v in acc["positions"].items()
                if s.split("@")[0] in config.UNIVERSE and v["qty"] > 0}
        equity, cash = acc["equity"], acc["cash"]
    else:
        held = {s: v["qty"] for s, v in state["positions"].items()}
        equity = state["cash"] + sum(v["qty"] * data[s][-1]["close"]
                                     for s, v in state["positions"].items() if s in data)
        cash = state["cash"]

    # --- сопровождение: трейлинг-стопы -------------------------------------
    for s in list(held):
        if s not in prep:
            continue
        bars, ind, idx = prep[s]
        pos = state["positions"].setdefault(s, {"qty": held[s], "entry": bars[-1]["close"],
                                                "date": d, "high": bars[-1]["high"], "stop": None})
        pos["qty"] = held[s]
        since = [b for b in bars if b["date"] >= pos.get("updated", pos["date"])]
        old_stop = pos["stop"]
        close = bars[-1]["close"]
        # бумажный счёт: был ли пробит стоп после прошлого запуска (как в бэктесте)
        hit = [b for b in since if b["date"] > pos.get("updated", pos["date"])
               and old_stop is not None and b["low"] <= old_stop]
        if not a.live and hit:
            price = min(hit[0]["open"], old_stop)
            state["cash"] += pos["qty"] * price * (1 - config.COSTS["commission"])
            state["history"].append({"symbol": s, "entry": pos["entry"], "exit": price,
                                     "from": pos["date"], "to": hit[0]["date"], "qty": pos["qty"]})
            del state["positions"][s]
            report.append(f"🔴 ПРОДАНО {s}: {pos['qty']:.0f} шт по ~{price:.2f} (стоп {old_stop}), "
                          f"итог {(price / pos['entry'] - 1) * 100:+.1f}%")
            continue
        pos["high"] = max([pos["high"]] + [b["high"] for b in since])
        pos["stop"] = round(trail_stop(old_stop, pos["high"], ind["atr"][-1], k), 2)
        pos["updated"] = d
        pnl = (close / pos["entry"] - 1) * 100
        report.append(f"⚪ ДЕРЖАТЬ {s}: {pos['qty']:.0f} шт, {pnl:+.1f}%, стоп {old_stop} → {pos['stop']}")
        if a.live and pos["stop"] != old_stop:
            if pos.get("stop_order"):
                try:
                    api.cancel(pos["stop_order"])
                except Exception as e:
                    print(f"  не удалось отменить старый стоп {s}: {e}", file=sys.stderr)
            r = api.stop_sell(f"{s}@{config.MIC}", pos["qty"], pos["stop"])
            pos["stop_order"] = r.get("order_id")

    # позиции, которых больше нет на счёте (сработал стоп на бирже), убираем из состояния
    if a.live:
        for s in [s for s in state["positions"] if s not in held]:
            report.append(f"✅ {s}: позиция закрыта (стоп-заявка исполнилась)")
            del state["positions"][s]

    # --- новые входы --------------------------------------------------------
    free = risk["max_positions"] - len(state["positions"])
    if free > 0 and br >= p["breadth_min"]:
        for score, s, close, atr_v in candidates(prep, d, state["positions"], p)[:free]:
            lot = api.lot_size(f"{s}@{config.MIC}") if api and api.account_id else 1
            qty = position_size(equity, cash, close, atr_v, risk, k, lot)
            stop = round(close - k * atr_v, 2)
            if qty <= 0:
                report.append(f"🟡 {s}: сигнал есть, но не хватает денег на лот")
                continue
            report.append(f"🟢 КУПИТЬ {s}: {qty} шт по ~{close:.2f} (≈{rub(qty * close)}), стоп {stop}, "
                          f"сила тренда {score * 100:+.0f}% за полгода")
            cost = qty * close * (1 + config.COSTS["commission"])
            cash -= cost
            pos = {"qty": qty, "entry": close, "date": d, "high": close, "stop": stop, "updated": d}
            if a.live:
                api.market(f"{s}@{config.MIC}", qty, "SIDE_BUY")
                r = api.stop_sell(f"{s}@{config.MIC}", qty, stop)
                pos["stop_order"] = r.get("order_id")
            else:
                state["cash"] -= cost
            state["positions"][s] = pos
    elif free > 0:
        report.append("Новых покупок нет: рынок в нисходящем тренде.")

    if len(report) == 2:
        report.append("Сигналов нет — ничего не делаем. Это нормально: стратегия торгует редко.")
    report.append(f"Капитал ≈ {rub(equity)}, свободно ≈ {rub(cash)}")
    save_state(a.state, state)
    text = "\n".join(report)
    print("\n" + text)
    telegram(text)


if __name__ == "__main__":
    main()
