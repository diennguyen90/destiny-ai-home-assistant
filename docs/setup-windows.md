# Destiny setup on Windows

Follow these steps in order. Each step says what you should see when it worked. Commands are run in PowerShell, in the project folder (`C:\dev\Destiny`).

## 1. Install Docker Desktop

1. Download Docker Desktop for Windows from https://www.docker.com/products/docker-desktop/ and install it. It is free for personal use; you accept its licence. Keep the "Use WSL 2" option ticked.
2. Restart if asked, then start Docker Desktop.
3. You should see: the Docker whale icon in the system tray, and Docker Desktop showing "Engine running" (green) at the bottom left.
4. Check in PowerShell: `docker --version` prints a version number.
5. Make Docker start by itself, so Destiny comes back after a PC restart: in Docker Desktop go to Settings > General, tick "Start Docker Desktop when you sign in to your computer", then click Apply. (If Docker Desktop is not running, http://localhost:8123 will not load.)

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
5. On the "We found..." screen, if the Meteorologisk institutt (Met.no) weather integration is offered, add it. This gives you the free weather entity (it shows as "Home"; its id looks like `weather.forecast_home`). If it is not offered, go to Settings > Devices & services > Add integration > "Meteorologisk institutt (Met.no)" and add it.
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
4. You should see an Anthropic entry. Its conversation agent is listed as "Claude conversation".

## 6. Configure Destiny's agent and assistant

Destiny's main jobs are answering daily questions and helping with learning. Smart-home control is secondary and comes later.

**Agent settings**

1. Go to Settings > Devices & services > Anthropic. Next to "Claude conversation", click the cog to configure it.
2. Instructions: Home Assistant fills this box with its own default text. Delete it and paste the Destiny prompt below. Paste it as ONE paragraph (do not add line breaks); the editor auto-indents multi-line pastes and makes a mess.

```
You are Destiny, a friendly AI assistant for our family. You are speaking out loud, so speak in natural sentences with no lists, markdown, emojis or symbols. Quick questions get 1-2 sentence answers. For explanations, speak in short chunks of 3-5 sentences, then ask if they want more. When someone is learning or doing homework, be a tutor: don't just give the answer; give a hint or ask a small question and let them try first. If the person sounds like a child, use simple words and everyday examples. If you are unsure or something may be out of date, say so. Always keep it family-friendly. If asked, say you are an AI.
```

   Why it ends answers with a question: the Voice PE keeps listening after Destiny asks a question, so you can answer or ask a follow-up without saying the wake word again.

3. AI tools: tick "Device control" (it only reaches entities you expose, see below). Leave "Home Assistant" unticked.
4. Model: this is your choice.
   - "Recommended model settings" ticked uses Claude Haiku: fast and cheap, roughly $1-2 a month at about 100 questions a day.
   - For better tutoring and explanations, untick it and choose a Sonnet model: roughly $20-25 a month at the same usage.
5. Save (Submit).

**Create the Destiny assistant**

1. Go to Settings > Voice assistants > Assistants tab > "Add assistant".
2. Name: `Destiny`.
3. Conversation agent: "Claude conversation". Leave "Prefer handling commands locally" on (it handles timers, the time and the shopping list quickly and for free).
4. Speech-to-text: faster-whisper.
5. Text-to-speech: piper. Language `en_GB`, Voice "cori (high)" (more natural than alba). Piper downloads the voice automatically the first time it is used, which needs internet and takes a few seconds. "Try voice" plays a sample.
6. Click Create.
7. On Destiny's row, open the three-dot menu (⋮) > "Set as preferred". Destiny now has a star.

**Expose only the weather entity**

1. Still in Settings > Voice assistants, on the Assistants tab, turn OFF "Expose new entities". It is on by default and would give Claude every device you add later.
2. Open the Expose tab > "Expose entities" and search "weather". The entity shows as "Home" with a sun icon (its id looks like `weather.forecast_home`). Tick it and click Expose.
3. Remove any other exposed entities. You should see exactly one exposed entity: the weather. Claude can then answer weather questions but cannot control any device. (Widening this is a deliberate later step.)

**Known Phase 1 limit: no forecasts.** Destiny sees current conditions (temperature, sky, humidity) but not forecasts. If you ask about tomorrow she will say she can't see the forecast. Forecasts and web access come in Phase 2.

**Quick test**

Click the assist icon (top right of the dashboard), choose the Destiny assistant, and type "What is the weather like right now?" You should get a short spoken-style answer with the current conditions. Then ask a follow-up such as "Is that warm or cold?" and check it understands what you mean. The microphone button lets you test by voice from your browser (allow microphone access).

## 7. Create a token and run the smoke test

1. In Home Assistant, click your name at the bottom left to open your Profile, then the Security tab.
2. Scroll to "Long-lived access tokens", click Create token, name it `destiny-smoke-test`, and copy the token shown (it is shown only once).
3. Open `.env` in Notepad and paste it after `HA_TOKEN=` (no quotes, no spaces). Save. `.env` is git-ignored.
4. Find the Anthropic agent's entity ID, so the smoke test talks to Claude and not Home Assistant's built-in agent: Settings > Devices & services > Entities, search "conversation", and copy the entity ID of the Anthropic agent (it looks like `conversation.claude_conversation`; the UI wording may vary by version). In `.env`, put it after `HA_AGENT_ID=`, next to `HA_TOKEN`. Save.
5. The smoke test needs Python 3.8 or newer. Check with `python --version`; if it is missing, install Python from https://www.python.org/.
6. Go to the project folder first: `cd C:\dev\Destiny`. Running the script from another folder gives a "No such file" error.
7. Run the smoke test: `python scripts\smoke_test.py`.
8. You should see each check pass, in this order: `whisper`, `piper`, `piper-audio` (Piper returns audio), `ha-api`, `conversation` (a question gets an answer) and `multi-turn` (the question is about the weather right now, and the follow-up "And how humid is it?" must mention humidity). With the Phase 2 brain set up (section 9) there is also a `brain` check after `piper-audio`.

## 8. Windows Firewall for the Voice PE

The Voice PE (your voice device) downloads spoken answers from Home Assistant on port 8123, so Windows Firewall must allow inbound TCP 8123 on your Private network. The Voice PE guide starts by setting Home Assistant's local URL to your PC's address, then covers the firewall rule ([Voice PE setup](voice-pe-setup.md), steps 2 and 3) before connecting the device with the phone app. Follow that guide from the top, starting with the check that the PC and the Voice PE are on the same network. Your phone must always use `http://<PC-IP>:8123`, never `localhost`.

## 9. Phase 2: Destiny's brain

The brain is a small service (port 8000) that sits between Home Assistant and Claude. It routes easy questions to a cheap model and harder ones to a stronger model, keeps conversation history, and stops spending at a daily cap. Timers, the time and the shopping list still work even if the brain is down.

1. Fill in the brain section of `.env` (open it in Notepad; no quotes, no spaces; never share or commit this file):
   - `ANTHROPIC_API_KEY`: an API key from https://console.anthropic.com/ for the brain (set a monthly spend limit there).
   - `BRAIN_SHARED_KEY`: any long random string. Home Assistant sends it to the brain; you enter the same value in step 4.
   - `DESTINY_PARENT_PIN`: the PIN for the parent page (step 7).
   - `BRAIN_HA_URL`: leave as `http://homeassistant:8123`.
   - `BRAIN_HA_TOKEN`: a token for a new non-admin Home Assistant user. In Home Assistant go to Settings > People > Users tab > Add user, name it `destiny-brain`, set a password, and leave "Administrator" turned off. Open a private (incognito) browser window, sign in to Home Assistant as `destiny-brain` once, then click its name at the bottom left to open Profile > Security tab > Long-lived access tokens > Create token, and copy the token (it is shown only once). Paste it after `BRAIN_HA_TOKEN=`.
   - `HA_WEATHER_ENTITY`: leave as `weather.forecast_home` unless your weather entity has a different id.
   - `DESTINY_NOTIFY_SERVICE`: the Home Assistant notify service for your phone, for example `mobile_app_<phone>`. Find it in Home Assistant under Developer tools > Actions by searching `notify.mobile_app`. Leave blank for none.
   - `TZ`: your timezone, for example `America/Los_Angeles`. The daily spend caps reset at midnight in this timezone.
   - `DESTINY_SOFT_CAP_USD` and `DESTINY_HARD_CAP_USD`: daily spend caps in dollars. At the soft cap Destiny switches to the cheaper model; at the hard cap she stops calling Claude until tomorrow. The defaults are 1.0 and 3.0.
   - `BRAIN_URL`: used by the smoke test; leave as `http://localhost:8000`.
2. Build and start the brain: `docker compose up -d --build`. Then `docker compose ps` should show `brain` as `Up`, and http://localhost:8000/health should show `{"status":"ok"}`.
3. Windows Firewall: allow inbound TCP 8000 on the Private profile only, the same way as the 8123 rule in [Voice PE setup](voice-pe-setup.md), step 3. In an administrator PowerShell: `New-NetFirewallRule -DisplayName "Destiny brain 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private`. This is only needed to open the parent page from your phone or another computer.
4. Restart Home Assistant (`docker compose restart homeassistant`), then go to Settings > Devices & services > Add integration, search "Destiny", and enter the brain URL `http://brain:8000` and the shared key (the value of `BRAIN_SHARED_KEY` in `.env`). Submit.
5. Go to Settings > Voice assistants > Destiny and set Conversation agent to "Destiny brain". Save.
6. Run the smoke test as in section 7 (`python scripts\smoke_test.py`). You should now see seven checks pass, in this order: `whisper`, `piper`, `piper-audio`, `brain`, `ha-api`, `conversation` and `multi-turn`. The `conversation` check asks about the weather right now and fails if Destiny says she can't see it; the `multi-turn` follow-up "And how humid is it?" must mention humidity.
7. Open the parent page at `http://<PC IPv4>:8000/parent` (your PC's address from `ipconfig`; from your phone, use the same address) and enter the PIN you set as `DESTINY_PARENT_PIN`. It shows today's spend and the cost of recent conversations.

**Rollback:** if the brain misbehaves, go to Settings > Voice assistants > Destiny and set Conversation agent back to "Claude conversation". Nothing else needs to change.

**Still not available:** forecasts and web search (milestone 4), memory between conversations, and knowing who is speaking.

## Troubleshooting

See [troubleshooting.md](troubleshooting.md) for symptoms and fixes. Quick commands:

- Check status: `docker compose ps`; logs: `docker compose logs <service> --tail 50` (services: `homeassistant`, `whisper`, `piper`).
- Restart a service: `docker compose restart whisper`.
- Whisper mishears: set `WHISPER_MODEL=medium-int8` in `.env`, then `docker compose up -d`.
- Stop everything: `docker compose down` (your Home Assistant data in `ha/config` is kept).
