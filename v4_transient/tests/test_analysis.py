"""Offline tests of analysis statistics that are not gates: the §15 change-level bootstrap. Synthetic data only.
    ./.venv/Scripts/python.exe v4_transient/tests/test_analysis.py
"""
import importlib.util
import inspect
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
sys.path.insert(0, str(V4.parent)); sys.path.insert(0, str(V4))

import numpy as np                                                   # noqa: E402

spec = importlib.util.spec_from_file_location("analyze_pilot", V4 / "analysis" / "analyze_pilot.py")
ap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ap)

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    fails += (not cond)


ids = np.array(["C2"] * 5 + ["C1"] * 3 + ["C3"] * 4 + ["C1"] * 1)      # unsorted, one change split across rows
sizes = Counter(ids.tolist())
boots = ap.change_bootstrap(ids, np.random.default_rng(7), n=300)
check("300 draws produced", len(boots) == 300)
whole = all(all(cnt % sizes[c] == 0 for c, cnt in Counter(ids[b].tolist()).items()) for b in boots)
check("every draw contains only complete changes (all rows of a drawn change)", whole)
check("each draw resamples exactly as many changes as exist",
      all(sum(cnt // sizes[c] for c, cnt in Counter(ids[b].tolist()).items()) == len(sizes) for b in boots))
# 3 changes -> C(5,3) = 10 distinct change multisets exist; 300 draws should visit most of them
check("draws vary (not a fixed resample)", len({tuple(sorted(b.tolist())) for b in boots}) >= 8,
      len({tuple(sorted(b.tolist())) for b in boots}))

u = np.array(["A", "B", "C", "D", "E"])
a = ap.change_bootstrap(u, np.random.default_rng(11), n=40)
r = np.random.default_rng(11)
b = [r.choice(5, 5, replace=True) for _ in range(40)]
check("on a change-mean table the change bootstrap equals the row bootstrap (same draws)",
      all(np.array_equal(x, y) for x, y in zip(a, b)))
check("baselines_on uses the change-level bootstrap", "change_bootstrap(df_unit.change_id" in inspect.getsource(ap.baselines_on))

print("\nFAILURES:", fails)
sys.exit(1 if fails else 0)
