"""Kimi's web page: local-only, passcode-protected, view plus replies to Kimi's requests."""

from __future__ import annotations

import http.client
import json

import pytest

from kimi import credentials
from kimi.web.server import FAIL_LIMIT, KimiWebServer

from .conftest import FakeClock

PASS = "lantern-moss-42"


class Client:
    def __init__(self, server: KimiWebServer) -> None:
        self.server = server

    def request(self, method, path, passcode=None, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        h = dict(headers or {})
        if passcode is not None:
            h["Authorization"] = f"Bearer {passcode}"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=h)
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        return r.status, dict(r.getheaders()), raw


@pytest.fixture
def web(make_runtime):
    rt = make_runtime()
    clock = FakeClock(100.0)
    state = {"passcode": PASS}
    server = KimiWebServer(rt, 0, passcode_provider=lambda: state["passcode"], clock=clock)
    server.start()
    yield rt, server, Client(server), state, clock
    server.stop()


def test_only_listens_on_this_pc(make_runtime):
    rt = make_runtime()
    with pytest.raises(ValueError):
        KimiWebServer(rt, 0, host="0.0.0.0")


def test_static_page_has_no_data_and_strict_headers(web):
    _, server, c, _, _ = web
    status, headers, body = c.request("GET", "/")
    assert status == 200 and b"<canvas" in body and b"Kimi" in body
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "DENY" and headers["Cache-Control"] == "no-store"
    for path in ("/app.js", "/app.css"):
        assert c.request("GET", path)[0] == 200
    assert c.request("GET", "/../kimi.db")[0] == 404
    assert c.request("GET", "/api/hello")[2] == b'{"passcodeSet": true}'


def test_data_needs_the_passcode(web):
    _, _, c, _, _ = web
    assert c.request("GET", "/api/state")[0] == 401
    assert c.request("GET", "/api/state", "wrong-passcode")[0] == 401
    status, _, body = c.request("GET", "/api/state", PASS)
    assert status == 200
    data = json.loads(body)
    assert {"day", "clock", "kimi", "needs", "thought", "status"} <= set(data)
    assert "sk-ant" not in body.decode()


def test_layout_and_feed(web):
    rt, _, c, _, _ = web
    lay = json.loads(c.request("GET", "/api/layout", PASS)[2])
    assert len(lay["places"]) == 7 and len(lay["curiosities"]) >= 60 and lay["paths"]
    rt.record_curiosity_visit("tiny_door", "The knob is warm.")
    feed = json.loads(c.request("GET", "/api/feed", PASS)[2])
    assert feed["curiosities"]["seen"] == 1 and feed["curiosities"]["recent"][0]["name"] == "The Tiny Green Door"
    assert isinstance(feed["events"], list) and isinstance(feed["diary"], list)


def test_no_passcode_means_locked(web):
    _, _, c, state, clock = web
    state["passcode"] = None
    clock.advance(60)                      # passcode cache expires
    assert c.request("GET", "/api/state", PASS)[0] == 503
    assert json.loads(c.request("GET", "/api/hello")[2]) == {"passcodeSet": False}


def test_repeated_wrong_passcodes_lock_the_page(web):
    _, _, c, _, clock = web
    for _ in range(FAIL_LIMIT):
        assert c.request("GET", "/api/state", "guess-guess")[0] == 401
    status, headers, _ = c.request("GET", "/api/state", PASS)
    assert status == 429 and int(headers["Retry-After"]) > 0      # even the right one waits
    clock.advance(61)
    assert c.request("GET", "/api/state", PASS)[0] == 200


def test_answering_a_request_from_the_web(web):
    rt, _, c, _, _ = web
    rid = rt.requests.create("information", "The sea", "What is the sea like?", 1, "nest")
    state = json.loads(c.request("GET", "/api/state", PASS)[2])
    assert state["request"]["id"] == rid
    assert c.request("POST", f"/api/requests/{rid}", None, {"action": "answer", "text": "Salty!"})[0] == 401
    assert c.request("POST", f"/api/requests/{rid}", PASS, {"action": "explode"})[0] == 400
    assert c.request("POST", f"/api/requests/{rid}", PASS, {"action": "answer", "text": "x"},
                     headers={"Content-Type": "text/plain"})[0] == 415
    status, _, body = c.request("POST", f"/api/requests/{rid}", PASS,
                                {"action": "answer", "text": "Like the lake, but endless and salty."})
    assert status == 200 and json.loads(body)["ok"]
    assert rt.requests.get(rid)["status"] == "answered"
    assert c.request("POST", f"/api/requests/{rid}", PASS, {"action": "answer", "text": "again"})[0] == 409
    assert c.request("POST", "/api/settings", PASS, {"web_enabled": False})[0] == 404
    assert c.request("PUT", "/api/state", PASS)[0] == 405


def test_oversized_bodies_are_refused(web):
    rt, _, c, _, _ = web
    rid = rt.requests.create("information", "Owls", "How do owls see at night?", 1, "nest")
    status, _, _ = c.request("POST", f"/api/requests/{rid}", PASS, {"action": "answer", "text": "x" * 6000})
    assert status == 413


def test_runtime_starts_and_stops_the_server(make_runtime):
    rt = make_runtime()
    rt.update_settings(web_enabled=True, web_port=58765)
    rt._thread = object()        # behave as if the world thread were running
    rt.apply_web_settings()
    try:
        running, url, problem = rt.web_status()
        assert running and url.startswith("http://127.0.0.1:58765") and not problem
        rt.update_settings(web_enabled=False)
        assert rt.web_status()[0] is False
    finally:
        if rt.web:
            rt.web.stop()
            rt.web = None
        rt._thread = None


def test_passcode_is_kept_in_secure_storage(secure_keyring):
    with pytest.raises(ValueError):
        credentials.save_web_passcode("short")
    credentials.save_web_passcode(PASS)
    assert credentials.load_web_passcode() == PASS
    assert secure_keyring.store[(credentials.SERVICE_NAME, credentials.WEB_ACCOUNT_NAME)] == PASS
    assert credentials.delete_web_passcode() is True
    assert credentials.load_web_passcode() is None
