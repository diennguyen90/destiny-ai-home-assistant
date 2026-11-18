"""Pure-stdlib HTTP client for the Destiny brain (no homeassistant imports)."""
from __future__ import annotations

import json
import urllib.request

NAP_LINE = "My brain is taking a nap. Try again in a minute."


def converse(url: str, key: str, payload: dict, timeout: float = 15.0) -> dict:
    """POST payload to the brain; never raises. Blocking: run in an executor."""
    nap = {
        "speech": NAP_LINE,
        "conversation_id": payload.get("conversation_id"),
        "continue_conversation": False,
    }
    try:
        req = urllib.request.Request(
            url.rstrip("/") + "/v1/converse",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Destiny-Key": key},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return nap
            data = json.loads(resp.read().decode("utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("speech"), str):
            return nap
        return data
    except Exception:  # noqa: BLE001 - any failure means the nap line
        return nap
