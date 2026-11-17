import logging
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from destiny_brain.app import create_app
from destiny_brain.config import load_settings
from destiny_brain.costs import Usage
from destiny_brain.deps import Deps
from destiny_brain.engine import ConverseResponse
from destiny_brain.store import RequestRecord, Store

KEY = "shared-key-xyz"
PIN = "482913"


class FakeEngine:
    def __init__(self):
        self.reqs = []

    def handle(self, req):
        self.reqs.append(req)
        return ConverseResponse(speech="Hi <there>", conversation_id="c1", continue_conversation=True)


def make(tmp_path):
    s = load_settings({"ANTHROPIC_API_KEY": "k", "BRAIN_SHARED_KEY": KEY, "DESTINY_PARENT_PIN": PIN,
                       "DESTINY_DB_PATH": str(tmp_path / "b.db")})
    store = Store(s.db_path, s.tz)
    store.init()
    store.log(RequestRecord(ts_utc=datetime.now(UTC), conversation_id="c", device_id="d", tier=1,
                            model="claude-haiku-5-5", route_reason="<b>rule</b>", usage=Usage(10, 5),
                            cost_usd=0.1234, latency_ms=321, outcome="ok", text_chars=5))
    eng = FakeEngine()
    return TestClient(create_app(s, Deps(engine=eng, store=store))), eng


def test_converse_requires_key(tmp_path):
    c, eng = make(tmp_path)
    assert c.post("/v1/converse", json={"text": "hi"}).status_code == 401
    assert c.post("/v1/converse", json={"text": "hi"}, headers={"X-Destiny-Key": "nope"}).status_code == 401
    assert eng.reqs == []


def test_converse_ok(tmp_path):
    c, eng = make(tmp_path)
    r = c.post("/v1/converse", json={"text": "hi", "device_id": "d1"}, headers={"X-Destiny-Key": KEY})
    assert r.status_code == 200
    assert r.json() == {"speech": "Hi <there>", "conversation_id": "c1", "continue_conversation": True}
    assert eng.reqs[0].text == "hi" and eng.reqs[0].device_id == "d1"


def test_parent_requires_pin(tmp_path):
    c, _ = make(tmp_path)
    r = c.get("/parent")
    assert r.status_code == 200
    assert 'name="pin"' in r.text
    assert "0.1234" not in r.text and "claude-haiku" not in r.text


def test_parent_login_wrong_pin_401(tmp_path):
    c, _ = make(tmp_path)
    r = c.post("/parent/login", data={"pin": "0000"}, follow_redirects=False)
    assert r.status_code == 401
    assert 'name="pin"' in r.text
    assert "0.1234" not in c.get("/parent").text


def test_parent_login_then_page_shows_spend(tmp_path):
    c, _ = make(tmp_path)
    r = c.post("/parent/login", data={"pin": PIN}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/parent"
    assert "httponly" in r.headers["set-cookie"].lower()
    page = c.get("/parent")
    assert "0.1234" in page.text and "claude-haiku-5-5" in page.text
    assert "&lt;b&gt;rule&lt;/b&gt;" in page.text and "<b>rule</b>" not in page.text
    assert "1.00" in page.text and "3.00" in page.text


def test_pin_not_in_logs(tmp_path, caplog):
    c, _ = make(tmp_path)
    with caplog.at_level(logging.DEBUG):
        c.post("/parent/login", data={"pin": "998877"})
        c.post("/parent/login", data={"pin": PIN})
    assert "998877" not in caplog.text and PIN not in caplog.text
