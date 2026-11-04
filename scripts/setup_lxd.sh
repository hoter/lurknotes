#!/usr/bin/env bash
# Optional LXD setup for a local `snapcraft pack`.
#
# This machine builds with Multipass instead: LXD's managed bridge cannot
# reach the internet here (Docker 29 owns the host's nftables rules, and
# `lxd init --auto` also fails to pick a subnet because docker0 plus seven
# docker br-* bridges already occupy 172.17-24.0.0/16). The script is kept
# for machines without that conflict.
#
#   sudo bash scripts/setup_lxd.sh
#   snapcraft pack --use-lxd

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run with: sudo bash $0" >&2
  exit 1
fi

# ipv4.address is the *bridge interface* address, not the subnet: passing
# "10.250.250.0/24" makes lxd reject it as "not a usable IPv4 address".
LXD_ADDR="${LXD_ADDR:-10.250.250.1/24}"

echo "Preseed: lxdbr0 ${LXD_ADDR}, no IPv6 networking, dir storage"
lxd init --preseed <<EOF
config: {}
networks:
- name: lxdbr0
  type: bridge
  config:
    ipv4.address: ${LXD_ADDR}
    ipv4.nat: "true"
    ipv6.address: none
storage_pools:
- name: default
  driver: dir
profiles:
- name: default
  description: Default LXD profile
  devices:
    eth0:
      name: eth0
      network: lxdbr0
      type: nic
    root:
      path: /
      pool: default
      type: disk
projects:
- name: default
EOF

echo
echo "Done. Current state:"
lxc network show lxdbr0 | sed -n '1,12p'
echo
echo "Log out and back in so the lxd group applies, then run:"
echo "  snapcraft pack --use-lxd"
