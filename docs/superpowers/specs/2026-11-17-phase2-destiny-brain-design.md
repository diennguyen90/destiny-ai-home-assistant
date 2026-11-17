# Destiny — Phase 2: Destiny's Brain (Design)

Date: 2026-11-17
Status: Approved 2026-11-17
Builds on: [Phase 1 design](2026-11-07-phase1-voice-prototype-design.md) (working, verified live 2026-11-17)

## 1. Intent

Destiny should feel like part of the family. Phase 1 proved the voice loop
(Voice PE → Whisper → Claude → Piper). Phase 2 gives Destiny her own **brain**:
a service we own that knows who she's talking to, remembers, keeps the kids
safe, tutors well, and spends money wisely.

The family's priorities, in order:

1. **Learning**, first for **Cillian (10, 5th grade)**. Daily routine:
   - 15 minutes of reading, then a check that he understood it
   - about 30 minutes of paper-worksheet homework (including about 15 math problems)
   - pop quizzes on what he's learning in school right now
2. **Companionship for Oliver (2)**. He'll shout her name and babble. Destiny
   chats back cheerily, as if they're having a real conversation, about what he loves
   (currently Hot Wheels, cars, trucks, spiders).
3. **Everyday family questions**, including current information through web search.
4. Later phases: household project management and reminders (Phase 3), smart-home
   control, voice recognition, more children.

Success looks like this:
- Cillian does his routine with Destiny most days, and it helps him; it doesn't do the work for him.
- The parents can see his progress without asking.
- Oliver enjoys his chats.
- Costs stay predictable, with a target of about $15/month or less.

## 2. Goals, non-goals, anti-goals

**Goals (Phase 2)**
- G1. A brain service that becomes Destiny's conversation agent in Home Assistant (HA)
  without changing the wake word, Whisper, Piper or HA's free local commands.
- G2. Tiered model routing with logging of model, cost, latency and outcome for every request.
- G3. Profiles (Cillian, Oliver, Parent, Family/unknown), plus a simple way to know who's talking.
- G4. Oliver toddler mode.
- G5. Cillian learning mode:
  - worksheet helper
  - reading check
  - pop quizzes
  - current-topics list
  - topic mastery memory
- G6. Progress tracking with a daily push summary to the parents and a parent web page.
- G7. Child-safety guardrails, with red flags surfaced to the parents.
- G8. Web search for current-information questions.
- G9. "Cillian's screen": a web page on any browser that shows quiz and worksheet visuals,
  driven by the voice session.

**Non-goals (Phase 2)**
- Voice recognition (speaker ID). It's planned next; the design leaves room for it (§7).
- Reminders, calendar, household projects (Phase 3), music, smart-home control.
- A custom "Destiny" wake word (separate task).
- Non-Anthropic model providers. The interface is pluggable, but only Anthropic is implemented.
- Native apps. Everything visual is a plain web page.

**Anti-goals** (failure even if it technically works)
- Destiny does Cillian's homework for him, giving final answers instead of guiding.
- Oliver can keep Destiny in an endless open-mic chat, or she says anything scary or
  unsafe to him.
- Kids' conversations leave the house to anywhere except the vetted model provider.
- Voice answers become noticeably slower than Phase 1 for everyday questions.
- Costs creep up silently.

## 3. Constraints

- **Host:**
  - The current Windows PC with Docker Desktop. It must later move unchanged to an
    N100 mini PC (Proxmox: a HAOS VM plus a Docker VM).
  - Everything runs as containers in the existing `docker-compose.yml`.
- **Home Assistant:**
  - HA 2026.11 in Docker; no host networking.
  - The Voice PE is at 192.168.86.32 and the PC at 192.168.86.143.
  - Phase 1 "Destiny" assistant: faster-whisper, Claude conversation, Piper cori (high).
    "Prefer handling commands locally" is on.
- **Network:**
  - The brain's web pages must be reachable from home devices only (LAN).
  - Windows Firewall needs an inbound rule for the brain's port on the Private profile.
  - No internet exposure.
- **Secrets:**
  - The Anthropic API key moves from HA's UI into the brain's `.env` (git-ignored).
  - The brain needs its own HA long-lived token to send push notifications.
  - Nothing secret is committed.
- **Latency:**
  - Everyday questions should feel as fast as Phase 1.
  - Routing must not add a model call on the common path.
- **Host Python is 3.8.** The brain targets Python 3.12 inside its container, so tests run
  in the container or a 3.12 venv. The Phase 1 stdlib smoke test stays as-is.
- **Children's data stays local:** the SQLite file lives on the PC, and text goes only to Anthropic.

## 4. Approaches considered

- **A. Separate brain service plus a thin HA connector — chosen.**
  - A Python/FastAPI container owns routing, profiles, memory, safety, logging, web search
    and web pages.
  - A tiny HA custom integration registers a conversation agent that forwards each request
    to the brain.
  - Keeps Phase 1 intact, is testable and portable, and matches the original handoff.
  - Cost: two moving parts instead of one.
- **B. Brain pretends to be an OpenAI-compatible endpoint behind an existing HA AI integration.**
  - No HA code to write.
  - But HA controls prompts and tools, and device and conversation context is hard to get,
    which makes profiles and toddler caps fragile.
  - Rejected.
- **C. Everything inside an HA custom integration.**
  - One fewer container.
  - But web pages, the database and tests are awkward inside HA, HA upgrades can break it,
    and it locks the brain to HA.
  - Rejected.

The family picked **A**.

## 5. Architecture

```
Voice PE ──wake word/audio──► Home Assistant (Assist pipeline "Destiny")
                                 │ 1. Whisper → text
                                 │ 2. "Prefer local": HA built-in intents (timers, time,
                                 │     shopping list) answered free — brain never sees these
                                 │ 3. otherwise → conversation agent "Destiny brain"
                                 ▼
                     ha/custom_components/destiny  (thin connector)
                                 │ HTTP POST /v1/converse
                                 ▼
                ┌─────────── brain (FastAPI, port 8000) ───────────┐
                │ identify speaker → profile                        │
                │ safety pre-check                                  │
                │ mode/session (learning, toddler, general)         │
                │ router → tier → model provider (Anthropic)        │
                │   tools: web search, learning tools (record       │
                │   result, update topic, start/stop timer …)       │
                │ log request (model, tokens, $, ms, outcome)       │
                │ push screen updates (websocket)                   │
                └──────┬───────────────────────────┬────────────────┘
                 SQLite (data/brain/)        Web pages: /screen, /parent
                       │
           HA REST API (notify.mobile_app_*) ← daily summary & red-flag alerts
```

### 5.1 HA connector (`ha/custom_components/destiny/`)
- A conversation agent entity ("Destiny brain"), configured in the UI with the brain URL.
- For each request it forwards these to the brain:
  - text
  - language
  - HA `conversation_id`
  - `device_id` / satellite id (which Voice PE or phone heard it)
- It returns the brain's speech text, plus whether to keep listening
  (`continue_conversation`), so the brain can end Oliver's chats.
- If the brain is unreachable or slow (more than 15 s), it says a short fallback line
  ("My brain is taking a nap, try again in a minute") instead of failing silently.
- The Phase 1 "Claude conversation" agent stays installed as a manual fallback. The
  Destiny assistant switches its agent to "Destiny brain".
- Deployment: compose bind-mounts `./ha/custom_components/destiny` into
  `/config/custom_components/destiny`, so it's committed in the repo while `ha/config`
  stays git-ignored. The connector is pinned to HA 2026.11 and re-tested on each
  deliberate HA upgrade (no HACS packaging).
- **Assumptions to prove first (milestone 1 opens with a spike on the real Voice PE):**
  1. A custom conversation agent can return `continue_conversation`, and the Voice PE
     keeps listening when it does.
  2. HA passes the device or satellite id to the agent.
  3. The pipeline tolerates replies of a few seconds, with 15 s as the hard limit.
  If (1) fails, the Oliver cap still works because she simply doesn't ask a question
  on the last turn. If (2) fails, identification falls back to a single
  "house" device. *Builder's call.*
- **Brain-owned timers and announcements.** The reading timer lives in the brain,
  shown on `/screen`. When it ends, the brain calls HA's `assist_satellite.announce`
  on the Voice PE ("Time's up, Cillian! Tell me about what you read.").
  - So the brain's HA token needs service-call access, not just notify.
  - It uses a dedicated non-admin HA user, "destiny-brain", for that token. *Builder's call.*
- **HA's free local commands don't depend on the brain.** HA handles them before
  calling any agent. Brain phrases such as "it's Cillian", "homework time" and "Oliver
  loves dinosaurs" match no built-in HA sentence, so they reach the brain.

### 5.2 Brain service (`brain/`)
- **Stack:** Python 3.12, FastAPI, the official Anthropic SDK, SQLite (one file in
  `data/brain/`), and plain HTML/JS pages with a websocket for live updates.
- **Compose:** a new `brain` service on port 8000, with `restart: unless-stopped` and a
  healthcheck.
- **Config:** `.env` holds `ANTHROPIC_API_KEY`, the brain's HA token, HA URL, the parent
  phone's notify service name, the daily summary time, the daily spend cap and the parent PIN.
- Profiles and interests are editable data, not code.

## 6. Model routing (Andrew's advice, adapted)

| Tier | Handles | Engine | Cost |
|---|---|---|---|
| 0 | Timers, time/date, shopping list, (later) devices | HA built-in intents, before the brain | $0 |
| 1 | Everyday questions, Oliver chat, quiz generation, classification | Claude Haiku | ~cents/day |
| 2 | Cillian tutoring and reading checks; long or complex explanations | Claude Sonnet | most of the spend |

- **Router is rules first:**
  - Active mode decides first: a Cillian learning session goes to Tier 2, Oliver goes to Tier 1.
  - Otherwise simple heuristics: question length, "explain", "why", "help me understand"
    go to Tier 2; everything else to Tier 1.
  - Only when the rules are unsure does a Haiku classification call decide.
  - The common path adds no extra model call.
- **Escalation:** Haiku may hand off to Sonnet by calling a `needs_deeper_answer` tool
  (logged), instead of guessing.
- **Logging:** every request records profile, mode, tier, model, input/output tokens,
  estimated $, latency, route reason, whether web search was used, and safety flags.
  The parent page shows cost per day and per profile.
- **Spend cap:** checked *before* each call, using the day's logged spend including
  web-search fees.
  - Above the soft cap (default $1/day), new non-learning Tier 2 requests drop to
    Tier 1, and the parents are notified once that day.
  - **A Cillian learning session is never downgraded mid-session.** Tutoring
    quality and the no-final-answer rule matter more than cents.
  - A hard cap (default $3/day) stops all model calls with a friendly spoken line.
  - *Builder's call.*
- **Latency budget:**
  - Tier 1 should reply within about 2 s of the text arriving.
  - Tier 2 within about 5 s.
  - The connector's 15 s timeout is a failure guard, not a target.
- **Prompt caching** on the long, stable system prompts to cut cost.
- **Pluggable providers:** a provider interface (send messages + tools, get text + usage).
  Only Anthropic is implemented. Trying others later is configuration plus one adapter,
  justified by the logs.

## 7. Profiles and knowing who's talking (v1, no voice recognition)

Profiles:
- **Cillian:** child, 10, learner.
- **Oliver:** toddler, 2.
- **Parent:** adults; full features.
- **Family:** unknown speaker; family-friendly defaults, with the same safety level as a child.

Identification v1:
1. **Explicit:** phrases like "it's Cillian", "this is Oliver", "it's Mom/Dad" set the
   speaker for that device. It sticks while the conversation continues and for
   10 minutes after the last turn (configurable).
2. **Learning session:** "Destiny, homework time" or "let's do reading" assumes Cillian
   if no speaker is set, and Destiny confirms ("Hi Cillian, ready?").
3. **Toddler heuristic:**
   - Applies when no adult or Cillian session is active on that device and the
     transcript looks like babble: fragments, repeated syllables, words that make no
     sentence.
   - Ordinary short replies and commands ("yes", "no", "stop", "okay", "thanks") are
     **never** treated as babble.
   - Treat it as Oliver: respond warmly, don't answer the words literally, and never say
     "I didn't understand".
   - A rare misfire toward an adult gets a cheerful line and they can rephrase.
   - "Stop" or "cancel" always ends the current chat or session, for anyone.
4. **Otherwise** the speaker is Family.
5. **Parent-only changes live on the PIN-protected parent page only:** profiles,
   interests, current topics, spend caps.
   - No spoken passphrase, since the kids would hear it.
   - Harmless voice requests are open to anyone: "how did Cillian do today?",
     "Oliver loves dinosaurs now". Interest updates by voice are logged and shown
     on the parent page.
   - The PIN is never logged.
6. **State is kept per device:**
   - Speaker, active mode and session are keyed by the device that heard the request.
   - Learning progress is keyed by profile.
   - Two devices can run independent conversations at once, e.g. Cillian on the Voice
     PE and a parent on the phone app.
   - A new explicit speaker or session on a device replaces whatever was active
     there. "Homework time" wins over an Oliver chat.

Future voice recognition plugs in as a "speaker hint" from a small step in front of
Whisper (it compares audio to enrolled voice samples). The brain treats it as one more
signal in this same order. No hardware is needed.

## 8. Oliver toddler mode

- **Tone:**
  - Cheery, encouraging, one or two short sentences, simple words.
  - Echoes and builds on what he seems to say ("A big truck? Vroom!").
  - Brings up his interests from his profile (Hot Wheels, cars, trucks, spiders).
  - Parents edit the interests by voice ("Destiny, Oliver loves dinosaurs now") or on the parent page.
- **Chat cap:**
  - A "chat" is one toddler-mode HA conversation, from a wake word until Destiny stops
    listening.
  - At most 6 back-and-forths per chat (configurable). The last turn ends warmly ("Bye
    bye, Oliver! Go zoom your cars!") with `continue_conversation=false` and no question.
- **Daily cap:** a configurable maximum number of toddler chats per day (default 10),
  counted per day across devices. After it, Destiny says a friendly goodbye line
  without calling a model.
- **Safety:**
  - Only happy, gentle topics.
  - She never suggests physical actions (climbing, going outside, opening things,
    touching anything).
  - No web search, and never personal questions.
- Tier 1 (Haiku).

## 9. Cillian learning mode

### 9.1 Session flow
- **Start:** "Destiny, homework time" or "let's do reading".
  - Destiny greets him, confirms it's Cillian, and offers the plan:
    "Reading first, 15 minutes, then worksheet, then a quick quiz?"
  - He can do any part on its own.
- **Reading (target 15 min):**
  1. He tells her the book and chapter.
  2. Destiny starts a timer, shown on the screen if one is open.
  3. When the time is up, or he says he's done, she does the comprehension check:
     - she asks him to retell it in his own words
     - then 2–4 questions: who and what, why something happened, a prediction, a
       vocabulary word he met
     - she helps where he's unclear
  4. She rates comprehension (good / partial / needs help) with a one-line note.
  5. She can't see the book. For well-known books she may use her own knowledge, but she
     relies on his retelling and never insists on details he disputes.
- **Worksheet (target about 30 min, about 15 math problems):**
  - He reads a problem aloud. **Destiny repeats it back to confirm** ("So that's
    three-fourths plus two-fifths?"), because Whisper can mangle spoken numbers. She only
    starts helping once he says yes.
  - She guides with hints and questions and never states the final answer. Claude works
    the answer out privately to judge his steps.
  - Enforcement is through the Tier 2 prompt rules (§9.4) plus the scripted conversation
    suite (§15). There's no extra verification model call, to protect latency. *Builder's call.*
  - When he gives his answer, she checks it. If it's wrong, she helps him find the step.
  - Each problem is recorded with its topic, correctness on the first try, and hints used.
  - Other subjects work the same way (English, science, history).
- **Pop quiz:**
  - 3–5 short spoken questions at 5th-grade level on his **current topics**, weighted
    toward shaky topics.
  - She adapts the difficulty and records the results.
- **End:** she gives a short spoken recap and praise ("47 minutes, all 15 problems,
  great job on decimals!").

### 9.2 Current topics
- "What Cillian is learning now" is stored per subject, e.g. Math: adding fractions with
  unlike denominators; Science: water cycle.
- It's updated by voice (Cillian or a parent) or on the parent page.
- If a list hasn't been updated in 3 weeks, Destiny asks at the start of a session.
- Grade-level knowledge comes from Claude's understanding of US 5th-grade
  standards (Common Core math, typical ELA, science and social-studies topics). No
  curriculum database in Phase 2.

### 9.3 Mastery memory
- Per topic she tracks attempts, first-try correct rate, hints per problem, last
  practised, and status: learning / shaky / solid. The status rules are left to the builder.
- Shaky topics come back in quizzes and in the session recap.

### 9.4 Tutoring rules (Tier 2 system prompt)
- Hint ladder: ask what he knows, then a nudge, then a worked example of a *similar*
  problem, then walk through the steps with him doing each step. Never give the final
  answer to a worksheet problem.
- Short spoken chunks, one question at a time, patient, and he never feels stupid.
- He can ask for a break. After 10 minutes of silence the session pauses; it resumes the
  same day where it left off.

## 10. Progress tracking and parent view

My proposal, accepted by the family:

- **Recorded per session:**
  - minutes per activity
  - problems done and first-try correct
  - hints
  - reading comprehension rating plus note
  - quiz results by topic
  - topics touched
  - safety flags
- **Daily push** at a configurable time (default 7:00 pm) to the parent's phone through
  the HA Companion app (`notify.mobile_app_<phone>`):
  "Cillian: 47 min (reading 16, worksheet 31). Math 15 problems, 12 right first try. Reading: good.
  Shaky: equivalent fractions. Oliver: 3 chats."
  If he skipped, it says so gently.
- **Parent page** at `http://<PC>:8000/parent`, behind a PIN:
  - today and this week per child: minutes vs. target, streak, problems, quiz accuracy by topic
  - mastery list (shaky/solid)
  - reading log (books and ratings)
  - editable current topics and Oliver's interests
  - cost per day by profile and tier
  - recent safety flags
  - a transcript viewer covering the last 30 days
- **Voice:** "Destiny, how did Cillian do today?" gives a spoken summary (parent only).
- **Retention:**
  - Raw transcripts are kept 30 days, then deleted.
  - Session summaries and mastery data are kept indefinitely.
- **Backup:** a nightly copy of the SQLite file goes to a configurable folder,
  default `data/backups/`, keeping 14 days. Copying that folder somewhere safe is the
  family's choice. *Builder's call.*

## 11. Child safety

- **Baseline for everyone:** family-friendly; she says she's an AI if asked.
- **Child and Family profiles get stricter rules in their system prompts:**
  - no scary, violent, sexual or adult content
  - no personal-information gathering
  - no instructions for dangerous activities
  - no medical, legal or drug advice beyond "ask a grown-up"
- **Red-flag check:**
  - Every child or unknown-speaker turn is checked for signs of danger, self-harm,
    abuse, being hurt, or a stranger contacting him.
  - This uses cheap rules plus a flag the model sets through a tool, with no extra model
    call on the common path.
  - **Sensitivity: normal (the family's choice).** Alert only when it's likely serious:
    self-harm, abuse, being hurt by someone, a stranger or online contact asking
    personal details or to meet, or real danger.
    - Don't alert on fiction, games, scary books, or figures of speech ("my brother is
      killing me"). Destiny can still respond kindly to those.
    - Borderline turns are logged as "noted" on the parent page without a push.
    - The sensitivity setting is adjustable on the parent page.
  - **On a serious flag:**
    - Destiny responds kindly and **tells the child gently that she's letting the
      parents know** (the family's choice): "That sounds really important. I'm going
      to let Mom and Dad know so they can help you."
    - The turn is logged.
    - The parents get an **immediate push**. A failed push is retried and always shown
      on the parent page.
    - The same rules apply to Oliver's chats.
- **Web search for children:** answers come out child-appropriate, and search results
  are never read out verbatim.
- Claude's own built-in safety is the last line of defence, not the only one.

## 12. Web search

- Uses the Anthropic API's server-side web search tool. It's available to Tier 1 and
  Tier 2, off for Oliver, and used only when the question needs current info (news,
  scores, hours, forecasts).
- This closes Phase 1's "no forecast" gap.
- It's logged, including its extra cost.

## 13. Cillian's screen

- `http://<PC>:8000/screen`, opened in any browser (PC, a tablet on a stand, an old laptop).
- A device or profile pairing is chosen once on the page and remembered by the browser.
- It shows live, via websocket from the active learning session:
  - the current quiz question with simple visuals (fraction bars, number lines)
  - the reading timer
  - session progress
  - hints as text
  - an idle "Hi Cillian" screen
- Voice remains the main input. Tap or typed answers are a later idea.
- It's built last within Phase 2 (milestone 5) because it reuses everything else.

## 14. Milestones (each is testable on its own)

1. **Brain parity:**
   - brain service, HA connector, Tier 1/2 routing, logging, spend cap
   - Destiny's assistant switched to "Destiny brain"
   - Phase 1 behaviour unchanged; costs visible in a minimal parent page
2. **Profiles, identification v1, Oliver mode, safety:** including red-flag push.
3. **Cillian learning:**
   - sessions, reading check, worksheet helper, quizzes, topics, mastery
   - daily summary push, the full parent page, and the family vault (§18)
4. **Web search.**
5. **Cillian's screen.**

Rollback at any point: switch the Destiny assistant back to the Phase 1 "Claude
conversation" agent in HA.

## 15. Testing

- Unit tests (pytest, in the brain container):
  - router decisions
  - identification rules
  - toddler caps
  - hint-ladder guard (worksheet answers never stated)
  - safety rules
  - progress math
  - daily summary text
  - cost calculation
- Model calls are faked.
- Integration test: the HA connector against a fake brain, and the brain against a fake
  provider.
- A small **scripted conversation suite**, run on demand against the real API (costs cents):
  - a Cillian worksheet problem, where the answer must not be given
  - a reading check
  - a quiz
  - an Oliver babble chat that ends by the cap
  - a red-flag phrase that triggers the push
  - a current-events question that uses web search
- Extend `scripts/smoke_test.py` with a brain health check. Also fix its known gap:
  the weather check must fail when Destiny says she has no weather data.
- Live checks with the family per milestone, with latency recorded as in Phase 1.
- Tests and the scripted suite run in the brain container
  (`docker compose run --rm brain ...`), with the API key from `.env`. The brain image
  is built locally from `brain/Dockerfile`; there's no registry.
- During setup the family supplies the brain's HA token and the parent phone's notify
  service name, which are found in HA under the Companion app's device.

## 16. Costs (estimate)

- Cillian about 45 min/day on Sonnet with caching: roughly $8–12/month.
- Everyday questions and Oliver on Haiku: about $1–3/month.
- Web search: small, logged.
- **Target: ≤ $15/month.** A daily cap (default $1/day) protects against surprises.

## 17. Privacy

- Audio never leaves the house (unchanged). Text goes to Anthropic only.
- The database and transcripts stay on the PC. Transcripts are deleted after 30 days.
- The parent page is LAN-only and behind a PIN. The brain port is open on the Private
  firewall profile only.

## 18. Family vault (Obsidian)

The family wants Destiny's knowledge of their life to be readable, browsable and
scalable: "so we can understand every aspect of our lives". Obsidian is the family's
reader for it.

- **Two vaults, kept apart:**
  - **Project docs:** `C:\dev\Destiny\docs`, opened in Obsidian as a vault. It holds how
    Destiny is built (specs, plans, log). It's git-tracked, and `.obsidian/` is ignored.
  - **Family vault:** Destiny's view of family life. It's a folder bind-mounted into the
    brain container, with the path set in `.env`.
- **Location (my default, changeable):** a folder in OneDrive, so parents can read it on
  their phones through Obsidian.
  - Markdown files sync safely; only the SQLite database must stay off OneDrive (it stays
    in `data/brain/`).
  - Because OneDrive is a cloud service, the vault holds **summaries only, never raw
    transcripts or safety-flag details**.
  - Set the folder to "Always keep on this device" so Docker sees real files.
- **Phase 2 scope: Destiny writes, one way.** SQLite stays the source of truth, and the
  vault is a readable mirror, regenerated after each session and nightly.
  - `Cillian/Daily/YYYY-MM-DD.md`: session summary (minutes, problems, reading rating,
    quiz results, shaky topics).
  - `Cillian/Progress.md`: mastery by topic, streaks, current topics.
  - `Cillian/Reading log.md`: books, chapters, comprehension notes.
  - `Oliver/Interests.md` and `Oliver/Chats.md` (counts and a happy-moments line, no transcripts).
  - `Family/Weekly/YYYY-Www.md`: weekly roll-up, including cost.
  - Notes use YAML frontmatter (date, child, minutes, topics), so Obsidian queries and
    graphs work and later phases can read them back.
- **Phase 3 and beyond: two-way.**
  - Household projects, reminders and family notes live in the vault as Markdown.
  - Destiny reads and updates them by voice, and parents edit them in Obsidian.
  - The vault becomes the place where the family's life is organised: projects, house,
    health, school, plans.
- Part of milestone 3 (§14), alongside progress tracking.

## 19. Left to the builder

- Exact API shapes between the connector and the brain, and the DB schema.
- Mastery status thresholds; prompt wording within the rules above.
- The router's heuristic details and the confidence threshold for the Haiku classifier.
- Page styling (simple, big text, kid-friendly for `/screen`).
- How the websocket picks which screen to update (pairing details).
- Exact model IDs and pricing table (use current Claude Haiku and Sonnet; prices in config).
