"""Внутридневной бот для фьючерсов: следит за свечами весь день и торгует (или пишет сигналы).

Запустите утром до 10:00 МСК и не закрывайте окно до 18:50 — бот сам остановится.

    python fut_bot.py                  # бумажная торговля: сигналы и виртуальные сделки
    python fut_bot.py --capital 200000
    python fut_bot.py --live           # РЕАЛЬНЫЕ заявки на счёт Финама (спросит подтверждение)
    python fut_bot.py --find USDRUBF   # узнать точный символ инструмента в Финаме

Переменные окружения:
    FINAM_TOKEN, FINAM_ACCOUNT_ID  — токен и счёт Финама. С токеном свечи берутся у Финама в реальном
                                     времени; без токена — с Мосбиржи с задержкой ~15 минут (только для пробы).
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID — по желанию: присылать сделки в Telegram.
"""
import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import fut_config as cfg
from bot import telegram
from data import aggregate, moex_futures_candles
from fut_strategy import Book, hm, indicators

HERE = os.path.dirname(os.path.abspath(__file__))
MSK = timezone(timedelta(hours=3))
FINAM_TF = {10: ("TIME_FRAME_M5", 10), 30: ("TIME_FRAME_M30", 30), 60: ("TIME_FRAME_H1", 60)}


def now_msk():
    return datetime.now(MSK)


def rub(x, sign=True):
    return (f"{x:+,.0f}" if sign else f"{x:,.0f}").replace(",", " ") + " ₽"


def say(text):
    print(f"[{now_msk():%H:%M:%S}] {text}", flush=True)
    telegram(text)


def fetch(api, s, tf):
    """Свечи за последние дни; незакрытую текущую свечу отбрасываем."""
    if api:
        frame, _ = FINAM_TF[tf]
        bars = api.candles(cfg.INSTRUMENTS[s]["symbol"], frame, days=7)
        if frame == "TIME_FRAME_M5":
            bars = aggregate(bars, tf)
    else:
        bars = aggregate(moex_futures_candles(s, (date.today() - timedelta(days=7)).isoformat()), tf)
    limit = (now_msk() - timedelta(minutes=tf)).strftime("%Y-%m-%d %H:%M")
    return [b for b in bars if b["t"] <= limit]


def describe(kind, s, x):
    side = "ЛОНГ" if x.get("dir", 0) > 0 else "ШОРТ"
    if kind == "SIGNAL":
        return f"⚡ {s}: сигнал {side} по {x['close']:.6g} (свеча {x['t'][11:]})"
    if kind == "ENTER":
        return f"🟢 {s}: вход {side} {x['qty']} шт по {x['entry']:.6g}, стоп {x['stop']:.6g}"
    if kind == "EXIT":
        return f"🔴 {s}: выход из {side} по {x['exit']:.6g} ({x['reason']}), результат {rub(x['pnl'])}"
    return f"↕ {s}: стоп передвинут на {x['stop']:.6g}"


class Live:
    """Переводит решения книги в реальные заявки Финама."""

    def __init__(self, api):
        self.api, self.stops = api, {}

    def positions(self):
        acc = self.api.account()
        out = {}
        for s, v in cfg.INSTRUMENTS.items():
            q = acc["positions"].get(v["symbol"], {}).get("qty", 0)
            if q:
                out[s] = q
        return out

    def _cancel_stop(self, s):
        oid = self.stops.pop(s, None)
        if oid:
            try:
                self.api.cancel(oid)
            except Exception as e:
                print(f"  {s}: стоп-заявка {oid} не снята (возможно, уже исполнена): {e}")

    def _place_stop(self, s, dir_, qty, price):
        side = "SIDE_SELL" if dir_ > 0 else "SIDE_BUY"
        r = self.api.stop_order(cfg.INSTRUMENTS[s]["symbol"], qty, side, price)
        self.stops[s] = r.get("order_id")

    def enter(self, s, dir_, qty, stop):
        sym = cfg.INSTRUMENTS[s]["symbol"]
        self.api.market(sym, qty, "SIDE_BUY" if dir_ > 0 else "SIDE_SELL", comment="birzha-fut")
        self._place_stop(s, dir_, qty, stop)

    def trail(self, s, pos):
        self._cancel_stop(s)
        self._place_stop(s, pos["dir"], pos["qty"], pos["stop"])

    def flatten(self, s):
        self._cancel_stop(s)
        q = self.positions().get(s, 0)
        if q:
            self.api.market(cfg.INSTRUMENTS[s]["symbol"], abs(q), "SIDE_SELL" if q > 0 else "SIDE_BUY",
                            comment="birzha-flat")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--capital", type=float, default=1_000_000)
    ap.add_argument("--only", nargs="*", help="только эти инструменты")
    ap.add_argument("--find", help="найти символ инструмента в Финаме")
    ap.add_argument("--once", action="store_true", help="один проход и выход (для проверки)")
    a = ap.parse_args()
    p, tf = cfg.STRATEGY, cfg.STRATEGY["timeframe"]
    if tf not in FINAM_TF:
        sys.exit("Для бота таймфрейм должен быть 10, 30 или 60 минут.")
    if a.only:
        cfg.INSTRUMENTS = {s: v for s, v in cfg.INSTRUMENTS.items() if s in a.only}

    api = None
    if os.getenv("FINAM_TOKEN"):
        from finam_api import Finam
        api = Finam(os.getenv("FINAM_TOKEN"), os.getenv("FINAM_ACCOUNT_ID"))
    if a.find:
        if not api:
            sys.exit("Для поиска нужен FINAM_TOKEN.")
        print("\n".join(api.find(a.find)) or "Не найдено")
        return

    live = None
    if a.live:
        if not (api and api.account_id):
            sys.exit("Для --live задайте FINAM_TOKEN и FINAM_ACCOUNT_ID.")
        if not a.yes and input("Будут отправлены РЕАЛЬНЫЕ заявки по фьючерсам. Введите ДА: ").strip().upper() != "ДА":
            sys.exit("Отменено.")
        live = Live(api)
        acc = api.account()
        a.capital = acc["equity"] or a.capital
        if live.positions():
            sys.exit(f"На счёте уже есть позиции по фьючерсам {live.positions()} — закройте их или уберите "
                     f"инструмент через --only, чтобы бот не путался.")
    elif not api:
        say("Нет FINAM_TOKEN: свечи с Мосбиржи с задержкой ~15 минут. Подходит только для знакомства.")

    book = Book(cfg.INSTRUMENTS, p, cfg.RISK, cfg.COSTS, a.capital)
    processed = {}
    say(f"Бот запущен: {', '.join(cfg.INSTRUMENTS)}; свечи {tf} мин; "
        f"{'РЕАЛЬНАЯ торговля' if live else 'бумажная торговля'}; капитал {rub(a.capital, sign=False)}")

    while True:
        t_now = now_msk()
        for s in cfg.INSTRUMENTS:
            try:
                bars = fetch(api, s, tf)
            except Exception as e:
                say(f"⚠ {s}: ошибка данных: {e}")
                continue
            if not bars:
                continue
            ind = indicators(bars, p)
            last = len(bars) - 1
            # сверка со счётом: стоп-заявка на бирже сработала раньше, чем это увидела книга
            if live and s in book.pos and s not in live.positions():
                live.stops.pop(s, None)
                say(describe("EXIT", s, book._close(s, book.pos[s]["stop"], bars[last]["t"], "стоп на бирже")))
            if s not in processed:          # первый проход: не «торгуем» прошлое, только запоминаем
                processed[s] = bars[last]["t"]
            # следующая свеча уже «за чертой» закрытия дня — выходим сейчас, не дожидаясь её
            nxt_start = hm(bars[last]["t"][11:16]) + tf
            if s in book.pos and bars[last]["date"] == t_now.date().isoformat() and nxt_start + tf > hm(p["flat"]):
                if live:
                    live.flatten(s)
                say(describe("EXIT", s, book._close(s, bars[last]["close"], bars[last]["t"], "конец дня")))
                if not a.once:
                    continue
                start_i = last
            else:
                start_i = next((i for i, b in enumerate(bars) if b["t"] > processed[s]), None)
                if start_i is None:
                    continue
            for i in range(start_i, last + 1):
                for kind, sym, x in book.on_bar(s, bars, ind, i):
                    stale = i != last
                    if kind == "SIGNAL" and stale:
                        book.pending.pop(s, None)   # старый сигнал не исполняем
                        continue
                    if kind == "SIGNAL":
                        x["qty"] = book.contracts(s, x["close"], x["atr"])
                        if x["qty"] <= 0:
                            book.pending.pop(s, None)
                            say(f"🟡 {s}: сигнал есть, но не хватает ГО/капитала на 1 контракт")
                            continue
                        x["stop"] = x["close"] - x["dir"] * p["stop_atr"] * x["atr"]
                        if live:   # в жизни входим сразу после закрытия свечи
                            live.enter(s, x["dir"], x["qty"], x["stop"])
                    if live and kind == "TRAIL":
                        live.trail(s, x)
                    if live and kind == "EXIT":
                        live.flatten(s)
                    if kind != "TRAIL" or not stale:
                        say(describe(kind, s, x))
            processed[s] = bars[last]["t"]
            # следующая свеча уже «за чертой» закрытия дня — выходим сейчас, не дожидаясь её
            nxt_start = hm(bars[last]["t"][11:16]) + tf
            if s in book.pos and bars[last]["date"] == t_now.date().isoformat() and nxt_start + tf > hm(p["flat"]):
                if live:
                    live.flatten(s)
                say(describe("EXIT", s, book._close(s, bars[last]["close"], bars[last]["t"], "конец дня")))

        if a.once:
            break
        if hm(t_now.strftime("%H:%M")) >= hm(p["flat"]) + 15:
            for s in list(book.pos):
                if live:
                    live.flatten(s)
            say(f"Торговый день окончен. Сделок: {len(book.trades)}, результат {rub(book.capital - a.capital)}")
            break
        # ждём закрытия следующей свечи (+20 секунд, чтобы биржа успела её отдать)
        nxt = t_now.replace(second=0, microsecond=0)
        nxt += timedelta(minutes=tf - nxt.minute % tf, seconds=20)
        time.sleep(max((nxt - now_msk()).total_seconds(), 5))

    with open(os.path.join(HERE, f"fut_trades_{date.today()}.json"), "w", encoding="utf-8") as f:
        json.dump(book.trades, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
