# Troubleshooting

Find the symptom you see, read the likely cause, and try the fix. Useful commands, run in PowerShell in the project folder (`C:\dev\Destiny`):

- Status: `docker compose ps`
- Logs: `docker compose logs <service> --tail 50` (services: `homeassistant`, `whisper`, `piper`)
- Restart one service: `docker compose restart whisper`

## Smoke test problems

The smoke test is `python scripts\smoke_test.py`, run from `C:\dev\Destiny`. It prints one `PASS` or `FAIL` line per check.

### "No such file" or "can't open file" when running the smoke test

- Cause: you ran it from a different folder.
- Fix: run `cd C:\dev\Destiny` first, then `python scripts\smoke_test.py`.

### `FAIL whisper:` or `FAIL piper:` with "Cannot connect"

You see something like: `FAIL whisper: Cannot connect to localhost:10300 (...)`.

- Cause: the service is not running, is still starting, or Docker Desktop is not running.
- Fix: run `docker compose ps`. If whisper or piper is not `Up`, run `docker compose up -d` and check again after a minute. If it keeps stopping, read `docker compose logs whisper --tail 50`.

### `FAIL ha-api:` "Cannot reach Home Assistant" or "timed out"

You see: `Cannot reach Home Assistant at http://localhost:8123 (...)` or `Home Assistant at ... timed out after 10.0s. It may still be starting or busy; try again.`

- Cause: Home Assistant is not running or is still starting (the first start can take a few minutes).
- Fix: run `docker compose ps`, wait a minute, and open http://localhost:8123 in your browser. If you changed the address in `.env`, check `HA_URL`.

### `FAIL ha-api:` "did not return JSON"

You see: `Home Assistant at ... did not return JSON. It may not be set up yet (finish onboarding in the browser) or the URL is wrong.`

- Fix: open http://localhost:8123 and finish creating the owner account (section 3 of the setup guide), then run the test again.

### `FAIL ha-api: HA_TOKEN is empty in .env`

You see: `HA_TOKEN is empty in .env`, and the `conversation` and `multi-turn` checks say `skipped: no token`.

- Fix: create a token. In Home Assistant click your name (bottom left) > Security tab > Long-lived access tokens > Create token. Copy it, open `.env` in Notepad, paste it after `HA_TOKEN=` (no quotes or spaces), and save.

### `FAIL ha-api:` "rejected the token (HTTP 401)"

You see: `Home Assistant rejected the token (HTTP 401). Create a long-lived token ...`

- Cause: the token is wrong, was cut off when pasted, or was deleted in Home Assistant.
- Fix: create a new long-lived token as above and paste the whole thing again.

### `FAIL conversation:` "conversation agent reported an error"

You see: `Home Assistant conversation agent reported an error: <some message>`, for example a message that the agent is not available or could not understand.

- Cause: usually the Anthropic agent is not set up, the API key is invalid or out of credit, or the Destiny pipeline is not using the Anthropic agent.
- Fix: check Settings > Devices & services > Anthropic shows no error; check your API key and spend limit at https://console.anthropic.com/; check Settings > Voice assistants > Destiny uses the Anthropic agent. Also check `HA_AGENT_ID` in `.env` (see the next entry).

### `conversation` fails with HTTP 400/404, or the answers sound canned

You see `Home Assistant returned HTTP 400 for /api/conversation/process` (or 404), or the answers are short canned phrases (for example "Sorry, I couldn't understand that") instead of Claude's.

- Cause: `HA_AGENT_ID` in `.env` is wrong or empty. When it is empty, Home Assistant's built-in agent answers, not Claude (the smoke test prints a hint about this).
- Fix: in Home Assistant go to Settings > Devices & services > Entities, search "conversation", and copy the Anthropic agent's entity ID (for example `conversation.claude_conversation`) into `.env` as `HA_AGENT_ID=`. See the [setup guide](setup-windows.md), section 7.

### `FAIL multi-turn:` "context was lost"

You see: `answer does not mention the weather, so context was lost: ...` (the follow-up is "What did I just ask you about?").

- Cause: either the follow-up was not treated as part of the same conversation, or Claude simply did not say the word "weather" in its answer. Run the test once more and read the printed answer before assuming context was lost. If it repeats and the answer really ignores the earlier question, check the agent settings (instructions pasted, "Device control" ticked under AI tools). The follow-up asks what the first question was about, so it only passes if the conversation history was kept.

### The smoke test hangs, or reports a protocol error on whisper or piper

You see the test sit for a long time, or messages like `Connection closed while reading ...`, `Invalid Wyoming header` or `Wyoming describe on ... failed`.

- Cause: the Whisper or Piper container is in a bad state, or its image version does not match what is expected.
- Fix: run `docker compose restart whisper piper`, wait a minute and retry. If it persists, check `WHISPER_IMAGE_TAG` and `PIPER_IMAGE_TAG` in `.env` match `.env.example`, then run `docker compose pull` and `docker compose up -d`.

### The smoke test will not start, or ignores your settings

- "python is not recognized" or a syntax error: the smoke test needs Python 3.8 or newer. Check with `python --version`, and install Python from https://www.python.org/ if needed.
- The smoke test crashes with a long Python error message ending in `UnicodeDecodeError` (and `docker compose` may also complain about `.env`): the `.env` file may have been saved as UTF-16, which happens if it was created with PowerShell `>` redirection. Open `.env` in Notepad, choose File > Save As, set Encoding to `UTF-8`, and save over it.
- Windows line endings, comments, blank lines and quoted values in `.env` are all handled automatically; you do not need to fix them.

## Phase 2 brain problems

### Destiny says "My brain is taking a nap. Try again in a minute."

- Cause: Home Assistant could not reach the brain, or it took longer than 15 seconds. Timers and the time still work because Home Assistant handles them itself.
- Fix: run `docker compose ps` and check `brain` is `Up`; if not, run `docker compose up -d` and read `docker compose logs brain --tail 50`. Check http://localhost:8000/health. In Home Assistant, Settings > Devices & services > Destiny should show the URL `http://brain:8000`. To get her back right now, set Settings > Voice assistants > Destiny > Conversation agent to "Claude conversation".

### 401 (unauthorized) on converse

You see HTTP 401 from `/v1/converse` in `docker compose logs brain`, or Home Assistant reports the brain rejected the key.

- Cause: the shared key entered in the Destiny integration does not match `BRAIN_SHARED_KEY` in `.env`, or `.env` was changed after the brain started.
- Fix: copy the current `BRAIN_SHARED_KEY` value from `.env` and reconfigure the Destiny integration in Home Assistant with it. After editing `.env`, run `docker compose up -d --build` so the brain picks it up.

### Parent page: wrong PIN, or it will not load

- Cause: the PIN you typed is not the value of `DESTINY_PARENT_PIN` in `.env`, or `DESTINY_PARENT_PIN` is blank.
- Fix: check the value in `.env` (set one if blank), run `docker compose up -d --build` after changing it, and try again. If the page does not load from another device, check the firewall rule for TCP 8000 on the Private profile (setup guide, section 9, step 3).

### Destiny says "I've done a lot of thinking today. Let's talk again tomorrow."

- Cause: today's spend reached the hard cap (`DESTINY_HARD_CAP_USD`). The brain makes no model calls until local midnight in `TZ`. Before that, at the soft cap (`DESTINY_SOFT_CAP_USD`), she quietly switches to the cheaper model.
- Fix: check the spend on the parent page. To allow more today, raise `DESTINY_HARD_CAP_USD` in `.env` and run `docker compose up -d --build`. If the day rolls over at the wrong time, check `TZ`.

### Destiny says "Sorry, something went wrong in my head. Please try again."

- Cause: the Anthropic API failed (rate limit, outage, or an invalid or out-of-credit key). The brain keeps running.
- Fix: check `ANTHROPIC_API_KEY` and your credit at https://console.anthropic.com/, read `docker compose logs brain --tail 50`, and try again in a minute.

### Destiny says "I didn't catch that. Could you say it again?"

- Cause: the transcript was empty. Speak closer to the Voice PE, or see "Whisper mishears words" below.

### `FAIL brain:` in the smoke test

- Cause: the brain is not running, or `BRAIN_URL` in `.env` is wrong.
- Fix: run `docker compose up -d --build`, then check http://localhost:8000/health.

### `FAIL conversation:` "answer says weather is unavailable"

- Cause: Destiny could not see the weather. The brain reads `HA_WEATHER_ENTITY` using `BRAIN_HA_TOKEN`.
- Fix: check the weather entity id in Developer tools > States, check `BRAIN_HA_URL` and `BRAIN_HA_TOKEN` in `.env`, then run `docker compose up -d --build`.

## Docker and startup problems

### Can't connect to localhost:8123

After a PC restart, http://localhost:8123 does not load.

- Cause: Docker Desktop is not running, so Home Assistant is not running either.
- Fix: start Docker Desktop and wait for "Engine running". Home Assistant comes back by itself in a minute or two. To stop this happening: Docker Desktop > Settings > General > tick "Start Docker Desktop when you sign in to your computer" > Apply.

### I forgot my Home Assistant password

- Your username is shown in Settings > People > Users tab.
- If you are still signed in on any device or browser, an owner can click the user in that list > Change password.
- Chrome's password manager may have it saved: search for `localhost` in your saved passwords.

### Docker Desktop says WSL 2 is not enabled

You see a message that WSL 2 is not installed or virtualisation is disabled, and Docker will not start.

- Fix: open PowerShell as administrator, run `wsl --install`, then restart the PC. If it still fails, turn on virtualisation in the PC's BIOS/UEFI settings (often called "Intel VT-x", "SVM" or "Virtualization"), and make sure the Windows features "Virtual Machine Platform" and "Windows Subsystem for Linux" are on.

### "port is already allocated" or "address already in use"

You see an error from `docker compose up -d` naming port 8123, 10300 or 10200.

- Cause: another program, or an old container, is using that port.
- Fix: run `docker compose down`, then `docker compose up -d` again. If another program uses the port, close it, or ask for help changing the published ports in `docker-compose.yml`.

### First start of whisper is very slow

- Cause: the first run downloads the speech model, which can take several minutes and looks like nothing is happening.
- Fix: wait. Watch with `docker compose logs whisper --tail 20`; the logs should show the service is ready or listening (exact wording varies by version). Later starts are fast.

## Voice PE problems

### Wizard stuck on "Say Okay Nabu again"

The Voice Satellite setup wizard can hang on the confirmation step even when the wake word worked.

- Fix: click "Skip" (top right) and carry on with the wizard ([Voice PE setup](voice-pe-setup.md), step 6). Remember to set the Assistant to "Destiny" on the last screen.

### Home Assistant can't find or reach the Voice PE

- Cause 1 (check first): the PC and the Voice PE are on different networks. A mesh Wi-Fi system (for example Google Nest Wifi) plugged into the internet provider's box creates a second network, so a PC cabled to the provider's box is on `192.168.1.x` while the Voice PE is on `192.168.86.x`. Fix: compare the first three numbers of the PC's `ipconfig` address and your phone's Wi-Fi address; if they differ, plug the PC into the main mesh router instead ([Voice PE setup](voice-pe-setup.md), step 1).
- Cause 2: the Voice PE's IP address changed (no reservation), it is switched off, or it is on a different Wi-Fi.
- Fix: check it has power and is on the home Wi-Fi. Find its current IP in your router's device list, then in Home Assistant go to Settings > Devices & services > ESPHome, open the entry and update the host. To stop it happening again, make a DHCP reservation ([Voice PE setup](voice-pe-setup.md), step 5). Home Assistant reaches the device on port `6053`; if it still fails, check that your router is not isolating Wi-Fi devices from the PC (a "guest network" or "AP isolation" setting).

### No spoken answer from the Voice PE

The light ring reacts to you, but no answer is spoken.

- Cause 1 (most common): Home Assistant's local network URL is wrong. In Docker it thinks its address is the container's, so the audio link it gives the Voice PE is unreachable. Fix: set Settings > System > Network > Home Assistant URL > Local network (with "Automatic" turned off) to `http://<your PC's IPv4>:8123` ([Voice PE setup](voice-pe-setup.md), step 2).
- Cause 2: Windows Firewall blocks port 8123, or the PC's network is set to Public. Fix: add the inbound rule for TCP 8123 on the Private network ([Voice PE setup](voice-pe-setup.md), step 3), and make sure your home network profile is Private.
- Also confirm the Voice PE and the PC are on the same network, and that the PC's IP address has not changed (use a DHCP reservation).

### The ring spins (blue or red) but she never speaks, after a restart or sleep

Two causes seen in practice (2026-11-18):

- **Docker's port forwarding stalled.** The brain still answers (its log shows `POST /v1/converse/stream 200`), but nothing outside Docker can reach Home Assistant: `curl http://<PC IP>:8123/manifest.json` returns nothing or "empty reply". The Voice PE can't download the spoken answer. Fix: quit and restart Docker Desktop (or run `wsl --shutdown`, then start Docker Desktop).
- **ElevenLabs is down or stuck starting.** Pulsing red ring; the HA pipeline debug says "Text-to-speech engine … does not support language en". Settings > Devices & services shows ElevenLabs stuck "Initializing". Check https://status.elevenlabs.io. Quick fix: Settings > Voice assistants > Destiny > Text-to-speech > Piper. When ElevenLabs is healthy again, restart the Home Assistant container (a stuck setup won't retry on its own) and switch back to Serena.
- If the brain log shows `401 ... invalid x-api-key`, the Claude API key in `.env` was deleted or replaced: make a new key in the Anthropic Console, update `ANTHROPIC_API_KEY`, then `docker compose up -d --no-deps --force-recreate brain`.

### The wake word never triggers

- Check the Voice PE is set to the `Destiny` assistant with a wake word ([Voice PE setup](voice-pe-setup.md), step 6), its mute switch is off, and you are within a couple of metres. "Okay Nabu" is the device default; try it if "Hey Jarvis" is unreliable.

### Answers are too quiet, or the sound is cut off or echoes

- Turn the top ring clockwise for more volume, or use the media player volume on the device page ([Voice PE setup](voice-pe-setup.md), step 7). With an external speaker, keep it about 30 cm (1 ft) from the Voice PE and not aimed at it, and avoid Bluetooth transmitter adapters.

## Answer problems

### Claude says "I can't access weather" (or similar)

First decide which of these you are seeing.

- She has no weather at all (cannot tell you the current temperature or sky). Cause: the weather entity is not exposed to the assistant, or the Met.no weather integration is not installed. Fix: go to Settings > Voice assistants > Expose tab and make sure the weather entity ("Home" with a sun icon, id like `weather.home`; the exact id can differ, search 'weather' under Settings > Devices & services > Entities) is exposed. If it does not exist, add the "Meteorologisk institutt (Met.no)" integration (setup guide, section 3).
- She knows the current conditions but says she can't see tomorrow's forecast. This is expected in Phase 1: Destiny sees current conditions (temperature, sky, humidity) but not forecasts. Since Phase 2 she also gets a 3-day forecast, and she can search the web for live questions.

### She says a "thinking" phrase before answering

That's on purpose. On longer questions she says a short filler ("Hmm, let me put my thinking cap on…") straight away, then streams the answer. On questions that need the internet she says a web filler instead ("One sec, I'm surfing through the web…"), and if a search takes a while she adds "Still digging, almost there." If the answer stream breaks partway through she says "Sorry, I lost my train of thought." and the turn isn't remembered: just ask again.

### Internet answers (sports, news, schedules)

- She searches only for live questions: news, headlines, scores, standings, prices, "open now", the 49ers or Nuggets, or a time word plus a game word ("who won the game last night"). Everyday questions and weather don't search.
- Each search costs about 1 cent plus reading time, and shows in the "Searches" column on the parent page (`http://<PC IP>:8000/parent`). Searches count toward the $1 soft and $3 hard daily caps.
- Search answers take a few seconds longer (about 5–9 s to the first word of the answer). If she answers a live question without searching, ask again with "look it up" or "search the web".

### Claude can control devices I did not expect

- Cause: "Expose new entities" is on (it is on by default), so every device you add later is exposed.
- Fix: Settings > Voice assistants > Assistants tab > turn OFF "Expose new entities", then on the Expose tab remove anything you do not want Destiny to reach.

### Whisper mishears words

- Set `WHISPER_MODEL=medium-int8` in `.env`, then run `docker compose up -d`. It is more accurate but slower, so re-check the latency table in the Voice PE guide.
