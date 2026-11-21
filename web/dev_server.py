"""Local preview of the Vercel site: python web/dev_server.py  ->  http://localhost:3000"""
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "api"))
import compare  # noqa: E402
import health  # noqa: E402


class Dev(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def do_GET(self):
        if self.path.startswith("/api/health"):
            return health.handler.do_GET(self)
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/compare"):
            return compare.handler.do_POST(self)
        self.send_error(404)

    _send = compare.handler._send
    _fail = compare.handler._fail


if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    print(f"Serving on http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Dev).serve_forever()
