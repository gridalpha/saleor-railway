"""A health endpoint for the two Saleor roles that serve no HTTP.

Railway can only health-check an HTTP port, and Celery exposes none — so a worker that
has wedged, or a scheduler that has stopped ticking, reports SUCCESS forever. This
serves ``/health/`` beside them and answers from a real probe of the process it lives
with:

  * ``worker`` — a Celery control ping addressed to *this container's* node name, so a
    sibling replica answering does not mask a dead one.
  * ``beat`` — the newest ``last_run_at`` across the enabled periodic tasks. Saleor
    schedules work every 20-30 seconds and django-celery-beat flushes that column on its
    own sync interval, so a stalled scheduler shows up as a stale maximum.

Both modes stay healthy for ``HEALTHD_GRACE_SECONDS`` after start: the first boot of a
project has to wait out migrations before either signal can exist.

Run it in the background; the role's own process stays in the foreground so that its
death still exits the container.
"""

import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODE = os.environ.get("HEALTHD_MODE", "worker")
PORT = int(os.environ.get("PORT", "8080"))
PATH = os.environ.get("HEALTHD_PATH", "/health/")
GRACE_SECONDS = int(os.environ.get("HEALTHD_GRACE_SECONDS", "900"))
CHECK_INTERVAL = int(os.environ.get("HEALTHD_CHECK_INTERVAL", "30"))
STALE_AFTER_SECONDS = int(os.environ.get("HEALTHD_STALE_AFTER_SECONDS", "900"))
PING_TIMEOUT = int(os.environ.get("HEALTHD_PING_TIMEOUT", "15"))

STARTED_AT = time.monotonic()
_state = {"ok": True, "detail": "starting"}
_lock = threading.Lock()


def log(message: str) -> None:
    print(f"healthd[{MODE}]: {message}", file=sys.stderr, flush=True)


def check_worker() -> tuple[bool, str]:
    from celery import Celery

    broker = os.environ.get("CELERY_BROKER_URL")
    if not broker:
        return False, "CELERY_BROKER_URL is not set"
    node = os.environ.get("HEALTHD_CELERY_NODE") or f"celery@{socket.gethostname()}"
    app = Celery(broker=broker)
    try:
        replies = app.control.ping(destination=[node], timeout=PING_TIMEOUT) or []
    finally:
        app.close()
    if replies:
        return True, f"{node} replied to ping"
    return False, f"{node} did not reply within {PING_TIMEOUT}s"


def check_beat() -> tuple[bool, str]:
    import psycopg

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return False, "DATABASE_URL is not set"
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        row = conn.execute(
            "SELECT EXTRACT(EPOCH FROM (now() - max(last_run_at))) "
            "FROM django_celery_beat_periodictask WHERE enabled"
        ).fetchone()
    age = row[0] if row else None
    if age is None:
        return False, "no periodic task has run yet"
    if age <= STALE_AFTER_SECONDS:
        return True, f"last scheduled run {int(age)}s ago"
    return False, f"last scheduled run {int(age)}s ago, over {STALE_AFTER_SECONDS}s"


CHECKS = {"worker": check_worker, "beat": check_beat}


def poll_forever() -> None:
    check = CHECKS[MODE]
    while True:
        try:
            ok, detail = check()
        except Exception as exc:  # noqa: BLE001 — a failing probe is an unhealthy probe
            ok, detail = False, f"probe raised {type(exc).__name__}: {exc}"
        if not ok and time.monotonic() - STARTED_AT < GRACE_SECONDS:
            ok, detail = True, f"within startup grace ({detail})"
        with _lock:
            previous = _state["ok"]
            _state.update(ok=ok, detail=detail)
        if ok != previous:
            log(detail)
        time.sleep(CHECK_INTERVAL)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's naming
        if self.path.split("?", 1)[0] != PATH:
            self.send_error(404)
            return
        with _lock:
            ok, detail = _state["ok"], _state["detail"]
        body = f"{'ok' if ok else 'unhealthy'}: {detail}\n".encode()
        self.send_response(200 if ok else 503)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        """Silence per-request logging; Railway probes this every few seconds."""


def main() -> None:
    if MODE not in CHECKS:
        log(f"unknown HEALTHD_MODE {MODE!r}, expected one of {sorted(CHECKS)}")
        raise SystemExit(2)
    threading.Thread(target=poll_forever, daemon=True).start()
    # Dual-stack: Railway's prober arrives over IPv4, private callers over IPv6.
    ThreadingHTTPServer.address_family = socket.AF_INET6
    server = ThreadingHTTPServer(("::", PORT), Handler)
    log(f"serving {PATH} on port {PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
