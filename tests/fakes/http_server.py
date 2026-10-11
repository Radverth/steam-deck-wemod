"""Tiny local HTTP server for download tests (no internet in tests).

``server.add(path, body)`` serves bytes, ``server.redirect(path, to)`` a
302, ``server.fail(path, status)`` an error. ``Range: bytes=a-b`` is
honoured (used by install.sh's 1-byte existence probe). Every request path
is recorded in ``server.requests``.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeServer:
    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, dict, bytes]] = {}
        self.requests: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server API
                outer.requests.append(self.path)
                status, headers, body = outer.routes.get(
                    self.path.split("?")[0], (404, {}, b"not found")
                )
                rng = self.headers.get("Range")
                if status == 200 and rng and rng.startswith("bytes="):
                    start_s, _, end_s = rng[6:].partition("-")
                    start = int(start_s or 0)
                    end = int(end_s) if end_s else len(body) - 1
                    part = body[start : end + 1]
                    self.send_response(206)
                    self.send_header(
                        "Content-Range", f"bytes {start}-{end}/{len(body)}"
                    )
                    body = part
                else:
                    self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def url(self, path: str) -> str:
        return self.base + path

    def add(self, path: str, body: bytes | str | dict | list) -> str:
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode()
        self.routes[path] = (200, {}, body)
        return self.url(path)

    def redirect(self, path: str, to: str) -> None:
        self.routes[path] = (302, {"Location": to}, b"")

    def fail(self, path: str, status: int = 500) -> None:
        self.routes[path] = (status, {}, b"error")

    def __enter__(self) -> FakeServer:
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
