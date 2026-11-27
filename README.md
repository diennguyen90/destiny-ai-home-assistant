# Destiny

Destiny is a family voice assistant prototype. Say a wake word to a voice device, ask a question, and hear a spoken answer from Claude, with follow-up questions working. Phase 1 uses Home Assistant (Assist), local Whisper speech-to-text and local Piper text-to-speech in Docker on a Windows PC, talking to Claude through Home Assistant's Anthropic integration. Audio stays on your PC; only transcribed text goes to Claude.

## Quick start

Requires Docker Desktop (see the setup guide).

```
copy .env.example .env
docker compose up -d
docker compose ps
```

Then open http://localhost:8123 and follow the setup guide to finish configuration (Home Assistant account, Whisper/Piper/Anthropic integrations, the "Destiny" pipeline).

## Docs

- [Project log](docs/project-log.md): status, decisions and what's next
- [Windows setup guide](docs/setup-windows.md)
- [Voice PE setup](docs/voice-pe-setup.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Phase 1 design spec](docs/superpowers/specs/2026-11-07-phase1-voice-prototype-design.md)
- [Phase 2 design spec](docs/superpowers/specs/2026-11-17-phase2-destiny-brain-design.md)
- [Streaming answers design](docs/superpowers/specs/2026-11-17-streaming-answers-design.md)
- [Web search design](docs/superpowers/specs/2026-11-26-web-search-design.md)
- [Phase 2 milestone 1 plan](docs/superpowers/plans/2026-11-17-phase2-m1-brain-parity.md)

Secrets (`.env`, `data/`, Home Assistant's config) are git-ignored. Your Anthropic API key is entered only in Home Assistant's web UI.
