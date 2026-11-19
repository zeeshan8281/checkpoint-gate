# CheckpointGate: first completed pilot

SFT completed 112/200 tasks; base completed 188/200. The observed difference was -38.0 percentage points. No RL update occurred: every sampled reward group had equal rewards.

A single-seed synthetic experiment with Qwen/Qwen3.6-35B-A3B and rank-8 LoRA. Every condition received the same 200 held-out task instances, two SQL calls and at most 768 generated tokens per task.

| Condition | Correct / offered | Accuracy | 95% Wilson interval | Strict format violations |
| --- | ---: | ---: | ---: | ---: |
| Base | 188/200 | 94.0% | 89.8%–96.5% | 296 |
| SFT | 112/200 | 56.0% | 49.1%–62.7% | 0 |

A strict format violation counts a model turn rejected by the strict action parser, including a JSON action wrapped in a Markdown fence. The frozen evaluator removes one whole outer fence in every condition; it does not repair SQL or extract JSON from surrounding prose. Format violations are therefore reported separately from task correctness.

## Paired comparisons

| Condition versus base | Accuracy difference | Paired 95% interval | Wins / losses / ties |
| --- | ---: | ---: | ---: |
| SFT | -38.0 pp | -45.0 to -31.0 pp | 2 / 78 / 120 |

These intervals resample generated task instances. They do not estimate uncertainty over new query families, databases from other generators, training seeds, or repeated provider sampling.

## Query-family breakdown

| Held-out family | Base | SFT |
| --- | ---: | ---: |
| anti_null | 49/50 | 13/50 |
| distinct_pairs | 48/50 | 49/50 |
| latest_window | 41/50 | 0/50 |
| relational_division | 50/50 | 50/50 |

## Tool-fault breakdown

| Condition | Clean tasks | Transient-error tasks | Generated tokens | Mean SQL calls |
| --- | ---: | ---: | ---: | ---: |
| Base | 95/100 | 93/100 | 40067 | 1.50 |
| SFT | 55/100 | 57/100 | 35004 | 1.51 |

## Elementary regression check

| Condition | Arithmetic / 50 | Copy / 50 |
| --- | ---: | ---: |
| Base | 45 | 23 |
| SFT | 44 | 10 |

This suite requires exact JSON without Markdown normalization. It measures simple arithmetic/copy and output-format behavior, not broad retained capability.

## Training and accounting

- Supervised updates: 12.
- Assistant-turn demonstrations consumed: 96.
- Actual reward updates: 0. Sampled reward groups: 18.
- Equal-reward groups skipped: 18.
- Training-distribution reward rollouts correct: 72/72 (repeated samples within each group, not distinct held-out tasks).
- Conservative compute reservation for this pilot: $0.871654; provider invoice not reconciled.

The sampled training problems, final checkpoint rule, normalization rule, and evaluation order were fixed before held-out evaluation. No checkpoint was selected by test accuracy. The dataset generator and related examples are public, so this is not a contamination-resistant benchmark.

All tasks use related two-table synthetic schemas. The next confirmatory study needs fresh private families, several training seeds, repeated base sampling, and broader regression tests. Results here apply to this task distribution.
