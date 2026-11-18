import importlib.util
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

_spec = importlib.util.spec_from_file_location("brain_client", "/connector/brain_client.py")
brain_client = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brain_client)

OK = {"speech": "hi there", "conversation_id": "c1", "continue_conversation": True}


def _serve(handler_fn):
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            seen["body"] = json.loads(self.rfile.read(n))
            seen["key"] = self.headers.get("X-Destiny-Key")
            handler_fn(self)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen, f"http://127.0.0.1:{srv.server_port}"


def _ok(h):
    data = json.dumps(OK).encode()
    h.send_response(200)
    h.send_header("Content-Type", "application/json")
    h.send_header("Content-Length", str(len(data)))
    h.end_headers()
    h.wfile.write(data)


@pytest.fixture
def stub():
    made = []

    def make(fn):
        s = _serve(fn)
        made.append(s[0])
        return s

    yield make
    for s in made:
        s.shutdown()
        s.server_close()


def test_ok_roundtrip(stub):
    _, seen, url = stub(_ok)
    out = brain_client.converse(url, "k", {"text": "héllo 🌟"})
    assert out == OK
    assert seen["body"]["text"] == "héllo 🌟"


def test_sends_key_header(stub):
    _, seen, url = stub(_ok)
    brain_client.converse(url, "secret", {"text": "x"})
    assert seen["key"] == "secret"


def test_timeout_returns_nap_line(stub):
    def slow(h):
        time.sleep(2)
        try:
            _ok(h)
        except OSError:
            pass

    _, _, url = stub(slow)
    start = time.monotonic()
    out = brain_client.converse(url, "k", {"text": "x", "conversation_id": "c9"}, timeout=0.5)
    assert time.monotonic() - start < 1.5
    assert out == {
        "speech": brain_client.NAP_LINE,
        "conversation_id": "c9",
        "continue_conversation": False,
    }


def test_connection_refused_returns_nap_line():
    out = brain_client.converse("http://127.0.0.1:1", "k", {"text": "x"}, timeout=1)
    assert out["speech"] == "My brain is taking a nap. Try again in a minute."
    assert out["conversation_id"] is None
    assert out["continue_conversation"] is False


def test_non_200_returns_nap_line(stub):
    def bad(h):
        h.send_response(401)
        h.send_header("Content-Length", "0")
        h.end_headers()

    _, _, url = stub(bad)
    out = brain_client.converse(url, "k", {"text": "x"})
    assert out["speech"] == brain_client.NAP_LINE
