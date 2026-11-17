# Destiny project log

A running record of what's built, what was decided and why, and what's next. Newest entries at the top. Add an entry whenever a phase, decision or setup change lands.

## Current status

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
