"""Портфельный симулятор стратегии и расчёт сигналов «на сегодня».

Правила исполнения (без заглядывания в будущее):
  * сигнал считается по закрытию дня D, покупка — по цене открытия дня D+1;
  * стоп проверяется внутри дня: если low ≤ стоп — продаём по стопу,
    а если открылись гэпом ниже стопа — по цене открытия (как в жизни);
  * комиссия и проскальзывание учитываются в каждой сделке.
"""
import math

from strategy import above_slow, entry_signal, indicators, position_size, rank_score, trail_stop


def prepare(data, p):
    """data: {тикер: [bars]} → {тикер: (bars, ind, {date: i})}."""
    return {s: (b, indicators(b, p), {x["date"]: i for i, x in enumerate(b)}) for s, b in data.items() if b}


def breadth(prep, d):
    up = total = 0
    for bars, ind, idx in prep.values():
        i = idx.get(d)
        if i is not None and ind["ema_slow"][i] is not None:
            total += 1
            up += above_slow(bars, ind, i)
    return up / total if total else 0.0


def candidates(prep, d, held, p):
    """Бумаги с сигналом на покупку на закрытии дня d, лучшие — первыми."""
    out = []
    for s, (bars, ind, idx) in prep.items():
        i = idx.get(d)
        if s not in held and i is not None and entry_signal(bars, ind, i):
            out.append((rank_score(ind, i), s, bars[i]["close"], ind["atr"][i]))
    out.sort(reverse=True)
    return out


def simulate(data, p, risk, costs, start="2016-01-01", end=None, capital=1_000_000):
    prep = prepare(data, p)
    dates = sorted({d for bars, _, idx in prep.values() for d in idx if d >= start and (not end or d <= end)})
    comm, slip, k = costs["commission"], costs["slippage"], p["stop_atr"]
    cash, positions, pending, trades, curve = capital, {}, [], [], []
    last_close = {}

    for d in dates:
        # 1) покупки по открытию (сигналы вчерашнего закрытия)
        equity_prev = curve[-1][1] if curve else capital
        for _, s, _, a in pending:
            bars, ind, idx = prep[s]
            i = idx.get(d)
            if i is None or len(positions) >= risk["max_positions"]:
                continue
            price = bars[i]["open"] * (1 + slip)
            qty = position_size(equity_prev, cash / (1 + comm), price, a, risk, k)
            if qty <= 0:
                continue
            cash -= qty * price * (1 + comm)
            positions[s] = {"qty": qty, "entry": price, "date": d, "high": bars[i]["high"],
                            "stop": price - k * a}
        pending = []

        # 2) стопы внутри дня + подтягивание стопа после закрытия
        for s in list(positions):
            bars, ind, idx = prep[s]
            i = idx.get(d)
            if i is None:
                continue
            pos, b = positions[s], bars[i]
            if b["low"] <= pos["stop"]:
                price = min(b["open"], pos["stop"]) * (1 - slip)
                cash += pos["qty"] * price * (1 - comm)
                trades.append({"symbol": s, "entry_date": pos["date"], "exit_date": d,
                               "entry": pos["entry"], "exit": price, "qty": pos["qty"],
                               "pnl": pos["qty"] * (price * (1 - comm) - pos["entry"] * (1 + comm))})
                del positions[s]
                continue
            pos["high"] = max(pos["high"], b["high"])
            if ind["atr"][i]:
                pos["stop"] = trail_stop(pos["stop"], pos["high"], ind["atr"][i], k)

        # 3) оценка капитала по закрытию
        for s, (bars, _, idx) in prep.items():
            i = idx.get(d)
            if i is not None:
                last_close[s] = bars[i]["close"]
        equity = cash + sum(pos["qty"] * last_close[s] for s, pos in positions.items())
        curve.append((d, equity))

        # 4) новые сигналы — только если рынок в целом растёт
        free = risk["max_positions"] - len(positions)
        if free > 0 and breadth(prep, d) >= p["breadth_min"]:
            pending = candidates(prep, d, positions, p)[:free]

    # закрываем остатки по последней цене, чтобы посчитать итог
    for s, pos in positions.items():
        price = last_close[s]
        trades.append({"symbol": s, "entry_date": pos["date"], "exit_date": "открыта",
                       "entry": pos["entry"], "exit": price, "qty": pos["qty"],
                       "pnl": pos["qty"] * (price - pos["entry"] * (1 + comm))})
    return {"curve": curve, "trades": trades, "open": positions, "capital": capital}


def buy_and_hold(data, start, end=None, capital=1_000_000):
    """Бенчмарк: равные доли во всех бумагах, купили в первый день и держим."""
    syms = [s for s, b in data.items() if b and b[0]["date"] <= start]
    if not syms:
        return []
    series = {s: {b["date"]: b["close"] for b in data[s]} for s in syms}
    dates = sorted({d for s in syms for d in series[s] if d >= start and (not end or d <= end)})
    first = {s: next(series[s][d] for d in dates if d in series[s]) for s in syms}
    last, curve = dict(first), []
    for d in dates:
        for s in syms:
            last[s] = series[s].get(d, last[s])
        curve.append((d, capital * sum(last[s] / first[s] for s in syms) / len(syms)))
    return curve


def metrics(curve, trades=None):
    if len(curve) < 2:
        return {}
    v = [e for _, e in curve]
    years = max((len(v) - 1) / 252, 1e-9)
    peak, mdd = v[0], 0.0
    for x in v:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1)
    rets = [v[i] / v[i - 1] - 1 for i in range(1, len(v))]
    mean = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1))
    m = {"return": v[-1] / v[0] - 1, "cagr": (v[-1] / v[0]) ** (1 / years) - 1,
         "max_dd": mdd, "sharpe": mean / sd * math.sqrt(252) if sd else 0.0}
    if trades:
        wins = [t["pnl"] for t in trades if t["pnl"] > 0]
        losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
        m.update({"trades": len(trades), "win_rate": len(wins) / len(trades),
                  "avg_win": sum(wins) / len(wins) if wins else 0,
                  "avg_loss": sum(losses) / len(losses) if losses else 0,
                  "profit_factor": sum(wins) / -sum(losses) if losses and sum(losses) else float("inf")})
    return m
