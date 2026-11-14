"""Проверка стратегии на истории Мосбиржи.

    python backtest.py                         # 2016 — сегодня, все бумаги из config.py
    python backtest.py --start 2021-01-01      # другой период
    python backtest.py --split 2022-01-01      # отдельно «до» и «после» даты (проверка на переобучение)
    python backtest.py --refresh               # перекачать историю
    python backtest.py --csv-dir мои_данные    # свои CSV (date,open,high,low,close,volume)
"""
import argparse
import os
import sys

import config
from data import history, load_csv
from engine import buy_and_hold, metrics, simulate


def pct(x):
    return f"{x * 100:+.1f}%"


def show(title, m, bh):
    print(f"\n=== {title}")
    print(f"  Стратегия:     доходность {pct(m['return'])}, в год {pct(m['cagr'])}, "
          f"макс. просадка {pct(m['max_dd'])}, Шарп {m['sharpe']:.2f}")
    if bh:
        print(f"  Купил и держи: доходность {pct(bh['return'])}, в год {pct(bh['cagr'])}, "
              f"макс. просадка {pct(bh['max_dd'])}, Шарп {bh['sharpe']:.2f}")
    if "trades" in m:
        print(f"  Сделок {m['trades']}, прибыльных {m['win_rate'] * 100:.0f}%, "
              f"средняя прибыль {m['avg_win']:,.0f} ₽, средний убыток {m['avg_loss']:,.0f} ₽, "
              f"profit factor {m['profit_factor']:.2f}".replace(",", " "))


def run(data, start, end=None, title=None):
    res = simulate(data, config.STRATEGY, config.RISK, config.COSTS, start=start, end=end)
    trades = [t for t in res["trades"] if t["entry_date"] >= start]
    show(title or f"{start} — {end or 'сегодня'}", metrics(res["curve"], trades),
         metrics(buy_and_hold(data, start, end)))
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end")
    ap.add_argument("--split", help="дата разделения: до неё — «обучение», после — «экзамен»")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--csv-dir")
    ap.add_argument("--trades", action="store_true", help="напечатать все сделки")
    a = ap.parse_args()

    data = {}
    for t in config.UNIVERSE:
        try:
            if a.csv_dir:
                data[t] = load_csv(os.path.join(a.csv_dir, f"{t}.csv"))
            else:
                data[t] = history(t, refresh=a.refresh)
            print(f"{t}: {len(data[t])} дней с {data[t][0]['date']}" if data[t] else f"{t}: нет данных")
        except Exception as e:
            print(f"{t}: не удалось загрузить ({e})", file=sys.stderr)
    if not data:
        sys.exit("Нет данных. Проверьте интернет (iss.moex.com) или укажите --csv-dir.")

    res = run(data, a.start, a.end)
    if a.split:
        run(data, a.start, a.split, f"До {a.split} (обучение)")
        run(data, a.split, a.end, f"После {a.split} (экзамен — главное)")

    year_end = {}
    for d, e in res["curve"]:
        year_end[d[:4]] = e
    prev, parts = res["capital"], []
    for y, e in year_end.items():
        parts.append(f"{y}: {pct(e / prev - 1)}")
        prev = e
    print("\nПо годам: " + "  ".join(parts))
    if a.trades:
        print("\nСделки:")
        for t in res["trades"]:
            print(f"  {t['symbol']:6} {t['entry_date']} → {t['exit_date']:10} "
                  f"{t['entry']:10.2f} → {t['exit']:10.2f}  {t['pnl']:+12,.0f} ₽".replace(",", " "))


if __name__ == "__main__":
    main()
