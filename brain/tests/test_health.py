from fastapi.testclient import TestClient

from destiny_brain.app import create_app
from destiny_brain.config import load_settings


def test_health():
    s = load_settings({"ANTHROPIC_API_KEY": "k", "BRAIN_SHARED_KEY": "s", "DESTINY_PARENT_PIN": "1234"})
    r = TestClient(create_app(s)).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
