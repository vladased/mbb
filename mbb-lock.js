// mbb-lock.js — Scriptable lock-screen widget for mbb          (callsign: mbb)
//
// Scriptable is the one free app that can BOTH render lock-screen accessory
// widgets AND read another app's folder (via a File Bookmark). It reads the
// same mbb-data/widget-snapshot.json the Pyto home widget uses — no network,
// so the WidgetKit no-localhost rule never applies.
//
// ONE-TIME SETUP (on the phone):
//   1. Scriptable → Settings (gear) → File Bookmarks → +
//      → pick folder: Files → On My iPhone → Pyto → mbb → mbb-data
//      → name it exactly:  mbb-data
//   2. New script → paste this file → name it "mbb-lock"
//   3. Lock screen → long-press → Customize → add a Scriptable accessory
//      widget (inline / circular / rectangular) → choose script "mbb-lock"
//   4. First run: verify the widget shows numbers, not "setup" — the
//      bookmark-inside-widget path is community-proven (Obsidian widgets)
//      but this is its first run against Pyto's folder.
//
// Honest staleness: snapshot older than 5 min renders as asleep, never as
// live numbers.

const STALE_AFTER = 300;
const BOOKMARK = "mbb-data";

function readSnapshot() {
  const fm = FileManager.local();
  if (!fm.bookmarkExists(BOOKMARK)) return { state: "setup" };
  try {
    const p = fm.bookmarkedPath(BOOKMARK) + "/widget-snapshot.json";
    if (!fm.fileExists(p)) return { state: "missing" };
    const d = JSON.parse(fm.readString(p));
    const age = Date.now() / 1000 - (d.ts || 0);
    return { state: age > STALE_AFTER ? "asleep" : "up", d, age };
  } catch (e) {
    return { state: "missing" };
  }
}

function ageLabel(age) {
  if (age < 60) return "now";
  if (age < 3600) return Math.floor(age / 60) + "m";
  if (age < 86400) return Math.floor(age / 3600) + "h";
  return Math.floor(age / 86400) + "d";
}

function line(snap) {
  if (snap.state === "setup") return "mbb: add File Bookmark";
  if (snap.state === "missing") return "mbb: run mbb.py once";
  if (snap.state === "asleep") return "mbb asleep " + ageLabel(snap.age);
  const d = snap.d;
  return "● mbb " + (d.memories || 0) + "m · " + (d.open_tasks || 0) + "t" +
         (d.pending ? " · " + d.pending + "✉" : "");
}

function makeWidget(snap) {
  const w = new ListWidget();
  w.addAccessoryWidgetBackground = true;
  w.url = "http://localhost:5100";                    // tap → the PWA
  w.refreshAfterDate = new Date(Date.now() + 15 * 60 * 1000);
  const fam = config.widgetFamily || "accessoryRectangular";
  const up = snap.state === "up";

  if (fam === "accessoryInline") {
    w.addText(line(snap));
    return w;
  }
  if (fam === "accessoryCircular") {
    const big = w.addText(up ? String(snap.d.open_tasks || 0) : "·");
    big.font = Font.boldSystemFont(20);
    big.centerAlignText();
    const cap = w.addText(up ? "tasks" : "mbb");
    cap.font = Font.systemFont(9);
    cap.centerAlignText();
    return w;
  }
  // accessoryRectangular (and home-screen fallback)
  const head = w.addText(up ? "● mbb · " + ageLabel(snap.age)
                            : "● mbb — " + snap.state);
  head.font = Font.boldSystemFont(12);
  if (up) {
    const last = w.addText((snap.d.last || "idle").slice(0, 40));
    last.font = Font.systemFont(10);
    last.textOpacity = 0.8;
    const pct = Math.min(100, Math.round(
      (snap.d.tokens_used || 0) * 100 / (snap.d.token_budget || 1)));
    const foot = w.addText(
      (snap.d.memories || 0) + "m · " + (snap.d.open_tasks || 0) + "t · " +
      pct + "% budget");
    foot.font = Font.systemFont(10);
    foot.textOpacity = 0.6;
  } else {
    const hint = w.addText(snap.state === "setup"
      ? "Settings → File Bookmarks → mbb-data"
      : "open Pyto ▶ mbb.py");
    hint.font = Font.systemFont(10);
    hint.textOpacity = 0.7;
  }
  return w;
}

const snap = readSnapshot();
const widget = makeWidget(snap);
if (config.runsInWidget) {
  Script.setWidget(widget);
} else {
  console.log(JSON.stringify(snap, null, 2));        // in-app: debug view
  await widget.presentAccessoryRectangular();
}
Script.complete();
