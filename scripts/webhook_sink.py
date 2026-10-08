"""A webhook receiver that verifies Veritium's deliveries (VRT-28) — for local
testing, and as a reference for integrators. Standard library only, and it
deliberately does not import Veritium: it checks the signature the way any
consumer would, from the spec (https://www.standardwebhooks.com).

    WEBHOOK_SECRET=whsec_... python scripts/webhook_sink.py --port 9099
    WEBHOOK_SECRET=whsec_... python scripts/webhook_sink.py --port 9099 --fail-first 2   # force retries

It answers 200 to a valid delivery, 401 to an invalid signature or a stale
timestamp, and deduplicates by ``webhook-id`` (deliveries are at-least-once).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

TOLERANCE_SECONDS = 5 * 60


def verify(secret: str, msg_id: str, timestamp: str, signatures: str, body: bytes) -> bool:
    try:
        if abs(time.time() - int(timestamp)) > TOLERANCE_SECONDS:
            return False
    except ValueError:
        return False
    key = base64.b64decode(secret.removeprefix("whsec_"))
    expected = "v1," + base64.b64encode(hmac.new(key, f"{msg_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()).decode()
    return any(hmac.compare_digest(expected, s) for s in signatures.split())


def make_handler(secret: str, fail_first: int):
    state = {"seen": set(), "failures_left": fail_first}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            body = self.rfile.read(int(self.headers.get("content-length", 0)))
            msg_id = self.headers.get("webhook-id", "")
            ok = verify(secret, msg_id, self.headers.get("webhook-timestamp", ""), self.headers.get("webhook-signature", ""), body)
            if not ok:
                print(f"✗ firma inválida  id={msg_id}", flush=True)
                self.send_response(401)
                self.end_headers()
                return
            if state["failures_left"] > 0:
                state["failures_left"] -= 1
                print(f"↻ fallo forzado (quedan {state['failures_left']})  id={msg_id}", flush=True)
                self.send_response(500)
                self.end_headers()
                return
            event = json.loads(body)
            duplicate = msg_id in state["seen"]
            state["seen"].add(msg_id)
            data = event.get("data", {})
            print(
                f"{'= duplicado' if duplicate else '✓ firma válida'}  {event['type']}  "
                f"case={data.get('case_id')}  ref={data.get('external_ref')}  verdict={data.get('verdict')}  "
                f"(antes={data.get('previous_verdict')})  run={data.get('run_number')}",
                flush=True,
            )
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 — quiet
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=9099)
    parser.add_argument("--fail-first", type=int, default=0, help="responder 500 a las primeras N entregas válidas (para ver los reintentos)")
    args = parser.parse_args()
    secret = os.environ.get("WEBHOOK_SECRET")
    if not secret:
        raise SystemExit("falta WEBHOOK_SECRET (el whsec_… que devolvió POST /v1/webhook-endpoints)")
    print(f"escuchando en http://127.0.0.1:{args.port}", flush=True)
    HTTPServer(("127.0.0.1", args.port), make_handler(secret, args.fail_first)).serve_forever()


if __name__ == "__main__":
    main()
