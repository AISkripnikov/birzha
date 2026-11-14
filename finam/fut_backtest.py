"""Проверка внутридневной стратегии на фьючерсах по истории Мосбиржи.

    python fut_backtest.py                       # с 2024-06-01 по сегодня, все инструменты из fut_config.py
    python fut_backtest.py --split 2025-06-01    # «обучение» до даты и «экзамен» после
    python fut_backtest.py --only USDRUBF CNYRUBF
    python fut_backtest.py --tf 10               # 10-минутные свечи вместо 30-минутных
    python fut_backtest.py --trades              # список сделок
"""
import argparse
import sys

import fut_config as cfg
from data import aggregate, futures_history
from engine import metrics
from fut_strategy import Book, indicators


def run(data, start, end=None, capital=1_000_000, p=None):
    p = p or cfg.STRATEGY
    prep = {s: (b, indicators(b, p)) for s, b in data.items()}
    events = sorted((b["t"], s, i) for s, (bars, _) in prep.items()
                    for i, b in enumerate(bars) if b["date"] >= start and (not end or b["date"] <= end))
    book = Book(cfg.INSTRUMENTS, p, cfg.RISK, cfg.COSTS, capital)
    curve, last_day = [], None
    for t, s, i in events:
        if last_day and t[:10] != last_day:
            curve.append((last_day, book.equity()))
        last_day = t[:10]
        bars, ind = prep[s]
        book.on_bar(s, bars, ind, i)
    if last_day:
        curve.append((last_day, book.equity()))
    return book, curve


def pct(x):
    return f"{x * 100:+.1f}%"


def rub(x):
    return f"{x:+,.0f} ₽".replace(",", " ")


def report(title, book, curve):
    m = metrics(curve, book.trades)
    print(f"\n=== {title}")
    if not m or "trades" not in m:
        print("  Сделок нет.")
        return
    days = len(curve)
    print(f"  Доходность {pct(m['return'])} за {days} торговых дней (в год {pct(m['cagr'])}), "
          f"макс. просадка {pct(m['max_dd'])}, Шарп {m['sharpe']:.2f}")
    print(f"  Сделок {m['trades']} (~{m['trades'] / max(days, 1):.1f} в день), прибыльных {m['win_rate'] * 100:.0f}%, "
          f"средняя прибыль {rub(m['avg_win'])}, средний убыток {rub(m['avg_loss'])}, "
          f"profit factor {m['profit_factor']:.2f}")
    for name, f in (("Лонги", lambda t: t["dir"] > 0), ("Шорты", lambda t: t["dir"] < 0)):
        tr = [t for t in book.trades if f(t)]
        if tr:
            print(f"  {name}: {len(tr)} сделок, итог {rub(sum(t['pnl'] for t in tr))}")
    by = {}
    for t in book.trades:
        by.setdefault(t["symbol"], []).append(t["pnl"])
    print("  По инструментам: " + ", ".join(
        f"{s} {rub(sum(v))} ({len(v)})" for s, v in sorted(by.items(), key=lambda x: -sum(x[1]))))
    reasons = {}
    for t in book.trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    print("  Выходы: " + ", ".join(f"{k} — {v}" for k, v in reasons.items()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2024-06-01")
    ap.add_argument("--end")
    ap.add_argument("--split")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--tf", type=int, help="таймфрейм в минутах (кратен 10)")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--trades", action="store_true")
    a = ap.parse_args()
    if a.tf:
        cfg.STRATEGY["timeframe"] = a.tf
    tf = cfg.STRATEGY["timeframe"]
    if tf % 10:
        sys.exit("Таймфрейм должен быть кратен 10 минутам (история Мосбиржи — 10-минутные свечи).")

    data = {}
    for s in a.only or cfg.INSTRUMENTS:
        try:
            raw = futures_history(s, frm="2023-01-01", refresh=a.refresh)
            data[s] = aggregate(raw, tf) if tf != 10 else raw
            print(f"{s}: {len(data[s])} свечей по {tf} мин с {data[s][0]['t']}" if data[s] else f"{s}: нет данных")
        except Exception as e:
            print(f"{s}: не удалось загрузить ({e})", file=sys.stderr)
    data = {s: b for s, b in data.items() if b}
    if not data:
        sys.exit("Нет данных. Нужен доступ к iss.moex.com.")

    book, curve = run(data, a.start, a.end)
    report(f"{a.start} — {a.end or 'сегодня'}, свечи {tf} мин", book, curve)
    if a.split:
        report(f"До {a.split} (обучение)", *run(data, a.start, a.split))
        report(f"После {a.split} (экзамен — главное)", *run(data, a.split, a.end))

    months, prev = {}, 1_000_000
    for d, e in curve:
        months[d[:7]] = e
    parts = []
    for mth, e in months.items():
        parts.append(f"{mth}: {pct(e / prev - 1)}")
        prev = e
    print("\nПо месяцам: " + "  ".join(parts))
    if a.trades:
        print("\nСделки:")
        for t in book.trades:
            print(f"  {t['symbol']:8} {'ЛОНГ' if t['dir'] > 0 else 'ШОРТ'} {t['qty']:3} шт  {t['entry_t']} → {t['exit_t'][11:]}"
                  f"  {t['entry']:.4g} → {t['exit']:.4g}  {rub(t['pnl']):>12}  ({t['reason']})")


if __name__ == "__main__":
    main()
