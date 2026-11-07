# Destiny setup on Windows

Follow these steps in order. Each step says what you should see when it worked. Commands are run in PowerShell, in the project folder (`C:\dev\Destiny`).

## 1. Install Docker Desktop

1. Download Docker Desktop for Windows from https://www.docker.com/products/docker-desktop/ and install it. It is free for personal use; you accept its licence. Keep the "Use WSL 2" option ticked.
2. Restart if asked, then start Docker Desktop.
3. You should see: the Docker whale icon in the system tray, and Docker Desktop showing "Engine running" (green) at the bottom left.
4. Check in PowerShell: `docker --version` prints a version number.

## 2. Start the services

1. Create your settings file: `copy .env.example .env`
2. Optional: open `.env` in Notepad and set `TZ` to your timezone (for example `America/New_York`). Leave everything else as is.
3. Start everything: `docker compose up -d`
4. Check: `docker compose ps`
5. You should see three services, `homeassistant`, `whisper` and `piper`, all with status `Up`. The first start downloads images and the speech model/voice, so give it a few minutes. To watch progress: `docker compose logs whisper piper --tail 20` should eventually show that each service is ready or listening (the exact wording varies by version).

## 3. Home Assistant onboarding

1. Open http://localhost:8123 in your browser.
2. You should see "Welcome to Home Assistant". Click "Create my smart home".
3. Create the owner account (name, username, password). Choose your own password and keep it safe.
4. Set your home location and country when asked. Opt out of analytics if you prefer.
5. On the "We found..." screen, if the Meteorologisk institutt (Met.no) weather integration is offered, add it. This gives you the free weather entity (usually `weather.home`). If it is not offered, go to Settings > Devices & services > Add integration > "Meteorologisk institutt (Met.no)" and add it.
6. You should see the Home Assistant dashboard.

## 4. Add the Whisper and Piper integrations

Home Assistant runs in Docker, so it reaches the other containers by service name, not `localhost`.

1. Go to Settings > Devices & services > Add integration, search for "Wyoming Protocol" and select it.
2. Host: `whisper`   Port: `10300`   then Submit. You should see "faster-whisper" added.
3. Add integration again > "Wyoming Protocol". Host: `piper`   Port: `10200`   then Submit. You should see "piper" added.

## 5. Add the Anthropic integration

1. Create an API key at https://console.anthropic.com/ (also set a monthly spend limit there; testing costs cents).
2. In Home Assistant: Settings > Devices & services > Add integration > "Anthropic".
3. Paste your API key into the box and Submit. The key is stored by Home Assistant only; never put it in this repo or in `.env`.
4. You should see an Anthropic entry with a conversation agent.

## 6. Configure Destiny's agent and pipeline

**Agent settings**

1. On the Anthropic integration, click the conversation agent's settings (the gear / "Configure").
2. Model: choose a Haiku model (fastest and cheapest) to start.
3. Instructions (system prompt): replace the text with this block:

```
You are Destiny, a friendly family assistant living in our home. Answer in one to three short sentences, written the way you would say them out loud: no lists, no markdown, no emoji. If someone asks, say you are an AI. If you do not know something, say so briefly.
```

4. Turn on "Control Home Assistant" (Assist API). Save.

**Pipeline**

1. Go to Settings > Voice assistants > Add assistant.
2. Name: `Destiny`. Language: English.
3. Conversation agent: the Anthropic agent. Turn on "Prefer handling commands locally" (a toggle in this dialog; wording may vary by version). Speech-to-text: faster-whisper. Text-to-speech: piper (voice `en_GB-alba-medium`). Leave wake word empty for now. Create.
4. Optionally mark it as the preferred assistant (the star / three-dot menu).

**Expose only the weather entity**

1. Go to Settings > Voice assistants > Expose tab.
2. Make sure the weather entity (for example `weather.home`) is exposed. Remove any other exposed entities; click "Expose entities" to add the weather one if it is missing.
3. You should see exactly one exposed entity: the weather. Claude can then answer weather questions but cannot control any device. (Widening this is a deliberate later step.)

**Quick test**

Click the assist icon (top right of the dashboard), choose the Destiny pipeline, and type "What is the weather tomorrow?" then "What about Saturday?". You should get short spoken-style answers that mention the weather, and the second answer should refer to Saturday. The microphone button lets you test by voice from your browser (allow microphone access).

## 7. Create a token and run the smoke test

1. In Home Assistant, click your name at the bottom left to open your Profile, then the Security tab.
2. Scroll to "Long-lived access tokens", click Create token, name it `destiny-smoke-test`, and copy the token shown (it is shown only once).
3. Open `.env` in Notepad and paste it after `HA_TOKEN=` (no quotes, no spaces). Save. `.env` is git-ignored.
4. Find the Anthropic agent's entity ID, so the smoke test talks to Claude and not Home Assistant's built-in agent: Settings > Devices & services > Entities, search "conversation", and copy the entity ID of the Anthropic agent (it looks like `conversation.claude_conversation`; the UI wording may vary by version). In `.env`, put it after `HA_AGENT_ID=`, next to `HA_TOKEN`. Save.
5. The smoke test needs Python 3.8 or newer. Check with `python --version`; if it is missing, install Python from https://www.python.org/.
6. Run the smoke test: `python scripts/smoke_test.py`.
7. You should see each check pass, in this order: `whisper`, `piper`, `piper-audio` (Piper returns audio), `ha-api`, `conversation` (a question gets an answer) and `multi-turn` (the follow-up "What about Saturday?" refers to Saturday).

## 8. Windows Firewall for the Voice PE

The Voice PE (your voice device) downloads spoken answers from Home Assistant on port 8123, so Windows Firewall must allow inbound TCP 8123 on your Private network. The Voice PE guide starts by setting Home Assistant's local URL to your PC's address, then covers the firewall rule ([Voice PE setup](voice-pe-setup.md), steps 1 and 2) before connecting the device with the phone app. Follow that guide from the top. Your phone must always use `http://<PC-IP>:8123`, never `localhost`.

## Troubleshooting

See [troubleshooting.md](troubleshooting.md) for symptoms and fixes. Quick commands:

- Check status: `docker compose ps`; logs: `docker compose logs <service> --tail 50` (services: `homeassistant`, `whisper`, `piper`).
- Restart a service: `docker compose restart whisper`.
- Whisper mishears: set `WHISPER_MODEL=medium-int8` in `.env`, then `docker compose up -d`.
- Stop everything: `docker compose down` (your Home Assistant data in `ha/config` is kept).
