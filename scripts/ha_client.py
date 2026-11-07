"""Home Assistant REST client (stdlib only) for the Destiny smoke test."""
import json
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple


class HAError(Exception):
    pass


def _request(base_url, token, path, payload=None, timeout=10.0):
    # type: (str, str, str, Optional[Dict[str, Any]], float) -> Any
    base = base_url.rstrip("/")
    url = base + path
    data = None
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise HAError(
                "Home Assistant rejected the token (HTTP 401). Create a long-lived token "
                "in Home Assistant (your profile > Security > Long-lived access tokens) "
                "and put it in the .env file.")
        raise HAError("Home Assistant returned HTTP %d for %s. Check the Home Assistant "
                      "logs for details." % (e.code, path))
    except socket.timeout:
        raise HAError("Home Assistant at %s timed out after %ss. It may still be "
                      "starting or busy; try again." % (base, timeout))
    except urllib.error.URLError as e:
        if isinstance(e.reason, socket.timeout):
            raise HAError("Home Assistant at %s timed out after %ss. It may still be "
                          "starting or busy; try again." % (base, timeout))
        raise HAError("Cannot reach Home Assistant at %s (%s). Is it running and is the "
                      "URL correct?" % (base, e.reason))
    except OSError as e:
        raise HAError("Cannot reach Home Assistant at %s (%s)." % (base, e))
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        raise HAError("Home Assistant at %s did not return JSON. It may not be set up "
                      "yet (finish onboarding in the browser) or the URL is wrong." % base)


def ha_ping(base_url, token, timeout=10.0):
    # type: (str, str, float) -> str
    body = _request(base_url, token, "/api/", None, timeout)
    try:
        return str(body["message"])
    except (KeyError, TypeError):
        raise HAError("Unexpected reply from Home Assistant /api/: %r" % (body,))


def ha_converse(base_url, token, text, conversation_id=None, agent_id=None, timeout=60.0):
    # type: (str, str, str, Optional[str], Optional[str], float) -> Tuple[str, Optional[str]]
    payload = {"text": text, "language": "en"}  # type: Dict[str, Any]
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if agent_id:
        payload["agent_id"] = agent_id
    body = _request(base_url, token, "/api/conversation/process", payload, timeout)
    try:
        response = body["response"]
        speech = response["speech"]["plain"]["speech"]
    except (KeyError, TypeError):
        raise HAError("Unexpected reply from the Home Assistant conversation API: %r"
                      % (body,))
    if response.get("response_type") == "error":
        raise HAError("Home Assistant conversation agent reported an error: %s" % speech)
    return speech, body.get("conversation_id")
