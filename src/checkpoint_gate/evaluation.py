from __future__ import annotations

import math
import random
from collections import Counter


def wilson(successes: int, n: int) -> list[float]:
    if n == 0:
        return [0.0, 1.0]
    z, p = 1.95996398454, successes / n
    center = (p + z*z / (2*n)) / (1 + z*z/n)
    margin = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1+z*z/n)
    return [max(0, center-margin), min(1, center+margin)]


def summarize(rows: list[dict]) -> dict:
    n, correct = len(rows), sum(r["correct"] for r in rows)
    return {
        "offered_tasks": n, "correct": correct,
        "accuracy": correct/n if n else None, "wilson_95": wilson(correct, n),
        "mean_tool_calls_all_tasks": sum(r.get("tool_calls", 0) for r in rows)/n if n else None,
        "output_tokens": sum(r.get("output_tokens", 0) for r in rows),
        "statuses": dict(Counter(r["status"] for r in rows)),
        "by_fault": {s: {
            "n": sum(r["fault"] == s for r in rows),
            "correct": sum(r["fault"] == s and r["correct"] for r in rows),
        } for s in sorted({r["fault"] for r in rows})},
    }


def paired(left: list[dict], right: list[dict], *, seed=91, replicates=5000) -> dict:
    a, b = {r["task_id"]: r for r in left}, {r["task_id"]: r for r in right}
    if not a or a.keys() != b.keys() or len(a) != len(left) or len(b) != len(right):
        raise ValueError("Paired comparison requires identical unique task IDs")
    if any(r["status"] == "not_run" for r in left + right):
        raise ValueError("Incomplete campaigns cannot produce a quality comparison")
    keys, rng = sorted(a), random.Random(seed)
    delta = [int(b[k]["correct"]) - int(a[k]["correct"]) for k in keys]
    boot = sorted(sum(rng.choices(delta, k=len(delta)))/len(delta) for _ in range(replicates))
    return {
        "paired_tasks": len(keys), "delta_accuracy": sum(delta)/len(delta),
        "paired_bootstrap_95": [boot[int(replicates*.025)], boot[int(replicates*.975)]],
        "wins": delta.count(1), "losses": delta.count(-1), "ties": delta.count(0),
        "uncertainty_unit": "Generated task instance. Does not estimate variation across new schema families or training seeds.",
    }
