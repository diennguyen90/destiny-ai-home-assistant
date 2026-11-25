"""Pure-stdlib NDJSON decoding for the Destiny brain stream (no homeassistant imports)."""
from __future__ import annotations

import json
from collections.abc import Iterable, Iterator

LOST_LINE = " Sorry, I lost my train of thought."


class NdjsonDecoder:
    """Incremental NDJSON decoder: feed bytes, get complete event dicts."""

    def __init__(self) -> None:
        self._buf = b""

    @staticmethod
    def _parse(line: bytes) -> dict | None:
        line = line.strip()
        if not line:
            return None
        try:
            obj = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        if isinstance(obj, dict) and isinstance(obj.get("type"), str):
            return obj
        return None

    def feed(self, chunk: bytes) -> list[dict]:
        self._buf += chunk
        *lines, self._buf = self._buf.split(b"\n")
        return [e for e in (self._parse(ln) for ln in lines) if e is not None]

    def flush(self) -> list[dict]:
        rest, self._buf = self._buf, b""
        e = self._parse(rest)
        return [e] if e is not None else []


def parse_ndjson_lines(chunks: Iterable[bytes]) -> Iterator[dict]:
    dec = NdjsonDecoder()
    for chunk in chunks:
        yield from dec.feed(chunk)
    yield from dec.flush()


def has_end(events: Iterable[dict]) -> bool:
    return any(e.get("type") == "end" for e in events)
