"""Локальный сервер для Биржевого помощника.

Раздаёт страницу и пересылает запросы рыночных данных к Bybit, чтобы браузер
не блокировал их (CORS). Только чтение публичных данных, никаких ключей.

Запуск:  python server.py   → откройте http://localhost:8000
"""
import http.server
import os
import urllib.error
import urllib.request
import webbrowser

PORT = 8000
BYBIT = "https://api.bybit.com"
ALLOWED = "/bybit/v5/market/"  # пропускаем только публичные рыночные данные


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if not self.path.startswith("/bybit/"):
            return super().do_GET()
        if not self.path.startswith(ALLOWED):
            return self.send_error(403)
        url = BYBIT + self.path[len("/bybit"):]
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "birzha-helper"})
            with urllib.request.urlopen(req, timeout=15) as r:
                body, status = r.read(), r.status
        except urllib.error.HTTPError as e:
            body, status = e.read(), e.code
        except Exception as e:  # сеть недоступна и т.п.
            body, status = f'{{"retCode":-1,"retMsg":"{type(e).__name__}"}}'.encode(), 502
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # не засоряем консоль


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Биржевой помощник: http://localhost:{PORT}  (Ctrl+C — остановить)")
    webbrowser.open(f"http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
