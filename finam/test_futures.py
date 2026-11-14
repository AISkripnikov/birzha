"""Проверки внутридневной механики на синтетике:  python -m unittest test_futures"""
import random
import unittest
from datetime import date, timedelta

import fut_backtest
import fut_config as cfg
from data import aggregate
from engine import metrics


def synthetic_intraday(seed, days=250, price=90.0, trend=True):
    rnd = random.Random(seed)
    out, d = [], date(2024, 6, 3)
    for _ in range(days):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        drift = rnd.choice([-1, 0, 1]) * 0.0006 if trend else 0.0
        times = [f"{h:02d}:{m:02d}" for h in range(10, 24) for m in range(0, 60, 10)
                 if not (h == 18 and m >= 50) and not (h == 19 and m == 0) and not (h == 23 and m >= 50)]
        price *= 1 + rnd.gauss(0, 0.003)  # ночной гэп
        for t in times:
            o = price
            c = o * (1 + drift + rnd.gauss(0, 0.0015))
            out.append({"t": f"{d} {t}", "date": str(d), "open": o, "close": c,
                        "high": max(o, c) * (1 + abs(rnd.gauss(0, 0.0007))),
                        "low": min(o, c) * (1 - abs(rnd.gauss(0, 0.0007))), "volume": 100})
            price = c
        d += timedelta(days=1)
    return out


class T(unittest.TestCase):
    def test_aggregate(self):
        bars = synthetic_intraday(1, days=2)
        agg = aggregate(bars, 30)
        self.assertTrue(all(b["t"][14:16] in ("00", "30") for b in agg))
        self.assertAlmostEqual(sum(b["volume"] for b in agg), sum(b["volume"] for b in bars))

    def _run(self, trend):
        data = {s: aggregate(synthetic_intraday(i, trend=trend), 30) for i, s in enumerate(cfg.INSTRUMENTS)}
        return fut_backtest.run(data, "2024-06-01")

    def test_rules(self):
        book, curve = self._run(True)
        self.assertGreater(len(book.trades), 50)
        for t in book.trades:
            self.assertEqual(t["entry_t"][:10], t["exit_t"][:10], "позиция перенесена через ночь")
            self.assertLessEqual(t["exit_t"][11:], "18:40")
            self.assertGreaterEqual(t["entry_t"][11:], "10:00")
        per_day = {}
        for t in book.trades:
            k = (t["symbol"], t["entry_t"][:10])
            per_day[k] = per_day.get(k, 0) + 1
        self.assertLessEqual(max(per_day.values()), cfg.STRATEGY["max_trades_per_day"])
        self.assertTrue({t["dir"] for t in book.trades} == {1, -1})
        self.assertFalse(book.pos)

    def test_no_edge_on_noise(self):
        book, curve = self._run(False)
        self.assertLess(metrics(curve)["return"], 0.03)


if __name__ == "__main__":
    unittest.main()
