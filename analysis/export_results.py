"""Export a completed run through an explicit evidence allowlist.

Never copies environment files, credentials, runtime databases, or UI captures.
"""
import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("run", type=Path)
parser.add_argument("--data", type=Path, required=True)
parser.add_argument("--evidence", type=Path, required=True)
parser.add_argument("--web", type=Path, required=True)
args = parser.parse_args()
if sys.version_info < (3, 12):
    raise SystemExit("Use the project's Python 3.12+ environment for read-only WAL access.")


def read(name):
    return json.loads((args.run / name).read_text())


results, status = read("results.json"), read("status.json")
if results.get("kind") != "baseten_experiment" or results.get("complete") is not True:
    raise ValueError("Only a complete real experiment may be exported")
if status.get("state") != "complete":
    raise ValueError("The runner must have completed cleanup")
if read("shutdown.json")["deactivation_errors"]:
    raise ValueError("Resolve reported shutdown errors before publishing")
with sqlite3.connect(f"file:{args.run / 'ledger.sqlite'}?mode=ro", uri=True) as con:
    con.row_factory = sqlite3.Row
    operations = [dict(row) for row in con.execute("SELECT * FROM ops ORDER BY created")]
if any(row["state"] != "committed" for row in operations):
    raise ValueError("Resolve pending/unknown operations before publishing")
for row in operations:
    row["reserved_usd"] = row.pop("reserved") / 1e9
    for key in ("units", "receipt"):
        row[key] = json.loads(row[key]) if row[key] else None
arms = [k for k in ("base", "sft", "sft_rl") if k in results["conditions"]]
rows = {k: read(f"{k}.json")["rows"] for k in arms}
ids = {r["task_id"] for r in rows["base"]}
for arm in arms:
    if len(rows[arm]) != len(ids) or {r["task_id"] for r in rows[arm]} != ids:
        raise ValueError("Every arm must preserve every unique offered task")
    if any(row["status"] == "not_run" for row in rows[arm]):
        raise ValueError("Incomplete task evaluation")
    summary = results["conditions"][arm]
    if summary["offered_tasks"] != len(rows[arm]) or summary["correct"] != sum(r["correct"] for r in rows[arm]):
        raise ValueError("Summary does not match preserved task traces")
dataset_manifest = json.loads((args.data / "manifest.json").read_text())
if dataset_manifest["sha256"] != read("manifest.json")["dataset_sha256"]:
    raise ValueError("Dataset manifest does not match this experiment")
task_bytes = (args.data / "tasks.json").read_bytes()
if hashlib.sha256(task_bytes).hexdigest() != dataset_manifest["files"]["tasks.json"]:
    raise ValueError("Task prompts have changed since dataset freezing")
args.evidence.mkdir(parents=True, exist_ok=True)
files = [
    "results.json", "status.json", "shutdown.json", "manifest.json",
    "training.json", "tokenizer.json", "capabilities.json", "evaluation_order.json",
    "dev-base.json",
]
for arm in arms:
    files.extend([f"{arm}.json", f"{arm}-regression.json"])
for pattern in ("checkpoint-*.json", "rl-group-*.json", "rl-token-data-*.json"):
    files.extend(p.name for p in args.run.glob(pattern))
for name in sorted(set(files)):
    shutil.copy2(args.run / name, args.evidence / name)
(args.evidence / "operations.json").write_text(json.dumps(operations, indent=2) + "\n")
tasks = json.loads(task_bytes)
public = {
    "results": results, "training": read("training.json"),
    "dataset_sha256": read("manifest.json")["dataset_sha256"], "rows": rows,
    "tasks": {t["id"]: {k: t[k] for k in ("schema", "question", "ordered")}
              for t in tasks if t["id"] in ids},
}
if public["tasks"].keys() != ids:
    raise ValueError("Task prompts do not match the evaluated instances")
args.web.mkdir(parents=True, exist_ok=True)
(args.web / "pilot.json").write_text(json.dumps(public, separators=(",", ":")) + "\n")
print(json.dumps({
    "evidence_files": len(set(files)) + 1,
    "real_sampling_requests": sum(row["kind"] == "sample" for row in operations),
    "conservative_reserved_usd": sum(row["reserved_usd"] for row in operations),
}))
