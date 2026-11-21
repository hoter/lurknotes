#!/usr/bin/env bash
# Does the strictly confined snap actually reach the sync server?
#
# The local test suite runs the client from the venv, so it says nothing about
# AppArmor: a strict snap without the `network` plug, or with it but not
# connected, fails at connect() with EACCES no matter how good the code is.
# This script proves it end to end from inside the snap.
#
# Prerequisites: the app is installed from a build that contains sync, and the
# Laravel server is serving on a LAN address (127.0.0.1 inside the snap is the
# snap itself, not this machine).
#
#   php artisan serve --host=0.0.0.0 --port=8123      # in web/
#   sudo bash scripts/check_snap_network.sh 192.168.0.194:8123
#
# Then sign in as the snap user and run a real sync:
#   printf '%s\n' "$PASSWORD" | snap run lurknotes sync login \
#       --server http://192.168.0.194:8123 --email you@example.com --password-stdin
#   snap run lurknotes sync status

set -euo pipefail

HOST_PORT="${1:-}"
if [[ -z "$HOST_PORT" ]]; then
  echo "usage: sudo bash $0 <host>:<port>   (e.g. 192.168.0.194:8123)" >&2
  exit 2
fi

echo "1. The snap declares the network plug:"
snap connections lurknotes | grep -E 'network|Interface' || true
echo

echo "2. The plug is connected (auto-connection is expected):"
if snap connections lurknotes | grep -qE 'network +lurknotes:network'; then
  echo "   connected"
else
  echo "   NOT connected — run: snap connect lurknotes:network" >&2
fi
echo

echo "3. Reachability from inside the snap:"
if snap run --shell lurknotes -c "python3 - <<'PY'
import socket, sys
host, port = sys.argv[1].split(':')
try:
    s = socket.create_connection((host, int(port)), timeout=5)
    s.close()
    print('   connected to ' + host + ':' + port)
except OSError as exc:
    print('   FAILED: ' + str(exc))
    raise SystemExit(1)
PY
" "$HOST_PORT"; then
  echo
  echo "The snap can reach the network. Next: sign in with 'snap run lurknotes sync login'."
else
  echo >&2
  echo "The snap cannot reach $HOST_PORT." >&2
  echo "Check, in order: the plug is connected, the server listens on 0.0.0.0," >&2
  echo "and the host firewall allows the port." >&2
  exit 1
fi
