"""Minimal .env file loader (stdlib only)."""
import io
from typing import Dict


def load_env(path):
    # type: (str) -> Dict[str, str]
    result = {}  # type: Dict[str, str]
    try:
        with io.open(path, "r", encoding="utf-8-sig", newline=None) as f:
            lines = f.read().splitlines()
    except (IOError, OSError):
        return result
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            result[key] = value
    return result
