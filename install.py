#!/usr/bin/env python3
# install.py — mbb bootstrap installer for Pyto (also works anywhere)
#
# In Pyto: new file → paste this → Run ▶. Or one-liner in any Python console:
#
#   import urllib.request as u
#   exec(u.urlopen('https://raw.githubusercontent.com/vladased/mbb/'
#                  'main/install.py')
#        .read().decode())
#
# Downloads mbb.py (+docs) next to this script, syntax-checks before writing,
# never overwrites your mbb-data/. Re-run any time to update (or use the
# built-in `python3 mbb.py update`, which also keeps rollback backups).

import urllib.request
from pathlib import Path

REPO_RAW = ('https://raw.githubusercontent.com/vladased/mbb/'
            'main')
FILES = ['mbb.py', 'mbb_widget.py', 'mbb-lock.js', 'README.md',
         'SHORTCUTS.md', 'SHAKEDOWN.md']

try:
    HERE = Path(__file__).resolve().parent
except NameError:                      # exec()'d one-liner has no __file__
    HERE = Path.cwd()

print('mbb installer')
print(f'  target  {HERE}')
for name in FILES:
    url = f'{REPO_RAW}/{name}'
    print(f'  fetch   {name} …', end=' ')
    req = urllib.request.Request(url, headers={'User-Agent': 'mbb-install'})
    data = urllib.request.urlopen(req, timeout=60).read().decode('utf-8')
    if name.endswith('.py'):
        compile(data, name, 'exec')    # refuse to write broken code
        if 'callsign: mbb' not in data:
            raise SystemExit(f'{name} failed sanity check — aborting')
    (HERE / name).write_text(data, encoding='utf-8')
    print(f'ok ({len(data) // 1024}kb)')

print('''
installed. Next:
  1. open mbb.py in Pyto → Run ▶
  2. Safari → http://localhost:5100 → Share → Add to Home Screen → "mbb"
  3. in the chat: /key claude sk-ant-...   (or free-tier groq/gemini)
  4. build the Shortcuts — see SHORTCUTS.md (or http://localhost:5100/install)
  5. optional: Pyto Settings → Background Execution → On; ⚡ dock mode in the app
''')
