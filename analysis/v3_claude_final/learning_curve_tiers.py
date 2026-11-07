import sys, json, warnings; sys.path.insert(0, '.'); warnings.filterwarnings('ignore')
from pathlib import Path
import numpy as np, pandas as pd
import nrl.phase4 as P
from sklearn.ensemble import HistGradientBoostingRegressor as H
L = P.load(Path('data/pilot-v3')); df = L['meta'].merge(L['p2'], on=['candidate_id', 'incident_id'])
t = pd.read_csv('analysis/v3_claude_final/r_three_way.csv')[['candidate_id', 'r_rib']]
df = df.merge(t, on='candidate_id').sort_values('candidate_id').reset_index(drop=True)
X, live, _ = P.matrix(df, P.feature_columns(df, 'C')[0]); y = df.r_rib.to_numpy(); topo = df.topology.to_numpy()
T = np.array(sorted(set(topo)))
def r2(a, b): return 1 - ((a - b) ** 2).sum() / ((a - a.mean()) ** 2).sum()
m = lambda: H(learning_rate=0.05, max_iter=300, max_leaf_nodes=15, l2_regularization=1.0, random_state=0)
print('learning curve: test = held-out topology, train = random subset of the other 11 (10 draws)')
for ntr in (4, 6, 8, 11):
    vals = []
    for s in range(10 if ntr < 11 else 1):
        rng = np.random.default_rng(s); p = np.full(len(y), np.nan)
        for g in T:
            rest = np.array([x for x in T if x != g]); tr = np.isin(topo, rng.choice(rest, ntr, replace=False))
            p[topo == g] = m().fit(X[tr], y[tr]).predict(X[topo == g])
        vals.append(r2(y, p))
    print(f'  train topologies {ntr:2d}: pooled R2 {np.mean(vals):.3f} (sd {np.std(vals):.3f})')
# Tier B headline, as §4 wants Tier C reported separately
for tier in ('B', 'C'):
    Xt, lt, _ = P.matrix(df, P.feature_columns(df, tier)[0]); p = np.full(len(y), np.nan); fr = []
    for g in T:
        te = topo == g; p[te] = m().fit(Xt[~te], y[~te]).predict(Xt[te]); fr.append(r2(y[te], p[te]))
    rng = np.random.default_rng(1); bs = []
    for _ in range(2000):
        ii = np.concatenate([np.flatnonzero(topo == x) for x in rng.choice(T, len(T))]); bs.append(r2(y[ii], p[ii]))
    print(f'tier {tier}: per-fold {np.mean(fr):.3f}±{np.std(fr, ddof=1):.3f} pooled {r2(y, p):.3f} CI [{np.quantile(bs, .025):.3f},{np.quantile(bs, .975):.3f}]')
# frozen v2 GBT hyperparameters as a regressor (the only frozen estimator config in the repo)
p = np.full(len(y), np.nan)
for g in T:
    te = topo == g; p[te] = H(max_depth=3, max_iter=200, learning_rate=0.06, l2_regularization=1.0, random_state=0).fit(X[~te], y[~te]).predict(X[te])
print(f'v2-frozen GBT hyperparameters as regressor, tier C LOTO pooled {r2(y, p):.3f}')
