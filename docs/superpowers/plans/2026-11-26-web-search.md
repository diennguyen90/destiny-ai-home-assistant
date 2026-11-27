# Internet Answers (Web Search) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Destiny answers live questions (sports, news, schedules) by letting Sonnet use Anthropic's server-side web search. A fun "surfing the web" filler covers the wait.

**Architecture:**
- A new `"live"` router rule sends current-information questions straight to Tier 2.
- Tier 2 calls, both blocking and streaming, add the `web_search_20260209` server tool.
- The provider passes server tools through and signals when a search starts.
- The engine:
  - picks a web filler for live routes;
  - adds a one-time web line when a search starts before any text;
  - continues a `pause_turn` once;
  - logs search counts and cost.

**Tech Stack:** Python 3.12, anthropic SDK 1.17.0 (beta messages surface), FastAPI, SQLite, pytest.

**Spec:** [docs/superpowers/specs/2026-11-26-web-search-design.md](../specs/2026-11-26-web-search-design.md)

## Global Constraints

- Every model call keeps today's parameters exactly:
  - `client.beta.messages.*`
  - `thinking={"type":"adaptive","block_binding":{"prefix_mismatch_behavior":"drop_block"}}`
  - betas include `"thinking-binding-controls-2026-08-01"`
  - Sonnet also gets `"server-side-fallback-2026-07-01"` and `fallbacks="default"`
  - `output_config={"effort": ...}`, `max_tokens=1024`, per-call timeout via `with_options`
- Web search tool, verbatim. Tier 2 (Sonnet) only; Tier 1 (Haiku) never gets it:
  `{"type": "web_search_20260209", "name": "web_search", "max_uses": 3, "user_location": {"type": "approximate", "region": "California", "country": "US", "timezone": "America/Los_Angeles"}}`
- `tool_choice` `{"type":"auto"}` is sent only when *custom* tools are given. A server-tool-only request sends no `tool_choice`.
- Search price: `$0.01` per search (`usage.server_tool_use.web_search_requests`). It is added to `cost_usd` and counts toward the $1 soft and $3 hard daily caps.
- Fillers:
  - Each web filler is at least 61 characters, spoken style (no `*#_[]{}<>~`, no emoji). There are 10–14 of them.
  - No repeats among the last 5 per device, per list.
  - Fillers are never sent to Claude or stored in history.
- The one-time unplanned-search line is verbatim: `" Let me check the web real quick."`.
- Assistant `content` (including `server_tool_use` and `web_search_tool_result` blocks) is appended to history exactly as returned, with no edits.
- Spoken text = all `text` blocks joined with `""`. Citations split text into several blocks, so a `" "` join would add stray spaces.
- The blocking `/v1/converse` behaviour is unchanged apart from Tier 2 gaining search. The smoke test passes 7/7.
- Secrets: never read `.env`. Never `git add -A`. Never add `.claude/`. Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Tests:
  - Brain (from `C:\dev\Destiny`): `docker compose run --rm --no-deps brain pytest -q`
  - Host connector: `python -X dev -W error -m unittest discover -s tests`

## Review Focus

1. **Multi-turn after a search.** The follow-up "and what time?" replays the `server_tool_use` and `web_search_tool_result` blocks from history. The conversation stays on Tier 2 (sticky), so Haiku, which has no search tool, never receives those blocks. Test in Task 4.
2. **Weather questions don't search.** "What's the weather tomorrow?" and "is it going to rain today" stay on the existing path (weather is already in context), even though "today" and "tomorrow" are live words. Test in Task 1.
3. **Word-boundary false positives.** "I wonder why…", "windows", "currently learning fractions" and "playground" must not trigger `"live"`. Test in Task 1.
4. **Search hits the deadline or `pause_turn`.** She continues once if time remains. Otherwise she says what she has, or the error line, and is never silent. Test in Task 4.
5. **Soft cap reached on a live question.** It is downgraded to Tier 1 (no search), as today, and Haiku can still escalate. The answer stays honest that it can't check live info. Test in Task 4.

---

### Task 1: Live routing, web fillers, prompt rules

**Files:**
- Modify: `brain/destiny_brain/router.py`, `brain/destiny_brain/fillers.py`, `brain/destiny_brain/prompts.py`
- Test: `brain/tests/test_router.py`, `brain/tests/test_fillers.py`

**Interfaces:**
- Produces:
  - `route()` may return `RouteDecision(2, "live")`. Order: sticky → live → keyword → long → default.
  - `fillers.WEB_FILLERS: tuple[str, ...]`
  - `FillerPicker.pick(device_id: str | None, kind: str = "normal") -> str`, where `kind` is `"normal"` (picks from `FILLERS`) or `"web"` (picks from `WEB_FILLERS`). History is kept per `(device, kind)`.
  - `prompts.WEB_SEARCH_TOOL: dict` holds the exact dict from the Global Constraints.

- [ ] **Step 1: Write the failing tests**
  - `test_live_words_route_tier2`:
    - each of these returns `(2, "live")` with `previous_tier=None`:
      - "do the nuggets play tonight"
      - "who won the 49ers game"
      - "what's in the news today"
      - "what time is the niners game"
      - "latest score"
    - `route("do the nuggets play tonight", 2).reason == "sticky"`
  - `test_weather_questions_not_live`: none of these return reason `"live"`:
    - "what's the weather tomorrow"
    - "is it going to rain today"
    - "how hot is it right now"
    - "what's the forecast this weekend"
  - `test_live_word_boundaries`: none of these return `"live"`:
    - "I wonder why cats purr"
    - "open the windows"
    - "currently learning fractions"
    - "let's go to the playground"
  - `test_web_fillers_rules`: 10–14 fillers, each at least 61 characters, spoken style (reuse the existing style check), no overlap with `FILLERS`
  - `test_pick_kinds_independent`:
    - 200 `pick("d1", "web")` calls never repeat among the previous 5
    - each is in `WEB_FILLERS`
    - `pick("d1")` still returns from `FILLERS`
  - `test_prompt_mentions_teams_and_no_links`: `DESTINY_BASE` contains "49ers", "Nuggets", "Pacific time" and "links"
  - `test_escalate_description_mentions_live_info`: `ESCALATE_TOOL.description` contains "current or live information"
- [ ] **Step 2: Run them;** they fail.
- [ ] **Step 3: Implement.**
  - **Router:** use word-boundary regexes. Live terms (builder may extend): today, tonight, tomorrow, yesterday, this week, this weekend, latest, current, right now, news, score(s), game(s), playing, schedule, won, win, lost, standings, price of, stock, open now, 49ers, niners, nuggets.
  - **Weather exclusion:** if any of weather, forecast, rain, snow, temperature, hot, cold, sunny, wind, humid matches, skip the live rule.
  - **Prompts:** append the §4.3 rules to `DESTINY_BASE`, and extend the `ESCALATE_TOOL` description per §4.1.
- [ ] **Step 4: Run the full suite;** it passes.
- [ ] **Step 5: Commit** `feat(brain): live-info routing, web fillers and search prompt rules`.

### Task 2: Search usage, cost and the `web_searches` column

**Files:**
- Modify: `brain/destiny_brain/costs.py`, `brain/destiny_brain/store.py`, `brain/destiny_brain/app.py` (parent page)
- Test: `brain/tests/test_costs.py`, `brain/tests/test_store.py`, `brain/tests/test_api.py`

**Interfaces:**
- Produces:
  - `Usage.web_search_requests: int = 0`
  - `costs.WEB_SEARCH_USD = 0.01`
  - `cost_usd(price, usage)` includes `usage.web_search_requests * WEB_SEARCH_USD`
  - `RequestRecord.web_searches: int | None = None`, persisted
  - `Store.init()` adds the `web_searches INTEGER` column if it's missing

- [ ] **Step 1: Write the failing tests**
  - `test_cost_includes_web_search`: `cost_usd(p, Usage(0, 0, web_search_requests=3)) == 0.03`
  - `test_store_migrates_web_searches`: create the old schema without the column, then `init()`; a record with `web_searches=2` round-trips via the recent-requests query
  - `test_parent_page_shows_web_searches`: the page HTML contains a "Searches" column header and the logged value
- [ ] **Step 2: Run them;** they fail.
- [ ] **Step 3: Implement,** following the `first_token_ms` pattern exactly.
- [ ] **Step 4: Run the full suite;** it passes.
- [ ] **Step 5: Commit** `feat(brain): web search cost and searches column`.

### Task 3: Provider server tools and the search-started signal

**Files:**
- Modify: `brain/destiny_brain/providers/base.py`, `brain/destiny_brain/providers/anthropic_provider.py`, `brain/tests/fakes.py`
- Test: `brain/tests/test_anthropic_provider.py`

**Interfaces:**
- Consumes: `Usage.web_search_requests` (Task 2).
- Produces:
  - `ChatProvider.complete(..., server_tools: list[dict] | None = None)` and `.stream(..., server_tools=None)`. Server tools are appended unchanged after custom tools in `kwargs["tools"]`.
  - `providers.base.SEARCH_STARTED`: a module-level sentinel object (not a `str`). `stream()` yields it once per `server_tool_use` content block start, between the text deltas (`str`).
  - `_to_result`:
    - sets `text` to the `""`-join of the text blocks;
    - maps `usage.server_tool_use.web_search_requests` (missing or `None` → 0) into `Usage`.
  - `FakeProvider.complete/stream` accept `server_tools`. They record the last call's `tools` and `server_tools`. A scripted stream may include `SEARCH_STARTED` items.

- [ ] **Step 1: Write the failing tests**
  - `test_server_tools_passed_through_sonnet`:
    - `kwargs["tools"] == [WEB_SEARCH_TOOL]`
    - no `tool_choice`
    - betas and fallbacks unchanged
  - `test_custom_plus_server_tools`: the custom tool comes first, then the server tool; `tool_choice` is auto
  - `test_stream_yields_search_started`:
    - the fake SDK stream emits `content_block_start(server_tool_use)`, then text deltas
    - the provider yields `[SEARCH_STARTED, "Tonight", " at 7."]`
  - `test_text_join_no_spaces`:
    - two text blocks "The Nuggets play" and " at 7 PM." give text `"The Nuggets play at 7 PM."`
    - `web_search_requests == 1` is mapped from `usage.server_tool_use`
- [ ] **Step 2: Run them;** they fail.
- [ ] **Step 3: Implement.**
  - Iterate the SDK stream's raw events instead of `text_stream`.
  - Check the event, block and delta attribute names in the installed 1.17.0 package (`anthropic/lib/streaming`, `types/beta`). Don't guess.
  - Keep `get_final_message()` for the result.
- [ ] **Step 4: Run the full suite;** it passes. Existing provider tests stay green: for text-only answers the `""` join equals today's output.
- [ ] **Step 5: Commit** `feat(brain): server tools and search signal in provider`.

### Task 4: Engine — search on Tier 2, web fillers, `pause_turn`, logging

**Files:**
- Modify: `brain/destiny_brain/engine.py`
- Test: `brain/tests/test_engine.py`

**Interfaces:**
- Consumes:
  - `route` reason `"live"`, `FillerPicker.pick(device, kind)` and `WEB_SEARCH_TOOL` (Task 1)
  - `Usage.web_search_requests` and `RequestRecord.web_searches` (Task 2)
  - `server_tools=` and `SEARCH_STARTED` (Task 3)
- Produces: no new public API. `Engine.handle` and `handle_stream` behave per spec §4.

- [ ] **Step 1: Write the failing tests**
  - `test_tier2_calls_get_web_search` (blocking and stream): the Tier 2 provider call has `server_tools == [WEB_SEARCH_TOOL]`. The Tier 1 call has `server_tools` empty or `None` and `tools == [ESCALATE_TOOL]`.
  - `test_stream_live_route_uses_web_filler`: for "do the nuggets play tonight" the first delta is in `WEB_FILLERS`
  - `test_stream_unplanned_search_line_once`:
    - a "why…" keyword route whose scripted stream is `[SEARCH_STARTED, SEARCH_STARTED, "Answer."]`
    - deltas are a normal filler, then `" Let me check the web real quick."` exactly once, then `"Answer."`
  - `test_stream_no_search_line_after_text`: the stream `["Part", SEARCH_STARTED, " two."]` gives no web line
  - `test_stream_live_route_no_extra_line`: on a live route, `SEARCH_STARTED` adds no second line
  - `test_search_blocks_kept_in_history`:
    - the scripted result content holds `server_tool_use`, `web_search_tool_result` and `text` blocks
    - the next request's messages contain that assistant content unchanged
    - the spoken text is only the text
  - `test_followup_after_search_stays_tier2`: the next turn's route reason is `"sticky"`, and the provider call includes `WEB_SEARCH_TOOL`
  - `test_pause_turn_continued_once`:
    - the first result has `stop_reason="pause_turn"`, the second `"end_turn"`
    - two provider calls are made, and the second call's messages end with an assistant message holding the first content
    - history stores one merged assistant message (first content + second content)
    - speech = both texts
  - `test_pause_turn_no_time_left`: the clock is advanced past the deadline after the first call; the partial text is spoken if there is any, otherwise `ERROR_LINE`; nothing is silent
  - `test_logs_web_searches`: `usage.web_search_requests=2` is logged as `web_searches=2` and the cost includes `0.02`
  - `test_soft_cap_live_downgrades`: with spend ≥ soft cap, a live question goes to Tier 1 with reason `"soft_cap"` and no server tools
- [ ] **Step 2: Run them;** they fail.
- [ ] **Step 3: Implement.**
  - Pass `server_tools=[WEB_SEARCH_TOOL]` on every Tier 2 call (`_call` when `tier == 2`, and `_stream_call`).
  - Filler kind is `"web"` when the reason is `"live"`.
  - In `_stream_call`:
    - on `SEARCH_STARTED` with no model text yet, a reason other than `"live"`, and the line not yet emitted: yield the web line (not counted as model text);
    - otherwise skip the sentinel.
  - Handle `pause_turn` in one shared helper used by both paths.
  - `_log` gains `web_searches=usage.web_search_requests or None`.
- [ ] **Step 4: Run the full suite;** it passes.
- [ ] **Step 5: Commit** `feat(brain): web search on tier 2 with web fillers`.

### Task 5: Deploy, live check, docs (controller and family)

- [ ] **Step 1:** Rebuild and redeploy the brain: `docker compose build brain && docker compose up -d --no-deps brain`. Then run `python scripts/smoke_test.py`, which must pass 7/7.
- [ ] **Step 2: Live checks through `/v1/converse/stream` (curl) and the Voice PE:**
  - "Do the Nuggets play tonight?": web filler, current answer in Pacific time, no URLs
  - "Who won the last 49ers game?"
  - "What's in the news today?"
  - Follow-up "what time?" after a search
  - "Why is the sky blue?": no search
  - "What's the weather tomorrow?": no search
  - The parent page shows Searches.
- [ ] **Step 3:** Update `docs/project-log.md` (entry + "what she can do"), `docs/troubleshooting.md` (search answers, the web line) and `README.md` (spec link). Commit.
- [ ] **Step 4:** Push the branch and open a PR. The base is `streaming-answers` until PR #1 merges, then `master`.
