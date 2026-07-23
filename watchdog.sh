#!/bin/sh
# watchdog.sh — mbb dead-server pager (runs in iSH, NOT in Pyto)   callsign: mbb
#
# The dead-man notification (Pyto local) covers most deaths. This is the
# second, fully independent layer: iSH's crond pings mbb every 5 minutes and
# pages you via Bark *directly* (straight to APNs — mbb is not involved), so
# it works precisely when mbb can't speak for itself.
#
# SETUP (in iSH, once):
#   apk add curl ca-certificates          # HTTPS from minimal Alpine needs certs
#   mkdir -p ~/.mbb && cp watchdog.sh ~/.mbb/ && chmod +x ~/.mbb/watchdog.sh
#   echo 'BARK_KEY=<your bark device key>' > ~/.mbb/watchdog.conf
#   # optional: echo 'BARK_SERVER=https://api.day.app' >> ~/.mbb/watchdog.conf
#   crond                                  # or via ish bootstrap
#   echo '*/5 * * * * /root/.mbb/watchdog.sh' | crontab -
#   # keep iSH alive in background: run `cat /dev/location > /dev/null &` once
#
# Two consecutive failed pings → one critical Bark page (rings through
# silent). Recovery → one all-clear. No flapping spam: state on disk.

CONF="$HOME/.mbb/watchdog.conf"
STATE="$HOME/.mbb/watchdog.state"
[ -f "$CONF" ] && . "$CONF"
BARK_SERVER="${BARK_SERVER:-https://api.day.app}"
[ -z "$BARK_KEY" ] && exit 0

fails=0
[ -f "$STATE" ] && fails=$(cat "$STATE")

if curl -sf -m 10 "http://localhost:5100/api/status" > /dev/null 2>&1; then
    if [ "$fails" -ge 2 ]; then
        curl -sf -m 10 "$BARK_SERVER/$BARK_KEY/mbb%20is%20back/server%20answering%20again?group=mbb-alert&sound=bell" > /dev/null 2>&1
    fi
    echo 0 > "$STATE"
else
    fails=$((fails + 1))
    echo "$fails" > "$STATE"
    if [ "$fails" -eq 2 ]; then
        curl -sf -m 10 "$BARK_SERVER/$BARK_KEY/mbb%20is%20DOWN/open%20Pyto%20and%20run%20mbb.py?group=mbb-alert&level=critical&volume=8&call=1&sound=alarm" > /dev/null 2>&1
    fi
fi
