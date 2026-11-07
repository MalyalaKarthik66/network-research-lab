"""Write the blank D1-D9 decisions template and its JSON Schema from v4lib/decisions.py.

    ./.venv/Scripts/python.exe v4_transient/tools/write_decision_template.py

Writes config/pilot_decisions.TEMPLATE.json (every value null, every status UNFROZEN) and
config/pilot_decisions.schema.json. It never writes config/pilot_decisions.json, the file that receives the
approved values.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
sys.path.insert(0, str(V4.parent)); sys.path.insert(0, str(V4))

from v4lib import decisions as D                                     # noqa: E402


def render(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    cfg = V4 / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (V4 / D.TEMPLATE_REL).write_text(render(D.template()), encoding="utf-8", newline="\n")
    (V4 / D.SCHEMA_REL).write_text(render(D.json_schema()), encoding="utf-8", newline="\n")
    print(f"wrote {D.TEMPLATE_REL} and {D.SCHEMA_REL}")
    print(f"{D.DECISIONS_REL} exists: {(V4 / D.DECISIONS_REL).exists()} (never written by this tool)")
    print(f"template validation problems: {len(D.validate(D.template()))} (the template can never pass)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
