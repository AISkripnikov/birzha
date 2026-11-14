"""Минимальный клиент Finam Trade API (REST, https://api.finam.ru/v1). Только стандартная библиотека.

Документация: https://tradeapi.finam.ru/docs/
Токен (secret) выпускается в личном кабинете Финама: раздел «API» → «Токены».
Символы инструментов — в виде ТИКЕР@MIC, например SBER@MISX.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

BASE = "https://api.finam.ru/v1"


class FinamError(Exception):
    pass


def _dec(x):
    """Финам отдаёт числа как {"value": "123.45"}."""
    if isinstance(x, dict):
        x = x.get("value", 0)
    return float(x or 0)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Finam:
    def __init__(self, secret, account_id=None):
        if not secret:
            raise FinamError("Не задан токен FINAM_TOKEN")
        self.secret = secret
        self.account_id = account_id
        self.jwt = None
        self.jwt_time = 0.0

    # --- транспорт ---------------------------------------------------------
    def _request(self, method, path, params=None, body=None, auth=True, retry=True):
        if auth and (self.jwt is None or time.time() - self.jwt_time > 600):
            self._login()
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json", "User-Agent": "birzha-bot"}
        if auth:
            headers["Authorization"] = self.jwt
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")
            if e.code == 401 and auth and retry:
                self._login()
                return self._request(method, path, params, body, auth, retry=False)
            if e.code == 429 and retry:  # лимит 200 запросов в минуту
                time.sleep(5)
                return self._request(method, path, params, body, auth, retry=False)
            raise FinamError(f"{method} {path}: HTTP {e.code} {text}") from None

    def _login(self):
        r = self._request("POST", "/sessions", body={"secret": self.secret}, auth=False)
        self.jwt = r["token"]
        self.jwt_time = time.time()

    # --- рыночные данные -----------------------------------------------------
    def bars(self, symbol, days=400, timeframe="TIME_FRAME_D"):
        """Дневные свечи за последние `days` дней (API отдаёт ≤365 дней за запрос — режем на куски)."""
        end = datetime.now(timezone.utc) + timedelta(days=1)
        start = end - timedelta(days=days)
        out, chunk_start = {}, start
        while chunk_start < end:
            chunk_end = min(chunk_start + timedelta(days=360), end)
            r = self._request("GET", f"/instruments/{symbol}/bars", params={
                "timeframe": timeframe,
                "interval.start_time": _iso(chunk_start),
                "interval.end_time": _iso(chunk_end),
            })
            for b in r.get("bars", []):
                d = b["timestamp"][:10]
                out[d] = {"date": d, "open": _dec(b["open"]), "high": _dec(b["high"]),
                          "low": _dec(b["low"]), "close": _dec(b["close"]), "volume": _dec(b["volume"])}
            chunk_start = chunk_end
        return [out[d] for d in sorted(out)]

    def last_price(self, symbol):
        q = self._request("GET", f"/instruments/{symbol}/quotes/latest").get("quote", {})
        return _dec(q.get("last"))

    def lot_size(self, symbol):
        r = self._request("GET", f"/assets/{symbol}", params={"account_id": self.account_id})
        return int(_dec(r.get("lot_size", 1))) or 1

    # --- счёт и заявки -------------------------------------------------------
    def account(self):
        r = self._request("GET", f"/accounts/{self.account_id}")
        positions = {p["symbol"]: {"qty": _dec(p["quantity"]), "avg": _dec(p["average_price"]),
                                   "price": _dec(p["current_price"])} for p in r.get("positions", [])}
        cash = sum(float(c.get("units", 0)) + c.get("nanos", 0) / 1e9
                   for c in r.get("cash", []) if c.get("currency_code") == "RUB")
        return {"equity": _dec(r.get("equity")), "cash": cash, "positions": positions}

    def orders(self):
        return self._request("GET", f"/accounts/{self.account_id}/orders").get("orders", [])

    def cancel(self, order_id):
        return self._request("DELETE", f"/accounts/{self.account_id}/orders/{order_id}")

    def _place(self, body):
        body.setdefault("client_order_id", uuid.uuid4().hex[:20])
        return self._request("POST", f"/accounts/{self.account_id}/orders", body=body)

    def market(self, symbol, qty, side, comment="birzha"):
        """side: "SIDE_BUY" / "SIDE_SELL"; qty — в штуках (кратно лоту)."""
        return self._place({"symbol": symbol, "quantity": {"value": str(int(qty))}, "side": side,
                            "type": "ORDER_TYPE_MARKET", "time_in_force": "TIME_IN_FORCE_DAY",
                            "comment": comment})

    def stop_sell(self, symbol, qty, stop_price, comment="birzha-stop"):
        """Стоп-заявка на продажу по рынку, если цена опустится до stop_price. Действует до отмены."""
        return self._place({"symbol": symbol, "quantity": {"value": str(int(qty))}, "side": "SIDE_SELL",
                            "type": "ORDER_TYPE_STOP", "stop_price": {"value": f"{stop_price:.4f}"},
                            "stop_condition": "STOP_CONDITION_LAST_DOWN",
                            "valid_before": "VALID_BEFORE_GOOD_TILL_CANCEL", "comment": comment})
