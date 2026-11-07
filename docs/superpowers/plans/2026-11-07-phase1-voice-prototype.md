# Phase 1 Voice Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run Home Assistant + local Whisper + local Piper in Docker on the Windows dev PC, wired to Claude through HA's Anthropic integration, with an automated smoke test that proves the voice loop and multi-turn context.

**Architecture:** Three containers via Docker Compose (`homeassistant`, `whisper`, `piper`). HA's Assist pipeline does STT → Anthropic agent → TTS. A stdlib-only Python smoke test talks Wyoming directly to whisper/piper and calls HA's REST conversation API.

**Tech Stack:** Docker Desktop (Windows, WSL2 backend), Home Assistant container, `rhasspy/wyoming-whisper`, `rhasspy/wyoming-piper`, Python 3.8+ stdlib (`unittest`, `socket`, `urllib`, `json`).

**Spec:** `docs/superpowers/specs/2026-11-07-phase1-voice-prototype-design.md`

## Global Constraints

- Project root: `C:\dev\Destiny` (not OneDrive).
- Python scripts and tests: **stdlib only**, must run on **Python 3.8** (installed version). Use `typing.Dict/Optional/Tuple`, not `dict[...]` / `X | None`.
- Run tests with: `python -m unittest discover -s tests -v` from repo root.
- Image versions pinned in `.env` (no `latest`); look up the current stable release of each image at implementation time and pin it in `.env.example`.
- Ports: HA `8123`, whisper `10300`, piper `10200`, all published to the host.
- Whisper defaults: model `small-int8`, language `en`. Piper default voice: `en_GB-alba-medium` (configurable via `PIPER_VOICE`).
- Never commit secrets: `.env`, `data/`, and `ha/config/*` (except `.gitkeep`) are git-ignored. The Anthropic key is entered by the user in HA's UI only.
- Don't claim anything works until the command proving it has been run and its output checked.
- Commit message trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

## Review Focus

1. **`.env` written on Windows** (CRLF line endings, `#` comments, blank lines, `"quoted"` values) → parsed to clean values. Test in Task 2.
2. **Service not running** (connection refused / timeout) → that check prints `FAIL <name>: <reason>`, other checks still run, exit code 1, no traceback. Test in Task 4.
3. **Missing or invalid `HA_TOKEN`** → clear message (`HA rejected the token (401) — create a long-lived token in your HA profile`), not a stack trace. Test in Task 3.
4. **HA conversation returns an error response** (`response.response_type == "error"`, e.g. agent not set up) → FAIL showing the speech text. Test in Task 3.
5. **Wyoming frames split across TCP reads / with `data_length` extra JSON** → parser reads exact byte counts. Test in Task 2.

---

### Task 1: Compose stack, repo hygiene, setup docs

**Files:**
- Create: `docker-compose.yml`, `.env.example`, `.gitignore`, `ha/config/.gitkeep`, `README.md`, `docs/setup-windows.md`

**Interfaces:**
- Produces: `.env` keys used by later tasks — `HA_URL` (default `http://localhost:8123`), `HA_TOKEN`, `HA_AGENT_ID` (optional), `WHISPER_HOST`=`localhost`, `WHISPER_PORT`=`10300`, `PIPER_HOST`=`localhost`, `PIPER_PORT`=`10200`, `TZ`, `HA_IMAGE_TAG`, `WHISPER_IMAGE_TAG`, `PIPER_IMAGE_TAG`, `WHISPER_MODEL`, `PIPER_VOICE`.

- [ ] **Step 1:** Write `docker-compose.yml`: services `homeassistant` (`ghcr.io/home-assistant/home-assistant:${HA_IMAGE_TAG}`, volume `./ha/config:/config`, env `TZ`, port `8123:8123`, `restart: unless-stopped`), `whisper` (`rhasspy/wyoming-whisper:${WHISPER_IMAGE_TAG}`, command `--model ${WHISPER_MODEL} --language en`, volume `./data/whisper:/data`, port `10300:10300`), `piper` (`rhasspy/wyoming-piper:${PIPER_IMAGE_TAG}`, command `--voice ${PIPER_VOICE}`, volume `./data/piper:/data`, port `10200:10200`). No host networking (unsupported on Docker Desktop).
- [ ] **Step 2:** Write `.env.example` with every key above and a comment per key; `HA_TOKEN=` left blank. Write `.gitignore`: `.env`, `data/`, `ha/config/*`, `!ha/config/.gitkeep`, `__pycache__/`, `*.pyc`.
- [ ] **Step 3:** Verify: `copy .env.example .env` then `docker compose config` → exits 0, shows three services with resolved image tags.
- [ ] **Step 4:** Verify: `docker compose up -d` then `docker compose ps` → all three `running`; `docker compose logs whisper piper --tail 20` shows each listening (first start downloads the model/voice — wait for it).
- [ ] **Step 5:** Write `docs/setup-windows.md` covering spec §4 steps 1–7 exactly (Docker Desktop, compose up, HA onboarding at `http://localhost:8123`, Wyoming integrations at host `whisper` port `10300` and host `piper` port `10200`, Anthropic integration with the user pasting their key, the agent's system prompt (copy-paste block: she is "Destiny", a friendly family assistant, answers in 1–3 spoken-style sentences, says she's an AI if asked), pipeline "Destiny", exposing **only** the weather entity, creating a long-lived token into `.env` as `HA_TOKEN`, running the smoke test). `README.md`: one-paragraph purpose, quick start (4 commands), links to docs.
- [ ] **Step 6:** Commit: `git add docker-compose.yml .env.example .gitignore ha/config/.gitkeep README.md docs/setup-windows.md` → `git commit -m "feat: add Phase 1 compose stack and setup docs"`. Confirm `git status` shows `.env` and `data/` untracked-ignored.

### Task 2: Env loader and Wyoming client

**Files:**
- Create: `scripts/__init__.py` (empty), `scripts/destiny_env.py`, `scripts/wyoming_client.py`
- Test: `tests/__init__.py` (empty), `tests/test_destiny_env.py`, `tests/test_wyoming_client.py`

**Interfaces:**
- Produces:
  - `load_env(path: str) -> Dict[str, str]` — missing file returns `{}`.
  - `class WyomingError(Exception)`
  - `wyoming_describe(host: str, port: int, timeout: float = 5.0) -> Dict[str, Any]` — returns the `info` event's merged data.
  - `piper_synthesize(host: str, port: int, text: str, timeout: float = 30.0) -> int` — total audio payload bytes.
  - Connection/timeout failures raise `WyomingError` with a human message.

Wyoming framing (both directions): one JSON header line terminated by `\n` with `type`, optional `data`, optional `data_length`, optional `payload_length`. If `data_length` > 0, read exactly that many bytes next and JSON-merge them into `data`. Then read exactly `payload_length` bytes of payload. Requests: describe = `{"type":"describe"}\n` → expect `info`; synthesize = `{"type":"synthesize","data":{"text":...}}\n` → read events, summing `payload_length` of `audio-chunk`, until `audio-stop`.

- [ ] **Step 1: Write failing tests.**
  - `test_load_env_handles_crlf_comments_quotes`: file bytes `b'# c\r\nHA_URL="http://x:8123"\r\n\r\nHA_TOKEN=abc\r\nEMPTY=\r\n'` → `{"HA_URL": "http://x:8123", "HA_TOKEN": "abc", "EMPTY": ""}`.
  - `test_load_env_missing_file_returns_empty`.
  - Wyoming tests use a fake server (`socketserver.TCPServer` on port 0 in a thread) that replies with scripted bytes:
  - `test_describe_reads_data_length_split_across_writes`: server sends header `{"type":"info","data_length":N}\n` then the N-byte JSON `{"asr":[{"name":"faster-whisper"}]}` in two separate `sendall` calls with a 50 ms sleep → result `["asr"][0]["name"] == "faster-whisper"`.
  - `test_synthesize_sums_audio_chunks`: server sends `audio-start`, two `audio-chunk` events with `payload_length` 100 and 50 plus those payload bytes, then `audio-stop` → returns `150`.
  - `test_connection_refused_raises_wyoming_error`: port of a closed socket → `WyomingError`.
- [ ] **Step 2:** Run `python -m unittest tests.test_destiny_env tests.test_wyoming_client -v` → FAIL (import errors).
- [ ] **Step 3:** Implement both modules. Use a buffered `sock.makefile("rb")` and `read(n)` loops for exact byte counts.
- [ ] **Step 4:** Run the same command → all PASS.
- [ ] **Step 5:** Commit `feat: add env loader and Wyoming client`.

### Task 3: Home Assistant client

**Files:**
- Create: `scripts/ha_client.py`
- Test: `tests/test_ha_client.py`

**Interfaces:**
- Produces:
  - `class HAError(Exception)`
  - `ha_ping(base_url: str, token: str, timeout: float = 10.0) -> str` — GET `/api/`, returns its `message` (`"API running."`).
  - `ha_converse(base_url: str, token: str, text: str, conversation_id: Optional[str] = None, agent_id: Optional[str] = None, timeout: float = 60.0) -> Tuple[str, Optional[str]]` — POST `/api/conversation/process` with JSON `{"text", "language": "en"}` plus `conversation_id` / `agent_id` only when given; returns `(response.speech.plain.speech, conversation_id)`.
  - Header `Authorization: Bearer <token>`, `Content-Type: application/json`.

- [ ] **Step 1: Write failing tests** against a fake `http.server` in a thread:
  - `test_ping_returns_message`: `/api/` → `{"message": "API running."}`.
  - `test_converse_sends_conversation_id_and_parses_speech`: server records the request body; reply `{"response":{"response_type":"action_done","speech":{"plain":{"speech":"Sunny."}}},"conversation_id":"c1"}` → returns `("Sunny.", "c1")`; second call with `conversation_id="c1"` → recorded body contains `"conversation_id": "c1"`; first call's body has no `conversation_id` key.
  - `test_401_raises_token_message`: server returns 401 → `HAError` whose message contains `"401"` and `"long-lived token"`.
  - `test_error_response_type_raises_with_speech`: `response_type: "error"`, speech `"No agent"` → `HAError` containing `"No agent"`.
  - `test_connection_refused_raises_ha_error`.
- [ ] **Step 2:** Run `python -m unittest tests.test_ha_client -v` → FAIL.
- [ ] **Step 3:** Implement with `urllib.request`; map `HTTPError` 401 and `URLError` to `HAError`.
- [ ] **Step 4:** Run → all PASS.
- [ ] **Step 5:** Commit `feat: add Home Assistant API client`.

### Task 4: Smoke test CLI

**Files:**
- Create: `scripts/smoke_test.py`
- Test: `tests/test_smoke_test.py`

**Interfaces:**
- Consumes: everything Task 2 and Task 3 produce.
- Produces: `run_checks(env: Dict[str, str]) -> List[Tuple[str, bool, str]]` (name, passed, detail) and `main(argv: Optional[List[str]] = None) -> int` (0 if all pass else 1). `python scripts/smoke_test.py [--env PATH]` (default `.env` in repo root).

Checks, in order, each isolated in try/except so one failure doesn't stop the rest:
1. `whisper` — `wyoming_describe` returns data with an `asr` key.
2. `piper` — `wyoming_describe` returns data with a `tts` key.
3. `piper-audio` — `piper_synthesize(..., "Hello from Destiny.")` > 0 bytes.
4. `ha-api` — `ha_ping` succeeds. If `HA_TOKEN` is empty: FAIL with `"HA_TOKEN is empty in .env — see docs/setup-windows.md"` and skip 5–6 (mark them FAIL `"skipped: no token"`).
5. `conversation` — `ha_converse("What's the weather tomorrow?")` returns non-empty speech.
6. `multi-turn` — `ha_converse("What about Saturday?", conversation_id=<from 5>)` returns speech containing `saturday` (case-insensitive).

Output: one line per check, `PASS name: detail` / `FAIL name: detail`, then `N/6 checks passed`. Print both answers in check 5/6 detail so a human can judge quality.

- [ ] **Step 1: Write failing tests** using `unittest.mock.patch` on the client functions:
  - `test_all_pass_returns_zero`.
  - `test_whisper_down_others_still_run`: `wyoming_describe` raises `WyomingError` for port 10300 only → whisper FAIL, piper PASS, exit 1, no exception escapes.
  - `test_empty_token_skips_ha_checks`: `HA_TOKEN=""` → `ha_ping` never called, checks 4–6 FAIL with the messages above.
  - `test_multi_turn_passes_conversation_id`: assert second `ha_converse` call got `conversation_id` returned by the first.
  - `test_multi_turn_fails_without_saturday`: second answer `"What do you mean?"` → multi-turn FAIL.
- [ ] **Step 2:** Run `python -m unittest tests.test_smoke_test -v` → FAIL.
- [ ] **Step 3:** Implement. Make `scripts/` importable when run as a script (insert repo root on `sys.path`).
- [ ] **Step 4:** Run full suite `python -m unittest discover -s tests -v` → all PASS.
- [ ] **Step 5:** Against the running stack (no token yet): `python scripts/smoke_test.py` → checks 1–3 PASS, 4–6 FAIL with the "HA_TOKEN is empty" message, exit 1. Paste output into the task report.
- [ ] **Step 6:** Commit `feat: add Phase 1 smoke test CLI`.

### Task 5: Voice PE and troubleshooting docs

**Files:**
- Create: `docs/voice-pe-setup.md`, `docs/troubleshooting.md`
- Modify: `README.md` (link both)

- [ ] **Step 1:** `voice-pe-setup.md`: spec §4 step 8 — Wi-Fi onboarding via HA companion app, DHCP reservation, add via ESPHome integration by IP (auto-discovery won't work from Docker Desktop), assign pipeline "Destiny", wake word "Hey Jarvis"/"Okay Nabu", optional 3.5 mm speaker, how to measure latency (stopwatch from end of speech to first audio; record in the doc's table).
- [ ] **Step 2:** `troubleshooting.md`: one entry each for every Review Focus item, plus: Docker Desktop WSL2 not enabled, port already in use, first whisper start slow (model download), Voice PE "unable to connect" (IP changed / firewall on port 6053), Claude answers "I can't access weather" (weather entity not exposed).
- [ ] **Step 3:** Commit `docs: add Voice PE setup and troubleshooting`.

### Task 6: Live end-to-end verification (controller + user, not a subagent)

- [ ] **Step 1 (user):** HA onboarding, Wyoming + Anthropic integrations, pipeline, expose weather only, long-lived token into `.env` — following `docs/setup-windows.md`. Fix any doc step that didn't match reality.
- [ ] **Step 2:** `python scripts/smoke_test.py` → `6/6 checks passed`.
- [ ] **Step 3 (user):** Speak via phone/browser Assist; spoken answer heard.
- [ ] **Step 4 (user, when Voice PE arrives):** wake word → spoken answer; follow-up works; latency recorded.
- [ ] **Step 5:** Commit doc fixes; report results honestly, including anything that failed.
