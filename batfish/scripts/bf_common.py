"""
bf_common.py -- shared helpers for every Phase 1 Batfish script.

Everything in this file exists so that the per-module scripts contain only the
networking logic and none of the plumbing.

Usage from any module script:

    from bf_common import bf_session, load, sanity, Checks, show

Design notes
------------
* One Batfish *network* holds many *snapshots*. We keep every Phase 1 snapshot
  inside a single network called "phase1" so that differential questions
  (comparing two snapshots) always work -- Batfish can only diff two snapshots
  that live in the same network.
* `load()` always re-initialises the snapshot (overwrite=True). Batfish caches
  aggressively; if you edit a config file and forget to overwrite, you will spend
  an hour debugging a result that came from the previous version of the file.
* `sanity()` runs the five parse-health questions. Never trust any other answer
  from a snapshot that has not passed this. An unparsed config produces an empty
  routing table, and an empty routing table produces confident, wrong answers.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from pybatfish.client.session import Session

# ---------------------------------------------------------------------------
# Display / logging
# ---------------------------------------------------------------------------

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 50)
pd.set_option("display.max_colwidth", 120)
pd.set_option("display.max_rows", 200)

# Pybatfish is chatty at INFO level. We only want warnings and errors.
logging.getLogger("pybatfish").setLevel(logging.WARNING)

BATFISH_HOST = os.environ.get("BATFISH_HOST", "localhost")
NETWORK_NAME = os.environ.get("BATFISH_NETWORK", "phase1")

# repo layout: <repo>/batfish/scripts/bf_common.py
SCRIPTS_DIR = Path(__file__).resolve().parent
BATFISH_DIR = SCRIPTS_DIR.parent
SNAPSHOT_DIR = BATFISH_DIR / "snapshots"
REPO_ROOT = BATFISH_DIR.parent


# ---------------------------------------------------------------------------
# Pretty printing
# ---------------------------------------------------------------------------

def banner(text: str, char: str = "=") -> None:
    print()
    print(char * 78)
    print(text)
    print(char * 78)


def show(title: str, frame: pd.DataFrame, max_rows: int = 40) -> pd.DataFrame:
    """Print a DataFrame under a heading, and return it so it can be chained."""
    print()
    print(f"--- {title} ---")
    if frame is None or len(frame) == 0:
        print("(empty result -- 0 rows)")
        print("NOTE: an empty Batfish answer is ambiguous. It can mean 'the property")
        print("      holds and there are no violations', or it can mean 'nothing")
        print("      parsed and Batfish has no idea what you are talking about'.")
        print("      Only the sanity questions can tell those two apart.")
    else:
        print(frame.head(max_rows).to_string())
        if len(frame) > max_rows:
            print(f"... ({len(frame) - max_rows} more rows)")
    return frame


# ---------------------------------------------------------------------------
# Session and snapshot management
# ---------------------------------------------------------------------------

def bf_session(network: str = NETWORK_NAME) -> Session:
    """Connect to the Batfish service and select (creating if needed) a network."""
    try:
        bf = Session(host=BATFISH_HOST)
    except Exception as exc:  # noqa: BLE001
        print(f"FATAL: could not reach the Batfish service at {BATFISH_HOST}:9996")
        print(f"       underlying error: {exc}")
        print()
        print("Check, in this order:")
        print("  1. docker ps            -- is a container named 'batfish' running?")
        print("  2. docker logs batfish  -- did the Java service finish starting?")
        print("  3. Did you publish the ports? -p 9996:9996 -p 9997:9997 -p 8888:8888")
        sys.exit(1)
    bf.set_network(network)
    return bf


def snapshot_path(name: str) -> Path:
    p = SNAPSHOT_DIR / name
    if not p.is_dir():
        raise FileNotFoundError(
            f"snapshot directory not found: {p}\n"
            f"Expected layout: {p}/configs/<device>.cfg"
        )
    if not (p / "configs").is_dir():
        raise FileNotFoundError(
            f"{p} exists but has no 'configs/' subdirectory.\n"
            f"Batfish will read zero devices. The configs/ folder name is mandatory."
        )
    return p


def load(bf: Session, name: str, snapshot_name: Optional[str] = None) -> str:
    """Initialise (or re-initialise) a snapshot from batfish/snapshots/<name>."""
    path = snapshot_path(name)
    snap = snapshot_name or name
    print(f"[load] initialising snapshot '{snap}' from {path}")
    bf.init_snapshot(str(path), name=snap, overwrite=True)
    bf.set_snapshot(snap)
    return snap


# ---------------------------------------------------------------------------
# Parse-health gate
# ---------------------------------------------------------------------------

def sanity(bf: Session, strict: bool = True, expect_warnings: bool = False) -> bool:
    """Run the five parse-health questions. Returns True if the snapshot is trustworthy.

    strict=True  -> any file that did not fully parse is treated as fatal.
    expect_warnings=True -> used by the deliberately-broken snapshots in Module 8,
                            where warnings are the point of the exercise.
    """
    banner("SANITY: is this snapshot trustworthy at all?", "-")
    ok = True

    init = bf.q.initIssues().answer().frame()
    show("initIssues -- anything Batfish itself is unhappy about", init)
    if len(init) > 0 and strict and not expect_warnings:
        ok = False

    fps = bf.q.fileParseStatus().answer().frame()
    show("fileParseStatus -- one row per configuration file", fps)
    if len(fps) == 0:
        print("FAIL: zero configuration files were read. Batfish found nothing.")
        return False
    bad = fps[fps["Status"] != "PASSED"]
    if len(bad) > 0:
        print(f"WARNING: {len(bad)} file(s) did not fully parse:")
        print(bad.to_string())
        if strict:
            ok = False

    pw = bf.q.parseWarning().answer().frame()
    show("parseWarning -- lines Batfish saw but did not understand", pw)
    if len(pw) > 0 and strict and not expect_warnings:
        print("WARNING: Batfish silently ignored the lines above.")
        print("         Every ignored line is a piece of your intent that Batfish")
        print("         is not modelling. This is the single most common cause of")
        print("         'Batfish gave me a wrong answer'.")

    ur = bf.q.undefinedReferences().answer().frame()
    show("undefinedReferences -- names used but never defined", ur)

    us = bf.q.unusedStructures().answer().frame()
    show("unusedStructures -- names defined but never used", us)

    print()
    print(f"[sanity] verdict: {'TRUSTWORTHY' if ok else 'NOT TRUSTWORTHY'}")
    return ok


# ---------------------------------------------------------------------------
# Assertion harness
# ---------------------------------------------------------------------------

class Checks:
    """Tiny assertion collector so each module script self-verifies.

    A module script that ends with 'ALL CHECKS PASSED' has reproduced the
    expected output in the lab manual. If a check fails, the manual and your
    environment disagree, and that disagreement is worth an entry in
    notes/surprises.md.
    """

    def __init__(self, module: str):
        self.module = module
        self.results: list[tuple[bool, str, str]] = []

    def check(self, label: str, condition: bool, detail: str = "") -> bool:
        self.results.append((bool(condition), label, detail))
        mark = "PASS" if condition else "FAIL"
        line = f"  [{mark}] {label}"
        if detail and not condition:
            line += f"\n         detail: {detail}"
        print(line)
        return bool(condition)

    def summary(self) -> int:
        passed = sum(1 for r in self.results if r[0])
        total = len(self.results)
        banner(f"{self.module}: {passed}/{total} checks passed",
               "=" if passed == total else "!")
        if passed != total:
            for ok, label, detail in self.results:
                if not ok:
                    print(f"  FAILED: {label}")
                    if detail:
                        print(f"          {detail}")
            print()
            print("Do not move to the next module until these pass, OR until you can")
            print("explain in notes/surprises.md exactly why the manual is wrong.")
            return 1
        print("ALL CHECKS PASSED")
        return 0


# ---------------------------------------------------------------------------
# Small conveniences used across modules
# ---------------------------------------------------------------------------

def routes_for(bf: Session, node: str, network: Optional[str] = None,
               protocols: Optional[Iterable[str]] = None) -> pd.DataFrame:
    kwargs = {"nodes": node}
    if network:
        kwargs["network"] = network
    if protocols:
        kwargs["protocols"] = ",".join(protocols)
    return bf.q.routes(**kwargs).answer().frame()


def dispositions(frame: pd.DataFrame) -> list[str]:
    """Extract the final disposition of every trace in a traceroute/reachability answer."""
    out = []
    if frame is None or len(frame) == 0:
        return out
    for traces in frame["Traces"]:
        for tr in traces:
            out.append(str(tr.disposition))
    return out
