"""V4 transient-disruption pilot library. Isolated from v2/v3: imports nrl read-only, writes only under v4_transient/."""
from pathlib import Path

V4_ROOT = Path(__file__).resolve().parents[1]
REPO = V4_ROOT.parent
EXPERIMENT_ID = "v4-transient-pilot"
PROTOCOL_VERSION = "transient-1.1.0"   # amendment A3 (link-state-aware FIB instrument, stricter validity and retry rules)
