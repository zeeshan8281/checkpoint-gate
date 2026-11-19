"""Render one shareable graph from a completed real held-out experiment.

Usage: python analysis/plot_results.py runs/pilot-seed7/results.json --out results.png
Requires matplotlib. Refuses scripted demonstrations and incomplete results.
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

parser = argparse.ArgumentParser()
parser.add_argument("results", type=Path)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
data = json.loads(args.results.read_text())
if data.get("kind") != "baseten_experiment" or data.get("complete") is not True:
    raise ValueError("Only complete real held-out experiment results may be plotted")
keys = [x for x in ("base", "sft", "sft_rl") if x in data["conditions"]]
labels = {"base":"Base", "sft":"Supervised\nfine-tuning", "sft_rl":"SFT + verifier\nreward training"}
colors = {"base":"#81938a", "sft":"#87b7e6", "sft_rl":"#b5ed87"}
bg, text, muted = "#101513", "#edf2ed", "#9aa99f"
plt.rcParams.update({"font.family":"DejaVu Sans", "font.size":12, "text.color":text,
                     "axes.labelcolor":muted, "xtick.color":text, "ytick.color":muted})
fig, ax = plt.subplots(figsize=(12, 8), dpi=180)
fig.patch.set_facecolor(bg)
ax.set_facecolor(bg)
fig.subplots_adjust(left=.11, right=.94, top=.74, bottom=.25)
fig.text(.11,.91,"CHECKPOINTGATE / HELD-OUT PILOT",fontsize=10,color="#b5ed87",weight="bold")
title = ("Can verifier training improve a SQL tool agent?" if "sft_rl" in keys
         else "Can supervised training improve a SQL tool agent?")
fig.text(.11,.845,title,fontsize=21,weight="bold")
n = {data["conditions"][k]["offered_tasks"] for k in keys}
if len(n) != 1:
    raise ValueError("All arms must have the same offered task count")
fig.text(.11,.794,f"Qwen3.6-35B-A3B · rank-8 LoRA · {next(iter(n))} tasks per condition",fontsize=12,color=muted)
for x, key in enumerate(keys):
    row = data["conditions"][key]
    accuracy = row["accuracy"] * 100
    low, high = [v*100 for v in row["wilson_95"]]
    ax.bar(x, accuracy, width=.53, color=colors[key], zorder=3)
    ax.errorbar(x, accuracy, yerr=[[accuracy-low],[high-accuracy]], fmt="none",
                ecolor=text, capsize=7, linewidth=1.5, zorder=4)
    ax.text(x, min(106, high+4), f"{row['correct']}/{row['offered_tasks']}\n{accuracy:.1f}%",
            ha="center", va="bottom", fontsize=14, color=text, weight="bold")
ax.set_ylim(0,119)
ax.set_yticks([0,25,50,75,100],["0%","25%","50%","75%","100%"])
ax.set_xticks(range(len(keys)), [labels[k] for k in keys])
ax.set_ylabel("Verified successful tasks",labelpad=12)
ax.grid(axis="y",color="#2d3831",zorder=0)
for spine in ax.spines.values():
    spine.set_visible(False)
ax.tick_params(length=0,pad=11)
notes = ["2 SQL calls + 768 generated tokens per task · all offered tasks counted",
         "Same outer-fence normalization in every arm · failures and timeouts included",
         "95% Wilson intervals over task instances · one training seed · four fixed query families"]
final = "sft_rl" if "sft_rl" in keys else "sft"
comparison = data["paired_vs_base"][final]
lo, hi = comparison["paired_bootstrap_95"]
fig.text(.11,.135,
         f"{'SFT + reward' if final == 'sft_rl' else 'SFT'} vs base: "
         f"{comparison['delta_accuracy']*100:+.1f} pp "
         f"(paired 95% interval {lo*100:+.1f} to {hi*100:+.1f} pp)",
         fontsize=12,color="#b5ed87")
fig.text(.11,.102,
         f"Actual reward updates: {data['rl_updates']}" if "sft_rl" in keys
         else "No informative reward update occurred; no RL condition is shown.",
         fontsize=10,color=muted)
fig.text(.11,.04,"\n".join(notes),fontsize=8.5,color=muted,linespacing=1.5)
args.out.parent.mkdir(parents=True,exist_ok=True)
fig.savefig(args.out,facecolor=bg)
plt.close(fig)
print(args.out)
