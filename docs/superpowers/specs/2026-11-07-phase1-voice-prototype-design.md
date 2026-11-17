# Destiny — Phase 1: Working Voice Prototype (Design Spec)

Date: 2026-11-07
Status: Implemented — Phase 1 verified live 2026-11-17

## 1. Goal

Say a wake word to one voice device, ask a question, and hear a natural spoken
answer from Claude. Follow-up questions ("What about Saturday?") work without
repeating context.

Phase 1 uses existing open-source parts. No custom AI code is written yet; the
custom "brain" service arrives in Phase 2.

## 2. What we're building on (decisions already agreed)

| Concern | Choice | Why |
|---|---|---|
| Voice pipeline | Home Assistant **Assist** | Already chains wake word → STT → agent → TTS, handles conversation IDs and follow-ups |
| Voice endpoint | **Home Assistant Voice Preview Edition** (purchased) | On-device wake word, echo cancellation, mute switch, finished case |
| Assistant name | **Destiny** | She introduces herself as Destiny; the system prompt and pipeline use this name |
| Wake word | Stock on-device **"Okay Nabu"** (the device default) or "Hey Jarvis" for now | **"Hey Destiny"** needs custom model training — its own task after Phase 1 |
| Speech-to-text | **faster-whisper** via Wyoming, running locally | Private, free; this PC (Ryzen 7 5700X, 48 GB) runs it fast |
| Text-to-speech | **Piper** via Wyoming, running locally | Free, private, good enough to prove the loop; voice is a swappable setting |
| AI agent | Home Assistant's built-in **Anthropic** conversation integration | Zero custom code for Phase 1; replaced by our brain in Phase 2 |
| Host (now) | **This Windows PC, Docker Desktop** | $0; move to a mini PC later without changing the compose file |

## 3. Architecture

```
 Voice PE (Wi-Fi)                    Windows PC — Docker Desktop
 ┌────────────────┐   ESPHome API   ┌──────────────────────────────────────┐
 │ wake word      │◄──────────────► │ homeassistant  (port 8123)           │
 │ (on device)    │   audio in/out  │   Assist pipeline "Destiny"          │
 │ mic + speaker  │                 │     STT  ──► whisper  (Wyoming 10300)│
 └────────────────┘                 │     agent ─► Anthropic integration ──┼──► Claude API
                                    │     TTS  ──► piper    (Wyoming 10200)│
 Phone / browser ── Assist UI ────► │                                      │
 (for testing before PE arrives)    └──────────────────────────────────────┘
```

Three containers in one `docker-compose.yml`:

- `homeassistant` — `ghcr.io/home-assistant/home-assistant:stable`, config in `./ha/config`, port 8123.
- `whisper` — `rhasspy/wyoming-whisper`, model `small-int8` to start (try `medium-int8` if accuracy is poor), language `en`.
- `piper` — `rhasspy/wyoming-piper`, one English voice (UK or US — chosen during setup).

Image versions are pinned in `.env` so upgrades are deliberate.

**Networking note (Windows):** Docker Desktop doesn't support host networking
reliably, so Home Assistant won't auto-discover the Voice PE. We add it manually
via the ESPHome integration using the device's IP address. Give the Voice PE a
fixed IP (DHCP reservation on the router) so this doesn't break.

## 4. Setup flow

1. **You** install Docker Desktop (free for personal use; you accept its licence).
2. `docker compose up -d` starts the three services.
3. Home Assistant onboarding in the browser (you create the owner account).
4. Add Wyoming integrations for whisper and piper (`whisper:10300`, `piper:10200`).
5. **You** add the Anthropic integration and paste your API key into Home Assistant's
   UI. The key is stored by Home Assistant, never in this repo.
6. Create an Assist pipeline "Destiny": faster-whisper → Anthropic → Piper.
   Agent settings: model choice (your call — Haiku is fastest/cheapest, a
   Sonnet model tutors better), a household system prompt (she is "Destiny", a
   friendly family assistant who speaks in plain sentences, gives 1-2 sentence
   answers to quick questions and 3-5 sentence chunks for explanations, then
   asks if they want more; acts as a tutor for learning and homework, using
   hints rather than answers; uses simple words for children; admits
   uncertainty; and says she's an AI if asked), "prefer handling commands
   locally" on.
   "Device control" is ticked, but **only the weather entity is exposed**
   (Met.no, free, created during onboarding) — so Claude can answer weather
   questions but can't touch any device. Phase 1 limit: she sees current
   conditions only, not forecasts (forecasts and web access come in Phase 2).
   Device exposure is widened deliberately in Phase 4.
7. Test by typing and by phone/browser microphone — **works before the Voice PE arrives.**
8. When the Voice PE arrives: Wi-Fi setup via the HA companion app, reserve its IP,
   add via ESPHome integration, assign the "Destiny" pipeline and wake word,
   plug in an external speaker via 3.5 mm if wanted.

## 5. Repository layout (Phase 1)

```
Destiny/
├── README.md                  # what this is, quick start
├── docker-compose.yml
├── .env.example               # image tags, whisper model, piper voice, timezone
├── .gitignore                 # ignores .env, ha/config secrets, .storage, logs
├── ha/config/                 # Home Assistant config (mostly generated; secrets ignored)
├── scripts/
│   └── smoke_test.py          # automated checks (stdlib only — runs on Python 3.8+)
├── tests/                     # unit tests for smoke_test helpers
└── docs/
    ├── setup-windows.md       # step-by-step setup above, with screenshots-worthy detail
    ├── voice-pe-setup.md      # device onboarding
    ├── troubleshooting.md
    └── superpowers/specs/     # this spec
```

Phase 2 adds `brain/` (FastAPI) and `ha/custom_components/destiny/`; nothing in
Phase 1 blocks that.

## 6. Testing — what "done" means

Automated (`scripts/smoke_test.py`, reads `HA_URL` and a long-lived token from `.env`):
1. Whisper and Piper ports accept Wyoming connections and report their info.
2. Home Assistant API responds.
3. Single question via `/api/conversation/process` returns a non-empty answer.
4. **Multi-turn:** ask about the weather tomorrow, then "What about Saturday?"
   using the same `conversation_id`; the second answer must reference Saturday
   weather, not ask what you mean.
5. TTS: Piper returns audio for a sample sentence.

Manual (cannot be automated here):
6. Phone/browser mic: spoken question → spoken answer.
7. Voice PE: "Okay Nabu, …" → spoken answer; follow-up within the conversation window.
8. Record rough end-to-end latency (target ≤ 4 s; Alexa is ~1 s).

Nothing is reported as working until these have actually run.

## 7. Privacy & secrets

- Audio is processed locally (wake word on device, Whisper and Piper on this PC);
  only the transcribed text goes to Claude.
- No raw audio is stored.
- `.env` and Home Assistant's `secrets.yaml` / `.storage/` are git-ignored.
- The Anthropic key lives only in Home Assistant's encrypted storage.

## 8. Costs in Phase 1

- Hardware: Voice PE (~$60, purchased). Optional external speaker.
- Claude API: pay-as-you-go; testing will cost cents. Set a monthly spend limit
  in the Anthropic Console.
- Everything else: free.

## 9. Out of scope for Phase 1

Custom brain service, profiles, child mode, memory, dashboard, device control,
shopping/reminders/calendar, music, custom "Hey Destiny" wake word, multi-room.
Each comes in its own later phase with its own spec.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Docker Desktop / WSL2 quirks on Windows | Documented troubleshooting; fall back to Docker Engine inside the existing WSL2 Ubuntu |
| Voice PE not reachable from container | Manual add by IP with DHCP reservation |
| Whisper mishears (esp. kids) | Try `medium-int8`; fall back to cloud STT later |
| Latency feels slow | Measure first; Haiku model, streaming TTS, smaller Whisper model |
| PC off = assistant off | Accepted for prototype; mini PC in Stage 2 |
