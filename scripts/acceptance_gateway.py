from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import http.client
from pathlib import Path


DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


class Gateway(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def do_GET(self) -> None:
        if self.path.startswith("/api/") or self.path.startswith("/acceptance/"):
            self._proxy()
        else:
            if self.path != "/" and not (DIST / self.path.lstrip("/")).is_file():
                self.path = "/index.html"
            super().do_GET()

    def do_POST(self) -> None:
        self._proxy()

    def _proxy(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length) if length else None
        connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=10)
        headers = {"content-type": self.headers.get("content-type", "application/json")}
        connection.request(self.command, self.path, body=body, headers=headers)
        response = connection.getresponse()
        payload = response.read()
        self.send_response(response.status)
        self.send_header("content-type", response.getheader("content-type", "application/json"))
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


ThreadingHTTPServer(("127.0.0.1", 5173), Gateway).serve_forever()
