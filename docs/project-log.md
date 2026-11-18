# Destiny project log

A running record of what's built, what was decided and why, and what's next. Newest entries at the top. Add an entry whenever a phase, decision or setup change lands.

## Current status

**Phase 2 milestone 1 (Destiny's brain, parity with Phase 1): built, awaiting live verification.**

The brain service, tier routing, spend caps, parent cost page and the Home Assistant "Destiny brain" conversation agent are in. Setup: [setup guide](setup-windows.md) section 9. The smoke test now has a `brain` check (7 checks), and its weather checks fail when Destiny says she can't see the weather. Next: the family runs the live smoke test and switches the Destiny assistant to "Destiny brain".

Phase 1 status:

**Phase 1 (working voice prototype): done, verified live 2026-11-17.**

Destiny answers spoken questions through the Voice PE ("Okay Nabu"), with follow-ups, a tutor-style personality and the cori (high) voice. Smoke test: 6/6.

What she can do now: general questions, explanations and homework help (hints, not answers), stories, jokes and quizzes, translation, time and date, timers, the shopping list, and current home weather.

What she can't do yet: current events or web lookups, weather forecasts, memory between conversations, knowing who is speaking, reminders, calendar, music, or smart-device control (deliberately off).

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
