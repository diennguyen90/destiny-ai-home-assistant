"""Tiny Wyoming protocol client (stdlib only) for smoke-testing Whisper and Piper."""
import json
import socket
from typing import Any, Dict, Optional, Tuple


class WyomingError(Exception):
    pass


def _read_exact(f, n):
    # type: (Any, int) -> bytes
    buf = b""
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            raise WyomingError("Connection closed while reading %d bytes" % n)
        buf += chunk
    return buf


def _send_event(sock, event_type, data=None):
    # type: (socket.socket, str, Optional[Dict[str, Any]]) -> None
    event = {"type": event_type}  # type: Dict[str, Any]
    if data is not None:
        event["data"] = data
    sock.sendall((json.dumps(event) + "\n").encode("utf-8"))


def _read_event(f):
    # type: (Any) -> Tuple[Dict[str, Any], int]
    """Return (event, payload_length) with payload already consumed."""
    line = f.readline()
    if not line:
        raise WyomingError("Connection closed before an event header arrived")
    try:
        event = json.loads(line.decode("utf-8"))
    except ValueError:
        raise WyomingError("Invalid Wyoming header: %r" % line[:80])
    data = event.get("data") or {}
    data_length = event.get("data_length") or 0
    if data_length > 0:
        extra = _read_exact(f, data_length)
        try:
            data.update(json.loads(extra.decode("utf-8")))
        except ValueError:
            raise WyomingError("Invalid Wyoming data block")
    event["data"] = data
    payload_length = event.get("payload_length") or 0
    if payload_length > 0:
        _read_exact(f, payload_length)
    return event, payload_length


def _connect(host, port, timeout):
    # type: (str, int, float) -> socket.socket
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except (socket.timeout, OSError) as e:
        raise WyomingError("Cannot connect to %s:%s (%s)" % (host, port, e))
    sock.settimeout(timeout)
    return sock


def wyoming_describe(host, port, timeout=5.0):
    # type: (str, int, float) -> Dict[str, Any]
    sock = _connect(host, port, timeout)
    try:
        f = sock.makefile("rb")
        try:
            _send_event(sock, "describe")
            while True:
                event, _ = _read_event(f)
                if event.get("type") == "info":
                    return event["data"]
        finally:
            f.close()
    except (socket.timeout, OSError) as e:
        raise WyomingError("Wyoming describe on %s:%s failed (%s)" % (host, port, e))
    finally:
        sock.close()


def piper_synthesize(host, port, text, timeout=30.0):
    # type: (str, int, str, float) -> int
    sock = _connect(host, port, timeout)
    total = 0
    try:
        f = sock.makefile("rb")
        try:
            _send_event(sock, "synthesize", {"text": text})
            while True:
                event, payload_length = _read_event(f)
                kind = event.get("type")
                if kind == "audio-chunk":
                    total += payload_length
                elif kind == "audio-stop":
                    return total
        finally:
            f.close()
    except (socket.timeout, OSError) as e:
        raise WyomingError("Wyoming synthesize on %s:%s failed (%s)" % (host, port, e))
    finally:
        sock.close()
