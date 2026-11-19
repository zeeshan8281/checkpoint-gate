# CheckpointGate

A verifier-driven SQL agent experiment with Baseten Loops and a Cloudflare evidence layer.

**Status: working local research build. No real model training results yet.** The bundled dashboard replays scripted infrastructure checks that deliberately use reference SQL. Baseten account capability, cloud deployment, training quality, and actual billing remain unverified.

The research question: **does supervised fine-tuning followed by deterministic reward training improve completion on unfamiliar SQL query families, within the same tool and token budget?**

## What is implemented

- 600 reproducible synthetic tasks: 200 training, 200 development, 200 held-out tests. Query construction families and schema vocabulary are disjoint across splits.
- A read-only SQLite tool with authorizer restrictions, a function allowlist, execution limits, and bounded results.
- Multi-turn SQL rollouts, deterministic result verification, transient fault injection, and training demonstrations.
- Native `baseten-loops==0.36.0` integration for SFT, group-centered `cispo` reward updates, saved optimizer state, and checkpoint-pinned sampling.
- Pre-dispatch token/dollar reservations in a durable SQLite ledger. A timeout or ambiguous operation retains its reservation and stops the campaign.
- Cloudflare Durable Object leases with fencing tokens, immutable receipts, and content-addressed evidence in R2.
- Paired test comparisons, task-level confidence intervals, a separate 100-case elementary format/arithmetic regression suite, and a trace replay UI.
- Tests that cover adversarial SQL, ambiguous remote outcomes, concurrency, SDK data contracts, the complete controller with a fake service, and the actual local Cloudflare runtime.

This is a synthetic pilot, not a validated general SQL benchmark or evidence of a novel training algorithm.

## Run locally without accounts

Python 3.12+:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m unittest discover -s tests -v

checkpoint-gate generate --out data/pilot --per-family 50
checkpoint-gate demo --data data/pilot --out runs/local-demo
cp runs/local-demo/demo.json web/demo.json
python -m http.server 8080 --bind 127.0.0.1 --directory web
```

Open [the local dashboard](http://localhost:8080). The committed demo was generated with these commands. A dataset directory cannot be overwritten; its manifest hashes every database and the task/gold files.

The scripted no-retry agent passes the 100 clean test cases and fails the 100 injected-error cases. The scripted retry agent passes all 200. These expected results validate fault plumbing and scoring. **They are not model performance.**

## Baseten setup and read-only check

1. Use a Baseten workspace with Loops access. A regular dashboard account alone does not establish serverless Loops entitlement.
2. Create an appropriate workspace API key in [Baseten API keys](https://app.baseten.co/settings/api_keys). Keep it out of source control and chat.
3. Set `BASETEN_API_KEY` in the shell that will run the experiment. Install the audited SDK:

```bash
pip install -e '.[baseten]'
checkpoint-gate preflight --config configs/pilot.json --out runs/capabilities.json
```

`preflight` performs one authenticated GET to `/v1/loops/capabilities`. It does not create an SDK session, trainer, sampler, or deployment. It requires `enabled=true`, `serverless=true`, and sufficient enabled sequence length. Rank validation happens on creation; the explicit serverless scope prevents dedicated fallback.

Model: **Qwen/Qwen3.6-35B-A3B, 35B total / 3B active**, rank-8 LoRA. Baseten hosts the heavy forward/backward and sampling work. This Mac handles the verifier, data, coordination, and analysis.

## Execute the paid pilot

Review the rates in `configs/pilot.json` against current account pricing first.

```bash
checkpoint-gate run \
  --config configs/pilot.json \
  --data data/pilot \
  --out runs/pilot-seed7 \
  --execute-paid-run
```

The command checks access before creating the output directory. It then runs an eight-task dev calibration, SFT, bounded reward groups, and a frozen held-out evaluation of the base and final checkpoints. A near-ceiling dev baseline stops the run before training. If no reward group has differing scores, it reports that no RL update occurred and evaluates only base/SFT.

There is no automatic restart of a stopped paid campaign. Existing output directories are refused. Do not work around a stop by picking a new directory: inspect reservations and reconcile remote operations first. Saved `weights/` checkpoints contain optimizer state and can be restored through Baseten's documented `load_state_with_optimizer`; implementing an audited automatic resume controller is follow-up work.

No dedicated inference endpoint is created. Cleanup deactivates runs and standalone samplers created in this session. Check `shutdown.json`; a failed deactivation is reported rather than treated as confirmed.

### Budget

| Allocation | Ceiling |
| --- | ---: |
| Compute reservations | $10 |
| Optional Cloudflare plan | $5 |
| Contingency | $4 |
| Tax/FX buffer | $4 |
| Total planning allocation | **$23** |

Additional ceilings: 4M training tokens, 1M uncached-prefill tokens, 1M sampled tokens, and a four-hour dispatch window. In-flight requests and cleanup can extend beyond the dispatch window. Each request has its own timeout.

Rates are the inspected 19 November 2026 promotional rates multiplied by 1.25 as a planning margin, **not a quote or billing guarantee**. The ledger counts full training sequences, full prompts, and the maximum possible generated tokens. Successful reservations stay consumed; unused generation allowance is not recycled. Pricing changes, taxes, unrelated account use, and metering discrepancies must be reconciled against the provider invoice. Baseten dashboard budgets do not enforce training spending.

The local ledger is the only spending authority. Do not run copies of the campaign from multiple machines or delete its ledger. Cloudflare leases coordinate evidence ownership; they do not create globally exactly-once model execution or a global billing cap.

## Cloudflare control layer

Node 22+:

```bash
cd worker
npm ci
npm test
npm run check
```

For local integration, put a **local-only** secret of at least 24 characters in `worker/.dev.vars`:

```text
CONTROL_TOKEN=your-local-test-secret-at-least-24-characters
```

Then:

```bash
npm run dev
# In another terminal, set CHECKPOINT_GATE_TOKEN to the same local secret:
node test/integration.mjs
```

This tests the real local workerd runtime, SQLite Durable Objects, and R2 emulation. It does not require a Cloudflare account.

For a cloud deployment, authenticate Wrangler, create the R2 bucket named in `wrangler.toml`, set `CONTROL_TOKEN` with `wrangler secret put CONTROL_TOKEN`, and deploy. These are explicit setup steps; the Python runner never provisions Cloudflare resources.

The public site is the static scripted demo. All `/api/` routes require the secret. Private campaign results are not automatically published into the public site.

To mirror a paid run:

```bash
checkpoint-gate run --data data/pilot --out runs/pilot-seed7 \
  --config configs/pilot.json --cloud-url https://YOUR-WORKER.workers.dev \
  --execute-paid-run
```

Set `CHECKPOINT_GATE_TOKEN` to the deployed Worker secret. The runner renews its lease before remote operations; evidence writes verify the fencing token both before upload and at receipt commit.

API routes:

| Method / path suffix | Behavior |
| --- | --- |
| `POST /api/campaigns/:id/init` | Freeze a campaign manifest; reject conflicting reinitialization |
| `POST /api/campaigns/:id/lease` | Acquire or renew a 10-minute lease |
| `POST /api/campaigns/:id/receipt` | Validate SHA-256, store in R2, commit immutable receipt |
| `GET /api/campaigns/:id/status` | Return manifest, lease, and evidence references |

Evidence can be retrieved with the authenticated R2 tooling using the returned object key. There is no public results download endpoint.

## Source map

| Module | Responsibility |
| --- | --- |
| `dataset.py` | Frozen tasks, database generation, gold separation |
| `verifier.py` | Restricted SQLite execution, strict actions, semantic rows |
| `rollout.py` | Tool protocol, demonstrations, bounded multi-turn execution |
| `ledger.py` | Reservation state machine and limits |
| `baseten_backend.py` | Native SDK operations and operation/checkpoint receipts |
| `campaign.py` | Calibration, SFT, reward groups, evaluation, cleanup |
| `evaluation.py` | Primary metrics and paired uncertainty |
| `cloud.py` / `worker/` | Leases and evidence mirroring |
| `web/` | Scripted trace replay |

See [PROTOCOL.md](PROTOCOL.md) for interpretation limits, [SOURCES.md](SOURCES.md) for implementation references, and [evidence/VALIDATION.json](evidence/VALIDATION.json) for what was actually tested.
