# Voice PE setup

The Home Assistant Voice Preview Edition (the "Voice PE") is the little speaker-and-microphone device you talk to. This guide connects it to your running Destiny setup. Do [the Windows setup guide](setup-windows.md) first, including the smoke test.

Wording in Home Assistant changes a little between versions. If a button or menu is named slightly differently on your screen, look for the closest match.

## 1. Check the PC and the Voice PE are on the same network

The PC and the Voice PE MUST be on the same home network, or Home Assistant cannot reach the device.

A common trap: a mesh Wi-Fi system (for example Google Nest Wifi) plugged into your internet provider's gateway (for example an AT&T box) creates a SECOND network. If the PC is cabled to the provider's box (addresses like `192.168.1.x`) while the Wi-Fi, and so the Voice PE, is on the mesh (addresses like `192.168.86.x`), they cannot see each other.

How to check:

1. On the PC, open PowerShell and run `ipconfig`. Note the "IPv4 Address".
2. On your phone, connected to the home Wi-Fi, find its IP address. iPhone: Settings > Wi-Fi > the (i) next to your network. Android: Wi-Fi > your network > details.
3. The first three numbers must match (for example both `192.168.86.x`). You should see them match.

If they do not match, fix it:

1. Unplug the PC's Ethernet cable from the provider's box and plug it into a free LAN port on the main mesh router (the unit connected to the provider's box). A small network switch plugged into that port also works.
2. Windows may set the new network to Public. Set it to Private: Settings > Network & Internet > Ethernet > click the network > Private.
3. Run `ipconfig` again. The PC's address has changed, so use the new one in step 2 below.

## 2. Tell Home Assistant your PC's address

Home Assistant runs in a Docker container, so on its own it thinks its address is the container's internal one (starting with `172.`). It then gives the Voice PE audio links that the Voice PE cannot reach. Fix this first.

1. On the PC, run `ipconfig` and find the "IPv4 Address" of your Wi-Fi or Ethernet adapter (for example `192.168.1.20`).
2. In Home Assistant go to Settings > System > Network. Under "Home Assistant URL" > "Local network", turn OFF the "Automatic" toggle. (In Docker, automatic fills in an internal `172.x` address that the Voice PE cannot reach.)
3. In the box that appears, type `http://<your PC's IPv4>:8123` (for example `http://192.168.1.20:8123`) and click Save.
4. Your router can change the PC's address later. Give the PC a DHCP reservation (step 5 below), and update this URL if the address ever changes.
5. You should see the new address shown as the local network URL.

## 3. Let the Voice PE and your phone reach your PC (Windows Firewall)

The Voice PE downloads Destiny's spoken answers from Home Assistant on your PC, on port 8123, and your phone reaches Home Assistant the same way. Windows Firewall may block that by default.

1. First check the network profile: Settings > Network & Internet > Wi-Fi (or Ethernet) > click your network > Network profile type must be Private. The rule below only applies to Private networks, so a Public profile blocks the Voice PE.
2. Press the Windows key, type `Windows Defender Firewall with Advanced Security`, and open it.
3. Click Inbound Rules, then New Rule (right side).
4. Choose Port, Next. Choose TCP and "Specific local ports": `8123`. Next.
5. Choose "Allow the connection". Next.
6. Tick only Private (your home network). Untick Domain and Public. Next.
7. Name it `Destiny Home Assistant 8123` and Finish.

You should see the new rule listed under Inbound Rules.

## 4. Power the Voice PE and connect it to Wi-Fi

1. Plug the Voice PE into a USB-C phone charger (5 V, 2 A or more) wherever it will live. It does not need a data connection to the PC; it talks over Wi-Fi.
2. Install the Home Assistant Companion app on your phone (iPhone or Android). When it asks for your server, enter `http://<PC IPv4>:8123` (for example `http://192.168.1.20:8123`), never `localhost` (on the phone, `localhost` means the phone itself). Sign in with your Home Assistant username and password. The phone must be on the same Wi-Fi as the PC, and the PC must be on with Destiny running.
3. Turn Bluetooth on and keep the phone near the Voice PE. The app finds the device; follow the prompts and enter your Wi-Fi details. Use your main Wi-Fi (2.4 GHz works best), not a guest network.
4. You should see the light ring show a blue "wave". That means it joined your Wi-Fi and is waiting for Home Assistant to connect to it. This is normal at this stage: with Docker there is no auto-discovery, so you add it by hand in step 6.

## 5. Give the Voice PE and the PC fixed addresses (DHCP reservation)

Your router hands out addresses that can change. Destiny needs the Voice PE and the PC to keep the same ones.

1. Find the Voice PE's IP address in your router or mesh app's list of connected devices. It is named like `home-assistant-voice-0af992`. Write the address down; you need it in the next step.
2. Reserve addresses for both the Voice PE and the PC.
   - Google Nest Wifi: in the Google Home app, go to Wi-Fi > Settings > Advanced networking > DHCP IP reservations, and reserve both devices.
   - Other routers: open the router's settings (usually a web page; the address and password are often on the router's label). Find "DHCP reservation", "Address reservation" or "Static lease" (the name varies) and reserve each device's current address.
3. You should see both devices listed with a reserved or fixed address.

## 6. Add it to Home Assistant and set up the voice assistant

Home Assistant normally finds devices on its own. Because it runs inside Docker Desktop on Windows, it usually cannot see them, so you add the Voice PE by hand.

1. In Home Assistant go to Settings > Devices & services > Add integration and search for "ESPHome".
2. Host: the Voice PE's IP address from step 5. Port: `6053`. Click Submit.
3. If asked for an encryption key and you do not have one, check Settings > Devices & services for an existing ESPHome entry before adding another.
4. A "Voice Satellite setup" wizard opens straight away. Go through it:
   1. "Say 'Okay Nabu' to wake the device up". "Okay Nabu" is the default wake word; the "Change wake word" link offers "Hey Jarvis". (A custom "Hey Destiny" comes in a later phase.)
   2. A confirmation screen "Say 'Okay Nabu' again" can hang even when it works. Click "Skip" (top right).
   3. Select an area (any; the Living Room default is fine) > Next.
   4. "How do you want your voice to be processed?" > "Full local processing" > Next.
   5. "Ready to Assist!": IMPORTANT. The Assistant dropdown defaults to "Full local assistant", a pipeline the wizard creates that does not use Claude. Change it to "Destiny" (the voice should follow Destiny's). Click Done.
5. The wizard leaves an extra "Full local assistant" pipeline under Settings > Voice assistants. It is harmless, and you can delete it.
6. Test: say "Okay Nabu", wait for the light ring to react, then ask "What is the weather like right now?". You should hear a short spoken answer. In Phase 1 Destiny only sees current conditions, not forecasts. If she ends with a question, you can answer without saying the wake word again.

To change things later: Settings > Devices & services > ESPHome > the Voice PE device > "Assistant" or "Wake word".

If the light ring reacts but you never hear an answer, see "No spoken answer from the Voice PE" in [troubleshooting](troubleshooting.md).

## 7. Volume and speaker

- Volume: the top ring is a dial. Turn it clockwise to get louder. You can also set it in Settings > Devices & services > ESPHome > the Voice PE device > the media player volume.
- The Voice PE has no Bluetooth audio output. To use a bigger speaker, plug it into the 3.5 mm jack with a cable. Any powered speaker with an AUX input works. The internal speaker turns off when something is plugged in. Many Bluetooth speakers also have an AUX-in socket.
- Avoid Bluetooth transmitter adapters: they add delay and clip the start of answers.
- Keep the speaker about 30 cm (1 ft) from the Voice PE and not pointing at it.

## 8. Measure how fast it answers

Our target is an answer within about 4 seconds of you finishing speaking (Alexa is about 1 second).

1. Use a phone stopwatch. Start it the moment you stop speaking.
2. Stop it when you hear the first word of the answer.
3. Repeat at least five times with the same question and record the results below. Start with a Haiku model, the fastest.

| Date | Question | Model | Whisper model | Time (seconds) | Notes |
|---|---|---|---|---|---|
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |

If it is regularly slower than 4 seconds, note it here and see the latency ideas in the design spec (smaller Whisper model, Haiku, streaming speech) before changing anything.
