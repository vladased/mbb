# mbb — Apple Shortcuts & phone UX setup (v7.1)

These shortcuts turn mbb into an ambient second brain **with hands**. All
built by hand in the Shortcuts app — no compiling, no Mac. Ordered by impact.

> v4 additions: **#0 Brain: Do** (the actuator — mbb queues real phone
> actions, this shortcut executes them), the **hourly tick** (runs mbb's
> self-built cron jobs), and **context pushers** (location/focus/battery).
>
> v7.1 additions (free-app audit): the **Actions** app (free, Sindre
> Sorhus) hardens every recipe — where a recipe says **[guard]**, prepend
> Actions' **"Is Web Server Reachable"** on `http://localhost:5100/api/status`
> and If-branch to the offline fallback instead of relying on
> "Continue on Error" + timeouts. Also: haptic confirm on capture,
> battery-level context automations, Morning on **Alarm Stopped**, an
> Obsidian mirror, and the **#8 widgets** section (Pyto + Scriptable).
> Note: mbb's notify actions now ALSO arrive instantly via Bark
> (`/key bark <device_key>`) — Brain: Do remains the rich/actioned copy.

---

## 0. 🤖 "Brain: Do" — the actuator (v4's centerpiece)

iOS gives no app permission to tap the screen or drive Accessibility. But
Shortcuts can send messages, add reminders/events, run HomeKit scenes, open
any app. So mbb *queues intentions* and this shortcut *executes* them:

0. **[guard]** Is Web Server Reachable (`/api/status`) → If No → Stop
1. **Get Contents of URL** — GET `http://localhost:5100/api/actions/next`
2. **Get Dictionary Value** `action` → **If** it has no value → Stop
3. **Get Dictionary Value** `kind`, `params`, `requires_confirm`, `id`
4. **If** `requires_confirm` is `true` → **Show Alert** ("mbb wants to:
   [kind + params]" — Cancel stops here and POSTs `ok:false`)
5. **If kind is** `notify` → Show Notification (params.title / params.text)
   · `reminder` → Add New Reminder (params.text, params.when)
   · `calendar` → Add New Event (params.title, params.start)
   · `clipboard` → Copy to Clipboard (params.text)
   · `open_url` → Open URL (params.url)
   · `message_draft` → Send Message (params.text to params.to — leave
     "Show When Run" ON so *you* hit send)
   · `homekit` → Run Home Scene (params.scene)
6. **Get Contents of URL** — POST `/api/actions/done` JSON
   `{id, ok: true, result: "done"}`
7. **Repeat** steps 1–6 ×5 (drains up to 5 queued actions per run)

Run it: manually, from Control Center, and **chain it after every automation
below** (tick, morning, nightly) so queued actions drain several times a day.
Safety: outward kinds always alert first; `/deny phone_do:*` kills a kind
entirely; every action's outcome is visible in the brain tab.

## 0b. ⏱ "Brain: Tick" — hourly heartbeat for self-built crons

mbb builds its own scheduled jobs (`cron_manage` / just ask it). They run
when *anything* ticks the server. Automation: **every hour** (or attach to
Charger/Focus changes) → Run Immediately:

1. **[guard]** Is Web Server Reachable → If No → Stop
2. **Get Contents of URL** — GET `http://localhost:5100/api/tick`
3. Run **Brain: Do** (drain any actions the crons queued)

More drain moments (all optional, all silent triggers): **App Opened =
Pyto** → run this (every manual wake immediately ticks), and an **NFC tag**
stuck to the charging stand → Brain: Tick + Brain: Do (tap-to-tick dock).

Plus: the PWA heartbeats every 5 min while ⚡ dock mode is on — a docked
phone runs its crons with zero shortcuts. Guards: ≥15-min intervals, max 12
jobs, 24 runs/day, skipped below 20% battery, every run audited.

## 0c. 📍 Context pushers — situational awareness

Tiny automations that POST to `/api/context` (JSON): **Arrive/Leave home** →
`{"location":"home"}` / `{"location":"away"}`; **Focus changes** →
`{"focus":"Work"}`; add `"battery"` (Battery Level) to the Tick shortcut.
v7.1: also **Battery falls below 20%** / **rises above 80%** →
`{"battery":"18"}` — feeds the cron battery-floor guard *between* ticks
(these run silently). Optional richer note via Actions (Get Battery State
charging? + Is Low Power Mode) → `{"note":"charging, low power"}`.
Wi-Fi-join-home / Bluetooth-connect triggers work too but always post a
visible "ran" notification (iOS rule) — use only if that doesn't annoy.
mbb injects fresh context into every turn ("Phone: location=home ·
focus=Work · battery=64%") and uses battery to throttle cron runs.

Design reality (verified July 2026): iOS suspends Pyto within ~a minute of
backgrounding, so **nothing here assumes the server is running** — capture
falls back to a file queue, jobs run in-process via Pyto's Run Script action.
Charger is the most reliable automation trigger; Time of Day can silently
skip during Sleep Focus. iPhone 14 has no Apple Intelligence, so Back Tap +
Control Center are your instant-capture hardware.

---

## 1. 🎙 "Brain: Voice" — voice capture (build this first)

iOS 26's **Transcribe Audio** action is on-device and free. Shortcut:

1. **Record Audio** (tap to stop)
2. **Transcribe Audio** (input: Recorded Audio)
3. **[guard]** Is Web Server Reachable → If Yes:
   **Get Contents of URL** — POST `http://localhost:5100/api/capture`,
   JSON body → `text`: Transcribed Text →
   **Generate Haptic Feedback** (Actions) — single buzz = filed
4. If No → **Append to Text File**: `inbox-queue.txt` in
   **On My iPhone → Pyto → mbb → mbb-data** — ⚠ pick the file with the
   action's file-picker while building (that stores a bookmark); a typed
   path silently can't reach Pyto's folder →
   **Generate Haptic Feedback** twice — double buzz = queued offline

Wire it to **Back Tap** (Settings → Accessibility → Touch → Back Tap →
Double Tap) — thought → double-tap phone → spoken → filed. Server dead?
Queued; drained on next wake, indexed into memory either way.

## 2. 📎 "Brain: Capture" — share sheet

Same as #1 minus recording: receives **Text/URLs/Safari pages** from the
Share Sheet; POST `text` + `url` to `/api/capture`; queue-file fallback.
Add it to **Control Center** (iOS 18+: Controls gallery → Shortcut) so
capture is one swipe away, even from the Lock Screen.
Optional Obsidian mirror: add Obsidian's native **"Capture to Daily Note"**
action (mobile 1.11.4+, appends without opening the app) so captures also
land in your vault. Known bug: fails if today's daily note doesn't exist
yet — put it AFTER the mbb POST so a failure never loses the capture.

## 3. 🌙 "Brain: Nightly" — Charger automation

Automation: **When Charger Connects** → Run Immediately.

1. **Run Script** (Pyto) — `mbb.py`, arguments: `nightly`, Show Console OFF
2. (optional) **Get Script Output** → **Show Notification**

Nightly = drain queue → prune stale memories → curate skills (stale at 30
idle days, archive at 90) → LLM distills the day into FACTS.md + journal →
consolidates FACTS if over 90% budget. The run is **audited**: if iOS kills
it mid-job, mbb marks it `unknown` and the next morning brief tells you.

## 4. ☀️ "Brain: Morning" — wake-up automation

Automation: **When "Alarm Stopped" (Wake-Up alarm)** → Run Immediately —
preferred: fires when you actually wake. Fixed **6:30 AM Time of Day**
works too but verifiably skips silently when the phone sits locked in
Sleep Focus — if you use it, pair it with the alarm trigger.

1. **Run Script** — `mbb.py`, arguments: `morning`, Show Console OFF
2. **Get Script Output** → **Show Notification** (or Speak Text)

Includes open tasks, journal, key memories, and any failed/unknown job runs.
If there's nothing worth saying the model replies `[SILENT]` and you hear
nothing — no noise, still logged. The brief is also written to the delivery
ledger, so it's waiting in the PWA (⟳ recovered) even if the notification
was missed.

## 5. ⚡ Dock mode — the pseudo-always-on

The PWA's **⚡ button** takes a Screen Wake Lock (Safari 18.4+): screen stays
on → Pyto stays alive → mbb answers instantly. Phone on a charging stand +
⚡ on = a bedside/desk terminal for your brain. This is the closest legal
thing to a daemon on one iPhone.

## 6. 💾 "Brain: Backup" — free off-device git backup (a-Shell)

Install **a-Shell** (free). Once: `lg2 clone https://TOKEN@github.com/YOU/brain-backup.git`
and point it at a copy job. Then a shortcut (chain it after Nightly):

1. a-Shell **Execute Command**: `cp -r ~/Documents/../Pyto/mbb-data ~/brain-backup/ && cd ~/brain-backup && lg2 add . && lg2 commit -m backup && lg2 push`

(Exact Pyto Documents path: check Files → On My iPhone → Pyto. Or skip git
entirely: the PWA brain tab has **⬇ brain zip** → share sheet → anywhere.)

## 7. 🛰 Tailscale — reach mbb from any of your devices

Install Tailscale (free personal). Run mbb with `MBB_HOST=0.0.0.0`, note the
token printed at boot, open `http://<phone-tailnet-name>:5100/?token=<token>`
from your laptop/iPad — the PWA stores the token after one visit. All
non-loopback requests without it get 401. Bonus: point mbb's `local`
provider at LM Studio on your Mac over the tailnet:
`/key local http://your-mac.tailnet:1234/v1 qwen3-30b` — a free big model
for the aux jobs whenever you're home.

---

## 8. ⿴ Widgets — home screen, StandBy, lock screen (v7.1)

mbb writes `mbb-data/widget-snapshot.json` after every turn/job/boot; the
widgets read the FILE (WidgetKit forbids localhost HTTP — every widget app).
Both render an honest "asleep" state when the snapshot is >5 min old.

**Home + StandBy (Pyto):** Pyto → widget (grid) icon → Run Script →
`mbb_widget.py` → add small/medium from the home-screen widget gallery.
The small one is offered in StandBy while charging in landscape.

**Lock screen (Scriptable):** one-time — Scriptable Settings →
File Bookmarks → + → Files → On My iPhone → Pyto → mbb → mbb-data →
name it `mbb-data`. New script "mbb-lock" ← paste `mbb-lock.js` → run once
in-app (debug view) → lock screen → Customize → add Scriptable accessory
widgets (inline / circular / rectangular) → choose "mbb-lock". Tap opens
the PWA. See SHAKEDOWN.md D13 — first run verifies the bookmark works
inside the widget extension.

---

## 🧠 Fully-offline brain (iPhone 14): the two-phase pipeline

No home machine, no VPS, no cloud — the phone is the whole stack.
**Locally AI** (free, by LM Studio) runs 3–4B models on-device with a
Shortcuts intent; mbb's jobs split into collect → model → apply so the
Shortcut carries the model call:

**"Brain: Nightly (offline)"** — Charger automation:
1. **Run Script** (Pyto) — `mbb.py`, arguments: `nightly-collect`,
   Show Console OFF → **Get Script Output**
2. **If** output is `[NOTHING]` → Stop
3. **Ask Locally AI** (App Intent) — prompt: Script Output
   *(model: Qwen3 4B — the iPhone 14's 6 GB handles it. Enclave AI's
   Shortcuts action is a drop-in alternative if you use that app instead;
   pick ONE so you keep a single model store.)*
4. **Run Script** — `mbb.py`, arguments: `nightly-apply` + Locally AI's reply
5. Chain **Brain: Do**

**"Brain: Morning (offline)"** — same shape with `morning-collect` /
`morning-apply`; put the reply in a notification too.

A 3–4B model is plenty for distill-my-day JSON and a 120-word brief. When
online, the normal `nightly`/`morning` commands use cloud keys instead —
run whichever variant fits, mbb's audits and ledger treat both the same.
Zero-infra big models: free-tier Groq/Gemini keys (`/key groq gsk_...`).

**On an iPhone 15 Pro or later:** two better options with zero machines —
swap step 3 for Shortcuts' **Use Model** action (Apple's on-device model),
or install the free "Local LLM Server" app and `/key local
http://localhost:PORT/v1` for a real always-available provider.

---

## Siri

"Ask my brain": **Dictate Text** → POST `/chat` (JSON `message`) → **Get
Dictionary Value** `text` → **Speak Text**. Requires the server up (dock
mode, or open Pyto first). Name the shortcut "Ask my brain" →
"Hey Siri, ask my brain…"
