# Destiny — Internet Answers (Web Search) (Design)

Date: 2026-11-26
Status: Approved 2026-11-26 (short design: a small change)
Builds on: [Streaming answers](2026-11-17-streaming-answers-design.md) (branch `streaming-answers`, PR #1)

## 1. Intent

The family's main goal is for Destiny to answer questions that need the internet today. Examples:
- "Do the Nuggets play tonight, and what time?"
- "Who won the 49ers game?"
- "What's in the news today?"

The family's teams are the **San Francisco 49ers** (NFL) and the **Denver Nuggets** (NBA). While she searches she says something fun, like "One sec, surfing through the web for that…".

This is project 1 of 3. Calendar and reminders (sent to the phone, using the family's Google account) and other integrations come later as separate designs.

## 2. Goals, non-goals, anti-goals

- **Goals:**
  - Live questions get current, correct answers, spoken naturally.
  - The 2–4 s search wait is covered by a web-flavoured filler.
  - Searches count toward the existing spend caps.
- **Non-goals:**
  - Calendar and reminders.
  - The Team Tracker sports feed and game-day phone alerts (a later option).
  - Per-person search rules, which need profiles (milestone 2).
  - Web fetch of whole pages.
- **Anti-goals:**
  - Reading URLs or source lists aloud.
  - Searching for questions that don't need it, such as "why is the sky blue?".
  - A slow search leaving her silent.
  - Unsafe content for the kids.

## 3. Approaches

- **A. Anthropic's server-side web search tool. Chosen.** No new accounts, Claude decides when to search, and it costs about $10 per 1,000 searches plus tokens.
- **B. Team Tracker (ESPN) in Home Assistant.** Instant and free, but sports only and one team at a time. Deferred; worth adding for game-day alerts.
- **C. A third-party search API (Brave or Tavily).** Another key and client-side tool loop for about the same result. Rejected.

## 4. Design

### 4.1 Who searches
- **Only Tier 2 (Sonnet) has the tool.** It is `{"type": "web_search_20260209", "name": "web_search", "max_uses": 3, "user_location": {"type": "approximate", "region": "California", "country": "US", "timezone": "America/Los_Angeles"}}`.
  - Haiku 5.5 is not on that tool version's model list.
  - Giving Sonnet the tool keeps every search behind a filler.
- **Router:** a new rule routes live-information questions straight to Tier 2 with reason `"live"`. It sits after the sticky check and before the existing keyword rule.
  - Trigger words: today, tonight, tomorrow, yesterday, this week, this weekend, latest, current, right now, news, score, scores, game, games, playing, schedule, won, win, lost, standings, price of, stock, open now, 49ers, niners, nuggets, and similar.
  - **Weather words stay on the existing path.** Weather is already in context, so "weather tomorrow" must not trigger a search. Weather wins when both kinds of word match.
- **Haiku escalation:** the `needs_deeper_answer` tool description adds "or when the question needs current or live information from the internet (news, sports, schedules, prices, recent events)".

### 4.2 Fillers
- **Web filler list:** a new `WEB_FILLERS` tuple of 10–14 fun, spoken phrases, each at least 61 characters. Examples:
  - "One sec, I'm surfing through the web to find that out for you."
  - "Ooh, let me hop on the internet real quick and check on that one."
- **Which list is used:**
  - `route_reason == "live"`: a web filler.
  - Other Tier 2 or escalation: the normal filler.
- **No repeats:** the picker is per device, never repeats among the last 5, and takes a separate history per list.
- **Unplanned searches:** if a non-live Tier 2 answer starts a search *before any model text has streamed*, add a short web line once, such as " Let me check the web real quick." (no minimum length). If text has already streamed, add nothing.
- **Never stored:** fillers are never stored in history or sent to Claude, as today.

### 4.3 Prompt
Add these rules to the frozen `DESTINY_BASE`, which keeps the cache stable:
- **Teams:** "our team / the game" means the 49ers or Nuggets unless another team is named.
- **Times:** say times in Pacific time.
- **Spoken results:** speak them as a short spoken answer, with no links, URLs, citations or source lists. It's fine to say "according to ESPN" now and then.
- **Freshness:** if search finds nothing current, say so briefly instead of guessing.
- **Kids:** keep results family-friendly, and decline or soften adult or violent news for kids.

### 4.4 Provider and engine
- **Tools:** the provider passes server tools through unchanged. `ToolSpec` gains a way to send a raw server-tool dict, or the provider takes a separate `server_tools` list (builder's call).
- **Text:** `ProviderResult.text` joins only `text` blocks, as today. Search result blocks are kept in `content` and appended to history unchanged, as preserved thinking requires.
- **Streaming:** the provider surfaces a "search started" signal, from the `server_tool_use` content-block start, so the engine can apply the §4.2 unplanned-search line.
- **`pause_turn`:** if `stop_reason == "pause_turn"`, the engine re-sends once with the assistant content appended, within the remaining deadline. If no time is left, it speaks what it has, or the error line.
- **Cost:**
  - `Usage` gains `web_search_requests` from `usage.server_tool_use.web_search_requests`.
  - `cost_usd` adds `$0.01` per search.
  - A new nullable `web_searches` column goes in `requests`, migrated like `first_token_ms`, and is shown on the parent page.
- **Deadline:** unchanged. The 13.5 s budget still applies to the first token.

## 5. Testing

- **Unit tests:**
  - Router "live" words and weather exclusions.
  - Web filler length and spoken style, with no repeats.
  - Live route gives a web filler.
  - A Tier 2 answer that searches before any text gets the one-time web line, and gets none if text came first.
  - Server tool kwargs exact for Sonnet; none for Haiku.
  - Search cost and the `web_searches` column.
  - `pause_turn` is continued once.
  - Search result blocks are kept in history and none of their text is spoken.
- **Live:**
  - "Do the Nuggets play tonight?"
  - "Who won the last 49ers game?"
  - "What's in the news today?"
  - "Why is the sky blue?" (no search)
  - "What's the weather tomorrow?" (no search)
  - The smoke test still passes 7/7.

## 6. Left to the builder

- Exact web filler wording, within the rules.
- The final trigger word list.
- How server tools are passed through the provider.
- Parent page column placement.
