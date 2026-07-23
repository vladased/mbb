# mbb — first real-device shakedown (iPhone 14)

Nothing has ever run on actual hardware; all validation is the 195-check
offline suite + container boots. This is the ordered first run. Do it in
sequence — later steps depend on earlier ones. Note anything that breaks in
`mbb-data/notes/inbox/shakedown.md` (or just tell mbb once it's alive).

## A. Install + boot

- [ ] 1. Pyto → new file → paste the installer one-liner (mbb/README.md §Install) → Run ▶
       — expect: `fetch mbb.py … ok`, plus README/SHORTCUTS/widget files, no red.
- [ ] 2. Open `mbb.py` → Run ▶ — expect the boot banner: `▣ mbb v7.1`, keys line,
       and `push  bark — · keep-alive ON (BackgroundTask id=mbb)`.
       If keep-alive says `n/a`: you're not in Pyto or the import failed — report.
- [ ] 3. Pyto Settings → Background Execution → **On**.
- [ ] 4. Safari → `http://localhost:5100` → chat replies (`/status` works with zero keys)
       → Share → **Add to Home Screen** → open the installed app once.

## B. Keys + push

- [ ] 5. `/key claude sk-ant-...` (and/or free-tier `groq`/`gemini`).
- [ ] 6. Open Bark once → copy the device key from its server URL →
       `/key bark <device_key>` — expect: "Test push sent" **and** the push
       arriving on the lock screen within seconds. This is the Phase-1
       centerpiece; if it fails, check the key and report.
- [ ] 7. Ask mbb: "queue a notify action saying hello" → the Bark copy should
       arrive instantly, *before* any Shortcut runs.

## C. Survival (the honest tests)

- [ ] 8. **Keep-alive**: background Pyto (go home), wait 5+ min, reopen the PWA —
       did it answer without relaunching Pyto? Then try 30 min. Note the
       point where iOS kills it anyway (memory pressure is still real).
- [ ] 9. **Dead-man**: with the server up, force-quit Pyto and wait ~90 min —
       expect the OS-held "⚠ mbb is asleep" notification. (First prime iOS
       notification permission: the prompt only appears while Pyto is
       foreground — step 6's test push usually triggers it.)
- [ ] 10. **Snapshot freshness**: Files → On My iPhone → Pyto → mbb →
       mbb-data → `widget-snapshot.json` exists and its `ts` updates after
       each chat turn.

## D. Widgets

- [ ] 11. Pyto → widget icon → Run Script → `mbb_widget.py`; add **small** and
       **medium** to the home screen — expect live numbers; kill the server,
       wait 5+ min → widget must flip to "asleep · open Pyto ▶ mbb.py"
       (if it keeps showing numbers, that's a bug — report).
- [ ] 12. Put the phone on the charger in landscape → StandBy → the small
       widget should be offered.
- [ ] 13. Scriptable → Settings → File Bookmarks → + → Pyto → mbb → mbb-data,
       name `mbb-data` → new script "mbb-lock" ← paste `mbb-lock.js` → run
       in-app once (debug JSON should print) → add lock-screen accessory
       widgets. **This is the one unproven link in the chain** (bookmark
       inside a widget against Pyto's folder) — if the widget says "setup"
       forever, report; Plan B is documented in the audit (Tailscale HTTPS).

## E. Shortcuts (build from SHORTCUTS.md, in this order)

- [ ] 14. **Brain: Do** (#0) + **Brain: Tick** (#0b) — run Do manually once;
       queued actions from step 7 should drain.
- [ ] 15. **Brain: Voice** (#1) with the haptic confirm — Back Tap → speak →
       buzz = filed. Verify the capture landed: `/recall` it.
- [ ] 16. **Brain: Nightly / Morning** automations (#3/#4 — charger + alarm-stopped).
- [ ] 17. Offline variants (#offline): FIRST open Shortcuts → search
       "Locally AI" — write down the intent's exact name + parameters
       (publicly undocumented; SHORTCUTS.md assumes prompt-in/text-out).
       Model: Qwen3 4B. Then build Brain: Nightly (offline) and run it once
       manually with the phone charged.
- [ ] 18. Context pushers (#0c) incl. the new battery-level automations.

## F. Wrap

- [ ] 19. `/status` — bark ✓, keys ✓, crons listed; `python3 mbb.py update`
       runs clean (proves the main-branch update path end-to-end).
- [ ] 20. Tell mbb what broke. It has a skill system — teach it the fixes.
