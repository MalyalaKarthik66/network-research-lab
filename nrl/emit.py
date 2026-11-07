"""Emitters: one artifact in, two consumers out, zero re-derivation.

    artifact/devices/<n>/interfaces  ---+--> bind-mounted into the container
                                        |    (applied by bin/apply-interfaces.sh)
                                        +--> embedded VERBATIM in the Batfish
                                             snapshot

    artifact/devices/<n>/frr.conf    ---+--> bind-mounted to /etc/frr/frr.conf
                                        +--> embedded VERBATIM in the snapshot

`emit_batfish_snapshot` adds exactly two things to those bytes: a leading
hostname line and a ports.conf stub. `extract_batfish_sections` is its inverse
and is used by the verifier to PROVE, per device, that the snapshot contains the
same bytes the container will run. That proof is the same-artifact guarantee.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict

from .model import Scenario
from .render import render_scenario

# Verified against the Docker Hub registry API on 2026-08-25: frrouting/frr
# publishes v8.4.0/v8.4.1 (note the `v` prefix) and nothing newer -- the image
# line has been dormant since Dec 2022. The earlier value here,
# quay.io/frrouting/frr:8.4.4, was wrong on registry, prefix AND version, and
# was never checked. Phase 3 records the resolved RepoDigest at run time.
FRR_IMAGE = "frrouting/frr:v8.4.1"
HOST_IMAGE = "alpine:3.19"

IFACE_MARKER = "# This file describes the network interfaces"
PORTS_MARKER = "# ports.conf --"
FRR_MARKER = "frr version"

PORTS_CONF = "\n".join([
    PORTS_MARKER,
    "# virtual node: no physical breakout ports",
    "1=10G", "2=10G", "3=10G", "4=10G", "",
])

APPLY_INTERFACES_SH = r"""#!/bin/sh
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
"""


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def emit_batfish_snapshot(node: str, files: Dict[str, str]) -> str:
    """Concatenate the artifact into one Batfish-readable config file.

    Adds ONLY: the hostname line, and the ports.conf stub. The interfaces and
    frr.conf bytes are passed through untouched -- note that both already begin
    with the marker line Batfish looks for, which is why nothing else is needed.
    """
    return (f"{node}\n"
            + files["interfaces"]
            + PORTS_CONF
            + files["frr.conf"])


def extract_batfish_sections(text: str) -> Dict[str, str]:
    """Inverse of emit_batfish_snapshot. Used by the verifier, not the pipeline."""
    lines = text.split("\n")
    i_start = next(i for i, l in enumerate(lines) if l == IFACE_MARKER)
    p_start = next(i for i, l in enumerate(lines) if l == PORTS_MARKER)
    f_start = next(i for i, l in enumerate(lines) if l.startswith(FRR_MARKER))
    return {
        "hostname": lines[0],
        "interfaces": "\n".join(lines[i_start:p_start]),
        "frr.conf": "\n".join(lines[f_start:]),
    }


def emit_clab(sc: Scenario, lab_name: str) -> str:
    """Containerlab topology. Hand-written YAML: deterministic key order, no
    dependency on a YAML dumper's formatting choices between versions."""
    out = [f"name: {lab_name}", "", "topology:", "  nodes:"]
    for n in sorted(sc.devices):
        d = sc.devices[n]
        if d.kind == "frr":
            out += [
                f"    {n}:",
                "      kind: linux",
                f"      image: {FRR_IMAGE}",
                "      binds:",
                f"        - devices/{n}/frr.conf:/etc/frr/frr.conf",
                f"        - devices/{n}/daemons:/etc/frr/daemons",
                f"        - devices/{n}/interfaces:/etc/nrl/interfaces:ro",
                "        - bin/apply-interfaces.sh:/etc/nrl/apply-interfaces.sh:ro",
                "      exec:",
                "        - sh /etc/nrl/apply-interfaces.sh",
            ]
        else:
            out += [
                f"    {n}:",
                "      kind: linux",
                f"      image: {HOST_IMAGE}",
                "      binds:",
                f"        - devices/{n}/setup.sh:/etc/nrl/setup.sh:ro",
                "      exec:",
                "        - sh /etc/nrl/setup.sh",
            ]
    out += ["", "  links:"]
    for l in sc.links:
        out.append(f'    - endpoints: ["{l.a_node}:{l.a_iface}", '
                   f'"{l.b_node}:{l.b_iface}"]')
    out.append("")
    return "\n".join(out)


def write_artifact(root: Path, sc: Scenario, lab_name: str) -> Dict[str, str]:
    """Write the artifact and its derived Batfish snapshot. Returns {relpath: sha256}."""
    rendered = render_scenario(sc)
    hashes = {}

    def w(rel: str, text: str):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, newline="\n", encoding="utf-8")
        hashes[rel] = sha256_text(text)

    for node, files in rendered.items():
        for fname, text in files.items():
            w(f"artifact/devices/{node}/{fname}", text)

    w("artifact/bin/apply-interfaces.sh", APPLY_INTERFACES_SH)
    w("artifact/topology.clab.yml", emit_clab(sc, lab_name))

    for node, files in rendered.items():
        if sc.devices[node].kind != "frr":
            continue
        w(f"batfish-snapshot/configs/{node}.cfg",
          emit_batfish_snapshot(node, files))

    l1 = {"edges": []}
    for l in sc.links:
        if sc.devices[l.a_node].kind == "frr" and sc.devices[l.b_node].kind == "frr":
            l1["edges"] += [
                {"node1": {"hostname": l.a_node, "interfaceName": l.a_iface},
                 "node2": {"hostname": l.b_node, "interfaceName": l.b_iface}},
                {"node1": {"hostname": l.b_node, "interfaceName": l.b_iface},
                 "node2": {"hostname": l.a_node, "interfaceName": l.a_iface}},
            ]
    w("batfish-snapshot/batfish/layer1_topology.json",
      json.dumps(l1, indent=2) + "\n")
    return hashes
