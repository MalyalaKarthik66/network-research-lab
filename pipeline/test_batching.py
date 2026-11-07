"""Prove the batch/resume mechanism without Batfish or Docker.

    python3 pipeline/test_batching.py

Simulates completion records appearing on disk and asserts the three properties
that matter: nothing is executed twice, everything is eventually executed, and
the ledger agrees with what happened.
"""
from __future__ import annotations
import shutil, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from nrl.batching import (append_ledger, ledger_integrity, plan_batch)  # noqa: E402

FAIL = []
def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAIL.append(label)
        if detail: print(f"         {detail}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    try:
        ids = [f"C-{i:05d}" for i in range(1, 24)]      # 23 items
        recs = tmp / "raw"; ledger = tmp / "batch_log.jsonl"
        def is_done(i): return (recs / i / "record.json").exists()
        def execute(i):
            (recs / i).mkdir(parents=True, exist_ok=True)
            (recs / i / "record.json").write_text("{}")

        print("simulating batches of 10 over 23 items")
        executed, batch = [], 0
        while True:
            plan = plan_batch(ids, is_done, 10)
            if not plan["this_batch"]:
                break
            batch += 1
            for i in plan["this_batch"]:
                assert i not in executed, f"{i} executed twice"
                execute(i); executed.append(i)
            append_ledger(ledger, {"batch": batch, "ids": plan["this_batch"],
                                   "n": len(plan["this_batch"])})
            print(f"    batch {batch}: {len(plan['this_batch'])} run, "
                  f"{plan['remaining_after']} remaining")

        check("every item executed exactly once",
              sorted(executed) == sorted(ids) and len(executed) == len(set(executed)),
              f"{len(executed)} executions for {len(ids)} items")
        check("batch sizes are 10/10/3", [len(r['ids']) for r in
              __import__('nrl.batching', fromlist=['read_ledger']).read_ledger(ledger)]
              == [10, 10, 3])
        integ = ledger_integrity(ledger)
        check("ledger records no duplicate execution", not integ["duplicates"],
              str(integ["duplicates"][:3]))
        check("ledger covers all 23 ids", integ["unique_ids"] == 23)

        print("\nsimulating a crash mid-batch, then resume")
        shutil.rmtree(recs / ids[-1])                    # last item lost
        plan = plan_batch(ids, is_done, 10)
        check("resume re-plans exactly the lost item",
              plan["this_batch"] == [ids[-1]], str(plan["this_batch"]))
        check("resume does not re-plan completed items",
              plan["already_done"] == 22, str(plan["already_done"]))

        print("\nbatch_size=0 means 'all remaining'")
        for i in ids[:5]: shutil.rmtree(recs / i)
        plan = plan_batch(ids, is_done, 0)
        check("unbatched plan takes every pending item",
              len(plan["this_batch"]) == 6, str(len(plan["this_batch"])))

        print(f"\n{'=' * 60}")
        print("FAILED" if FAIL else "ALL BATCHING CHECKS PASSED")
        return 1 if FAIL else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
