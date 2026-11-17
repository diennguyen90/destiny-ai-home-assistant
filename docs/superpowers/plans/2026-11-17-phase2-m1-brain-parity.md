# Phase 2 · Milestone 1: Brain Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Destiny's voice requests flow through our own brain service, with tiered model routing, per-request cost logging and daily spend caps. To the family, everything behaves as in Phase 1, plus a small parent page showing costs.

**Architecture:**
- A new `brain` container (Python 3.12, FastAPI) exposes `POST /v1/converse`.
- A thin Home Assistant custom integration (`destiny`) registers a conversation agent, "Destiny brain", that forwards each request to the brain.
- The brain routes to Claude Haiku 5.5 (Tier 1) or Claude Sonnet 5.5 (Tier 2), keeps per-conversation history, injects the current home weather and date, logs every request to SQLite and enforces spend caps.
- HA's free local intents still run before any agent.

**Tech Stack:**
- Python 3.12, FastAPI, uvicorn
- `anthropic` Python SDK (pin the latest 1.x release at implementation time)
- `httpx` for calls to HA
- SQLite via the stdlib `sqlite3`
- pytest
- Docker Compose
- The HA custom integration targets HA 2026.11.0

**Spec:** [docs/superpowers/specs/2026-11-17-phase2-destiny-brain-design.md](../specs/2026-11-17-phase2-destiny-brain-design.md). This plan covers §14 milestone 1 and the parts of §5, §6 and §15 it needs.

## Global Constraints

- Model IDs, exactly:
  - Tier 1: `claude-haiku-5-5`
  - Tier 2: `claude-sonnet-5-5`
  - No date suffixes.
- Pricing (USD per million tokens) lives in config, not code. Defaults:

  | Model | Input | Output | Cache read | Cache write |
  |---|---|---|---|---|
  | `claude-haiku-5-5` | 0.10 | 0.50 | 0.01 | 0.125 |
  | `claude-sonnet-5-5` | 2.00 | 10.00 | 0.10 | 2.50 |

- Thinking and effort:
  - Never send `thinking: {type: "disabled"}` or `budget_tokens`; both return a 400 on these models.
  - Set `output_config={"effort": ...}` explicitly, with defaults Tier 1 `"low"` and Tier 2 `"medium"`, both configurable.
  - `max_tokens` is 1024; answers are spoken and short.
- Never use forced `tool_choice` `any` or `tool` (400 on Sonnet 5.5). Use `auto`.
- Sonnet requests use server-side refusal fallback:
  - `client.beta.messages.create(..., betas=["server-side-fallback-2026-07-01"], fallbacks="default")`
  - Haiku has no server-side fallback.
  - Any final `stop_reason == "refusal"` is spoken as: `I can't help with that one. Let's ask a grown-up.`
- Conversation history stores assistant `response.content` blocks exactly as returned (`block.model_dump()`), appended only, never edited or filtered, and replayed unchanged.
- Destiny base system prompt, verbatim. It's stable and comes first, with `cache_control: {"type": "ephemeral"}`:
  `You are Destiny, a friendly AI assistant for our family. You are speaking out loud, so speak in natural sentences with no lists, markdown, emojis or symbols. Quick questions get 1-2 sentence answers. For explanations, speak in short chunks of 3-5 sentences, then ask if they want more. When someone is learning or doing homework, be a tutor: don't just give the answer; give a hint or ask a small question and let them try first. If the person sounds like a child, use simple words and everyday examples. If you are unsure or something may be out of date, say so. Always keep it family-friendly. If asked, say you are an AI.`
- Volatile context goes in a second system block with no `cache_control`: current local date and time, plus the current home weather line.
- Spend caps (local day in `TZ`):
  - soft `DESTINY_SOFT_CAP_USD=1.00`
  - hard `DESTINY_HARD_CAP_USD=3.00`
  - checked before each model call against logged spend
- Spoken fixed lines, verbatim:
  - Brain unreachable or over 15 s (said by the connector): `My brain is taking a nap. Try again in a minute.`
  - Hard cap reached: `I've done a lot of thinking today. Let's talk again tomorrow.`
  - API or other error: `Sorry, something went wrong in my head. Please try again.`
  - Empty or whitespace text: `I didn't catch that. Could you say it again?`
- Brain port `8000`. `/v1/converse` requires header `X-Destiny-Key` equal to `.env` `BRAIN_SHARED_KEY`; return 401 otherwise.
- Parent page `/parent` requires `DESTINY_PARENT_PIN`. The PIN and API keys never appear in logs or the DB.
- Secrets live only in `.env` (git-ignored); `.env.example` gets blank placeholders. Never `git add -A`; never add `.claude/`.
- Brain tests run in the container: `docker compose run --rm brain pytest -q`. The host's Python 3.8 smoke test and its tests stay stdlib-only and must keep passing: `python -X dev -W error -m unittest discover -s tests`.
- Commit message trailer on every commit: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Brain down or hung.** The voice user hears the nap line within 15 s, and HA's built-in timers and time still work. *Test in Task 8.*
2. **Anthropic API failure** (429, 5xx, timeout, connection error). The brain returns the error line with HTTP 200, the failure is logged with `outcome="error"`, and the process keeps serving. *Test in Task 6.*
3. **Missing or unknown `conversation_id`, including one from a different device.** The brain creates a new id, returns it, and never leaks another conversation's history. *Test in Task 6.*
4. **Day boundary for spend caps.** Spend resets at local midnight in `TZ`, not UTC. *Test in Task 3.*
5. **Junk transcripts** (empty, whitespace, 2,000+ characters of Whisper garbage, emoji or non-ASCII). Empty input gets the "didn't catch that" line with no model call. Long input is truncated to 2,000 characters before routing. Non-ASCII round-trips intact. *Tests in Tasks 5 and 6.*

---

### Task 1: Spike — confirm HA's conversation-agent contract

**Files:**
- Create: `docs/superpowers/notes/2026-11-17-ha-conversation-agent.md`

**Interfaces:**
- Produces: the exact HA 2026.11.0 names Task 8 will use:
  - the `ConversationEntity` base class and its `async_process` / `_async_handle_message` method
  - the `ConversationInput` fields (text, conversation_id, device_id, satellite_id, language, agent_id)
  - how to build the result (`ConversationResult`, `intent.IntentResponse.async_set_speech`)
  - whether `continue_conversation` exists on the result
  - how the pipeline treats agent latency

- [ ] **Step 1: Read HA's source inside the running container.**
  Run `docker exec destiny-homeassistant sh -c "ls /usr/src/homeassistant/homeassistant/components/conversation/"`, then read `entity.py`, `models.py` and `__init__.py`. Also read one in-tree agent that subclasses `ConversationEntity`, such as `components/anthropic/conversation.py`. Expected: you find the class, the input dataclass and the result dataclass.
- [ ] **Step 2: Write the notes file.** Record:
  - exact class, method and field names with file:line
  - a minimal agent skeleton in a code block
  - `continue_conversation` support (yes/no)
  - whether `device_id` / `satellite_id` are populated for Voice PE requests
  - any timeout HA applies

  If `continue_conversation` doesn't exist, note it. The brain still returns the flag; the connector ignores it.
- [ ] **Step 3: Commit.**
  `git add docs/superpowers/notes/2026-11-17-ha-conversation-agent.md && git commit -m "docs: HA conversation agent contract notes"` (plus trailer).

---

### Task 2: Brain skeleton, config, container

**Files:**
- Create:
  - `brain/Dockerfile`
  - `brain/requirements.txt`
  - `brain/destiny_brain/__init__.py`
  - `brain/destiny_brain/config.py`
  - `brain/destiny_brain/app.py`
  - `brain/tests/__init__.py`
  - `brain/tests/test_config.py`
  - `brain/tests/test_health.py`
  - `brain/pytest.ini`
- Modify:
  - `docker-compose.yml`: add a `brain` service
  - `.env.example`: add a brain section
  - `.gitignore`: already ignores `data/`, so nothing to add

**Interfaces:**
- Produces:
  - `config.Settings`, a frozen dataclass with these fields:
    - `anthropic_api_key: str`
    - `brain_shared_key: str`
    - `parent_pin: str`
    - `ha_url: str` (default `http://homeassistant:8123`)
    - `ha_token: str`
    - `ha_weather_entity: str` (default `weather.forecast_home`)
    - `notify_service: str` (default `""`, e.g. `mobile_app_dien_iphone`)
    - `tz: str` (default `Etc/UTC`)
    - `db_path: str` (default `/data/brain.db`)
    - `soft_cap_usd: float = 1.0`
    - `hard_cap_usd: float = 3.0`
    - `tier1_model: str = "claude-haiku-5-5"`
    - `tier2_model: str = "claude-sonnet-5-5"`
    - `tier1_effort: str = "low"`
    - `tier2_effort: str = "medium"`
    - `prices: dict[str, ModelPrice]`
  - `config.ModelPrice(input, output, cache_read, cache_write)`, all floats in USD per MTok.
  - `config.load_settings(env: Mapping[str, str]) -> Settings`
  - `app.create_app(settings: Settings, deps: "Deps | None" = None) -> FastAPI`

- [ ] **Step 1: Write failing tests.**
  - `test_config.py::test_defaults`: `load_settings({"ANTHROPIC_API_KEY": "k", "BRAIN_SHARED_KEY": "s", "DESTINY_PARENT_PIN": "1234"})` gives:
    - `tier1_model == "claude-haiku-5-5"`
    - `prices["claude-sonnet-5-5"].output == 10.0`
    - `soft_cap_usd == 1.0`
    - `hard_cap_usd == 3.0`
  - `test_config.py::test_missing_required_raises`: an empty env raises `ValueError` whose message names `ANTHROPIC_API_KEY` and doesn't contain any key value.
  - `test_config.py::test_overrides`: `DESTINY_SOFT_CAP_USD="2.5"` gives `2.5`.
  - `test_health.py::test_health`: `GET /health` returns 200 `{"status": "ok"}`.
- [ ] **Step 2: Build and run the tests; confirm they fail.**
  `docker compose build brain && docker compose run --rm brain pytest -q`. Expected: import errors or FAIL.
- [ ] **Step 3: Implement.**
  - Env names: `ANTHROPIC_API_KEY`, `BRAIN_SHARED_KEY`, `DESTINY_PARENT_PIN`, `BRAIN_HA_URL`, `BRAIN_HA_TOKEN`, `HA_WEATHER_ENTITY`, `DESTINY_NOTIFY_SERVICE`, `TZ`, `DESTINY_DB_PATH`, `DESTINY_SOFT_CAP_USD`, `DESTINY_HARD_CAP_USD`, `DESTINY_TIER1_EFFORT`, `DESTINY_TIER2_EFFORT`.
  - Dockerfile: `python:3.12-slim`, install requirements (include pytest and httpx test deps), copy `brain/`, `CMD uvicorn destiny_brain.app:main_app --factory --host 0.0.0.0 --port 8000`. Add a `main_app()` factory that calls `create_app(load_settings(os.environ))`.
  - Compose `brain` service:
    - `build: ./brain`, `container_name: destiny-brain`
    - `env_file: .env`, volume `./data/brain:/data`, port `8000:8000`
    - `restart: unless-stopped`
    - healthcheck on `/health` via `python -c` urllib
    - also bind-mount `./ha/custom_components/destiny:/connector:ro` so Task 8's pure client can be tested here
  - `.env.example`: add the new keys with blank secrets and comments, including the soft and hard cap defaults.
- [ ] **Step 4: Run the tests.** Expected: 4 passed.
- [ ] **Step 5: Commit.** `feat(brain): skeleton service, config and container`.

---

### Task 3: Request log, cost math, spend caps

**Files:**
- Create:
  - `brain/destiny_brain/costs.py`
  - `brain/destiny_brain/store.py`
  - `brain/tests/test_costs.py`
  - `brain/tests/test_store.py`

**Interfaces:**
- Consumes: `config.ModelPrice`, `Settings.prices`, `Settings.tz`.
- Produces:
  - `costs.Usage(input_tokens: int, output_tokens: int, cache_read_tokens: int = 0, cache_write_tokens: int = 0)`
  - `costs.cost_usd(price: ModelPrice, usage: Usage) -> float`
  - `store.RequestRecord`, a dataclass:
    - `ts_utc: datetime`, `conversation_id: str`, `device_id: str | None`
    - `tier: int` (0 means no model call), `model: str | None`, `route_reason: str`
    - `usage: Usage`, `cost_usd: float`, `latency_ms: int`
    - `outcome: str` (`"ok"|"refusal"|"error"|"capped"|"empty"`)
    - `text_chars: int`
  - `store.Store(db_path: str, tz: str)` with:
    - `.init() -> None`
    - `.log(rec: RequestRecord) -> None`
    - `.spend_today(now_utc: datetime) -> float`
    - `.recent(limit: int = 50) -> list[RequestRecord]`
    - `.cost_by_day(days: int = 14, now_utc: datetime | None = None) -> list[tuple[date, float]]`
    - `.soft_cap_notified(day: date) -> bool` and `.mark_soft_cap_notified(day: date) -> None`
  - The store never stores the request or response text; only its length.

- [ ] **Step 1: Write failing tests.**
  - `test_cost_usd_sonnet`: `Usage(1_000_000, 100_000)` on Sonnet prices gives `2.0 + 1.0 == 3.0`.
  - `test_cost_includes_cache`: `Usage(0, 0, cache_read_tokens=1_000_000, cache_write_tokens=1_000_000)` on Sonnet gives `0.10 + 2.50`.
  - `test_spend_today_sums_local_day`: with tz `America/Los_Angeles`, log $0.40 at 2026-11-17 07:30Z (Nov 16 local) and $0.25 at 2026-11-17 09:00Z (Nov 17 local). `spend_today(2026-11-17T20:00Z) == 0.25`. This is Review Focus 4.
  - `test_recent_has_no_text_fields`: `RequestRecord` has no attribute containing "text" other than `text_chars`.
  - `test_soft_cap_notified_once_per_day`.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.** One table `requests`, plus a table `flags(day TEXT PRIMARY KEY, soft_cap_notified INTEGER)`. Use `zoneinfo` for local-day bounds and store timestamps as ISO UTC strings.
- [ ] **Step 4: Run the tests; they pass.**
- [ ] **Step 5: Commit.** `feat(brain): request log, cost math and daily spend`.

---

### Task 4: Model provider (Anthropic)

**Files:**
- Create:
  - `brain/destiny_brain/providers/__init__.py`
  - `brain/destiny_brain/providers/base.py`
  - `brain/destiny_brain/providers/anthropic_provider.py`
  - `brain/tests/test_anthropic_provider.py`

**Interfaces:**
- Consumes: `costs.Usage`.
- Produces:
  - `base.ToolSpec(name: str, description: str, input_schema: dict)`
  - `base.ProviderResult`:
    - `text: str` (joined text blocks)
    - `content: list[dict]` (assistant blocks as `model_dump()`)
    - `tool_calls: list[tuple[str, dict]]` (name, input)
    - `stop_reason: str`, `usage: Usage`, `model: str`
  - `base.ChatProvider`, a Protocol, with `complete(*, model: str, system: list[dict], messages: list[dict], tools: list[ToolSpec], effort: str, max_tokens: int = 1024) -> ProviderResult`
  - `anthropic_provider.AnthropicProvider(client)`, where `client` is an `anthropic.Anthropic`; injectable for tests.
  - Errors are raised as `base.ProviderError(kind: str)` with `kind` in `{"rate_limit", "server", "timeout", "connection", "bad_request"}`, mapped from the SDK's typed exceptions most-specific-first.

- [ ] **Step 1: Write failing tests** with a fake client object recording the kwargs passed to `messages.create` and `beta.messages.create`.
  - `test_haiku_uses_plain_create`: model `claude-haiku-5-5` calls `client.messages.create` with `output_config == {"effort": "low"}`, `max_tokens == 1024`, no `thinking` key and no `fallbacks`.
  - `test_sonnet_uses_beta_fallbacks`: model `claude-sonnet-5-5` calls `client.beta.messages.create` with `betas == ["server-side-fallback-2026-07-01"]` and `fallbacks == "default"`.
  - `test_tools_auto`: when tools are given, `tool_choice == {"type": "auto"}` and each tool is `{"name","description","input_schema"}`.
  - `test_usage_mapping`: a fake response with `usage.input_tokens=10, output_tokens=5, cache_read_input_tokens=3, cache_creation_input_tokens=2` gives `Usage(10, 5, 3, 2)`. `None` cache fields become 0.
  - `test_tool_calls_parsed`: a `tool_use` block named `needs_deeper_answer` appears in `tool_calls`.
  - `test_rate_limit_maps_to_provider_error`: the fake raises `anthropic.RateLimitError`, which becomes `ProviderError("rate_limit")`.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement** `AnthropicProvider.complete`. The SDK client is constructed with `timeout=12.0` and `max_retries=1`, so total time stays under the connector's 15 s.
- [ ] **Step 4: Run the tests; they pass.**
- [ ] **Step 5: Commit.** `feat(brain): Anthropic provider with usage, tools and refusal fallback`.

---

### Task 5: Router

**Files:**
- Create:
  - `brain/destiny_brain/router.py`
  - `brain/tests/test_router.py`

**Interfaces:**
- Produces:
  - `router.RouteDecision(tier: int, reason: str)`
  - `router.route(text: str, previous_tier: int | None) -> RouteDecision`
  - `router.clean_text(text: str) -> str`: strips, collapses whitespace and truncates to 2,000 characters.

Rules, in order:
1. If `previous_tier == 2`, return `(2, "sticky")`.
2. If the text contains any of these (case-insensitive), return `(2, "keyword")`: `explain`, `why does`, `why do`, `why is`, `why are`, `how does`, `how do`, `help me understand`, `teach me`, `what's the difference`, `what is the difference`, `homework`.
3. If the text has 25 or more words, return `(2, "long")`.
4. Otherwise return `(1, "default")`.

- [ ] **Step 1: Write failing tests** (parametrised):
  - "what time is it in Tokyo" gives `(1,"default")`
  - "Why is the sky blue?" gives `(2,"keyword")`
  - "Can you EXPLAIN photosynthesis" gives `(2,"keyword")`
  - a 30-word sentence gives `(2,"long")`
  - "ok" with `previous_tier=2` gives `(2,"sticky")`
  - `clean_text("  a \n b ")` gives `"a b"`
  - `clean_text("x"*5000)` has length 2000 (Review Focus 5)
  - `clean_text("¿Qué tal? 🚗")` keeps those characters
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests; they pass.**
- [ ] **Step 5: Commit.** `feat(brain): rules-first tier router`.

---

### Task 6: Conversation engine

**Files:**
- Create:
  - `brain/destiny_brain/engine.py`
  - `brain/destiny_brain/ha.py`
  - `brain/destiny_brain/prompts.py`
  - `brain/tests/test_engine.py`
  - `brain/tests/fakes.py`

**Interfaces:**
- Consumes: `Settings`, `Store`, `ChatProvider`, `router.route`, `router.clean_text`, `costs.cost_usd`.
- Produces:
  - `engine.ConverseRequest(text: str, conversation_id: str | None, device_id: str | None, satellite_id: str | None, language: str = "en")`
  - `engine.ConverseResponse(speech: str, conversation_id: str, continue_conversation: bool)`
  - `engine.Engine(settings, store, provider, ha, clock=lambda: datetime.now(UTC))` with `.handle(req: ConverseRequest) -> ConverseResponse` (sync)
  - `ha.HAClient(base_url, token, http: httpx.Client)` with:
    - `.weather_line(entity_id) -> str | None`, e.g. `"Home weather now: sunny, 69°F, humidity 26%."`; returns `None` on any failure, and caches for 5 minutes
    - `.notify(service: str, title: str, message: str) -> bool`, a POST to `/api/services/notify/{service}`; returns `False` on failure and never raises
  - `prompts.DESTINY_BASE` (verbatim from Global Constraints)
  - `prompts.context_block(now_local: datetime, weather_line: str | None) -> str`
  - `prompts.ESCALATE_TOOL = ToolSpec("needs_deeper_answer", "Call this instead of answering when the question needs a careful, multi-step or teaching explanation.", {"type":"object","properties":{"reason":{"type":"string"}},"required":["reason"],"additionalProperties":False})`

Behaviour of `handle`:
1. Clean the text. If it's empty, return the empty line, log `outcome="empty"` with tier 0, and make no model call.
2. Resolve the conversation:
   - If `conversation_id` is unknown or missing, create a new uuid4 hex.
   - History is kept in memory per id, holding the last 20 messages, and expires 10 minutes after the last turn.
3. Check the hard cap. If `spend_today >= hard_cap`, return the hard-cap line and log `outcome="capped"`.
4. Route with `previous_tier` from the conversation. If the soft cap is reached and the tier is 2, downgrade to 1 with reason `"soft_cap"`, and call `ha.notify` once per day (only if `notify_service` is set) with title `Destiny` and message `Destiny reached today's soft spending cap ($X.XX). Long answers use the faster model until tomorrow.`
5. Build the request:
   - `system = [{"type":"text","text":DESTINY_BASE,"cache_control":{"type":"ephemeral"}}, {"type":"text","text":context_block(...)}]`
   - messages are the history plus the new user turn
6. **Tier 1:** call with `tools=[ESCALATE_TOOL]`. If the result calls `needs_deeper_answer`, discard that result (don't append it), log it as its own record with reason `"escalated"`, and then do a Tier 2 call on the same messages with no tools.
7. **Tier 2:** call with no tools.
8. If `stop_reason == "refusal"`, speak the refusal line and log `outcome="refusal"`.
9. Append the user turn and the final assistant `content` to history, unedited.
10. `continue_conversation` is `True` if the speech ends with `?`; otherwise `False`.
11. On `ProviderError` or any exception, return the error line with `outcome="error"`, and don't append to history.
12. Every model call is logged with tokens, cost, `latency_ms` and the route reason.

- [ ] **Step 1: Write failing tests** with a `FakeProvider` (scripted results that record calls) and a `FakeHA`:
  - `test_empty_text_no_model_call`
  - `test_simple_question_tier1`: one call, to `claude-haiku-5-5`, and the speech equals the fake text
  - `test_keyword_goes_tier2`
  - `test_escalation_runs_sonnet_and_logs_two_records`
  - `test_followup_keeps_history`: the second call's messages contain the first user turn and the first assistant content unchanged, as an equal list of dicts
  - `test_unknown_conversation_id_gets_new_and_isolated`: Review Focus 3. Ids A and B don't share history; an unknown id returns a different id.
  - `test_history_expires_after_10_min`, using an injected clock
  - `test_hard_cap_blocks`
  - `test_soft_cap_downgrades_and_notifies_once`: two Tier 2 requests produce one notify
  - `test_provider_error_returns_line_and_logs_error`: Review Focus 2. A `ProviderError("rate_limit")` gives the error line and an `outcome=="error"` record.
  - `test_refusal_line`
  - `test_context_has_weather_and_local_time`: the second system block contains the fake weather line and local date. The first block equals `DESTINY_BASE` with `cache_control`.
  - `test_continue_conversation_on_question`
  - `test_weather_line_none_on_ha_failure`: the HA client returns `None`, and the context omits weather without crashing.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement** `engine.py`, `ha.py` and `prompts.py`.
- [ ] **Step 4: Run the tests; they pass.**
- [ ] **Step 5: Commit.** `feat(brain): conversation engine with routing, history, caps and logging`.

---

### Task 7: HTTP API and minimal parent page

**Files:**
- Modify: `brain/destiny_brain/app.py`
- Create:
  - `brain/destiny_brain/deps.py`
  - `brain/destiny_brain/templates/parent.html` (plain HTML, no JS framework)
  - `brain/tests/test_api.py`

**Interfaces:**
- Consumes: `Engine`, `Store`, `Settings`.
- Produces:
  - `deps.Deps(engine: Engine, store: Store)` and `deps.build_deps(settings) -> Deps`, which wires the real provider, store and HA client
  - `POST /v1/converse`: request JSON `{text, conversation_id?, device_id?, satellite_id?, language?}`, response 200 `{speech, conversation_id, continue_conversation}`. A missing or wrong `X-Destiny-Key` gets 401.
  - `GET /parent`:
    - Without a valid session cookie it shows a PIN form.
    - `POST /parent/login` with form field `pin`: a correct PIN sets an HttpOnly cookie (random token kept in memory, valid 12 h) and redirects to `/parent`; a wrong PIN returns 401 with the form.
    - The page shows today's spend vs the caps, cost by day (14 days), and the last 50 requests (time, tier, model, reason, tokens, cost, latency, outcome).

- [ ] **Step 1: Write failing tests** using FastAPI `TestClient` and `create_app(settings, deps=fake_deps)`:
  - `test_converse_requires_key`: no header gives 401; wrong key gives 401
  - `test_converse_ok`: returns the fake engine's response JSON
  - `test_parent_requires_pin`: GET with no cookie shows the form and no cost data
  - `test_parent_login_wrong_pin_401`
  - `test_parent_login_then_page_shows_spend`
  - `test_pin_not_in_logs`: capture logging during a login; the PIN string doesn't appear
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.** The engine is synchronous, so run it with `run_in_threadpool`.
- [ ] **Step 4: Run the tests; they pass.** Also run the full brain suite.
- [ ] **Step 5: Commit.** `feat(brain): converse API and PIN-protected parent cost page`.

---

### Task 8: Home Assistant connector

**Files:**
- Create:
  - `ha/custom_components/destiny/manifest.json`
  - `ha/custom_components/destiny/__init__.py`
  - `ha/custom_components/destiny/config_flow.py`
  - `ha/custom_components/destiny/conversation.py`
  - `ha/custom_components/destiny/brain_client.py` (pure Python, no `homeassistant` imports)
  - `ha/custom_components/destiny/strings.json`
  - `brain/tests/test_connector_client.py` (imports `/connector/brain_client.py` via `importlib`)
- Modify: `docker-compose.yml`. In the `homeassistant` service, add the volume `./ha/custom_components/destiny:/config/custom_components/destiny`.

**Interfaces:**
- Consumes: Task 1 notes (exact HA names), the Task 7 API contract.
- Produces:
  - `brain_client.NAP_LINE = "My brain is taking a nap. Try again in a minute."`
  - `brain_client.converse(url: str, key: str, payload: dict, timeout: float = 15.0) -> dict`. It returns the brain's JSON. On any network error, timeout, non-200 response or bad JSON it returns `{"speech": NAP_LINE, "conversation_id": payload.get("conversation_id"), "continue_conversation": False}` and never raises. It uses stdlib `urllib.request`, run off the event loop by the caller.
  - Config flow fields: `brain_url` (default `http://brain:8000`) and `shared_key`.
  - The entity is named "Destiny brain". It forwards text, conversation_id, device_id, satellite_id and language, sets the speech on the intent response, passes through `continue_conversation` if HA supports it (per Task 1), and returns the brain's conversation id.

- [ ] **Step 1: Write failing tests** (they run in the brain container against a local stub HTTP server on a thread):
  - `test_ok_roundtrip`: the stub returns JSON and `converse` returns it unchanged
  - `test_sends_key_header`: the stub sees `X-Destiny-Key`
  - `test_timeout_returns_nap_line`: the stub sleeps 2 s and `timeout=0.5` gives `NAP_LINE` within 1.5 s (Review Focus 1)
  - `test_connection_refused_returns_nap_line`
  - `test_non_200_returns_nap_line`
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement** `brain_client.py`, then the HA files using the exact names from the Task 1 notes. In `conversation.py`, call `await hass.async_add_executor_job(brain_client.converse, ...)`.
- [ ] **Step 4: Run the tests; they pass.** Then `docker compose up -d homeassistant brain` and check the HA logs for errors: `docker logs destiny-homeassistant --since 5m | findstr /i destiny` shows no tracebacks.
- [ ] **Step 5: Commit.** `feat(ha): Destiny brain conversation agent connector`.

---

### Task 9: Setup docs, smoke test, log

**Files:**
- Modify:
  - `scripts/smoke_test.py`, `tests/test_smoke_test.py`: add a `brain` check, and fix the weather gap
  - `docs/setup-windows.md`: new section "Phase 2: Destiny's brain"
  - `docs/troubleshooting.md`
  - `docs/project-log.md`
  - `README.md`

**Interfaces:**
- Consumes: `/health` (Task 2), the connector (Task 8).
- Produces:
  - Smoke test check `brain`: GET `{BRAIN_URL}/health` (env `BRAIN_URL`, default `http://localhost:8000`) expecting `{"status":"ok"}`.
  - Weather-gap fix:
    - The `conversation` check now asks `What's the weather like at home right now?`. Forecasts are unavailable until milestone 4, so "tomorrow" would always fail.
    - It fails if the answer contains any of `can't see`, `don't have access`, `no weather`, `not able to see` (case-insensitive), with detail `answer says weather is unavailable: <answer>`.
    - The `multi-turn` follow-up becomes `And how humid is it?` (same conversation_id), and the answer must contain `humid`.

- [ ] **Step 1: Write failing stdlib tests in `tests/test_smoke_test.py`:**
  - `test_brain_check_pass`
  - `test_brain_check_fail_when_down`
  - `test_conversation_fails_when_weather_unavailable`, with the fake answer "I don't have access to weather data."
- [ ] **Step 2: Run them; they fail.** `python -X dev -W error -m unittest discover -s tests`.
- [ ] **Step 3: Implement the smoke-test changes.** Keep it stdlib-only and Python 3.8-compatible. The check order becomes whisper, piper, piper-audio, brain, ha-api, conversation, multi-turn.
- [ ] **Step 4: Run the tests; all pass,** the existing 25 plus 3 new.
- [ ] **Step 5: Docs.** The setup-windows.md "Phase 2" section covers:
  1. Fill in the brain section of `.env`: API key, shared key, PIN, brain HA token from a new non-admin HA user `destiny-brain`, notify service name, TZ.
  2. `docker compose up -d --build`.
  3. Add a firewall rule for TCP 8000 on the Private profile.
  4. Restart HA, then Settings > Devices & services > Add integration > "Destiny" with URL `http://brain:8000` and the shared key.
  5. Settings > Voice assistants > Destiny: set the conversation agent to "Destiny brain".
  6. Run the smoke test.
  7. Open `http://<PC>:8000/parent`.

  Add a rollback note: set the agent back to "Claude conversation". Add troubleshooting entries for the nap line, a 401 on converse, the parent PIN, and the cap lines. Update the project log status and the README docs list.
- [ ] **Step 6: Commit.** `feat: brain smoke check, weather-gap fix and Phase 2 setup docs`.

---

### Task 10: Live verification (controller and family, not a subagent)

- [ ] **Step 1: Prepare the environment.**
  - The family puts the API key, shared key and PIN in `.env`.
  - Create the `destiny-brain` HA user and token.
  - Find the notify service under Developer tools > Actions, search `notify.mobile_app`.
  - Add firewall rule 8000.
- [ ] **Step 2: Start the services.** Run `docker compose up -d --build`, then `docker compose run --rm brain pytest -q`. Expected: all pass.
- [ ] **Step 3: Switch the agent.** Add the integration, then switch the Destiny agent to "Destiny brain".
- [ ] **Step 4: Run the smoke test.** `python scripts\smoke_test.py`. Expected: 7/7, and the conversation answer includes real current weather.
- [ ] **Step 5: Voice checks on the Voice PE:**
  - "what time is it" is answered by HA locally; no row appears on the parent page.
  - "who wrote Charlotte's Web" goes to Tier 1.
  - "why is the sky blue" goes to Tier 2.
  - A follow-up answered without the wake word.
  - Stop the brain (`docker stop destiny-brain`): Destiny says the nap line and a timer still works. Then start it again.
  - Record latency for 5 Tier 1 and 5 Tier 2 questions in `docs/voice-pe-setup.md`'s table.
- [ ] **Step 6: Parent page.** `http://192.168.86.143:8000/parent` shows the requests and costs.
- [ ] **Step 7: Close out.** Update the project log with results, commit, and report honestly, including any doc step that didn't match.
