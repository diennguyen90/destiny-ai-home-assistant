# Connect Google Calendar to Destiny

This guide links your family's Google Calendar to Home Assistant, so Destiny can read your events and add new ones by voice. It is about 20 minutes of clicking. You do it once.

Reminders ("Remind me at 5 to take out the trash") do not need this guide. They work already and arrive as a notification on the phone with the Home Assistant Companion app. This guide is only for the calendar.

You will need:

- The family's own Google account, and its password (you type it yourself).
- A computer browser on the Destiny PC (or any computer on your home network).
- Home Assistant open at http://localhost:8123.

This follows Home Assistant's own guide, <https://www.home-assistant.io/integrations/google/>. If Google changes its screens, that page is the source of truth.

## 1. Create a Google Cloud project

1. Go to <https://console.cloud.google.com/> and sign in with the family Google account.
2. At the top of the page, open the project picker and choose **New project**.
3. Name it something like `Destiny` and click **Create**. Make sure the new project is the one selected at the top.

## 2. Turn on the Google Calendar API

1. In the search bar at the top, type `Google Calendar API` and open it.
2. Click **Enable**.

## 3. Set up the consent screen

Google calls this the "Google Auth Platform". Search for it in the top search bar, or open the menu and look for **APIs & Services > OAuth consent screen**.

1. If you see **Get started**, click it.
2. Enter an app name (for example `Destiny`) and choose the family account as the support email. Click **Next**.
3. For Audience, choose **External**. Click **Next**.
4. Enter the family account as the contact email, accept the data policy, and click **Create**.
5. Open **Branding**. Set the application home page, privacy policy link and terms of service link all to `https://home-assistant.io`. Under **Authorized domains**, add `home-assistant.io`. Save.
6. Open **Audience**. Click **Publish app**.
   - Do not skip this. Home Assistant warns that if the app stays in "Testing", the sign-in expires every 7 days and Destiny will lose the calendar each week.
   - If you decide to stay in Testing anyway, add the family account under **Test users**, and expect to sign in again weekly.

## 4. Create the sign-in credentials

Important: choose **Web application**. Do not choose "Desktop app" or "TVs and limited input devices". Those are older types that Home Assistant no longer recommends.

1. Open **Clients** (or **APIs & Services > Credentials**) and click **Create client** (or **Create credentials > OAuth client ID**).
2. Application type: **Web application**. Give it a name like `Destiny`.
3. Under **Authorized redirect URIs**, click **Add URI** and enter exactly this:

   ```
   https://my.home-assistant.io/redirect/oauth
   ```

   It must match exactly, with no extra spaces or slash at the end.
4. Click **Create**.
5. Google shows a **Client ID** and a **Client secret**. Copy both somewhere safe for the next step. Google does not show the secret again after you close this box, so if you lose it you must make a new one.

Google says new credentials usually work within a few minutes, but can take up to five hours. If the next step fails right away, wait and try again.

## 5. Link it in Home Assistant

1. Open http://localhost:8123.
2. Go to **Settings > Devices & services**, click **Add integration** (bottom right), and choose **Google Calendar**.
3. Home Assistant asks for Application Credentials. Paste the **Client ID** and the **Client secret** from step 4 and continue.
4. A Google sign-in window opens. Sign in with the family account.
5. Google may say "Google hasn't verified this app". That is expected, because you made the app yourself. Click **Advanced**, then continue to the app.
6. Review the access it asks for and continue.
7. On the "Link account to Home Assistant?" page, check the address is your Home Assistant, then click **Link Account**.
8. Close the window. Home Assistant shows a Success message.

Optional: on the Google Calendar card in Devices & services, click the cogwheel to pick **Read/Write** (the default) or **Read-only**. Destiny needs **Read/Write** to add events. If you change it, Home Assistant asks you to sign in to Google again.

## 6. Check that Destiny sees it

Give it a few minutes. After you link the calendar, Destiny can take up to about 5 minutes to notice it.

Then try these:

- "What's on our calendar today?"
- "What's on the calendar tomorrow?"
- "What do we have this week?"
- "Add the dentist on Friday at 3."
- "Put soccer practice on Saturday at 9 at the park on the calendar."
- "Add Grandma's birthday on December 12th." (an all-day event)

She should read events back in a natural sentence, and say plainly what she added and when.

Note: she can read and add events, but not edit or delete them yet. Do that in Google Calendar.

## 7. If you have more than one calendar

Destiny uses the first calendar Home Assistant finds. If your Google account has several (for example a personal one and the family one) and she reads the wrong one, tell her which one to use:

1. In Home Assistant, go to **Settings > Devices & services > Entities** and search for `calendar.`. Note the id of the one you want, for example `calendar.family`.
2. Open the `.env` file in `C:\dev\Destiny` in Notepad and add a line:

   ```
   DESTINY_CALENDAR_ENTITY=calendar.family
   ```

   Use your own id after the equals sign.
3. In PowerShell, in `C:\dev\Destiny`, run:

   ```
   docker compose up -d --no-deps --force-recreate brain
   ```

4. Ask "What's on our calendar today?" again.

## If something goes wrong

- She says "The family calendar isn't connected yet." See [troubleshooting](troubleshooting.md#she-says-the-family-calendar-isnt-connected-yet).
- Home Assistant says "Authentication code expired" while linking: just start the link again.
- Home Assistant says the client ID or secret is invalid: the credentials may not be active yet (wait a few minutes), or were pasted wrong. Delete them under **Settings > Application credentials** and add them again.
