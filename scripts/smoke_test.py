"""Destiny Phase 1 smoke test: proves the whole voice loop works. Stdlib only."""
import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.destiny_env import load_env  # noqa: E402
from scripts.ha_client import HAError, ha_converse, ha_ping  # noqa: E402
from scripts.wyoming_client import WyomingError, piper_synthesize, wyoming_describe  # noqa: E402

Result = Tuple[str, bool, str]
NO_AGENT_HINT = (" (HA_AGENT_ID is empty, so Home Assistant's built-in agent answered, "
                 "not Claude; see docs/setup-windows.md)")
NO_TOKEN = "HA_TOKEN is empty in .env — see docs/setup-windows.md"


WEATHER_UNAVAILABLE = ("can't see", "don't have access", "no weather", "not able to see")


def brain_health(base_url, timeout=5.0):
    # type: (str, float) -> str
    url = base_url.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise HAError("the brain at %s returned HTTP %d" % (url, e.code))
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        raise HAError("Cannot reach the brain at %s (%s)" % (url, e))
    try:
        ok = json.loads(body).get("status") == "ok"
    except (ValueError, AttributeError):
        ok = False
    if not ok:
        raise HAError("the brain at %s did not answer {\"status\":\"ok\"}: %s" % (url, body[:200]))
    return "status ok"


def _port(env, key, default):
    # type: (Dict[str, str], str, int) -> int
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError("%s=%r in .env is not a number" % (key, raw))


def _program(info, key):
    # type: (Dict, str) -> str
    items = info.get(key)
    if not isinstance(items, list) or not items:
        raise WyomingError("the service answered but lists no %r programs" % key)
    first = items[0]
    name = first.get("name") if isinstance(first, dict) else None
    return 'info["%s"][0]["name"] = %s' % (key, name)


def run_checks(env):
    # type: (Dict[str, str]) -> List[Result]
    results = []  # type: List[Result]

    def record(name, fn):
        try:
            results.append((name, True, fn()))
        except (WyomingError, HAError, ValueError) as e:
            results.append((name, False, str(e)))
        except Exception as e:  # keep going no matter what
            results.append((name, False, "unexpected error: %s: %s" % (type(e).__name__, e)))

    w_host = env.get("WHISPER_HOST") or "localhost"
    p_host = env.get("PIPER_HOST") or "localhost"

    record("whisper", lambda: _program(
        wyoming_describe(w_host, _port(env, "WHISPER_PORT", 10300)), "asr"))
    record("piper", lambda: _program(
        wyoming_describe(p_host, _port(env, "PIPER_PORT", 10200)), "tts"))

    def synth():
        n = piper_synthesize(p_host, _port(env, "PIPER_PORT", 10200), "Hello from Destiny.")
        if n <= 0:
            raise WyomingError("Piper returned no audio")
        return "%d bytes of audio" % n
    record("piper-audio", synth)

    record("brain", lambda: brain_health(env.get("BRAIN_URL") or "http://localhost:8000"))

    base = env.get("HA_URL") or "http://localhost:8123"
    token = env.get("HA_TOKEN") or ""
    agent = env.get("HA_AGENT_ID") or None

    if not token.strip():
        results.append(("ha-api", False, NO_TOKEN))
        results.append(("conversation", False, "skipped: no token"))
        results.append(("multi-turn", False, "skipped: no token"))
        return results

    record("ha-api", lambda: ha_ping(base, token))

    state = {}  # type: Dict[str, Optional[str]]

    def conv():
        speech, cid = ha_converse(base, token, "What's the weather like at home right now?",
                                  agent_id=agent)
        if not speech.strip():
            raise HAError("Home Assistant gave an empty answer")
        if any(p in speech.lower().replace("’", "'") for p in WEATHER_UNAVAILABLE):
            raise HAError("answer says weather is unavailable: %s" % speech)
        state["cid"] = cid
        return "answer: %s" % speech
    record("conversation", conv)
    if agent is None:
        name, ok, detail = results[-1]
        results[-1] = (name, ok, detail + NO_AGENT_HINT)

    if not results[-1][1]:
        results.append(("multi-turn", False, "skipped: conversation check failed"))
        return results

    def multi():
        speech, _ = ha_converse(base, token, "What did I just ask you about?",
                                conversation_id=state.get("cid"), agent_id=agent)
        if "weather" not in speech.lower():
            raise HAError("answer does not mention the weather, so context was lost: %s" % speech)
        return "answer: %s" % speech
    record("multi-turn", multi)
    return results


def main(argv=None):
    # type: (Optional[List[str]]) -> int
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="Destiny Phase 1 smoke test")
    parser.add_argument("--env", default=os.path.join(REPO_ROOT, ".env"),
                        help="path to .env file (default: .env in the repo root)")
    args = parser.parse_args(argv)
    if not os.path.exists(args.env):
        print("Note: %s not found. Run: copy .env.example .env  (using defaults for now)" % args.env)
    results = run_checks(load_env(args.env))
    for name, ok, detail in results:
        print("%s %s: %s" % ("PASS" if ok else "FAIL", name, detail))
    passed = sum(1 for _, ok, _ in results if ok)
    print("%d/%d checks passed" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
