"""A small web page for watching Kimi from a browser.

* Served by Python's standard library on **127.0.0.1 only**, so nothing
  outside this PC can reach it directly. To see Kimi from your phone
  anywhere, put Tailscale's free ``tailscale serve`` in front of it (see
  ``docs/REMOTE_ACCESS.md``); that keeps it private to your own devices.
* Every data request needs the passcode you set in Settings, sent as an
  ``Authorization: Bearer`` header (no cookies, so other websites can't make
  requests on your behalf). The passcode lives in Windows Credential Manager.
  Repeated wrong passcodes lock the page for a while.
* The page shows Kimi and lets you reply to Kimi's requests. It cannot
  change settings, run anything, or reveal the API key (which isn't in
  Kimi's data at all).
"""

from __future__ import annotations

import hmac
import json
import logging
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any, Callable

from .. import credentials
from ..world import layout3d
from ..world.curio3d import curiosity_layout
from ..world.curiosities import BY_ID as CURIOSITIES
from ..world.mesh3d import pond_centre

log = logging.getLogger("kimi.web")

STATIC = {
    "/": ("page.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
}
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Content-Security-Policy": ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                                "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
}
MAX_BODY = 4096
FAIL_LIMIT = 5            # wrong passcodes allowed before a lockout
LOCK_BASE_S = 60.0        # first lockout; doubles each time, up to an hour
PASSCODE_CACHE_S = 30.0


def _static(name: str) -> bytes:
    return resources.files(__package__).joinpath(name).read_bytes()


class _Guard:
    """Wrong-passcode counting and lockouts, per client address."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._lock = threading.Lock()
        self._fails: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}
        self._lockouts: dict[str, int] = {}

    def locked_for(self, who: str) -> float:
        with self._lock:
            return max(0.0, self._locked_until.get(who, 0.0) - self.clock())

    def failed(self, who: str) -> None:
        with self._lock:
            n = self._fails.get(who, 0) + 1
            self._fails[who] = n
            if n >= FAIL_LIMIT:
                k = self._lockouts.get(who, 0)
                self._locked_until[who] = self.clock() + min(3600.0, LOCK_BASE_S * (2 ** k))
                self._lockouts[who] = k + 1
                self._fails[who] = 0
                log.warning("Web page locked after repeated wrong passcodes")

    def succeeded(self, who: str) -> None:
        with self._lock:
            self._fails.pop(who, None)
            self._lockouts.pop(who, None)


def _norm_layout() -> dict:
    """Static map data in world coordinates (the page scales it to fit)."""
    px, pz = pond_centre()
    return {
        "places": [{"id": p.id, "name": p.name, "x": p.x, "z": p.z} for p in layout3d.PLACES.values()],
        "paths": [[[round(x, 1), round(z, 1)] for x, z in line] for line in layout3d.path_polylines(24)],
        "curiosities": [{"id": c["id"], "name": c["name"], "x": round(c["x"], 1), "z": round(c["z"], 1),
                         "zone": c["zone"]} for c in curiosity_layout()],
        "pond": {"x": px, "z": pz, "r": 95.0},
        "square": {"x": layout3d.PLACES["square"].x, "z": layout3d.PLACES["square"].z, "r": layout3d.SQUARE_RADIUS},
        "islandRadius": layout3d.ISLAND_RADIUS,
        "townRadius": layout3d.TOWN_RADIUS,
    }


class KimiWebServer:
    """Serve Kimi's web page on 127.0.0.1:<port> in a background thread."""

    def __init__(self, runtime, port: int, passcode_provider: Callable[[], str | None] | None = None,
                 host: str = "127.0.0.1", clock: Callable[[], float] = time.monotonic) -> None:
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("Kimi's web page only listens on this PC (127.0.0.1)")
        self.rt = runtime
        self.host = host
        self.port = port
        self._provider = passcode_provider or credentials.load_web_passcode
        self._passcode: str | None = None
        self._passcode_at = -1e9
        self.clock = clock
        self.guard = _Guard(clock)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._layout = _norm_layout()

    # -- lifecycle ---------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def start(self) -> None:
        if self._httpd is not None:
            return
        handler = type("KimiHandler", (_Handler,), {"app": self})
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="kimi-web", daemon=True)
        self._thread.start()
        log.info("Web page running at %s", self.url)

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        log.info("Web page stopped")

    # -- passcode ---------------------------------------------------------------------
    def refresh_passcode(self) -> None:
        self._passcode_at = -1e9

    def passcode(self) -> str | None:
        if self.clock() - self._passcode_at > PASSCODE_CACHE_S:
            try:
                self._passcode = self._provider()
            except Exception:  # noqa: BLE001 - a broken store just means "locked"
                self._passcode = None
            self._passcode_at = self.clock()
        return self._passcode

    # -- data ---------------------------------------------------------------------------
    def state(self) -> dict:
        rt = self.rt
        snap = rt.snapshot()
        target = layout3d.kimi_target(rt.pose())
        thought = snap.get("thought") or {}
        cid = snap.get("curiosity")
        req = snap.get("request")
        return {
            "day": snap["day"], "clock": snap["clock"], "hour": snap["hour"], "timeOfDay": snap["time_of_day"],
            "light": snap["light"], "weather": snap["weather"], "temperature": snap.get("temperature"),
            "status": snap["status_text"], "place": snap["place_name"], "location": snap["location"],
            "activity": snap["activity"], "asleep": snap["asleep"], "mood": snap.get("mood"),
            "thinking": snap["thinking"], "needs": snap["needs"], "needLabels": snap["need_labels"],
            "thought": {"text": thought.get("text", ""), "clock": thought.get("clock"), "day": thought.get("day")},
            "kimi": {"x": round(target["x"], 1), "z": round(target["z"], 1), "moving": target["moving"]},
            "curiosity": CURIOSITIES[cid].name if cid in CURIOSITIES else None,
            "curiositiesSeen": snap.get("curiosities_seen") or [],
            "request": _request_view(req) if req else None,
            "spentToday": round(float(snap.get("spent_today") or 0), 4), "budget": snap.get("budget"),
        }

    def feed(self) -> dict:
        rt = self.rt
        events = [e for e in list(rt.recent_events) if e["kind"] not in ("time", "thinking")][-15:]
        diary = [{"title": e.title, "body": e.body[:700], "day": e.day, "clock": e.clock, "kind": e.kind}
                 for e in rt.diary.list(limit=3, chronological=False)]
        board = [{"author": r["author"], "body": r["body"][:300]} for r in rt.db.query(
            "SELECT author, body FROM board_messages ORDER BY id DESC LIMIT 5")]
        visits = sorted(rt.curiosity_visits().values(), key=lambda v: -v["last_seen"])
        found = [{"name": CURIOSITIES[v["curiosity"]].name, "visits": v["visits"], "detail": v["last_detail"]}
                 for v in visits[:8] if v["curiosity"] in CURIOSITIES]
        return {
            "events": [{"clock": e["clock"], "day": e["day"], "kind": e["kind"], "text": e["text"]} for e in reversed(events)],
            "diary": diary,
            "board": board,
            "curiosities": {"seen": len(visits), "total": len(CURIOSITIES), "recent": found},
            "requests": [_request_view(r) for r in rt.requests.recent(5)],
        }

    def layout(self) -> dict:
        return self._layout


def _request_view(r: dict) -> dict:
    return {"id": r["id"], "kind": r["kind"], "title": r["title"], "body": r["body"], "status": r["status"],
            "reply": r.get("reply"), "day": r.get("sim_day")}


_REQ_PATH = re.compile(r"^/api/requests/(\d{1,9})$")


class _Handler(BaseHTTPRequestHandler):
    app: KimiWebServer
    server_version = "Kimi"
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet; never log headers (they carry the passcode)
        log.debug("web %s %s", self.command, self.path.split("?")[0])

    # -- helpers ------------------------------------------------------------------------
    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in {**SECURITY_HEADERS, **(extra or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, data: Any, extra: dict | None = None) -> None:
        self._send(status, json.dumps(data, default=str).encode("utf-8"), "application/json; charset=utf-8", extra)

    def _authorised(self) -> bool:
        who = self.client_address[0]
        wait = self.app.guard.locked_for(who)
        if wait > 0:
            self._json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "locked", "retryAfter": int(wait) + 1},
                       {"Retry-After": str(int(wait) + 1)})
            return False
        expected = self.app.passcode()
        if not expected:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "no_passcode"})
            return False
        header = self.headers.get("Authorization", "")
        given = header[7:] if header.startswith("Bearer ") else ""
        if not hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
            self.app.guard.failed(who)
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "wrong_passcode"})
            return False
        self.app.guard.succeeded(who)
        return True

    # -- routes ---------------------------------------------------------------------------
    def do_HEAD(self) -> None:  # noqa: N802 - http.server naming
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in STATIC:
            name, ctype = STATIC[path]
            self._send(HTTPStatus.OK, _static(name), ctype)
            return
        if path == "/api/hello":
            self._json(HTTPStatus.OK, {"passcodeSet": bool(self.app.passcode())})
            return
        if path in ("/api/state", "/api/feed", "/api/layout"):
            if not self._authorised():
                return
            try:
                data = {"/api/state": self.app.state, "/api/feed": self.app.feed, "/api/layout": self.app.layout}[path]()
            except Exception:  # noqa: BLE001
                log.exception("Web page data failed")
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "unavailable"})
                return
            self._json(HTTPStatus.OK, data)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        m = _REQ_PATH.match(self.path)
        if not m:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._authorised():
            return
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "json_only"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "too_large"})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            action = str(body.get("action", ""))
            text = str(body.get("text", ""))[:1500]
        except (ValueError, AttributeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "bad_json"})
            return
        if action not in ("answer", "wishlist", "decline"):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "bad_action"})
            return
        ok, message = self.app.rt.answer_request(int(m.group(1)), action, text)
        self._json(HTTPStatus.OK if ok else HTTPStatus.CONFLICT, {"ok": ok, "message": message})

    def do_PUT(self) -> None:  # noqa: N802
        self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method"})

    do_DELETE = do_PATCH = do_PUT  # noqa: N815
