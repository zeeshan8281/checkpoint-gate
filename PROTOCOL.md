# Pilot protocol, version 1

## Hypothesis and primary outcome

Training may increase successful completion of held-out SQL tasks within two tool calls and 768 generated tokens. Correctness is the primary outcome. Efficiency is secondary and is reported over all offered tasks, not just successes.

Three conditions share the provider base model, task set, tool contract, decoding settings, and inference budget:

1. Base weights.
2. Final SFT checkpoint.
3. Final SFT + verifier-reward checkpoint, if at least one RL update occurs.

The configured seed is 7. Final checkpoints are prespecified; test results do not select a checkpoint. Evaluation arm order is shuffled with the fixed seed and saved. One seed is preliminary and does not measure training-seed variation.

## Tasks and generalization

Default generation creates 50 instances per construction family, half clean and half with a deterministic transient error on the first tool call.

| Split | Query families |
| --- | --- |
| Train | filter, grouped sum, missing child, filtered join |
| Development | conditional count, grouped HAVING, tied maxima, correlated EXISTS |
| Test | latest-row window, relational division, NULL-safe anti-join, distinct joined pairs |

Vocabulary is also split: customers/orders, teams/tickets, laboratories/readings. Each database contains 12 parent rows, 52 child rows, NULLs, ties, duplicate logical events, and a parent with no children.

All families use a related two-table relational skeleton. This is a limited compositional shift, not a broad schema-generalization claim. Eight dev instances provide only a coarse ceiling gate. The development split can support a separately budgeted calibration study before a new frozen experiment.

The generator and demo traces are public. Expected answers are hidden from model prompts and the SQLite runtime, but this is not a contamination-resistant public benchmark. For a future confirmatory study, freeze a fresh private seed and construction families before evaluation.

## Scoring

An assistant action must be exactly one JSON object with either `sql` or `answer`. A final answer is a two-dimensional row array. At least one tool query must have succeeded. Every final answer is checked against trusted expected rows.

Column order matters. Row order matters when requested; otherwise comparisons use multisets, preserving duplicate multiplicity. SQL integer and exactly equal floating-point values compare equal; strings and booleans remain distinct. NULL is JSON null. This integer-valued dataset requires no approximate floating-point tolerance.

Successful reward is `1 - 0.05 * max(0, tool_calls - 1)`. Failure reward is 0. Correctness always dominates reduced tool usage. The injected-error stratum necessarily needs an additional call; report it separately.

SFT masks prompts and supervises assistant action/answer tokens plus EOS. Reward updates assign each trajectory's group-centered reward advantage to its assistant tokens, retaining sampled log probabilities for `cispo`. Tool feedback is masked as prompt context. This is a simple multi-turn policy-gradient baseline, not a novel algorithm; variable trajectory length can affect gradient weighting.

Uninformative groups are skipped, with a strict group ceiling. Skipped groups still consume their sampling reservation. The runner never loops indefinitely waiting for reward variance.

## Spending and failure semantics

The ledger persists a reservation before dispatch. Successful calls commit the conservative reservation. Exceptions make it unknown. Restart detection changes pending reservations into unknown. New work is prohibited while an unknown operation remains.

The pinned SDK internally retries queued submissions with the same idempotency key. A new application invocation would create a new remote operation, so the application never retries an ambiguous optimizer update. Accepted training operation IDs and checkpoint paths are saved for investigation. The SDK exposes only the first operation ID for a chunked backward call.

Interrupted evaluation is marked incomplete; all remaining tasks appear as `not_run`. It cannot produce a paired model-quality comparison. An incomplete run is useful operational evidence, not a training win.

A local file lock prevents simultaneous runners against one directory. Cloudflare uses leases and monotonically increasing fencing tokens. A lease expires after ten minutes and cannot be automatically renewed after expiry. It never authorizes re-executing paid work.

R2 uploads precede receipt commits. A failure can leave an unreferenced content-addressed object. Receipt identity is immutable. The system provides duplicate-safe evidence storage, not a distributed exactly-once guarantee for external computation.

## Uncertainty and regression

Accuracy has a Wilson interval; differences from base use paired bootstrap intervals over task instances. These intervals are conditional on the four fixed test construction families. They do not estimate variation over unseen families, model seeds, or provider infrastructure. Report per-family and per-fault results from the raw rows.

The separate 100-case regression suite covers elementary arithmetic and literal string copying into a JSON format. It is a narrow check for collateral format/instruction changes, not a measure of broad catastrophic forgetting.

## Security boundary

The model emits SQL strings; it never runs Python, shell commands, or arbitrary code. SQLite uses read-only immutable connections, an authorizer, function allowlist, VM/time limits, and output limits. The generated databases contain only synthetic task data.

The verifier runs in the coordinator process. This is appropriate for bounded SQL over generated data, not an OS sandbox for malicious native code. If arbitrary execution is added, isolate it in a separate resource-constrained process or sandbox and keep gold data out of that environment.

## Remaining gates

- Verify actual Baseten workspace serverless availability, rank support, current prices, and billing.
- Perform a small real-model smoke run before committing to the full pilot.
- Reconcile token reservations against actual invoices.
- Test deployment and recovery on real Cloudflare infrastructure.
- Add audited resume from confirmed checkpoint state; current CLI deliberately refuses automatic continuation.
- Broaden query/schema families and add multiple training seeds if the pilot has informative signal.
- Validate exported adapter compatibility before claiming portability to MLX or another inference engine.
