"""Kite OAuth redirect-capture helper.

Kite Connect logs the user in on Zerodha's hosted page, then redirects the
browser to the app's registered redirect URL with a one-time ``request_token``
appended.  This module runs a tiny localhost HTTP server bound to that redirect
URL's host:port, opens the system browser at the login page, and blocks until
the redirect arrives — returning the captured ``request_token``.

Pure standard-library (no Qt).  ``capture_request_token`` BLOCKS, so call it from
a worker thread, never the Qt main thread.

The registered redirect URL in the Kite developer console must match the host
and port used here (default ``http://127.0.0.1:5010/``).
"""

from __future__ import annotations

import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5010

_SUCCESS_HTML = (
    b"<!doctype html><html><head><meta charset='utf-8'>"
    b"<title>DemonEdge</title></head>"
    b"<body style='font-family:sans-serif;background:#0d1117;color:#e6edf3;"
    b"text-align:center;padding-top:80px'>"
    b"<h2>&#10003; Login complete</h2>"
    b"<p>You can close this tab and return to DemonEdge.</p></body></html>"
)

_FAIL_HTML = (
    b"<!doctype html><html><head><meta charset='utf-8'>"
    b"<title>DemonEdge</title></head>"
    b"<body style='font-family:sans-serif;background:#0d1117;color:#f85149;"
    b"text-align:center;padding-top:80px'>"
    b"<h2>Login failed</h2>"
    b"<p>Return to DemonEdge and try again.</p></body></html>"
)


class KiteAuthError(Exception):
    """Raised when the request_token could not be captured."""


def capture_request_token(
    login_url: str,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 180.0,
) -> str:
    """Open *login_url* in the browser and capture the redirected request_token.

    Blocks until the redirect is received or *timeout* seconds elapse.
    Raises :class:`KiteAuthError` on timeout, denial, or bind failure.
    """
    result: dict[str, str | None] = {"token": None, "error": None}
    done = threading.Event()

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            token = (params.get("request_token") or [None])[0]
            status = (params.get("status") or [None])[0]

            if token:
                result["token"] = token
                self._reply(_SUCCESS_HTML)
                done.set()
            elif status or "request_token" in params:
                # Redirect arrived but login was not successful.
                result["error"] = "Kite login failed or was denied."
                self._reply(_FAIL_HTML)
                done.set()
            else:
                # Stray request (e.g. /favicon.ico) — ignore, keep waiting.
                self._reply(b"<html><body>Waiting for Kite login...</body></html>")

        def _reply(self, body: bytes) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass

        def log_message(self, *args) -> None:  # silence default stderr logging
            pass

    try:
        server = HTTPServer((host, port), _Handler)
    except OSError as exc:
        raise KiteAuthError(
            f"Could not start the login capture server on {host}:{port} "
            f"(is it already in use?): {exc}"
        ) from exc

    thread = threading.Thread(target=server.serve_forever, name="kite-auth", daemon=True)
    thread.start()
    logger.info("Kite auth: capture server listening on http://%s:%d/", host, port)

    try:
        webbrowser.open(login_url)
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("Kite auth: could not open browser automatically: %s", exc)

    captured = done.wait(timeout)

    server.shutdown()
    server.server_close()

    if not captured:
        raise KiteAuthError(
            "Timed out waiting for the Kite login redirect. "
            "Check that your Kite app's redirect URL is "
            f"http://{host}:{port}/"
        )
    if result["error"]:
        raise KiteAuthError(str(result["error"]))
    return str(result["token"])
