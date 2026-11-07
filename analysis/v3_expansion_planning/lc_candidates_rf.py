"""EXPLORATORY: candidate-count learning curve with an estimator that does not collapse at small n (RF).
Same LOTO outer split and stratified per-topology subsampling as offline_analyses.py section 3."""
import json, sys, warnings
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(REPO)); warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from sklearn.ensemble import RandomForestRegressor
import nrl.phase4 as P
L = P.load(REPO / "data/pilot-v3")
df = L["meta"].merge(L["p2"], on=["candidate_id", "incident_id"])
t = pd.read_csv(REPO / "analysis/v3_claude_final/r_three_way.csv")[["candidate_id", "r_rib"]]
df = df.merge(t, on="candidate_id").sort_values("candidate_id").reset_index(drop=True)
y = df.r_rib.to_numpy(float); topo = df.topology.to_numpy(); T = sorted(set(topo))
def r2(a, b): return float(1 - ((a - b) ** 2).sum() / ((a - a.mean()) ** 2).sum())
out = {}
for tier in ("B", "C"):
    X, live, _ = P.matrix(df, P.feature_columns(df, tier)[0])
    out[tier] = {}
    for frac in (0.2, 0.4, 0.6, 0.8, 1.0):
        vals = []
        for d in range(1 if frac == 1.0 else 15):
            p = np.full(len(y), np.nan)
            for gi, g in enumerate(T):
                tr = np.flatnonzero(topo != g); rng = np.random.default_rng(2000 * d + gi); keep = []
                for tt in sorted(set(topo[tr])):
                    ix = tr[topo[tr] == tt]; keep.append(rng.choice(ix, max(1, int(round(frac * len(ix)))), replace=False))
                tr = np.concatenate(keep); te = topo == g
                p[te] = RandomForestRegressor(n_estimators=300, min_samples_leaf=2, random_state=0, n_jobs=-1).fit(X[tr], y[tr]).predict(X[te])
            vals.append(r2(y, p))
        out[tier][frac] = {"mean": float(np.mean(vals)), "sd": float(np.std(vals)), "n_train_rows_approx": int(round(frac * 139))}
        print(f"tier {tier} RF candidates {frac:.0%}: R2 {np.mean(vals):.3f} +- {np.std(vals):.3f}", flush=True)
(REPO / "analysis/v3_expansion_planning/lc_candidates_rf.json").write_text(json.dumps(out, indent=2))
