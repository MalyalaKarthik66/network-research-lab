"""
Run every Phase 1 module script in order and print a single summary table.

Use this to re-verify the whole environment after any change -- a new Batfish
image, a new pybatfish version, a config you edited. It is also the fastest way
to find out whether something you changed in Module 3 broke Module 9.

    python run_all.py
    python run_all.py --only m07 m09
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

MODULES = [
    ("m01", "environment smoke test",      "m01_smoke_test.py"),
    ("m03", "snapshots",                   "m03_snapshots.py"),
    ("m04", "basic verification",          "m04_basic_verification.py"),
    ("m05", "routing analysis",            "m05_routing_analysis.py"),
    ("m06", "forwarding analysis",         "m06_forwarding_analysis.py"),
    ("m07", "ACL verification",            "m07_acl_verification.py"),
    ("m08", "configuration validation",    "m08_config_validation.py"),
    ("m09", "our own network",             "m09_corp_verify.py"),
    ("m10", "limitations",                 "m10_limitations.py"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None,
                    help="module ids to run, e.g. --only m07 m09")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress module output, show only the summary")
    args = ap.parse_args()

    todo = [m for m in MODULES if args.only is None or m[0] in args.only]
    results = []

    for mid, name, script in todo:
        print(f"\n{'#' * 78}\n# {mid} -- {name}\n{'#' * 78}")
        t0 = time.time()
        proc = subprocess.run(
            [sys.executable, str(HERE / script)],
            cwd=HERE,
            capture_output=args.quiet,
            text=True,
        )
        dt = time.time() - t0
        if args.quiet and proc.returncode != 0:
            print(proc.stdout[-4000:] if proc.stdout else "")
            print(proc.stderr[-4000:] if proc.stderr else "")
        results.append((mid, name, proc.returncode, dt))

    print(f"\n{'=' * 78}\nPHASE 1 SUMMARY\n{'=' * 78}")
    for mid, name, rc, dt in results:
        print(f"  {'PASS' if rc == 0 else 'FAIL'}  {mid}  {name:28s} {dt:6.1f}s")
    failed = [r for r in results if r[2] != 0]
    print()
    if failed:
        print(f"{len(failed)} module(s) failed: {[r[0] for r in failed]}")
        return 1
    print("Phase 1 environment verified end to end.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
