"""Describe a completed pilot from its preserved traces, without new model calls."""
import argparse
import json
from collections import Counter
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("run", type=Path)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()


def read(name):
    return json.loads((args.run / name).read_text())


results = read("results.json")
if results.get("kind") != "baseten_experiment" or results.get("complete") is not True:
    raise ValueError("A complete real experiment is required")
training = read("training.json")
arms = [k for k in ("base", "sft", "sft_rl") if k in results["conditions"]]
rows = {k: read(f"{k}.json")["rows"] for k in arms}
families = sorted({r["family"] for r in rows["base"]})
labels = {"base": "Base", "sft": "SFT", "sft_rl": "SFT + reward"}
by_family = {
    family: {arm: {
        "n": sum(r["family"] == family for r in rows[arm]),
        "correct": sum(r["family"] == family and r["correct"] for r in rows[arm]),
    } for arm in arms} for family in families
}
regression = {}
for arm in arms:
    r = read(f"{arm}-regression.json")["rows"]
    regression[arm] = {
        "arithmetic": {"n": 50, "correct": sum(x["correct"] for x in r if x["id"] < 50)},
        "copy": {"n": 50, "correct": sum(x["correct"] for x in r if x["id"] >= 50)},
    }
rl = [x for x in training if x["stage"] == "rl"]
groups = []
for path in sorted(args.run.glob("rl-group-*.json"), key=lambda p: int(p.stem.rsplit("-", 1)[1])):
    group = json.loads(path.read_text())
    groups.append({"file": path.name, "rewards": [x["reward"] for x in group],
                   "correct": sum(x["correct"] for x in group), "n": len(group)})
details = {
    "by_family": by_family,
    "regression_by_task_type": regression,
    "rl_groups": groups,
    "rl_skipped_groups": dict(Counter(x["skipped"] for x in rl if "skipped" in x)),
    "source_of_statistics": "Completed results and all offered task traces; no model calls.",
}
args.out.mkdir(parents=True, exist_ok=True)
(args.out / "analysis.json").write_text(json.dumps(details, indent=2) + "\n")

final_arm = "sft_rl" if "sft_rl" in arms else "sft"
final_score, base_score = results["conditions"][final_arm], results["conditions"]["base"]
headline = (
    f"{labels[final_arm]} completed {final_score['correct']}/{final_score['offered_tasks']} tasks; "
    f"base completed {base_score['correct']}/{base_score['offered_tasks']}. "
    f"The observed difference was "
    f"{100*results['paired_vs_base'][final_arm]['delta_accuracy']:+.1f} percentage points."
)
if not results["rl_updates"]:
    headline += " No RL update occurred: every sampled reward group had equal rewards."

lines = [
    "# CheckpointGate: first completed pilot",
    "",
    headline,
    "",
    "A single-seed synthetic experiment with Qwen/Qwen3.6-35B-A3B and rank-8 LoRA. "
    "Every condition received the same 200 held-out task instances, two SQL calls "
    "and at most 768 generated tokens per task.",
    "",
    "| Condition | Correct / offered | Accuracy | 95% Wilson interval | Strict format violations |",
    "| --- | ---: | ---: | ---: | ---: |",
]
for arm in arms:
    s = results["conditions"][arm]
    lo, hi = s["wilson_95"]
    lines.append(
        f"| {labels[arm]} | {s['correct']}/{s['offered_tasks']} | {s['accuracy']:.1%} "
        f"| {lo:.1%}–{hi:.1%} | {s['strict_format_violations']} |"
    )
lines += [
    "",
    "A strict format violation counts a model turn rejected by the strict action parser, "
    "including a JSON action wrapped in a Markdown fence. "
    "The frozen evaluator removes one whole outer fence in every condition; "
    "it does not repair SQL or extract JSON from surrounding prose. "
    "Format violations are therefore reported separately from task correctness.",
    "",
    "## Paired comparisons",
    "",
    "| Condition versus base | Accuracy difference | Paired 95% interval | Wins / losses / ties |",
    "| --- | ---: | ---: | ---: |",
]
for arm in arms[1:]:
    c = results["paired_vs_base"][arm]
    lo, hi = c["paired_bootstrap_95"]
    lines.append(
        f"| {labels[arm]} | {100*c['delta_accuracy']:+.1f} pp "
        f"| {100*lo:+.1f} to {100*hi:+.1f} pp "
        f"| {c['wins']} / {c['losses']} / {c['ties']} |"
    )
lines += [
    "",
    "These intervals resample generated task instances. They do not estimate "
    "uncertainty over new query families, databases from other generators, "
    "training seeds, or repeated provider sampling.",
    "",
    "## Query-family breakdown",
    "",
    "| Held-out family | " + " | ".join(labels[a] for a in arms) + " |",
    "| --- | " + " | ".join("---:" for _ in arms) + " |",
]
for family, stats in by_family.items():
    lines.append("| " + family + " | " + " | ".join(
        f"{stats[a]['correct']}/{stats[a]['n']}" for a in arms) + " |")
lines += [
    "",
    "## Tool-fault breakdown",
    "",
    "| Condition | Clean tasks | Transient-error tasks | Generated tokens | Mean SQL calls |",
    "| --- | ---: | ---: | ---: | ---: |",
]
for arm in arms:
    s = results["conditions"][arm]
    fault = s["by_fault"]
    lines.append(f"| {labels[arm]} | " + " | ".join(
        f"{fault[name]['correct']}/{fault[name]['n']}"
        for name in ("none", "transient_first_call")) +
        f" | {s['output_tokens']} | {s['mean_tool_calls_all_tasks']:.2f} |")
lines += [
    "",
    "## Elementary regression check",
    "",
    "| Condition | Arithmetic / 50 | Copy / 50 |",
    "| --- | ---: | ---: |",
]
for arm, r in regression.items():
    lines.append(
        f"| {labels[arm]} | {r['arithmetic']['correct']} | {r['copy']['correct']} |"
    )
lines += [
    "",
    "This suite requires exact JSON without Markdown normalization. It measures "
    "simple arithmetic/copy and output-format behavior, not broad retained capability.",
    "",
    "## Training and accounting",
    "",
    f"- Supervised updates: {sum(x['stage'] == 'sft' for x in training)}.",
    f"- Assistant-turn demonstrations consumed: "
    f"{sum(x['stage'] == 'sft' for x in training) * read('manifest.json')['config']['sft_batch_size']}.",
    f"- Actual reward updates: {results['rl_updates']}. Sampled reward groups: {len(groups)}.",
    f"- Equal-reward groups skipped: {sum('skipped' in x for x in rl)}.",
    f"- Training-distribution reward rollouts correct: "
    f"{sum(g['correct'] for g in groups)}/{sum(g['n'] for g in groups)} "
    f"(repeated samples within each group, not distinct held-out tasks).",
    f"- Conservative compute reservation for this pilot: "
    f"${results['budget']['conservative_reserved_usd']:.6f}; provider invoice not reconciled.",
    "",
    "The sampled training problems, final checkpoint rule, normalization rule, "
    "and evaluation order were fixed before held-out evaluation. No checkpoint "
    "was selected by test accuracy. The dataset generator and related examples "
    "are public, so this is not a contamination-resistant benchmark.",
    "",
    "All tasks use related two-table synthetic schemas. The next confirmatory "
    "study needs fresh private families, several training seeds, repeated base "
    "sampling, and broader regression tests. Results here apply to this task distribution.",
    "",
]
(args.out / "RESULTS.md").write_text("\n".join(lines))
print(args.out / "RESULTS.md")
