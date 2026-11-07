"""Phase 4: dataset assembly, risk modelling, calibration and risk control.

This module answers three questions, in order of how much data each needs:

  1. RATE       what is P(harm | verification PASS)?         -- needs the least
  2. SELECTION  among an incident's passing repairs, can we rank them?
  3. CONTROL    can we bound harm among auto-applied changes? -- needs the most

WHAT CHANGED FROM THE numpy VERSION, AND WHY
--------------------------------------------
The hand-written models were justified at n=24: the whole analysis fit in a
hundred auditable lines. At n~=860 with calibration, hierarchical conformal,
clustered bootstrap and a learning curve they became a liability -- a reviewer
trusts sklearn's logistic regression more than ours, and should.

Four defects are fixed here, all of them optimistic in direction:

B4  y_harmful was `(outcome == "HARMFUL")`, which mapped NO_CONVERGENCE,
    UNDETERMINED and EXECUTION_FAILED to y = 0, SAFE. The frozen harm
    definition counts NO_CONVERGENCE as harmful in the primary analysis, and
    the other two are not labels at all. See LABEL_MAP.

    Excluding the undecidable rows is not free either: if they correlate with
    riskier changes -- plausible, since a change that wedges the emulator is
    not a benign change -- excluding them biases P(harm|PASS) DOWNWARD. So the
    exclusion is reported, broken down by topology and family, and bracketed
    with Manski partial-identification bounds.

LEAK The banned-substring filter dropped columns silently. A filter that
    removes inputs without saying which is the same shape as every defect in
    this project's log. It now returns what it removed and the caller prints it.

CAL Calibration is fitted on a fold the model never saw, using nested grouped
    CV, and BOTH Platt and beta calibration are fitted with the selection rule
    fixed in advance. Isotonic is not used: its effective degrees of freedom
    scale with n and it overfits below roughly a thousand calibration points.

CONF Conformal calibration is HIERARCHICAL. Candidates cluster inside
    incidents, which cluster inside topologies, so candidate-level
    exchangeability is false and a candidate-level bound does not hold.
    Dunn, Wasserman & Ramdas, "Distribution-Free Prediction Sets for Two-Layer
    Hierarchical Models", arXiv:1809.07441, JASA 118(544). One score per
    cluster, max within cluster (conservative -- this is harm control), and the
    exact quantile, so a vacuous bound announces itself instead of appearing
    tight.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# frozen analysis constants -- see docs/ANALYSIS-PLAN.md
# ---------------------------------------------------------------------------

#: outcome -> y. Anything not listed is EXCLUDED from the modelling population.
LABEL_MAP = {
    "HARMFUL": 1,
    "SAFE": 0,
    "NO_CONVERGENCE": 1,      # frozen harm definition, primary analysis
}
EXCLUDED_OUTCOMES = ("UNDETERMINED", "EXECUTION_FAILED")
#: sensitivity analysis: NO_CONVERGENCE excluded rather than counted harmful
LABEL_MAP_SENSITIVITY = {"HARMFUL": 1, "SAFE": 0}

ORACLE_ONLY = ["P03", "P04", "P06", "P09", "P10", "P11", "P12"]
SPEC_PIDS = ["P01", "P02", "P05", "P07", "P08"]

#: provenance and outcome fields that must never reach X. docs/LEAKAGE.md.
BANNED_SUBSTRINGS = ("_BANNED", "prov_", "fault_", "repair_", "candidate_id",
                     "incident_id", "run_id", "label", "outcome", "violation",
                     "golden", "harm", "transient_")

N_CALIBRATION_BINS = 4        # equal-FREQUENCY; see docs/ANALYSIS-PLAN.md
BOOTSTRAP_RESAMPLES = 2000


def _require_sklearn():
    try:
        import sklearn                                        # noqa: F401
    except ImportError as exc:                                 # pragma: no cover
        raise SystemExit(
            "scikit-learn is required for Phase 4.\n"
            "    .venv\\Scripts\\pip install scikit-learn\n"
            "The numpy-only models were appropriate at n=24 and are not at "
            "n~=860 with calibration, conformal and bootstrap CIs.") from exc


# ---------------------------------------------------------------------------
# dataset assembly
# ---------------------------------------------------------------------------

def load(pilot: Path) -> Dict[str, pd.DataFrame]:
    p2 = pd.read_csv(pilot / "phase2" / "batfish_summary.csv")
    oc = pd.read_csv(pilot / "phase3" / "containerlab_outcomes.csv")
    man = json.loads((pilot / "manifest.json").read_text())
    meta = []
    for c in man["candidates"]:
        f = pilot / "candidates" / c["candidate_id"] / "meta.json"
        if not f.exists():
            continue
        m = json.loads(f.read_text())
        row = {"candidate_id": c["candidate_id"],
               "incident_id": c["incident_id"],
               "topology": c.get("topology"),
               # provenance, kept for ANALYSIS ONLY and banned from X
               "prov_fault_family_BANNED": c.get("fault_family"),
               "prov_repair_class_BANNED": c.get("repair_class"),
               "prov_repair_id_BANNED": c.get("repair_id")}
        row.update({f"chg_{k}": v for k, v in m.get("change_stats", {}).items()
                    if not isinstance(v, list)})
        row.update({f"cov_{k}": v for k, v in m.get("spec_coverage", {}).items()})
        row.update({k: v for k, v in (m.get("graph_features") or {}).items()})
        meta.append(row)
    return {"p2": p2, "outcomes": oc, "meta": pd.DataFrame(meta)}


def build_dataset(pilot: Path, sensitivity: bool = False,
                  verdict: str = "PASS") -> Tuple[pd.DataFrame, Dict]:
    """Returns (modelling population, an audit dict that must be reported).

    The primary population is candidates with the requested Batfish verdict
    and a decidable Containerlab outcome. The default is PASS because the
    residual-risk target is conditional on the Batfish SPEC gate.
    """
    if verdict not in {"PASS", "FAIL"}:
        raise ValueError("verdict must be PASS or FAIL")
    d = load(pilot)
    df = (d["meta"]
          .merge(d["p2"], on=["candidate_id", "incident_id"], how="inner")
          .merge(d["outcomes"][["candidate_id", "outcome_harm_v1"]],
                 on="candidate_id", how="inner"))

    audit = {"n_joined": int(len(df))}
    if "batfish_spec_verdict" in df.columns:
        audit["n_spec_pass"] = int((df.batfish_spec_verdict == "PASS").sum())
        audit["n_spec_fail"] = int((df.batfish_spec_verdict == "FAIL").sum())
        audit["population_verdict"] = verdict
        df = df[df.batfish_spec_verdict == verdict].copy()
    else:
        raise KeyError("Phase 2 summary lacks batfish_spec_verdict")

    mapping = LABEL_MAP_SENSITIVITY if sensitivity else LABEL_MAP
    audit["label_map"] = dict(mapping)
    audit["outcome_counts"] = {k: int(v) for k, v in
                               df.outcome_harm_v1.value_counts().items()}

    keep = df.outcome_harm_v1.isin(mapping)
    excluded = df[~keep]
    audit["n_excluded"] = int(len(excluded))
    audit["excluded_rate"] = round(len(excluded) / max(1, len(df)), 4)
    audit["excluded_by_outcome"] = {k: int(v) for k, v in
                                    excluded.outcome_harm_v1.value_counts().items()}
    # Perplexity's point: a global exclusion rate hides a rate concentrated in
    # exactly the subpopulation where the interesting risk lives.
    for by in ("topology", "prov_fault_family_BANNED"):
        if by in df.columns:
            tot = df.groupby(by).size()
            exc = excluded.groupby(by).size().reindex(tot.index).fillna(0)
            audit[f"excluded_rate_by_{by}"] = {
                str(k): round(float(exc[k] / tot[k]), 4) for k in tot.index}

    out = df[keep].copy()
    if not out.empty and not (out.batfish_spec_verdict == verdict).all():
        raise AssertionError("population contains an unexpected Batfish verdict")
    out["y_harmful"] = out.outcome_harm_v1.map(mapping).astype(int)
    audit["n_modelling"] = int(len(out))
    audit["n_harmful"] = int(out.y_harmful.sum())
    audit["n_safe"] = int((out.y_harmful == 0).sum())
    audit["base_rate"] = round(float(out.y_harmful.mean()), 4) if len(out) else None
    audit["manski_bounds"] = manski_bounds(df, mapping)
    return out, audit


def build_fail_control_dataset(pilot: Path, sensitivity: bool = False):
    """Build the separate Batfish-FAIL control population.

    This population is deliberately not used by ``run_phase4``. Keeping the
    entry point explicit prevents FAIL controls from becoming training rows
    for the PASS-conditioned residual-risk target.
    """
    return build_dataset(pilot, sensitivity=sensitivity, verdict="FAIL")


def manski_bounds(df: pd.DataFrame, mapping: Dict[str, int]) -> Dict:
    """Worst-case bracket on P(harm | PASS) given undecidable outcomes.

    Excluding a row is an assumption, not a neutral act. These are the sharp
    bounds you get by making no assumption at all: every excluded row harmful,
    then every excluded row safe. If the bracket is wider than ~10 points the
    harness is too fragile to support a rate, and that is a stop condition.
    """
    n = len(df)
    if not n:
        return {}
    harmful = int(sum(mapping.get(o, 0) == 1 for o in df.outcome_harm_v1))
    undecidable = int(sum(o not in mapping for o in df.outcome_harm_v1))
    lo = harmful / n
    hi = (harmful + undecidable) / n
    return {"p_min": round(lo, 4), "p_max": round(hi, 4),
            "width_points": round(100 * (hi - lo), 2),
            "n": n, "n_undecidable": undecidable,
            "note": "p_min assumes every undecidable outcome was safe, p_max "
                    "that every one was harmful. Report both."}


# ---------------------------------------------------------------------------
# features
# ---------------------------------------------------------------------------

def feature_columns(df: pd.DataFrame, tier: str) -> Tuple[List[str], List[str]]:
    """(kept, removed_by_leakage_filter). The second value is not optional --
    a filter that silently drops columns is how features go missing."""
    a = [c for c in df.columns if c.startswith(("chg_", "cov_"))]
    gph = [c for c in df.columns if c.startswith("g_")]
    b = [c for c in ("parse_warning_rows", "init_issue_rows",
                     "undefined_reference_rows", "unused_structure_rows",
                     "nodes_parsed", "interfaces_total", "interfaces_active",
                     "ip_owner_rows", "layer3_edge_rows", "route_rows",
                     "ospf_session_rows", "ospf_sessions_established",
                     "loop_rows", "multipath_inconsistency_rows",
                     "subnet_multipath_inconsistency_rows",
                     "diff_vs_incident_rows") if c in df.columns]
    c = [f"verdict_{p}" for p in ORACLE_ONLY if f"verdict_{p}" in df.columns]
    cols = {"A": a, "A+": a + gph, "B": a + gph + b,
            "C": a + gph + b + c}[tier]
    kept = [x for x in cols if not any(s in x for s in BANNED_SUBSTRINGS)]
    removed = [x for x in cols if x not in kept]
    return kept, removed


def matrix(df: pd.DataFrame, cols: Sequence[str]):
    X = df[list(cols)].copy()
    for c in cols:
        if X[c].dtype == object:
            X[c] = X[c].map({"PASS": 0.0, "FAIL": 1.0, "True": 1.0,
                             "False": 0.0, True: 1.0, False: 0.0})
        X[c] = pd.to_numeric(X[c], errors="coerce")
    X = X.fillna(0.0)
    keep = [c for c in cols if X[c].std() > 0]
    dropped = [c for c in cols if c not in keep]
    return X[keep].to_numpy(dtype=float), keep, dropped


def effective_n(X: np.ndarray) -> int:
    """Distinct feature vectors. RC-cost_norm_1..9 differ by one integer; if
    they collapse to one row they are ONE point to the model however many rows
    the CSV has, and this is the number that sets achievable precision."""
    return int(len({tuple(np.round(r, 9)) for r in X})) if len(X) else 0


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

def model_zoo():
    _require_sklearn()
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import (RandomForestClassifier,
                                  HistGradientBoostingClassifier)
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.tree import DecisionTreeClassifier
    return {
        "gbt": lambda: HistGradientBoostingClassifier(
            max_depth=3, max_iter=200, learning_rate=0.06,
            l2_regularization=1.0, random_state=0),
        "logreg": lambda: make_pipeline(
            StandardScaler(), LogisticRegression(C=1.0, max_iter=5000)),
        "rf": lambda: RandomForestClassifier(
            n_estimators=400, min_samples_leaf=3, random_state=0, n_jobs=-1),
        # deliberately kept: if one threshold on one feature separates the
        # classes, that is a shortcut, not a model
        "stump": lambda: DecisionTreeClassifier(max_depth=1, random_state=0),
    }


class BaseRate:
    """The floor every model must clear."""
    def fit(self, X, y):
        self.p = float(np.mean(y)) if len(y) else 0.5
        return self

    def predict_proba(self, X):
        return np.column_stack([np.full(len(X), 1 - self.p),
                                np.full(len(X), self.p)])


# ---------------------------------------------------------------------------
# calibration
# ---------------------------------------------------------------------------

def _logit(p, eps=1e-6):
    p = np.clip(np.asarray(p, dtype=float), eps, 1 - eps)
    return np.log(p / (1 - p))


class PlattCalibrator:
    """One-dimensional logistic regression on the logit of the score."""
    name = "platt"

    def fit(self, s, y):
        _require_sklearn()
        from sklearn.linear_model import LogisticRegression
        self.m = LogisticRegression(C=1e6, max_iter=5000)
        self.m.fit(_logit(s).reshape(-1, 1), np.asarray(y))
        return self

    def transform(self, s):
        return self.m.predict_proba(_logit(s).reshape(-1, 1))[:, 1]

    def params(self):
        return {"slope": float(self.m.coef_[0][0]),
                "intercept": float(self.m.intercept_[0])}


class BetaCalibrator:
    """Kull, Silva Filho & Flach, AISTATS 2017 (PMLR v54). Nests Platt and
    handles asymmetric miscalibration; two extra parameters, which is
    affordable at n_cal ~= 170 where isotonic is not."""
    name = "beta"

    def fit(self, s, y):
        _require_sklearn()
        from sklearn.linear_model import LogisticRegression
        s = np.clip(np.asarray(s, dtype=float), 1e-6, 1 - 1e-6)
        Z = np.column_stack([np.log(s), -np.log(1 - s)])
        self.m = LogisticRegression(C=1e6, max_iter=5000)
        self.m.fit(Z, np.asarray(y))
        return self

    def transform(self, s):
        s = np.clip(np.asarray(s, dtype=float), 1e-6, 1 - 1e-6)
        Z = np.column_stack([np.log(s), -np.log(1 - s)])
        return self.m.predict_proba(Z)[:, 1]

    def params(self):
        return {"a": float(self.m.coef_[0][0]), "b": float(self.m.coef_[0][1]),
                "intercept": float(self.m.intercept_[0])}


def log_loss(y, p, eps=1e-9):
    p = np.clip(np.asarray(p, dtype=float), eps, 1 - eps)
    y = np.asarray(y)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def pick_calibrator(s, y):
    """Selection rule fixed in advance: lower log loss on the calibration fold
    wins; ties go to Platt, the simpler model."""
    cands = []
    for C in (PlattCalibrator, BetaCalibrator):
        try:
            c = C().fit(s, y)
            cands.append((log_loss(y, c.transform(s)), c.name, c))
        except Exception:                                      # noqa: BLE001
            continue
    if not cands:
        return None, {}
    cands.sort(key=lambda t: (t[0], t[1] != "platt"))
    best = cands[0]
    return best[2], {n: round(l, 6) for l, n, _ in cands}


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def auc_roc(y, s):
    y, s = np.asarray(y), np.asarray(s, dtype=float)
    pos, neg = int((y == 1).sum()), int((y == 0).sum())
    if pos == 0 or neg == 0:
        return float("nan")
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), float)
    ranks[order] = np.arange(1, len(s) + 1)
    for v in np.unique(s):
        m = s == v
        if m.sum() > 1:
            ranks[m] = ranks[m].mean()
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def auc_pr(y, s):
    _require_sklearn()
    from sklearn.metrics import average_precision_score
    y = np.asarray(y)
    if (y == 1).sum() == 0 or (y == 0).sum() == 0:
        return float("nan")
    return float(average_precision_score(y, np.asarray(s, dtype=float)))


def brier_murphy(y, p) -> Dict[str, float]:
    """Brier score decomposed: BS = reliability - resolution + uncertainty.
    Reliability is the calibration term (lower better), resolution the
    discrimination term (higher better). More informative than either AUC or
    ECE alone, and standard in forecast verification."""
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    n = len(y)
    if n == 0:
        return {}
    ybar = y.mean()
    bs = float(np.mean((p - y) ** 2))
    # bin by unique forecast value, which is exact for a decomposition
    rel = res = 0.0
    for v in np.unique(p):
        m = p == v
        k = m.sum()
        rel += k * (v - y[m].mean()) ** 2
        res += k * (y[m].mean() - ybar) ** 2
    rel, res = rel / n, res / n
    unc = float(ybar * (1 - ybar))
    return {"brier": round(bs, 6), "reliability": round(rel, 6),
            "resolution": round(res, 6), "uncertainty": round(unc, 6),
            "identity_check": round(rel - res + unc, 6)}


def ece(y, p, n_bins=N_CALIBRATION_BINS) -> float:
    """Equal-FREQUENCY bins. Equal-width bins are empty at the tails at this n
    and produce extreme points that are pure noise."""
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    if len(y) == 0:
        return float("nan")
    qs = np.quantile(p, np.linspace(0, 1, n_bins + 1))
    qs[0], qs[-1] = -np.inf, np.inf
    tot = 0.0
    for i in range(n_bins):
        m = (p > qs[i]) & (p <= qs[i + 1])
        if m.sum() == 0:
            continue
        tot += m.sum() / len(y) * abs(p[m].mean() - y[m].mean())
    return float(tot)


def spiegelhalter_z(y, p) -> Dict[str, float]:
    """A test of calibration with NO binning, so it does not inherit the bin
    count's arbitrariness. Under perfect calibration Z ~ N(0,1)."""
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    num = np.sum((y - p) * (1 - 2 * p))
    den = math.sqrt(np.sum(((1 - 2 * p) ** 2) * p * (1 - p)))
    if den == 0:
        return {"z": float("nan"), "p_value": float("nan")}
    z = float(num / den)
    pv = float(math.erfc(abs(z) / math.sqrt(2)))
    return {"z": round(z, 4), "p_value": round(pv, 4)}


def reliability_table(y, p, n_bins=N_CALIBRATION_BINS) -> List[Dict]:
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    qs = np.quantile(p, np.linspace(0, 1, n_bins + 1))
    qs[0], qs[-1] = -np.inf, np.inf
    rows = []
    for i in range(n_bins):
        m = (p > qs[i]) & (p <= qs[i + 1])
        if m.sum() == 0:
            continue
        k, obs = int(m.sum()), float(y[m].mean())
        lo, hi = wilson(int(y[m].sum()), k)
        rows.append({"bin": i + 1, "n": k,
                     "predicted_mean": round(float(p[m].mean()), 4),
                     "observed_rate": round(obs, 4),
                     "ci_low": lo, "ci_high": hi})
    return rows


def wilson(k: int, n: int, z: float = 1.959964) -> Tuple[float, float]:
    """Wilson score interval. Not the normal approximation -- that misbehaves
    at the extremes, which is exactly where the interesting bins are."""
    if n == 0:
        return (float("nan"), float("nan"))
    ph = k / n
    d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - h), 4), round(min(1.0, c + h), 4))


def clopper_pearson_upper(k: int, n: int, alpha: float = 0.05) -> float:
    """Exact upper bound. For k=0 this is 1-alpha**(1/n), the exact form of the
    rule of three (0/150 -> ~1.97%, not exactly 2%)."""
    if n == 0:
        return float("nan")
    if k == 0:
        return round(1 - alpha ** (1.0 / n), 6)
    try:
        from scipy.stats import beta as _b                    # type: ignore
        return round(float(_b.ppf(1 - alpha, k + 1, n - k)), 6)
    except Exception:                                          # noqa: BLE001
        lo, hi = k / n, 1.0
        for _ in range(200):
            mid = (lo + hi) / 2
            tail = sum(math.comb(n, i) * mid ** i * (1 - mid) ** (n - i)
                       for i in range(0, k + 1))
            if tail > alpha:
                lo = mid
            else:
                hi = mid
        return round((lo + hi) / 2, 6)


def clustered_bootstrap(y, s, groups, fn, n=BOOTSTRAP_RESAMPLES, seed=0):
    """Resample INCIDENTS, not candidates. Resampling candidates ignores the
    clustering and produces intervals that are too narrow."""
    rng = np.random.default_rng(seed)
    y, s, groups = np.asarray(y), np.asarray(s), np.asarray(groups)
    uniq = np.unique(groups)
    idx_by_g = {g: np.where(groups == g)[0] for g in uniq}
    vals = []
    for _ in range(n):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([idx_by_g[g] for g in pick])
        if len(np.unique(y[idx])) < 2:
            continue
        try:
            vals.append(fn(y[idx], s[idx]))
        except Exception:                                      # noqa: BLE001
            continue
    if not vals:
        return (float("nan"), float("nan"))
    return (round(float(np.percentile(vals, 2.5)), 4),
            round(float(np.percentile(vals, 97.5)), 4))


def permutation_p(y, s, fn, groups=None, n=2000, seed=0):
    """P(metric this good | labels are noise). Permutes WITHIN nothing -- the
    null is that the score carries no information about the label."""
    rng = np.random.default_rng(seed)
    y = np.asarray(y)
    obs = fn(y, s)
    if not np.isfinite(obs):
        return float("nan")
    hits = sum(1 for _ in range(n) if fn(rng.permutation(y), s) >= obs)
    return round((hits + 1) / (n + 1), 5)


# ---------------------------------------------------------------------------
# grouped nested cross-validation
# ---------------------------------------------------------------------------

def grouped_folds(groups: Sequence, k: int, seed: int = 0) -> List[np.ndarray]:
    """k folds of GROUP ids. Candidates from one incident share a fault, a
    BEFORE state and most of their config; splitting them randomly leaks."""
    rng = np.random.default_rng(seed)
    uniq = np.array(sorted(set(groups)))
    rng.shuffle(uniq)
    return [uniq[i::k] for i in range(k)]


def nested_cv(X, y, groups, model_factory, k_outer=5, seed=0) -> Dict:
    """Out-of-fold CALIBRATED probabilities for every row.

    Within each outer fold: the remaining groups are split again, most of them
    fitting the model and one fitting the calibrator, so no calibrator ever
    sees a row the model trained on and no row is scored by a model that saw
    its incident.

    Pooling the five folds' outputs into one curve mixes five calibrators. That
    is a visualisation, not an inferential object: per-fold metrics are the
    primary report, and the spread of the fitted calibrator parameters across
    folds is returned so the reader can see how much they disagree.
    """
    X, y, groups = np.asarray(X), np.asarray(y), np.asarray(groups)
    folds = grouped_folds(groups, k_outer, seed)
    oof = np.full(len(y), np.nan)
    raw = np.full(len(y), np.nan)
    per_fold, cal_params, cal_choice = [], [], []
    for gi, test_groups in enumerate(folds):
        te = np.isin(groups, test_groups)
        tr = ~te
        if te.sum() == 0 or len(np.unique(y[tr])) < 2:
            continue
        inner = grouped_folds(groups[tr], max(2, k_outer - 1), seed + gi + 1)
        cal_groups = inner[0]
        cal = np.isin(groups, cal_groups) & tr
        fit = tr & ~cal
        if len(np.unique(y[fit])) < 2 or cal.sum() < 10:
            fit, cal = tr, tr           # degenerate fold: no held-out calibrator
        m = model_factory().fit(X[fit], y[fit])
        s_cal = m.predict_proba(X[cal])[:, 1]
        s_te = m.predict_proba(X[te])[:, 1]
        raw[te] = s_te
        c, losses = pick_calibrator(s_cal, y[cal])
        if c is None:
            oof[te] = s_te
        else:
            oof[te] = c.transform(s_te)
            cal_params.append(c.params())
            cal_choice.append(c.name)
        per_fold.append({
            "fold": gi, "n_test": int(te.sum()), "n_fit": int(fit.sum()),
            "n_cal": int(cal.sum()),
            "calibrator": c.name if c else None,
            "calibrator_log_loss": losses,
            "auc_roc": round(auc_roc(y[te], oof[te]), 4),
            "auc_pr": round(auc_pr(y[te], oof[te]), 4),
            "brier": brier_murphy(y[te], oof[te]).get("brier"),
            "ece": round(ece(y[te], oof[te]), 4),
        })
    spread = {}
    if cal_params:
        keys = sorted({k for d in cal_params for k in d})
        spread = {k: {"mean": round(float(np.mean([d[k] for d in cal_params
                                                   if k in d])), 4),
                      "sd": round(float(np.std([d[k] for d in cal_params
                                                if k in d])), 4)}
                  for k in keys}
    return {"oof_calibrated": oof, "oof_raw": raw, "per_fold": per_fold,
            "calibrator_choices": cal_choice,
            "calibrator_param_spread": spread}


# ---------------------------------------------------------------------------
# selection: the question the operator actually asks
# ---------------------------------------------------------------------------

def within_incident_ranking(df: pd.DataFrame, risk: np.ndarray,
                            seed: int = 0) -> Dict:
    """Given several passing repairs for one incident, does acting on the
    lowest-risk one beat picking arbitrarily?

    Reported as top-1 accuracy, mean per-incident AUC, and REGRET -- the harm
    rate of the model's pick minus that of the best available pick, against the
    baseline of choosing uniformly at random among that incident's candidates.
    A model can rank usefully while being badly calibrated, and vice versa;
    this is the metric that matches the motivating example.
    """
    rng = np.random.default_rng(seed)
    d = df.copy()
    d["_risk"] = risk
    picks, rands, bests, aucs, n_inc = [], [], [], [], 0
    for _, grp in d.groupby("incident_id"):
        if len(grp) < 2:
            continue
        n_inc += 1
        y = grp.y_harmful.to_numpy()
        r = grp._risk.to_numpy()
        picks.append(int(y[int(np.argmin(r))]))
        rands.append(float(y.mean()))
        bests.append(int(y.min()))
        if len(np.unique(y)) > 1:
            aucs.append(auc_roc(y, r))
    if not picks:
        return {"n_incidents": 0}
    return {
        "n_incidents_with_2plus": n_inc,
        "top1_selected_harm_rate": round(float(np.mean(picks)), 4),
        "random_choice_harm_rate": round(float(np.mean(rands)), 4),
        "oracle_best_harm_rate": round(float(np.mean(bests)), 4),
        "regret_vs_oracle": round(float(np.mean(picks) - np.mean(bests)), 4),
        "improvement_vs_random":
            round(float(np.mean(rands) - np.mean(picks)), 4),
        "mean_within_incident_auc":
            round(float(np.mean(aucs)), 4) if aucs else None,
        "n_incidents_scorable": len(aucs),
    }


# ---------------------------------------------------------------------------
# hierarchical conformal risk control
# ---------------------------------------------------------------------------

def conformal_threshold(cal_df: pd.DataFrame, risk: np.ndarray, alpha: float,
                        cluster: str = "incident_id") -> Dict:
    """Largest risk threshold whose auto-apply set keeps harm at or below alpha.

    Candidate-level exchangeability is FALSE -- candidates cluster inside
    incidents which cluster inside topologies -- so calibration is done on ONE
    score per cluster (Dunn, Wasserman & Ramdas, arXiv:1809.07441). The
    within-cluster summary is the MAX, which is the conservative choice and the
    right one for harm control.

    The exact quantile is used, and a vacuous bound is reported as vacuous
    rather than silently returned as a tight one: if ceil((K+1)(1-alpha)) > K
    then no finite threshold is supported at that alpha, and the alpha FLOOR
    is 1/(K+1).
    """
    d = cal_df.copy()
    d["_risk"] = risk
    scores = d.groupby(cluster)["_risk"].max().to_numpy()
    K = len(scores)
    if K == 0:
        return {"alpha": alpha, "n_clusters": 0, "threshold": None,
                "vacuous": True, "reason": "no calibration clusters"}
    rank = math.ceil((K + 1) * (1 - alpha))
    floor = round(1.0 / (K + 1), 4)
    if rank > K:
        return {"alpha": alpha, "n_clusters": K, "cluster": cluster,
                "threshold": None, "vacuous": True, "alpha_floor": floor,
                "reason": f"ceil((K+1)(1-alpha))={rank} > K={K}; the finite-"
                          f"sample quantile is infinite. alpha must be >= "
                          f"{floor} with {K} clusters."}
    thr = float(np.sort(scores)[rank - 1])
    return {"alpha": alpha, "n_clusters": K, "cluster": cluster,
            "threshold": round(thr, 6), "vacuous": False,
            "alpha_floor": floor, "quantile_rank": rank,
            "method": "two-layer hierarchical split conformal, max-per-cluster "
                      "score (Dunn/Wasserman/Ramdas arXiv:1809.07441)"}


def conformal_incident_split(df: pd.DataFrame, train_n: int = 120,
                             calibration_n: int = 40, test_n: int = 40,
                             seed: int = 0) -> Dict[str, object]:
    """Return a deterministic, topology-stratified 120/40/40 split.

    The split is over incident IDs, never candidate rows. For the pilot-v2
    design each topology contributes ten incidents, so each contributes six
    training, two calibration and two test incidents. The explicit disjoint
    assertions make accidental row-level or overlapping splits fail loudly.
    """
    required = train_n + calibration_n + test_n
    if "incident_id" not in df or "topology" not in df:
        raise KeyError("conformal split requires incident_id and topology")
    incident_meta = df[["incident_id", "topology"]].drop_duplicates()
    if len(incident_meta) != required:
        raise ValueError(f"expected exactly {required} unique incidents, "
                         f"got {len(incident_meta)}")
    if incident_meta.groupby("incident_id").size().max() != 1:
        raise AssertionError("an incident maps to multiple topologies")
    topology_counts = incident_meta.groupby("topology").size()
    if topology_counts.nunique() != 1:
        raise ValueError("topology-stratified conformal split needs equal "
                         "incident counts per topology")
    ratios = np.array([train_n, calibration_n, test_n], dtype=float) / required
    per_topology = topology_counts.iloc[0] * ratios
    if not np.allclose(per_topology, np.round(per_topology)):
        raise ValueError("requested split cannot preserve topology strata")
    per_topology = per_topology.astype(int)

    rng = np.random.default_rng(seed)
    parts = [[], [], []]
    for topology in sorted(topology_counts.index):
        ids = incident_meta.loc[
            incident_meta.topology == topology, "incident_id"
        ].to_numpy()
        rng.shuffle(ids)
        start = 0
        for part, count in enumerate(per_topology):
            parts[part].extend(ids[start:start + count].tolist())
            start += count

    train_ids, calibration_ids, test_ids = map(set, parts)
    if (train_ids & calibration_ids or train_ids & test_ids
            or calibration_ids & test_ids):
        raise AssertionError("conformal incident partitions overlap")
    if {len(train_ids), len(calibration_ids), len(test_ids)} != {
            train_n, calibration_n, test_n}:
        raise AssertionError("conformal partition sizes are incorrect")

    groups = df["incident_id"]
    return {
        "train_incidents": sorted(train_ids),
        "calibration_incidents": sorted(calibration_ids),
        "test_incidents": sorted(test_ids),
        "train_mask": groups.isin(train_ids).to_numpy(),
        "calibration_mask": groups.isin(calibration_ids).to_numpy(),
        "test_mask": groups.isin(test_ids).to_numpy(),
        "seed": seed,
    }


def conformal_protocol(df: pd.DataFrame, X: np.ndarray, y: np.ndarray,
                       model_factory, alpha=(0.05, 0.10), seed: int = 0):
    """Fit and evaluate the planned grouped conformal protocol.

    The model sees only training incidents. Platt/beta selection sees only the
    calibration incidents. The test incidents remain untouched until risk
    thresholds are applied. The returned rows make the three populations
    auditable without writing any intermediate data.
    """
    split = conformal_incident_split(df, seed=seed)
    train = split["train_mask"]
    calibration = split["calibration_mask"]
    test = split["test_mask"]
    model = model_factory().fit(X[train], y[train])
    calibration_raw = model.predict_proba(X[calibration])[:, 1]
    test_raw = model.predict_proba(X[test])[:, 1]
    calibrator, losses = pick_calibrator(calibration_raw, y[calibration])
    calibration_risk = (calibrator.transform(calibration_raw)
                        if calibrator else calibration_raw)
    test_risk = (calibrator.transform(test_raw)
                 if calibrator else test_raw)

    calibration_df = df.loc[calibration].reset_index(drop=True)
    test_df = df.loc[test].reset_index(drop=True)
    result = {"split": split, "calibrator": calibrator.name
              if calibrator else None, "calibrator_log_loss": losses,
              "n_train_rows": int(train.sum()),
              "n_calibration_rows": int(calibration.sum()),
              "n_test_rows": int(test.sum()), "alpha": {}}
    for level in alpha:
        result["alpha"][str(level)] = {}
        for cluster in ("incident_id", "topology"):
            threshold = conformal_threshold(
                calibration_df, calibration_risk, level, cluster=cluster)
            if threshold["vacuous"]:
                result["alpha"][str(level)][cluster] = threshold
                continue
            accepted = test_risk <= threshold["threshold"]
            result["alpha"][str(level)][cluster] = {
                **threshold,
                "test_coverage": round(float(accepted.mean()), 4),
                "test_harm_rate": round(float(y[test][accepted].mean()), 4)
                if accepted.any() else None,
            }
    return result


def autonomy_risk_curve(y, risk, groups, n_points: int = 25) -> List[Dict]:
    """Coverage (fraction auto-applied) versus REALISED harm among them.

    This is the operator's question and it needs far less data than a ten-bin
    reliability diagram, because it is a one-dimensional curve rather than ten
    independent bin estimates.
    """
    y, risk = np.asarray(y), np.asarray(risk, dtype=float)
    out = []
    for t in np.quantile(risk, np.linspace(0.02, 1.0, n_points)):
        m = risk <= t
        k = int(m.sum())
        if k == 0:
            continue
        harmful = int(y[m].sum())
        lo, hi = wilson(harmful, k)
        out.append({"threshold": round(float(t), 6),
                    "coverage": round(k / len(y), 4), "n_auto_applied": k,
                    "realised_harm_rate": round(harmful / k, 4),
                    "ci_low": lo, "ci_high": hi})
    return out


# ---------------------------------------------------------------------------
# learning curve
# ---------------------------------------------------------------------------

def learning_curve(X, y, groups, model_factory,
                   sizes=(50, 100, 200, 400, 600, 850), reps=5,
                   seed=0) -> List[Dict]:
    """Sampled BY INCIDENT so the grouping is preserved at every size.

    Read it as: still rising at the largest size means more data helps and the
    recommendation has a number attached; flat by the middle means the ceiling
    is the representation or the label noise, not n -- which is the argument
    for a distribution-free bound instead of a sharper classifier.
    """
    X, y, groups = np.asarray(X), np.asarray(y), np.asarray(groups)
    uniq = sorted(set(groups))
    rng = np.random.default_rng(seed)
    rows = []
    for n_target in sizes:
        if n_target > len(y):
            continue
        aucs, eces = [], []
        for r in range(reps):
            order = list(uniq)
            rng.shuffle(order)
            chosen, idx = [], []
            for g in order:
                gi = np.where(groups == g)[0]
                if len(idx) + len(gi) > n_target and idx:
                    break
                chosen.append(g)
                idx.extend(gi.tolist())
            idx = np.array(idx)
            if len(np.unique(y[idx])) < 2 or len(chosen) < 4:
                continue
            res = nested_cv(X[idx], y[idx], groups[idx], model_factory,
                            k_outer=4, seed=seed + r)
            ok = ~np.isnan(res["oof_calibrated"])
            if ok.sum() < 10 or len(np.unique(y[idx][ok])) < 2:
                continue
            aucs.append(auc_pr(y[idx][ok], res["oof_calibrated"][ok]))
            eces.append(ece(y[idx][ok], res["oof_calibrated"][ok]))
        if aucs:
            rows.append({"n": n_target, "reps": len(aucs),
                         "auc_pr_mean": round(float(np.mean(aucs)), 4),
                         "auc_pr_sd": round(float(np.std(aucs)), 4),
                         "ece_mean": round(float(np.mean(eces)), 4)})
    return rows
