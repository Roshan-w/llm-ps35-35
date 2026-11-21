"""POST /api/compare  ->  newline-delimited JSON stream: sources, tokens, then done (or error)."""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))
from _core import LLMError, UserError, build_prompt, stream_answer, validate, LLM_MODEL  # noqa: E402

MAX_BODY = 1_600_000


class handler(BaseHTTPRequestHandler):
    def _send(self, obj):
        self.wfile.write((json.dumps(obj) + "\n").encode())
        self.wfile.flush()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._fail(413, "The PDFs are too large for the online demo.")
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            docs, question, k = validate(payload)
            prompt, sources = build_prompt(docs, question, k)
        except UserError as e:
            return self._fail(400, str(e))
        except ValueError:
            return self._fail(400, "Invalid request.")

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        start = time.time()
        self._send({"type": "meta", "question": question, "model": LLM_MODEL, "sources": sources})
        try:
            for piece in stream_answer(prompt):
                self._send({"type": "token", "t": piece})
            self._send({"type": "done", "seconds": round(time.time() - start, 1)})
        except LLMError as e:
            self._send({"type": "error", "message": str(e)})
        except Exception:  # noqa: BLE001
            self._send({"type": "error", "message": "Something went wrong while generating the answer."})

    def _fail(self, code, message):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"type": "error", "message": message}).encode())

    def log_message(self, *args):  # keep request bodies out of logs
        pass
