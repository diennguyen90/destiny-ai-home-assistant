# Troubleshooting

Find the symptom you see, read the likely cause, and try the fix. Useful commands, run in PowerShell in the project folder (`C:\dev\Destiny`):

- Status: `docker compose ps`
- Logs: `docker compose logs <service> --tail 50` (services: `homeassistant`, `whisper`, `piper`)
- Restart one service: `docker compose restart whisper`

## Smoke test problems

The smoke test is `python scripts/smoke_test.py`. It prints one `PASS` or `FAIL` line per check.

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

You see: `answer does not mention Saturday, so context was lost: ...`

- Cause: either the follow-up was not treated as part of the same conversation, or Claude simply did not say the word "Saturday" in its answer. Run the test once more and read the printed answer before assuming context was lost. If it repeats and the answer really ignores the earlier question, check the agent settings (Haiku model chosen, instructions pasted, "Control Home Assistant" on).

### The smoke test hangs, or reports a protocol error on whisper or piper

You see the test sit for a long time, or messages like `Connection closed while reading ...`, `Invalid Wyoming header` or `Wyoming describe on ... failed`.

- Cause: the Whisper or Piper container is in a bad state, or its image version does not match what is expected.
- Fix: run `docker compose restart whisper piper`, wait a minute and retry. If it persists, check `WHISPER_IMAGE_TAG` and `PIPER_IMAGE_TAG` in `.env` match `.env.example`, then run `docker compose pull` and `docker compose up -d`.

### The smoke test will not start, or ignores your settings

- "python is not recognized" or a syntax error: the smoke test needs Python 3.8 or newer. Check with `python --version`, and install Python from https://www.python.org/ if needed.
- The smoke test crashes with a long Python error message ending in `UnicodeDecodeError` (and `docker compose` may also complain about `.env`): the `.env` file may have been saved as UTF-16, which happens if it was created with PowerShell `>` redirection. Open `.env` in Notepad, choose File > Save As, set Encoding to `UTF-8`, and save over it.
- Windows line endings, comments, blank lines and quoted values in `.env` are all handled automatically; you do not need to fix them.

## Docker and startup problems

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

### Home Assistant is "unable to connect" to the Voice PE

- Cause: the Voice PE's IP address changed (no reservation), it is switched off, or it is on a different Wi-Fi.
- Fix: check it has power and is on the home Wi-Fi. Find its current IP in your router's device list, then in Home Assistant go to Settings > Devices & services > ESPHome, open the entry and update the host. To stop it happening again, make a DHCP reservation ([Voice PE setup](voice-pe-setup.md), step 4). Home Assistant reaches the device on port `6053`; if it still fails, check that your router is not isolating Wi-Fi devices from the PC (a "guest network" or "AP isolation" setting).

### No spoken answer from the Voice PE

The light ring reacts to you, but no answer is spoken.

- Cause 1 (most common): Home Assistant's local network URL is wrong. In Docker it thinks its address is the container's, so the audio link it gives the Voice PE is unreachable. Fix: set Settings > System > Network > Home Assistant URL > Local network to `http://<your PC's IPv4>:8123` ([Voice PE setup](voice-pe-setup.md), step 1).
- Cause 2: Windows Firewall blocks port 8123, or the PC's network is set to Public. Fix: add the inbound rule for TCP 8123 on the Private network ([Voice PE setup](voice-pe-setup.md), step 2), and make sure your home network profile is Private.
- Also confirm the Voice PE and the PC are on the same network, and that the PC's IP address has not changed (use a DHCP reservation).

### The wake word never triggers

- Check the Voice PE is set to the `Destiny` assistant with a wake word ([Voice PE setup](voice-pe-setup.md), step 6), its mute switch is off, and you are within a couple of metres. Try "Okay Nabu" if "Hey Jarvis" is unreliable.

## Answer problems

### Claude says "I can't access weather" (or similar)

- Cause: the weather entity is not exposed to the assistant, or the Met.no weather integration is not installed.
- Fix: go to Settings > Voice assistants > Expose tab and make sure the weather entity (for example `weather.home`) is exposed. If it does not exist, add the "Meteorologisk institutt (Met.no)" integration (setup guide, section 3).

### Whisper mishears words

- Set `WHISPER_MODEL=medium-int8` in `.env`, then run `docker compose up -d`. It is more accurate but slower, so re-check the latency table in the Voice PE guide.
