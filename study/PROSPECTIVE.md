# Prospective replication: frozen plan, no results yet

The machine-readable authority is `protocol.json`. `prospective-commitment.json` records input and code hashes; it does not contain private test inputs.

## Primary question

Does the original small-data SFT recipe reduce final-answer SQL completion on fresh instances of the four known test templates, consistently across three new training seeds?

The intervention is fixed: Qwen/Qwen3.6-35B-A3B, rank 8, learning rate 4e-5, 12 updates, batch size eight conditional assistant turns, and 96 turns sampled by the original flattened-turn recipe. Training seeds are 17, 29, and 43. The dataset is shared across seeds so that training randomness is separated from data resampling.

No learning-rate search or new RL stage is included. Choosing a new recipe based on the published test would answer a different question and needs a new protocol.

## Design and analysis

- Generate new databases from a private dataset seed. Preserve the train/dev/test family split. Use all 200 training tasks, 80 balanced development tasks, and 200 balanced test tasks.
- Evaluate base and step-12 SFT for every training seed: 3 × 2 × (80 + 200) = **1,680 task episodes**, before separate setup checks. Each task may need multiple model requests.
- Shuffle tasks and paired arm order using a saved deterministic schedule. Do not infer equal actual compute from equal token/call ceilings.
- Use the original action normalization, tool limits, decoding mode, and verifier.
- Primary outcome: paired final-answer accuracy change, averaged equally across fitted seeds and fixed query families. Report every seed and family, plus all offered-task outcomes.
- Conditional intervals resample original tasks within family/fault cells, using the same resampled IDs across seeds. Report the between-seed range separately. Three seeds do not reliably estimate a population distribution of training seeds.
- Secondary selection policies: always base; always SFT; ordinary development-accuracy selection; and a conservative development gate with a fixed family-regression tolerance. All see the same two candidates and the same development budget. Ties fall back to base.
- Freeze policy selections before any test scoring. The gate's 10-point family tolerance is an engineering rule, not proof of statistical noninferiority.

Fresh examples from public known templates remain a limited repeatability study. An eight-family or real-world benchmark would require an explicit new version, independently checked gold answers, and additional resources.

## Before measured compute

1. Record actual trainer and sampler hardware separately: device model/count, memory, allocation scope, provenance reference, and observation time. Future allocation must not be inferred from the old support ticket.
2. Record base and adapter identity, tokenizer/template hashes, precision, runtime, parallelism, and any undisclosed fields. A serverless hardware name alone does not make shared-service timing controlled.
3. Reconcile the original invoice and outstanding charges. Keep the entire project under $25; the proposed new compute-reservation ceiling is $10, conditional on real remaining headroom and current tariffs.
4. Validate the exact training targets, masks, EOS/turn endings, and adapter-disabled baseline on development-only setup cases. A failed contract check stops execution.
5. Implement and integration-test the native executor for the frozen paired multi-seed schedule. The old `checkpoint-gate run` command performs the historical pilot and does **not** implement this new schedule.
6. Use one durable accounting authority across seeds, retain ambiguous reservations, stop on unknown paid operations, and close all created resources.

The proposed dispatch window is four hours, not a promised completion time. If hardware access, memory fit, cost headroom, contract checks, or execution integration fail, report that failure and retain the frozen plan. Do not reduce the final sample or change the model after viewing test results.

## Execution state

`prepare.py` has generated and hashed private future data, selected training-turn identities, and the evaluation schedule. It makes no model calls and provisions no resources. Those private inputs remain local. Publication of the commitment supplies a timestamped prospective plan; it is not a registration in an external study registry.

The retrospective pilot and SQL replay are the completed experiments in version 1.0. This prospective replication remains pending.
