import sys, warnings; sys.path.insert(0, '.'); warnings.filterwarnings('ignore')
from pathlib import Path
import numpy as np, pandas as pd, json
import nrl.phase4 as P
from sklearn.ensemble import HistGradientBoostingRegressor as H
L = P.load(Path('data/pilot-v3')); df = L['meta'].merge(L['p2'], on=['candidate_id', 'incident_id'])
man = pd.DataFrame(json.load(open('data/pilot-v3/manifest.json'))['candidates'])[['candidate_id', 'mechanism']]
t = pd.read_csv('analysis/v3_claude_final/r_three_way.csv')[['candidate_id', 'r_rib', 'broken', 'rerouted', 'golden_flows']]
df = df.merge(man, on='candidate_id').merge(t, on='candidate_id').sort_values('candidate_id').reset_index(drop=True)
y = df.r_rib.to_numpy(); topo = df.topology.to_numpy(); T = sorted(set(topo)); mech = df.mechanism.to_numpy()
X, live, _ = P.matrix(df, P.feature_columns(df, 'C')[0])
def r2(a, b): return 1 - ((a - b) ** 2).sum() / ((a - a.mean()) ** 2).sum()
p6 = X[:, live.index('verdict_P06')]; p11 = X[:, live.index('verdict_P11')]
print(pd.crosstab([df.mechanism, p6], columns='n'))
print(df.assign(P06=p6).groupby(['mechanism', 'P06']).r_rib.agg(['count', 'mean', 'std', 'min', 'max']).round(3))
m = lambda: H(learning_rate=0.05, max_iter=300, max_leaf_nodes=15, l2_regularization=1.0, random_state=0)
def loto_cells(keys):
    key = pd.Series(list(zip(*keys))).astype(str).to_numpy(); p = np.zeros(len(y))
    for i in range(len(y)):
        tr = (topo != topo[i]) & (key == key[i])
        p[i] = y[tr].mean() if tr.any() else y[topo != topo[i]].mean()
    return p
for name, keys in [('mechanism', [mech]), ('P06', [p6]), ('mechanism x P06', [mech, p6]), ('mechanism x P06 x P11', [mech, p6, p11])]:
    p = loto_cells(keys); print(f'LOTO cell-mean {name:24s} R2 {r2(y, p):.4f}')
def loto_model(cols):
    Xs = X[:, [live.index(c) for c in cols]]; p = np.full(len(y), np.nan)
    for g in T:
        te = topo == g; p[te] = m().fit(Xs[~te], y[~te]).predict(Xs[te])
    return p
nonP06 = [c for c in live if c != 'verdict_P06']
p = loto_model(nonP06); print(f'full model minus verdict_P06 (42 feats) LOTO R2 {r2(y, p):.4f}')
for mm in ('blackhole', 'cost'):
    idx = mech == mm
    print(f'  within {mm}: R2 of P06 alone (in-sample) {np.corrcoef(p6[idx], y[idx])[0,1]**2 if p6[idx].std() > 0 else float("nan"):.3f}  broken>0 share {(df.broken[idx] > 0).mean():.2f}  rerouted>0 share {(df.rerouted[idx] > 0).mean():.2f}')
