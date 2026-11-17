import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from scripts import smoke_test
from scripts.ha_client import HAError
from scripts.wyoming_client import WyomingError

ENV = {"HA_URL": "http://ha:8123", "HA_TOKEN": "tok", "HA_AGENT_ID": "",
       "WHISPER_HOST": "w", "WHISPER_PORT": "10300",
       "PIPER_HOST": "p", "PIPER_PORT": "10200"}

INFO = {"asr": [{"name": "faster-whisper"}], "tts": [{"name": "piper"}]}


def _describe(host, port, timeout=5.0):
    return INFO


def _patches(describe=_describe, synth=None, ping=None, converse=None, brain=None):
    return [
        mock.patch.object(smoke_test, "wyoming_describe", side_effect=describe),
        mock.patch.object(smoke_test, "piper_synthesize", side_effect=synth or (lambda *a, **k: 1234)),
        mock.patch.object(smoke_test, "ha_ping", side_effect=ping or (lambda *a, **k: "API running.")),
        mock.patch.object(smoke_test, "ha_converse", side_effect=converse or mock.Mock(
            side_effect=[("It is sunny and 20 degrees.", "cid1"), ("You asked about the weather.", "cid1")])),
        mock.patch.object(smoke_test, "brain_health", side_effect=brain or (lambda *a, **k: '{"status":"ok"}')),
    ]


class _Ctx(object):
    def __init__(self, **kw):
        self.ps = _patches(**kw)

    def __enter__(self):
        self.m = [p.start() for p in self.ps]
        return self.m

    def __exit__(self, *a):
        for p in self.ps:
            p.stop()


class SmokeTests(unittest.TestCase):
    def test_all_pass_returns_zero(self):
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "e")
            with open(path, "w") as f:
                f.write("HA_TOKEN=tok\n")
            with _Ctx(), redirect_stdout(buf):
                code = smoke_test.main(["--env", path])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("7/7 checks passed", out)
        self.assertEqual(out.count("PASS "), 7)
        self.assertIn("faster-whisper", out)

    def test_whisper_down_others_still_run(self):
        def describe(host, port, timeout=5.0):
            if port == 10300:
                raise WyomingError("whisper down")
            return INFO
        with _Ctx(describe=describe):
            res = smoke_test.run_checks(ENV)
        d = {n: ok for n, ok, _ in res}
        self.assertFalse(d["whisper"])
        self.assertTrue(d["piper"])
        self.assertEqual(len(res), 7)

    def test_whisper_empty_asr_fails(self):
        with _Ctx(describe=lambda h, p, timeout=5.0: {"asr": [], "tts": [{"name": "piper"}]}):
            res = smoke_test.run_checks(ENV)
        d = {n: ok for n, ok, _ in res}
        self.assertFalse(d["whisper"])
        self.assertTrue(d["piper"])

    def test_empty_token_skips_ha_checks(self):
        env = dict(ENV, HA_TOKEN="")
        with _Ctx() as m:
            res = smoke_test.run_checks(env)
            self.assertEqual(m[2].call_count, 0)
            self.assertEqual(m[3].call_count, 0)
        d = {n: (ok, det) for n, ok, det in res}
        self.assertEqual(d["ha-api"], (False, "HA_TOKEN is empty in .env — see docs/setup-windows.md"))
        self.assertEqual(d["conversation"], (False, "skipped: no token"))
        self.assertEqual(d["multi-turn"], (False, "skipped: no token"))

    def test_multi_turn_passes_conversation_id(self):
        with _Ctx() as m:
            smoke_test.run_checks(ENV)
        calls = m[3].call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0][2], "What's the weather like at home right now?")
        self.assertEqual(calls[1][0][2], "What did I just ask you about?")
        self.assertEqual(calls[1][1].get("conversation_id"), "cid1")
        self.assertIsNone(calls[0][1].get("agent_id"))

    def test_agent_id_reaches_both_calls(self):
        with _Ctx() as m:
            res = smoke_test.run_checks(dict(ENV, HA_AGENT_ID="conversation.claude"))
        calls = m[3].call_args_list
        self.assertEqual(len(calls), 2)
        for c in calls:
            self.assertEqual(c[1].get("agent_id"), "conversation.claude")
        for _, _, detail in res:
            self.assertNotIn("HA_AGENT_ID is empty", detail)

    def test_empty_agent_id_adds_hint(self):
        with _Ctx():
            res = smoke_test.run_checks(ENV)
        d = {n: det for n, _, det in res}
        self.assertIn("HA_AGENT_ID is empty", d["conversation"])
        with _Ctx(converse=mock.Mock(side_effect=HAError("boom"))):
            res = smoke_test.run_checks(ENV)
        d = {n: det for n, _, det in res}
        self.assertIn("boom", d["conversation"])
        self.assertIn("HA_AGENT_ID is empty", d["conversation"])

    def test_multi_turn_fails_without_weather(self):
        conv = mock.Mock(side_effect=[("Sunny.", "c"), ("What do you mean?", "c")])
        with _Ctx(converse=conv):
            res = smoke_test.run_checks(ENV)
        d = {n: ok for n, ok, _ in res}
        self.assertTrue(d["conversation"])
        self.assertFalse(d["multi-turn"])

    def test_brain_check_pass(self):
        with _Ctx():
            res = smoke_test.run_checks(dict(ENV, BRAIN_URL="http://b:8000"))
        d = {n: ok for n, ok, _ in res}
        self.assertTrue(d["brain"])
        self.assertEqual([n for n, _, _ in res],
                         ["whisper", "piper", "piper-audio", "brain", "ha-api", "conversation", "multi-turn"])

    def test_brain_check_fail_when_down(self):
        def down(*a, **k):
            raise smoke_test.HAError("Cannot reach the brain")
        with _Ctx(brain=down) as m:
            res = smoke_test.run_checks(ENV)
        d = {n: (ok, det) for n, ok, det in res}
        self.assertFalse(d["brain"][0])
        self.assertIn("Cannot reach", d["brain"][1])
        self.assertTrue(d["ha-api"][0])
        self.assertEqual(m[4].call_args[0][0], "http://localhost:8000")

    def test_conversation_fails_when_weather_unavailable(self):
        conv = mock.Mock(side_effect=[("I don't have access to weather data.", "c")])
        with _Ctx(converse=conv):
            res = smoke_test.run_checks(ENV)
        d = {n: (ok, det) for n, ok, det in res}
        self.assertFalse(d["conversation"][0])
        self.assertIn("answer says weather is unavailable: I don't have access to weather data.",
                      d["conversation"][1])
        self.assertEqual(d["multi-turn"], (False, "skipped: conversation check failed"))

    def test_curly_apostrophe_weather_unavailable_detected(self):
        conv = mock.Mock(side_effect=[("I don’t have access to weather data.", "c")])
        with _Ctx(converse=conv):
            res = smoke_test.run_checks(ENV)
        d = {n: ok for n, ok, _ in res}
        self.assertFalse(d["conversation"])

    def test_conversation_failure_skips_multi_turn(self):
        conv = mock.Mock(side_effect=HAError("boom"))
        with _Ctx(converse=conv):
            res = smoke_test.run_checks(ENV)
        d = {n: (ok, det) for n, ok, det in res}
        self.assertFalse(d["conversation"][0])
        self.assertEqual(d["multi-turn"], (False, "skipped: conversation check failed"))

    def test_bad_port_fails_cleanly(self):
        with _Ctx():
            res = smoke_test.run_checks(dict(ENV, WHISPER_PORT="abc"))
        d = {n: (ok, det) for n, ok, det in res}
        self.assertFalse(d["whisper"][0])
        self.assertIn("WHISPER_PORT", d["whisper"][1])
        self.assertTrue(d["piper"][0])

    def test_defaults_when_env_empty(self):
        with _Ctx() as m:
            smoke_test.run_checks({})
        hosts = [c[0][:2] for c in m[0].call_args_list]
        self.assertEqual(hosts, [("localhost", 10300), ("localhost", 10200)])

    def test_missing_env_file_hint(self):
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            with _Ctx(), redirect_stdout(buf):
                smoke_test.main(["--env", os.path.join(d, "nope")])
        self.assertIn("copy .env.example .env", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
