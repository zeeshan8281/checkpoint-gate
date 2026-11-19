"""Read a running pilot without instantiating its state-changing Ledger class."""
import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("run", type=Path)
args = parser.parse_args()
if sys.version_info < (3, 12):
    raise SystemExit("Use the project's Python 3.12+ environment for read-only WAL access.")
directory = args.run.resolve()
with sqlite3.connect((directory / "ledger.sqlite").as_uri() + "?mode=ro", uri=True) as con:
    con.row_factory = sqlite3.Row
    operations = [dict(row) for row in con.execute(
        "SELECT id,kind,state,reserved,units,created FROM ops ORDER BY created")]
    config = json.loads(con.execute("SELECT value FROM meta WHERE key='config'").fetchone()[0])
units = Counter()
for operation in operations:
    units.update(json.loads(operation["units"]))
last = operations[-1] if operations else None
output = {
    "states": dict(Counter(o["state"] for o in operations)),
    "conservative_reserved_usd": round(sum(o["reserved"] for o in operations) / 1e9, 6),
    "compute_cap_usd": config["compute_cap_usd"],
    "reserved_tokens": dict(units),
    "latest_operation": {
        "id": last["id"], "state": last["state"],
        "seconds_since_dispatch": round(time.time() - last["created"], 1),
    } if last else None,
}
for label in ("sft", "base", "sft_rl"):
    task_ops = [o for o in operations if o["id"].startswith(f"{label}-test-")]
    if task_ops:
        output[label] = {
            "tasks_started": len({o["id"].rsplit("-t", 1)[0] for o in task_ops}),
            "evaluation_saved": (directory / f"{label}.json").exists(),
            "regression_saved": (directory / f"{label}-regression.json").exists(),
        }
status_file = directory / "status.json"
if status_file.exists():
    output["final_status"] = json.loads(status_file.read_text())["state"]
print(json.dumps(output, indent=2))
