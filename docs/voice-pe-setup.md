# Voice PE setup

The Home Assistant Voice Preview Edition (the "Voice PE") is the little speaker-and-microphone device you talk to. This guide connects it to your running Destiny setup. Do [the Windows setup guide](setup-windows.md) first, including the smoke test.

Wording in Home Assistant changes a little between versions. If a button or menu is named slightly differently on your screen, look for the closest match.

## 1. Connect the Voice PE to your Wi-Fi

1. Plug the Voice PE into power using its USB-C cable. Wait for it to start up (the light ring animates).
2. Install the Home Assistant Companion app on your phone (iPhone or Android) and sign in to your Home Assistant. Your phone must be on the same Wi-Fi as the PC, and the PC must be on with Destiny running.
3. The phone app finds the Voice PE over Bluetooth. A "Discovered" or "New device found" card should appear in the app. If not, open Settings > Devices & services in the app and look for it. Follow the prompts and pick your home Wi-Fi (2.4 GHz works best), then enter the Wi-Fi password.
4. You should see: the app reports the Voice PE was connected and added.

If the phone app cannot reach Home Assistant at `localhost`, it needs your PC's address instead. In PowerShell run `ipconfig`, find the "IPv4 Address" (for example `192.168.1.20`), and use `http://192.168.1.20:8123` in the app.

## 2. Let the Voice PE reach your PC (Windows Firewall)

The Voice PE downloads Destiny's spoken answers from Home Assistant on your PC, on port 8123. Windows Firewall may block that by default.

1. Press the Windows key, type `Windows Defender Firewall with Advanced Security`, and open it.
2. Click Inbound Rules, then New Rule (right side).
3. Choose Port, Next. Choose TCP and "Specific local ports": `8123`. Next.
4. Choose "Allow the connection". Next.
5. Tick only Private (your home network). Untick Domain and Public. Next.
6. Name it `Destiny Home Assistant 8123` and Finish.

You should see the new rule listed under Inbound Rules. If Windows treats your home network as "Public", change it to Private in Settings > Network & Internet > Wi-Fi > your network > Network profile.

## 3. Give the Voice PE a fixed address (DHCP reservation)

Your router hands out addresses that can change. Destiny needs the Voice PE to keep the same one.

1. Find the Voice PE's IP address: in Home Assistant go to Settings > Devices & services, open the Voice PE device (ESPHome), and look for "IP address" in the device info. Or look at your router's list of connected devices.
2. Open your router's settings (usually a web page; the address and password are often on the router's label). Find "DHCP reservation", "Address reservation" or "Static lease". The name varies by router.
3. Reserve the Voice PE's current address for it, and save.
4. You should see the Voice PE listed with a reserved or fixed address. Write the address down; you need it in the next step.

## 4. Add it to Home Assistant by IP address

Home Assistant normally finds devices on its own. Because it runs inside Docker Desktop on Windows, it usually cannot see them, so you add the Voice PE by hand.

1. In Home Assistant go to Settings > Devices & services > Add integration and search for "ESPHome".
2. Host: the Voice PE's IP address from step 3. Port: `6053`. Submit.
3. If asked for an encryption key and you do not have one, the device may already be configured from the phone app. Check Settings > Devices & services for an existing ESPHome entry before adding another.
4. You should see an ESPHome entry for the Voice PE, with its device and entities (microphone, speaker and so on).

## 5. Choose Destiny's pipeline and wake word

1. Go to Settings > Devices & services > ESPHome > your Voice PE device.
2. Find the "Assistant" setting (a dropdown). Choose `Destiny`.
3. Find the wake word setting and choose "Hey Jarvis" or "Okay Nabu". These are the built-in wake words; a custom "Hey Destiny" comes in a later phase. The wake word is detected on the device itself; nothing is sent anywhere until it hears the wake word.
4. Test: say the wake word, wait for the light ring to react, then ask "What is the weather tomorrow?". You should hear a short spoken answer. Then ask "What about Saturday?" as a follow-up.

If the light ring reacts but you never hear an answer, see "No spoken answer from the Voice PE" in [troubleshooting](troubleshooting.md).

## 6. Optional: use an external speaker

The Voice PE has a 3.5 mm audio output socket. Plug in a powered speaker (or one with its own amplifier) using a 3.5 mm cable. If the sound does not switch over automatically, look for an audio output setting on the Voice PE device page in Home Assistant. Exact options vary by firmware version.

## 7. Measure how fast it answers

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
