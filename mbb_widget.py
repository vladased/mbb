#!/usr/bin/env python3
# mbb_widget.py — Pyto WidgetKit home-screen/StandBy widget    (callsign: mbb)
#
# WHY A FILE, NOT HTTP: WidgetKit extension processes cannot make any
# non-HTTPS network request (OS-level rule — every widget app hits it for
# http://localhost). This script runs inside Pyto's widget extension, which
# shares Pyto's sandbox, and reads mbb-data/widget-snapshot.json — written
# atomically by mbb.py after every turn, job, and boot. No network at all.
#
# SETUP (on the phone):
#   1. Pyto → widget (grid) icon → "Run Script" → choose mbb_widget.py
#   2. Home screen → long-press → + → Pyto → small or medium → add
#   3. The small widget also appears in StandBy (charging, landscape)
#
# The widget asks WidgetKit to reload every 15 min (advisory — iOS budgets
# decide). Staleness is rendered honestly: if the snapshot is older than
# 5 minutes the widget says the server is asleep instead of showing old
# numbers as if they were live.
#
# Desktop: `python3 mbb_widget.py` prints a text preview of both layouts.

import json
import os
import time
from pathlib import Path

try:                                    # resolve() matches mbb.py's HOME fix
    _HERE = Path(__file__).resolve().parent
except NameError:
    _HERE = Path.cwd()
HOME = Path(os.environ.get('MBB_HOME', _HERE)).resolve()
SNAPSHOT = HOME / 'mbb-data' / 'widget-snapshot.json'
STALE_AFTER = 300                       # seconds before "asleep"
BAR_CELLS = 6


def load_snapshot(path=None):
    try:
        return json.loads(Path(path or SNAPSHOT).read_text(encoding='utf-8'))
    except Exception:
        return None


def fmt_age(secs):
    if secs < 60:
        return 'now'
    if secs < 3600:
        return f'{int(secs // 60)}m ago'
    if secs < 86400:
        return f'{int(secs // 3600)}h ago'
    return f'{int(secs // 86400)}d ago'


def snapshot_state(d, now=None):
    """→ (state, hint): 'up' | 'asleep' | 'missing' — never lie about age."""
    if not d:
        return 'missing', 'run mbb.py once, then re-add the widget'
    age = (now or time.time()) - d.get('ts', 0)
    if age > STALE_AFTER:
        return 'asleep', f'snapshot {fmt_age(age)} — open Pyto ▶ mbb.py'
    return 'up', ''


def budget_line(d):
    used, limit = d.get('tokens_used', 0), d.get('token_budget') or 1
    pct = min(100, int(used * 100 / limit))
    filled = min(BAR_CELLS, round(pct * BAR_CELLS / 100))
    return '▰' * filled + '▱' * (BAR_CELLS - filled) + f' {pct}%'


def counts_line(d):
    parts = [f"{d.get('memories', 0)} mem", f"{d.get('open_tasks', 0)} tasks"]
    if d.get('pending'):
        parts.append(f"{d['pending']} undelivered")
    return ' · '.join(parts)


def text_preview():
    d = load_snapshot()
    state, hint = snapshot_state(d)
    lines = [f'[mbb widget preview — {state}]']
    if state != 'up':
        lines.append(hint)
    if d:
        lines += [d.get('last', ''), counts_line(d), 'budget ' + budget_line(d)]
    return '\n'.join(lines)


def build(wd):
    from datetime import timedelta
    BG = wd.Color(0.04, 0.05, 0.08, 1.0)
    BLUE = wd.Color(0.35, 0.62, 1.0, 1.0)      # hologram blue, mbb's one accent
    WHITE = wd.Color(0.95, 0.96, 1.0, 1.0)
    GRAY = wd.Color(0.55, 0.58, 0.65, 1.0)
    DIM = wd.Color(0.33, 0.35, 0.42, 1.0)

    d = load_snapshot()
    state, hint = snapshot_state(d)
    dot = BLUE if state == 'up' else DIM

    def small(layout):
        layout.set_background_color(BG)
        layout.add_row([wd.Text('● mbb', font=wd.Font('Helvetica-Bold', 14),
                                color=dot)])
        if state == 'up':
            layout.add_row([wd.Text(str(d.get('memories', 0)),
                                    font=wd.Font('Helvetica-Bold', 26),
                                    color=WHITE)])
            layout.add_row([wd.Text(f"mem · {d.get('open_tasks', 0)} tasks",
                                    font=wd.Font('Helvetica', 10), color=GRAY)])
            layout.add_row([wd.Text(budget_line(d),
                                    font=wd.Font('Helvetica', 9), color=DIM)])
        else:
            layout.add_row([wd.Text('asleep' if state == 'asleep' else 'no data',
                                    font=wd.Font('Helvetica', 12), color=GRAY)])
            layout.add_row([wd.Text('open Pyto ▶ mbb.py',
                                    font=wd.Font('Helvetica', 9), color=DIM)])

    def medium(layout):
        layout.set_background_color(BG)
        if state != 'up':
            layout.add_row([wd.Text('● mbb — ' +
                                    ('asleep' if state == 'asleep' else 'no data'),
                                    font=wd.Font('Helvetica-Bold', 13), color=DIM)])
            layout.add_row([wd.Text(hint, font=wd.Font('Helvetica', 11),
                                    color=GRAY)])
            return
        layout.add_row([
            wd.Text('● mbb', font=wd.Font('Helvetica-Bold', 13), color=dot),
            wd.Text(f"  up {d.get('uptime_m', 0)}m",
                    font=wd.Font('Helvetica', 11), color=DIM)])
        layout.add_row([wd.Text((d.get('last') or 'idle')[:58],
                                font=wd.Font('Helvetica', 11), color=GRAY)])
        layout.add_row([wd.Text(counts_line(d),
                                font=wd.Font('Helvetica-Bold', 12), color=WHITE)])
        nightly = d.get('last_nightly_h')
        layout.add_row([
            wd.Text('budget ' + budget_line(d),
                    font=wd.Font('Helvetica', 10), color=GRAY),
            wd.Text(f'  · nightly {nightly}h ago' if nightly is not None else '',
                    font=wd.Font('Helvetica', 10), color=DIM)])

    widget = wd.Widget()
    small(widget.small_layout)
    medium(widget.medium_layout)
    wd.show_widget(widget)
    wd.schedule_next_reload(timedelta(minutes=15))


if __name__ == '__main__':
    try:
        import widgets as _wd
    except ImportError:
        print(text_preview())           # desktop / non-Pyto: text preview
    else:
        build(_wd)
