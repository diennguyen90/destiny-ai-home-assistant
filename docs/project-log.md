# Destiny project log

A running record of what's built, what was decided and why, and what's next. Newest entries at the top. Add an entry whenever a phase, decision or setup change lands.

## Current status

**Phase 2: brain live, with streaming answers and internet search (2026-11-26).**

Destiny runs through her own brain with Haiku/Sonnet routing, spend caps, a parent cost page, streamed answers with thinking fillers, and web search for live questions. Voice: ElevenLabs "Serena" (Piper as fallback). Smoke test: 7/7.

What she can do now:
- general questions, explanations and homework help (hints, not answers)
- stories, jokes and quizzes, translation, time and date, timers, the shopping list
- current home weather and a 3-day forecast
- live questions from the web: news, sports (the 49ers and Nuggets by default), schedules, prices
- one-time reminders pushed to the phone, and reading or adding calendar events (once Google Calendar is linked)

What she can't do yet:
- Google Calendar is not linked yet (family to follow the [setup guide](google-calendar-setup.md))
- knowing who is speaking, music, smart-device control (deliberately off)

## Roadmap (reprioritised 2026-11-07: learning first, smart home second)

1. **Phase 1: voice prototype.** Done.
2. **Phase 2: Destiny's own brain** (FastAPI service between Home Assistant and Claude):
   - family profiles and speaker awareness
   - learning mode with per-child memory and progress
   - child safety and parent controls
   - web search (current events, forecasts)
3. **Later:**
   - reminders, calendar and music
   - custom "Hey Destiny" wake word
   - smart-home device control
   - dashboard
   - more rooms (more Voice PEs)
   - move to an always-on mini PC

## Log

### 2026-11-26: Reminders and calendar

- **Reminders** (built, one-time only):
  - "Remind me at 5 to take out the trash" or "in 20 minutes". She can list and cancel them too.
  - The brain stores them in its own database and a background scheduler checks every 15 seconds, then pushes each one to the phone through HA notify (`mobile_app_iphone`). They survive restarts. More than 5 minutes late is sent as "(Late)"; more than 24 hours late is dropped.
  - Limits: 200 characters, up to a year ahead, 50 pending.
  - Reminders don't touch Google Calendar (a deliberate choice, to avoid clutter).
- **Calendar**: she reads events for a day or up to 14 days, and adds events (timed or all day). Editing and deleting events isn't supported. Any HA calendar entity works: the brain uses `DESTINY_CALENDAR_ENTITY` or else the first `calendar.*` it finds (cached 5 minutes). Until one exists she says "The family calendar isn't connected yet."
- **Household tool loop**: the brain runs these tools itself (up to 3 rounds per answer), and reminder or calendar words route to Haiku.
- **To do (family):** link Google Calendar in Home Assistant using the [setup guide](google-calendar-setup.md) (Web application OAuth client; publish the app so it doesn't expire weekly). Then verify with "What's on our calendar today?".
- **Next:** speaker awareness and per-person reminders, then the "Destiny" wake word.
- Spec: [calendar and reminders design](superpowers/specs/2026-11-26-calendar-reminders-design.md); plan: [calendar and reminders plan](superpowers/plans/2026-11-26-calendar-reminders.md).

### 2026-11-26: Internet search, plus streaming answers

- **Streaming answers** (PR #1): on longer questions she says a short "thinking" filler at once, then streams Claude's answer into ElevenLabs. On Sonnet, the first word now arrives 0.6–1.5 s after the question reaches the brain.
- **Web search** (Anthropic's server-side search, Sonnet only):
  - Live questions route straight to Sonnet: news, headlines, scores, standings, prices, "open now", the 49ers/Nuggets, or a time word plus a game word. Kid talk ("chicken nuggets for dinner", "I won my game today") doesn't search.
  - She says one filler (a web filler like "Let me look that up online real quick…" for live questions, a normal one otherwise), then stays quiet until the answer. During searches the brain sends silent keep-alive pings so Home Assistant doesn't give up.
  - Answers are spoken without links, in Pacific time.
  - Live results:
    - Nuggets schedule: 1 search, about 3.5¢, first word of the answer after 8.5 s.
    - News headlines and the last 49ers score (2–3 searches): longest silence 3.4 s.
  - Cost: about 1¢ per search plus reading. A "Searches" column is on the parent page, and searches count toward the $1/$3 daily caps. After the soft cap, a conversation that already searched stays on Sonnet, because Haiku can't read search results.
- **Incidents on 2026-11-18** (added to troubleshooting):
  - Docker Desktop's port forwarding stalled, so the Voice PE couldn't fetch audio. Restarting Docker Desktop fixed it.
  - An ElevenLabs outage left its setup stuck, so we used Piper and then restarted Home Assistant.
  - Later, the Claude API key was replaced, causing 401 errors. Updated `.env` and recreated the brain.
- **Next:** calendar and reminders (Google Calendar, reminders sent to the phone), then the "Destiny" wake word.
- Spec: [web search design](superpowers/specs/2026-11-26-web-search-design.md); plan: [web search plan](superpowers/plans/2026-11-26-web-search.md).

### 2026-11-17 (evening): Voice, forecast and live fixes

- **Voice:**
  - Now ElevenLabs "Serena – Gentle Coach and Wellness Guide" on the Multilingual v2 model, stability 0.7.
  - Flash sounded rushed. Multilingual v2 costs about 2× the credits per character.
  - Piper stays installed as the free fallback.
- **Brain fix:** switching between Haiku and Sonnet in one conversation caused a 400 ("thinking block bound to a different conversation… tools list differs"). All calls now send `thinking.block_binding.prefix_mismatch_behavior: "drop_block"` (beta `thinking-binding-controls-2026-08-01`). Failed calls now log Anthropic's detailed error.
- **Forecast:** the brain adds a 3-day daily forecast from `weather.get_forecasts` to the per-turn context, so Destiny answers "what's the weather tomorrow?".
- **Voice PE:**
  - "Finished speaking detection" set to `relaxed` for pauses and kids.
  - A stuck red ring (known firmware glitch) was cleared by toggling the mute switch.
  - An external speaker on the 3.5 mm jack works.
- **Usage so far:**
  - 48 Claude requests through the brain, about $0.07 total.
  - Haiku: 26 requests, about $0.002.
  - Sonnet: 22 requests, about $0.064.

### 2026-11-17: Phase 2 milestone 1 (brain parity) verified live

- **Destiny now runs through her own brain** (a FastAPI container) via the "Destiny brain" conversation agent.
- **Smoke test: 7/7 passed.** She reports real current weather (`weather.home`) and remembers the conversation.
- **Voice PE checks:**
  - Time is answered free by Home Assistant.
  - Quick questions go to Haiku (brain time about 0.9 s).
  - "Why…" questions go to Sonnet (about 2.8 s).
  - A follow-up after her question works without the wake word. Answer after the light ring shows she's listening.
- **End-to-end delay is about 5 s:** speech-to-text 1.5 s, brain 0.9–2.8 s, voice preparation about 1 s.
- **Next speed win:** stream the answer so she starts speaking the first sentence early. Planned for milestone 2.
- **Voice** changed to Piper `en_US-lessac-high` (American female).
- **Audio:** the built-in speaker gets scratchy at full volume. Keep it around 70–80%, or use a 3.5 mm speaker.
- **Settings and accounts:**
  - Parent cost page at `http://192.168.86.143:8000/parent` (PIN-protected).
  - Firewall rule for TCP 8000, Private profile only.
  - New non-admin HA user `destiny-brain` for the brain's token.
- **Fixed during review:**
  - The Voice PE never adopts the conversation id the agent returns, so the brain now adopts the id it is sent.
  - Time and weather context moved out of the fixed system prompt into a per-turn system message, so replayed thinking stays valid.
  - History resets after 12 turns instead of being trimmed.
  - A single model attempt with a 13.5 s deadline.
  - An empty answer now gets the error line instead of silence.
- **Known issue:** the old Phase 1 "Claude conversation" (Anthropic integration) fails to load, probably because its API key was removed. It's no longer used. For rollback, use HA's built-in agent or remove the integration.

### 2026-11-17: Wake word decision

- The custom wake word will be **"Destiny"** (not "Hey Destiny"), so Oliver can wake her by shouting her name.
- If false wake-ups get annoying, we retrain for "Hey Destiny".
- "Okay Nabu" stays as a second, backup wake word.
- Scheduled alongside Phase 2 milestone 2 (profiles, Oliver mode).
- Needs a custom-trained microWakeWord model and custom ESPHome firmware on the Voice PE, built from an ESPHome container. After that, firmware updates are done manually.

### 2026-11-17: Phase 2 input: model routing (from Andrew)

- **Advice:** use a cheap "decision" model to route requests, so simple things go to tiny or free models and complex ones to bigger models. Add logging and guardrails to see where it's lapsing. Try cheap models (DeepSeek Flash, GLM Flash, Cloudflare Workers AI) for cheap tasks. Start simple and expand when needed.
- **Adapted for Destiny:**
  - Tier 0: Home Assistant's built-in commands, which already cost $0 (lights, timers, time).
  - Tier 1: Haiku for everyday questions.
  - Tier 2: Sonnet for tutoring and long explanations.
  - Routing: rules first, with Haiku deciding only when unclear, because a router call adds voice delay.
  - Logging of model, cost, latency and outcome from day one.
  - Providers are pluggable, so cheaper ones can be tried where the logs justify it.
  - Kids' traffic stays on a provider with vetted data and safety policies.

### 2026-11-17: Phase 1 live setup and verification

- **Home Assistant setup:**
  - Destiny assistant created: Claude conversation, faster-whisper, Piper en_GB cori (high).
  - Set as the preferred assistant.
  - Only the weather entity is exposed, and "Expose new entities" is turned off.
- **Claude instructions:** replaced with the tutor-style Destiny prompt (see [setup guide](setup-windows.md) section 6), because the main use is daily questions and learning. The model is still Haiku (cheap and fast). Switching to Sonnet (~$20–25/month) for better tutoring is an open option.
- **Network:**
  - The PC was on the AT&T gateway's network (192.168.1.x), but Wi-Fi comes from Google Nest Wifi, which runs its own network (192.168.86.x), so Home Assistant couldn't reach the Voice PE.
  - Fixed by moving the PC's Ethernet cable to the Nest router: the PC is now 192.168.86.143 and the Voice PE 192.168.86.32.
  - The network is set to Private, with a firewall rule for TCP 8123 (Private profile only).
  - Home Assistant's local URL is `http://192.168.86.143:8123`.
- **Voice PE:**
  - Added via ESPHome by IP.
  - The setup wizard's "say the wake word again" step hung, so it was skipped.
  - The wizard defaulted to its own "Full local assistant" (no Claude), which was changed to Destiny.
- **Audio:** the Voice PE has no Bluetooth audio output. A louder speaker uses the 3.5 mm AUX jack.
- **Docs** updated with all of the above ([setup](setup-windows.md), [Voice PE](voice-pe-setup.md), [troubleshooting](troubleshooting.md)).
- **To do:**
  - Reserve both IPs in the Google Home app (DHCP reservations).
  - Turn on Docker Desktop's "start when you sign in".
- **Known gaps:**
  - The smoke test's weather checks can pass even when Destiny has no weather data. It should fail when she says she can't see the weather.
  - Forecasts aren't available until Phase 2.
  - (Update: the smoke test weather gap was fixed in Phase 2 milestone 1.)

### 2026-11-07: Plan and build

- Reviewed the original handoff. Chose Home Assistant Assist plus the Anthropic integration for Phase 1 (no custom code), with the custom brain planned for Phase 2.
- Hardware:
  - Voice PE purchased.
  - Using the existing Windows PC (Docker Desktop) for now.
  - Planned move to an N100/N150 mini PC.
- Named the assistant Destiny.
- Project moved out of OneDrive to `C:\dev\Destiny`, since syncing would risk corrupting Home Assistant's database.
- Built:
  - Docker Compose stack (Home Assistant, whisper, piper)
  - a stdlib-only smoke test (25 unit tests)
  - setup, Voice PE and troubleshooting guides
- Plan and spec: [design spec](superpowers/specs/2026-11-07-phase1-voice-prototype-design.md), [implementation plan](superpowers/plans/2026-11-07-phase1-voice-prototype.md).
- Decided usage priority: daily questions and education first, smart devices second.
