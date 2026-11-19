"""Render the measured replay results; no generated or forecast performance."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("--results", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
data = json.loads((args.results / "summary.json").read_text())
args.out.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 12,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.spines.left": False, "axes.edgecolor": "#cbd5e1",
    "text.color": "#14213d", "axes.labelcolor": "#334155",
    "xtick.color": "#334155", "ytick.color": "#334155",
    "svg.hashsalt": "checkpoint-gate-study-v1",
})
base, sft = "#2563eb", "#d97706"
families = ["latest_window", "anti_null", "distinct_pairs", "relational_division"]
labels = ["Latest row", "NULL-safe\nanti-join", "Distinct\npairs", "Relational\ndivision"]

fig, axes = plt.subplots(1, 2, figsize=(14, 7.7), gridspec_kw={"width_ratios": [1.1, 1.4]})
fig.subplots_adjust(top=.72, bottom=.24, left=.07, right=.97, wspace=.32)
fig.text(.07, .93, "Cleaner format. Worse task completion.", fontsize=27, weight="bold")
fig.text(.07, .865, "Checkpoint Gate  •  Qwen3.6-35B-A3B  •  rank-8 LoRA  •  one training seed",
         fontsize=13, color="#475569")
ax = axes[0]
metrics = [("Strict-format\nvalid tasks", "strict_valid_tasks"),
           ("Correct final\nanswers", "original_correct"),
           ("Exact SQL on\noriginal + 8 variants", "static_suite_survival")]
x = np.arange(3)
for offset, arm, color, label in [(-.18, "base", base, "Base"), (.18, "sft", sft, "SFT")]:
    vals = [100 * data["arms"][arm]["all"][key] / 200 for _, key in metrics]
    bars = ax.bar(x + offset, vals, width=.34, color=color, label=label, zorder=3)
    ax.bar_label(bars, labels=[f"{v:g}%" for v in vals], padding=5, fontsize=11, weight="bold")
ax.set_xticks(x, [name for name, _ in metrics], fontsize=10)
ax.set_ylabel("Tasks (%)")
ax.set_ylim(0, 110)
ax.set_yticks([0, 25, 50, 75, 100])
ax.grid(axis="y", alpha=.18, zorder=0)
ax.set_title("Observed behavior on 200 tasks", loc="left", pad=23, fontsize=14, weight="bold")
ax.legend(frameon=False, loc="upper right", ncols=2, bbox_to_anchor=(1.0, 1.21))
ax = axes[1]
x = np.arange(4)
for offset, arm, color in [(-.18, "base", base), (.18, "sft", sft)]:
    vals = [100 * data["arms"][arm][family]["original_correct"] / 50 for family in families]
    bars = ax.bar(x + offset, vals, width=.34, color=color, zorder=3)
    ax.bar_label(bars, labels=[f"{v:g}%" for v in vals], padding=5, fontsize=11, weight="bold")
ax.set_xticks(x, labels, fontsize=10)
ax.set_ylim(0, 110)
ax.set_yticks([0, 25, 50, 75, 100])
ax.grid(axis="y", alpha=.18, zorder=0)
ax.set_title("Final-answer accuracy by query family", loc="left", pad=23, fontsize=14, weight="bold")
fig.text(.07, .115, "Replay: 400 original outcomes reproduced; 1,800 independent-oracle checks; 3,200 candidate SQL replays.",
         fontsize=11, weight="bold")
fig.text(.07, .048, "Retrospective synthetic pilot. Static SQL replay is not a new interactive model evaluation.\n"
         "Eight variants share each task. No multi-seed or unseen-family claim; Baseten GPU model/count undisclosed.",
         fontsize=10, color="#475569", linespacing=1.6)
for suffix in ("png", "svg"):
    fig.savefig(args.out / f"study-overview.{suffix}", dpi=180, facecolor="white",
                metadata={"Date": None} if suffix == "svg" else {})
plt.close(fig)
print(args.out / "study-overview.png")
