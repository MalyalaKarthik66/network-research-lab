#!/bin/sh
# Applies the artifact's `interfaces` file inside the container.
#
# This script exists so the container and Batfish read the SAME file. It
# understands exactly the subset nrl/render.py emits:
#
#     auto <name>
#     iface <name>
#         address <a.b.c.d/len>
#         alias <text>          (ignored here; Batfish uses it)
#
# It sets ADDRESSES ONLY. It deliberately does not touch link state: admin
# state lives in frr.conf as `shutdown`, zebra owns it, and having this script
# race zebra by forcing interfaces up would make the container disagree with
# the snapshot about exactly the thing fault families F01/F02 inject.
set -e
SRC=/etc/nrl/interfaces
[ -f "$SRC" ] || { echo "nrl: $SRC missing"; exit 1; }

cur=""
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    \#*|"") continue ;;
    iface\ *) cur=$(echo "$line" | awk '{print $2}') ;;
    auto\ *) : ;;
    *address\ *)
      addr=$(echo "$line" | awk '{print $2}')
      [ -n "$cur" ] || continue
      ip addr replace "$addr" dev "$cur" 2>/dev/null || \
        echo "nrl: could not set $addr on $cur"
      ;;
    *alias\ *) : ;;
    *) echo "nrl: ignoring unrecognised line: $line" ;;
  esac
done < "$SRC"
echo "nrl: addresses applied"

# Enforce admin state from frr.conf.
#
# FRR parses `shutdown` under an interface stanza and stores it, but does NOT
# apply it to a veth that Containerlab moves into the namespace after the
# daemon has read its config: verified on I-01, where the running-config showed
# `shutdown` while FRR reported admin=up, the kernel reported UP,LOWER_UP, and
# OSPF held a Full neighbour on the interface. Batfish models it as down, so
# without this the two tools run different networks for the whole iface_down
# family.
#
# This is not a second source of truth: the state is READ from frr.conf, the
# same file FRR itself loads. Nothing new is asserted here.
FRR=/etc/frr/frr.conf
if [ -f "$FRR" ]; then
  awk '/^interface /{ifc=$2} /^[[:space:]]*shutdown[[:space:]]*$/{if(ifc!="")print ifc}' \
      "$FRR" | while read -r d; do
    if ip link set "$d" down 2>/dev/null; then
      echo "nrl: admin-down $d (from frr.conf)"
    else
      echo "nrl: FAILED to shut $d"
    fi
  done
fi
