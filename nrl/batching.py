"""Batch + resume primitives shared by Phase 2 and Phase 3.

One rule: an item is DONE iff its completion record exists on disk. Nothing is
tracked in memory across runs and no separate "state" file can drift out of
sync with reality -- the artifacts on disk ARE the state. That is what makes
"never re-execute a completed item" true after a crash, a reboot, or a laptop
lid closing mid-batch.

The ledger (batch_log.jsonl) is append-only provenance: what each batch did,
when, and how long. It is never read to decide what to run.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Sequence


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def partition(all_ids: Sequence[str], is_done: Callable[[str], bool]):
    """(done, pending) preserving manifest order, so batches are deterministic."""
    done = [i for i in all_ids if is_done(i)]
    pending = [i for i in all_ids if not is_done(i)]
    return done, pending


def plan_batch(all_ids: Sequence[str], is_done: Callable[[str], bool],
               batch_size: int) -> Dict:
    done, pending = partition(all_ids, is_done)
    todo = pending if batch_size <= 0 else pending[:batch_size]
    return {"total": len(all_ids), "already_done": len(done),
            "pending": len(pending), "this_batch": todo,
            "remaining_after": len(pending) - len(todo)}


def append_ledger(path: Path, record: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, default=str) + "\n")


def read_ledger(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def ledger_integrity(path: Path) -> Dict:
    """Every id must appear in exactly one batch. Overlap means something was
    executed twice; that is the failure this whole mechanism exists to prevent."""
    seen, dupes = {}, []
    for rec in read_ledger(path):
        for i in rec.get("ids", []):
            if i in seen:
                dupes.append((i, seen[i], rec.get("batch")))
            seen[i] = rec.get("batch")
    return {"unique_ids": len(seen), "duplicates": dupes,
            "batches": len(read_ledger(path))}


def print_batch_summary(title: str, plan: Dict, counts: Dict,
                        cumulative: Dict, seconds: float) -> None:
    print(f"\n{'=' * 70}")
    print(f"{title}")
    print(f"{'=' * 70}")
    print(f"  this batch : {len(plan['this_batch'])} items in {int(seconds)}s")
    for k, v in counts.items():
        print(f"      {k:28} {v}")
    print(f"  cumulative :")
    for k, v in cumulative.items():
        print(f"      {k:28} {v}")
    print(f"  remaining  : {plan['remaining_after']} of {plan['total']}")
    if plan["remaining_after"] == 0:
        print("  ALL ITEMS COMPLETE")
    else:
        print("  stopping cleanly -- rerun the same command to continue")
    print("=" * 70)
