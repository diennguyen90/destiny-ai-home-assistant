import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from scripts.ha_client import HAError, ha_converse, ha_ping


class _FakeHA(object):
    """Fake HA REST server; handler(path, method, body, headers) -> (status, body_bytes)."""

    def __init__(self, handler):
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def _do(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                outer.requests.append((self.command, self.path, body, dict(self.headers)))
                status, payload = handler(self.path, self.command, body, self.headers)
                self.send_response(status)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = _do
            do_POST = _do

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(5)


def _json(obj):
    return json.dumps(obj).encode("utf-8")


def _reply(speech, rtype="action_done", cid="c1"):
    return _json({"response": {"response_type": rtype,
                               "speech": {"plain": {"speech": speech}}},
                  "conversation_id": cid})


class HAClientTests(unittest.TestCase):
    def test_ping_returns_message(self):
        s = _FakeHA(lambda p, m, b, h: (200, _json({"message": "API running."})))
        try:
            msg = ha_ping(s.url + "/", "tok")
        finally:
            s.close()
        self.assertEqual(msg, "API running.")
        self.assertEqual(s.requests[0][1], "/api/")
        self.assertEqual(s.requests[0][3]["Authorization"], "Bearer tok")

    def test_converse_sends_conversation_id_and_parses_speech(self):
        s = _FakeHA(lambda p, m, b, h: (200, _reply("Sunny.")))
        try:
            r1 = ha_converse(s.url, "tok", "weather?")
            r2 = ha_converse(s.url, "tok", "and tomorrow?", conversation_id="c1",
                             agent_id="conversation.claude")
        finally:
            s.close()
        self.assertEqual(r1, ("Sunny.", "c1"))
        self.assertEqual(r2, ("Sunny.", "c1"))
        b1 = json.loads(s.requests[0][2].decode("utf-8"))
        b2 = json.loads(s.requests[1][2].decode("utf-8"))
        self.assertNotIn("conversation_id", b1)
        self.assertNotIn("agent_id", b1)
        self.assertEqual(b1["language"], "en")
        self.assertEqual(b2["conversation_id"], "c1")
        self.assertEqual(b2["agent_id"], "conversation.claude")
        self.assertEqual(s.requests[0][3]["Content-Type"], "application/json")

    def test_401_raises_token_message(self):
        s = _FakeHA(lambda p, m, b, h: (401, b"Unauthorized"))
        try:
            with self.assertRaises(HAError) as cm:
                ha_ping(s.url, "bogus")
        finally:
            s.close()
        self.assertIn("401", str(cm.exception))
        self.assertIn("long-lived token", str(cm.exception))

    def test_error_response_type_raises_with_speech(self):
        s = _FakeHA(lambda p, m, b, h: (200, _reply("No agent", rtype="error")))
        try:
            with self.assertRaises(HAError) as cm:
                ha_converse(s.url, "tok", "hi")
        finally:
            s.close()
        self.assertIn("No agent", str(cm.exception))

    def test_http_500_raises_ha_error(self):
        s = _FakeHA(lambda p, m, b, h: (500, b"boom"))
        try:
            with self.assertRaises(HAError) as cm:
                ha_converse(s.url, "tok", "hi")
        finally:
            s.close()
        self.assertIn("500", str(cm.exception))

    def test_non_json_body_raises_ha_error(self):
        s = _FakeHA(lambda p, m, b, h: (200, b"<html>onboarding</html>"))
        try:
            with self.assertRaises(HAError):
                ha_ping(s.url, "tok")
        finally:
            s.close()

    def test_timeout_raises_ha_error(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)  # accepts at the OS level but never replies
        try:
            with self.assertRaises(HAError) as cm:
                ha_ping("http://127.0.0.1:%d" % srv.getsockname()[1], "tok", timeout=0.3)
        finally:
            srv.close()
        self.assertIn("timed out", str(cm.exception))

    def test_connection_refused_raises_ha_error(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        with self.assertRaises(HAError) as cm:
            ha_ping("http://127.0.0.1:%d" % port, "tok", timeout=10.0)
        self.assertIn("Cannot reach", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
