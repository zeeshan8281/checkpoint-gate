"""Retrospective SQL replay. No model, network, or paid service calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from checkpoint_gate.common import file_hash, write_json
from checkpoint_gate.dataset import load
from checkpoint_gate.verifier import SQLiteTool, equivalent, parse_action


def names(task):
    tables = re.findall(r"CREATE TABLE (\w+)", task["schema"])
    if len(tables) != 2:
        raise ValueError("Expected the frozen two-table schema")
    parent, child = tables
    suffix = parent.rsplit("_", 1)[1]
    return parent, child, f"sector_{suffix}", f"value_{suffix}", f"label_{suffix}"


def oracle(task, db):
    """Independent Python implementation of the four natural-language tasks."""
    parent, child, group, value, label = names(task)
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
        parents = con.execute(f"SELECT id,name,{group} FROM {parent}").fetchall()
        children = con.execute(
            f"SELECT id,parent_id,{value},{label},tick FROM {child}"
        ).fetchall()
    family = task["family"]
    if family == "latest_window":
        chosen = {}
        for row in children:
            rid, pid, val, state, tick = row
            if pid is not None and (
                pid not in chosen or (tick, rid) > (chosen[pid][4], chosen[pid][0])
            ):
                chosen[pid] = row
        return [[pid, row[0], row[2]] for pid, row in sorted(chosen.items())]
    if family in ("anti_null", "relational_division"):
        states = defaultdict(set)
        for _, pid, _, state, _ in children:
            if pid is not None:
                states[pid].add(state)
        return [[pid, name] for pid, name, _ in sorted(parents)
                if ({"open", "closed"} <= states[pid] if family == "relational_division"
                    else "closed" not in states[pid])]
    if family == "distinct_pairs":
        threshold = int(re.search(r">=(\d+)", task["question"]).group(1))
        groups = {pid: grp for pid, _, grp in parents}
        pairs = {(groups[pid], state) for _, pid, val, state, _ in children
                 if pid in groups and val is not None and val >= threshold}
        return [list(pair) for pair in sorted(pairs, key=lambda x: json.dumps(x))]
    raise ValueError(f"Unsupported oracle family: {family}")


def perturb(task, destination, variant):
    """Same schema and question, changed valid data; no model-dependent choices."""
    key = f"checkpoint-gate-static-suite-v1:{task['id']}:{variant}"
    seed = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")
    rng = random.Random(seed)
    parent, child, group, value, label = names(task)
    # The IDs, nullable columns, duplicate events, ties, and empty parent are
    # legal under the existing schema and do not change the question.
    parents = [(i, f"entity-{i:02}", rng.choice(["north", "south", None]))
               for i in range(1, 13)]
    children = [
        (i, rng.choice(list(range(1, 12)) + [None]),
         rng.choice([None, 0, 2, 5, 10, 20, 35]),
         rng.choice(["open", "closed", "hold", None]), rng.randint(1, 12))
        for i in range(1, 65)
    ]
    # Guaranteed adversarial witnesses: timestamp/ID disagreement, timestamp
    # tie, mixed labels, duplicate logical events, NULL foreign key and value.
    children += [
        (65, 1, 20, "open", 30), (66, 1, 5, "closed", 1),
        (67, 2, 10, "open", 40), (68, 2, 35, "hold", 40),
        (69, 3, 10, "closed", 7), (70, 3, 10, "open", 7),
        (71, 4, 20, "open", 9), (72, 4, 20, "open", 9),
        (73, None, 35, "closed", 10), (74, 5, None, None, 10),
    ]
    with sqlite3.connect(destination) as con:
        con.executescript(task["schema"])
        con.executemany(f"INSERT INTO {parent} VALUES(?,?,?)", parents)
        con.executemany(f"INSERT INTO {child} VALUES(?,?,?,?,?)", children)
    return seed


def extract(row, expected, ordered):
    last_sql, last_rows, final = None, None, None
    for turn in row["trace"]:
        try:
            action = parse_action(turn["assistant"], allow_outer_fence=True)
        except ValueError:
            continue
        if "sql" in action and "rows" in turn.get("tool", {}):
            last_sql, last_rows = action["sql"], turn["tool"]["rows"]
        if "answer" in action:
            final = action["answer"]
    correct = last_sql is not None and equivalent(final, expected, ordered)
    if correct != row["correct"]:
        raise ValueError(f"Recorded score disagrees with independent rescoring: {row['task_id']}")
    query_exact = last_sql is not None and equivalent(last_rows, expected, ordered)
    if correct:
        category = "correct_final"
    elif last_sql is None:
        category = "no_successful_query"
    elif query_exact:
        category = "wrong_final_despite_exact_last_query"
    else:
        category = "wrong_final_and_inexact_last_query"
    return last_sql, last_rows, query_exact, category


def paired_summary(rows, left_key, right_key, *, seed=20261120, replicates=10000):
    """Stratify paired resampling within the fixed family x fault cells."""
    rng = random.Random(seed)
    strata = defaultdict(list)
    for r in rows:
        strata[(r["family"], r["fault"])].append(int(r[right_key]) - int(r[left_key]))
    n = len(rows)
    if n == 0:
        raise ValueError("No paired tasks")
    deltas = [v for group in strata.values() for v in group]
    boot = sorted(sum(sum(rng.choices(g, k=len(g))) for g in strata.values()) / n
                  for _ in range(replicates))
    losses, wins = deltas.count(-1), deltas.count(1)
    discordant = losses + wins
    p = (min(1., 2 * sum(math.comb(discordant, i)
                         for i in range(min(losses, wins) + 1)) / 2**discordant)
         if discordant else 1.)
    return {
        "n": n, "delta": sum(deltas) / n, "wins": wins, "losses": losses,
        "ties": n - discordant,
        "stratified_task_bootstrap_95": [
            boot[int(.025 * replicates)], boot[min(replicates - 1, int(.975 * replicates))]
        ],
        "exploratory_exact_mcnemar_p": p, "bootstrap_replicates": replicates,
        "unit": "Original task, stratified by fixed query family and fault; not variants or seeds",
        "limitation": "Conditional on one training run and four fixed templates. Exploratory, not preregistered.",
    }


def analyze(evidence, data, output, scratch, variants=8):
    if variants < 1:
        raise ValueError("At least one perturbation is required")
    if output.exists() or scratch.exists():
        raise FileExistsError("Use new output/scratch directories; immutable prior analyses are preserved")
    tasks, gold, manifest = load(data, "test")
    run_manifest = json.loads((evidence / "manifest.json").read_text())
    if run_manifest["dataset_sha256"] != manifest["sha256"]:
        raise ValueError("Dataset does not match the recorded pilot")
    original = json.loads((evidence / "results.json").read_text())
    if original.get("complete") is not True:
        raise ValueError("Requires a complete pilot")
    arms = {}
    for arm in ("base", "sft"):
        obj = json.loads((evidence / f"{arm}.json").read_text())
        if obj.get("complete") is not True:
            raise ValueError(f"Incomplete {arm} evaluation")
        rows = {r["task_id"]: r for r in obj["rows"]}
        if len(rows) != len(obj["rows"]) or set(rows) != {t["id"] for t in tasks}:
            raise ValueError("Task identity mismatch or duplicate")
        arms[arm] = rows
    output.mkdir(parents=True)
    scratch.mkdir(parents=True)
    all_rows, variant_rows, comparisons = [], [], []
    checks = {"original_final_scores": 0, "original_tool_rows": 0,
              "gold_sql_vs_python_oracle": 0, "candidate_sql_replays": 0}
    for task in tasks:
        expected = gold[task["id"]]["rows"]
        if not equivalent(oracle(task, data / task["db"]), expected, task["ordered"]):
            raise ValueError("Independent oracle disagrees with original gold")
        checks["gold_sql_vs_python_oracle"] += 1
        info = {}
        for arm, arm_rows in arms.items():
            row = arm_rows[task["id"]]
            if row["family"] != task["family"] or row["fault"] != task["fault"]:
                raise ValueError("Trace family/fault metadata mismatch")
            sql, saved, exact, category = extract(row, expected, task["ordered"])
            checks["original_final_scores"] += 1
            if sql is not None:
                feedback = SQLiteTool(data / task["db"]).execute(sql)
                if "rows" not in feedback or not equivalent(feedback["rows"], saved, True):
                    raise ValueError("Original SQL replay disagrees with recorded tool result")
                checks["original_tool_rows"] += 1
            info[arm] = {
                "task_id": task["id"], "family": task["family"], "fault": task["fault"],
                "arm": arm, "original_correct": row["correct"],
                "strict_trace_valid": row["format_violations"] == 0,
                "last_sql": sql, "last_query_exact_original": exact, "failure_category": category,
                "variant_passes": 0, "variants": variants,
                "output_tokens": row["output_tokens"], "elapsed_seconds": row["elapsed_seconds"],
            }
        for variant in range(variants):
            db = scratch / f"{task['id']}-v{variant}.sqlite"
            seed = perturb(task, db, variant)
            expected_variant = oracle(task, db)
            trusted = SQLiteTool(db).execute(gold[task["id"]]["sql"])
            if "rows" not in trusted or not equivalent(
                trusted["rows"], expected_variant, task["ordered"]
            ):
                raise ValueError(f"Gold and independent oracle disagree: {task['id']}:{variant}")
            checks["gold_sql_vs_python_oracle"] += 1
            for arm, item in info.items():
                result = SQLiteTool(db).execute(item["last_sql"]) if item["last_sql"] else {}
                checks["candidate_sql_replays"] += item["last_sql"] is not None
                passed = "rows" in result and equivalent(
                    result["rows"], expected_variant, task["ordered"])
                item["variant_passes"] += passed
                variant_rows.append({
                    "task_id": task["id"], "arm": arm, "variant": variant,
                    "seed": seed, "database_sha256": file_hash(db), "query_exact": passed,
                    "error": result.get("error"), "expected_rows": expected_variant,
                    "candidate_rows": result.get("rows"),
                })
        pair = {"task_id": task["id"], "family": task["family"], "fault": task["fault"]}
        for arm, item in info.items():
            item["static_suite_survival"] = (
                item["last_query_exact_original"] and item["variant_passes"] == variants)
            item["original_success_and_suite_survival"] = (
                item["original_correct"] and item["static_suite_survival"])
            all_rows.append(item)
            pair[f"{arm}_correct"] = item["original_correct"]
            pair[f"{arm}_suite"] = item["static_suite_survival"]
        comparisons.append(pair)
    summaries = {}
    for arm in arms:
        selected = [r for r in all_rows if r["arm"] == arm]
        groups = {"all": selected}
        groups.update({f: [r for r in selected if r["family"] == f]
                       for f in sorted({r["family"] for r in selected})})
        summaries[arm] = {}
        for group, rows in groups.items():
            summaries[arm][group] = {
                "n": len(rows), "original_correct": sum(r["original_correct"] for r in rows),
                "strict_valid_tasks": sum(r["strict_trace_valid"] for r in rows),
                "last_query_exact_original": sum(r["last_query_exact_original"] for r in rows),
                "static_suite_survival": sum(r["static_suite_survival"] for r in rows),
                "original_success_and_suite_survival": sum(
                    r["original_success_and_suite_survival"] for r in rows),
                "failure_categories": dict(Counter(r["failure_category"] for r in rows)),
            }
    summary = {
        "kind": "retrospective_static_sql_replay", "version": 1,
        "new_model_calls": 0, "new_cloud_spend_usd": 0, "complete": True,
        "pilot_dataset_sha256": manifest["sha256"], "perturbations_per_task": variants,
        "schema_question_unchanged": True, "checks": checks, "arms": summaries,
        "paired_original_accuracy": paired_summary(comparisons, "base_correct", "sft_correct"),
        "paired_static_suite": paired_summary(comparisons, "base_suite", "sft_suite"),
        "denominators": {
            "all_tasks": len(tasks),
            "both_originally_correct": sum(r["base_correct"] and r["sft_correct"] for r in comparisons),
        },
        "limitations": [
            "Designed after viewing the public pilot, so this is exploratory retrospective analysis.",
            "Standalone last-query equivalence is not end-to-end agent accuracy on changed databases.",
            "An agent may intentionally retrieve extra rows and postprocess them correctly.",
            "Variants share a source task and are not independent statistical observations.",
            "Finite suites can expose counterexamples but cannot prove SQL equivalence.",
            "Original elapsed time includes provider/network/queueing; GPU model and count remain undisclosed.",
        ],
        "source_hashes": {p.name: file_hash(p) for p in [
            evidence / "base.json", evidence / "sft.json", evidence / "results.json",
            evidence / "manifest.json", Path(__file__).resolve(),
        ]},
    }
    for arm in arms:
        both = {r["task_id"] for r in comparisons if r["base_correct"] and r["sft_correct"]}
        summary["arms"][arm]["both_originally_correct"] = {
            "n": len(both),
            "static_suite_survival": sum(
                r["static_suite_survival"] for r in all_rows
                if r["arm"] == arm and r["task_id"] in both),
        }
    write_json(output / "summary.json", summary)
    write_json(output / "task-audit.json", all_rows)
    write_json(output / "variant-results.json", variant_rows)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=REPO / "evidence/pilot-seed7")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--variants", type=int, default=8)
    args = parser.parse_args()
    result = analyze(args.evidence, args.data, args.out, args.scratch, args.variants)
    print(json.dumps({"complete": result["complete"], "checks": result["checks"],
                      "arms": {a: x["all"] for a, x in result["arms"].items()}}, indent=2))
