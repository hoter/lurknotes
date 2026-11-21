#!/usr/bin/env bash
# Does the strictly confined snap actually reach the sync server?
#
# The local test suite runs the client from the venv, so it says nothing about
# AppArmor: a strict snap without the `network` plug, or with it but not
# connected, fails at connect() with EACCES no matter how good the code is.
# This script proves it end to end from inside the snap.
#
# Run it as your own user, NOT with sudo: `snap run` under root would enter the
# snap as root (no /run/user/<uid>, no session), which tests nothing.
#
#   php artisan serve --host=0.0.0.0 --port=8123      # in web/
#   bash scripts/check_snap_network.sh 192.168.0.194:8123

set -euo pipefail

HOST_PORT="${1:-}"
if [[ -z "$HOST_PORT" ]]; then
  echo "usage: bash $0 <host>:<port>   (e.g. 192.168.0.194:8123)" >&2
  exit 2
fi

echo "1. The snap declares and has connected the network plug:"
if snap connections lurknotes | grep -qE '^network +lurknotes:network'; then
  echo "   connected"
else
  echo "   NOT connected — run: snap connect lurknotes:network" >&2
  exit 1
fi
echo

echo "2. Reachability from inside the snap:"
# The address is baked into the probe: `snap run --shell ... -c` does not pass
# arguments through, which is what broke the first version of this script.
probe=$(cat <<PY
import socket
host, port = "$HOST_PORT".split(":")
try:
    s = socket.create_connection((host, int(port)), timeout=5)
    s.close()
    print("   connected to " + host + ":" + port)
except OSError as exc:
    print("   FAILED: " + str(exc))
    raise SystemExit(1)
PY
)

if snap run --shell lurknotes -c "python3 -" <<<"$probe"; then
  echo
  echo "The snap can reach the network."
  echo "Next: printf '%s\\n' \"\$PASSWORD\" | snap run lurknotes sync login \\"
  echo "        --server http://$HOST_PORT --email you@example.com --password-stdin"
else
  echo >&2
  echo "The snap cannot reach $HOST_PORT." >&2
  echo "Check, in order: the server listens on 0.0.0.0, and the host firewall" >&2
  echo "allows the port. The plug is already connected." >&2
  exit 1
fi
