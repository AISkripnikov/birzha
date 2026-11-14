"""Проверки механики на синтетических данных (без интернета):  python -m unittest test_strategy"""
import random
import unittest
from datetime import date, timedelta

import config
from data import adjust_splits
from engine import buy_and_hold, metrics, simulate
from strategy import atr, ema, position_size


def synthetic(seed, n=2000, drift_regimes=True):
    rnd = random.Random(seed)
    price, bars, d = 100.0, [], date(2015, 1, 1)
    drift = 0.0
    for i in range(n):
        if drift_regimes and i % 250 == 0:
            drift = rnd.choice([-0.001, 0.0, 0.0015])
        d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        o = price * (1 + rnd.gauss(0, 0.004))
        c = o * (1 + drift + rnd.gauss(0, 0.018))
        h, l = max(o, c) * (1 + abs(rnd.gauss(0, 0.006))), min(o, c) * (1 - abs(rnd.gauss(0, 0.006)))
        bars.append({"date": d.isoformat(), "open": o, "high": h, "low": l, "close": c, "volume": 1e6})
        price = c
    return bars


class T(unittest.TestCase):
    def test_indicators(self):
        self.assertAlmostEqual(ema([1, 2, 3, 4, 5], 3)[-1], 4.0)
        bars = [{"high": 11, "low": 9, "close": 10}] * 30
        self.assertAlmostEqual(atr(bars, 14)[-1], 2.0)

    def test_position_size(self):
        q = position_size(1_000_000, 1_000_000, 100, 2, config.RISK, 3.0, lot=10)
        self.assertEqual(q % 10, 0)
        self.assertLessEqual(q * 3 * 2, 1_000_000 * 0.01 + 1e-6)   # риск ≤ 1 %
        self.assertLessEqual(q * 100, 1_000_000 * 0.20 + 1e-6)     # доля ≤ 20 %

    def test_split_adjust(self):
        bars = [{"date": str(i), "open": 10000.0, "high": 10100.0, "low": 9900.0, "close": 10000.0, "volume": 1.0}
                for i in range(5)]
        bars += [{"date": "9", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 100.0}]
        adjust_splits(bars)
        self.assertAlmostEqual(bars[0]["close"], 100.0)

    def test_simulation_is_consistent(self):
        data = {f"S{i}": synthetic(i) for i in range(12)}
        res = simulate(data, config.STRATEGY, config.RISK, config.COSTS, start="2016-01-01")
        m = metrics(res["curve"], res["trades"])
        self.assertGreater(m["trades"], 10)
        for t in res["trades"]:
            if t["exit_date"] != "открыта":
                self.assertLessEqual(t["entry_date"], t["exit_date"])
        # капитал никогда не уходит в минус, позиций не больше лимита
        self.assertTrue(all(e > 0 for _, e in res["curve"]))
        self.assertLessEqual(len(res["open"]), config.RISK["max_positions"])
        self.assertTrue(buy_and_hold(data, "2016-01-01"))

    def test_no_edge_on_pure_noise(self):
        """На случайном блуждании без трендов стратегия не должна «печатать деньги» — иначе где-то утечка будущего."""
        data = {f"N{i}": synthetic(100 + i, drift_regimes=False) for i in range(12)}
        res = simulate(data, config.STRATEGY, config.RISK, config.COSTS, start="2016-01-01")
        self.assertLess(metrics(res["curve"])["cagr"], 0.05)


if __name__ == "__main__":
    unittest.main()
