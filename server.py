"""로컬 전용 대시보드 서버.

표준 라이브러리 http.server 만 사용. 두 가지만 한다:
  GET /            → dashboard.html
  GET /api/status  → collectors.collect_all() 를 JSON 으로

127.0.0.1 에만 바인딩한다. 외부에서 접근 불가.
"""
import json
import http.server
from pathlib import Path

import collectors

HOST = "127.0.0.1"
PORT = 8787
ROOT = Path(__file__).parent


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = (ROOT / "dashboard.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
        elif self.path == "/api/status":
            try:
                data = collectors.collect_all()
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self._send(200, body, "application/json; charset=utf-8")
            except Exception as e:
                body = json.dumps({"error": str(e)}).encode("utf-8")
                self._send(500, body, "application/json; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, *args):
        # 콘솔을 조용히 유지. 필요하면 이 줄을 지운다.
        pass


def main():
    with http.server.ThreadingHTTPServer((HOST, PORT), Handler) as httpd:
        print(f"agent-dashboard  →  http://{HOST}:{PORT}")
        print("종료하려면 Ctrl+C")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n종료")


if __name__ == "__main__":
    main()
