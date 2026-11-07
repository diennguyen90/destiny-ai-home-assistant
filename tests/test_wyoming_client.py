import json
import socket
import socketserver
import threading
import time
import unittest

from scripts.wyoming_client import WyomingError, piper_synthesize, wyoming_describe


def _header(obj):
    return (json.dumps(obj) + "\n").encode("utf-8")


class _Server(object):
    """Fake Wyoming server: reads one request line, then runs script(sock)."""

    def __init__(self, script):
        class Handler(socketserver.BaseRequestHandler):
            def handle(inner):
                f = inner.request.makefile("rb")
                try:
                    f.readline()
                    script(inner.request)
                finally:
                    f.close()

        class Srv(socketserver.TCPServer):
            allow_reuse_address = True

        self.srv = Srv(("127.0.0.1", 0), Handler)
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.handle_request, daemon=True)
        self.thread.start()

    def close(self):
        self.thread.join(10)
        self.srv.server_close()


class WyomingClientTests(unittest.TestCase):
    def test_describe_reads_data_length_split_across_writes(self):
        body = json.dumps({"asr": [{"name": "faster-whisper"}]}).encode("utf-8")

        def script(sock):
            sock.sendall(_header({"type": "info", "data_length": len(body)}))
            time.sleep(0.05)
            sock.sendall(body[:5])
            time.sleep(0.05)
            sock.sendall(body[5:])

        s = _Server(script)
        try:
            info = wyoming_describe("127.0.0.1", s.port, timeout=5.0)
        finally:
            s.close()
        self.assertEqual(info["asr"][0]["name"], "faster-whisper")

    def test_synthesize_sums_audio_chunks(self):
        def script(sock):
            sock.sendall(_header({"type": "audio-start", "data": {"rate": 22050}}))
            sock.sendall(_header({"type": "audio-chunk", "payload_length": 100}) + b"a" * 100)
            sock.sendall(_header({"type": "audio-chunk", "payload_length": 50}) + b"b" * 50)
            sock.sendall(_header({"type": "audio-stop"}))

        s = _Server(script)
        try:
            total = piper_synthesize("127.0.0.1", s.port, "hello", timeout=5.0)
        finally:
            s.close()
        self.assertEqual(total, 150)

    def test_connection_refused_raises_wyoming_error(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        with self.assertRaises(WyomingError):
            wyoming_describe("127.0.0.1", port, timeout=2.0)


if __name__ == "__main__":
    unittest.main()
