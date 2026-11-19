# Analyze a completed pilot

These scripts make no model calls. The exporter requires a completed experiment,
completed cleanup, and no pending or unknown ledger operations. It copies only
an explicit evidence allowlist and verifies trace counts and dataset identity.

From the repository root:

```bash
python analysis/status.py runs/pilot-seed7

pip install -r analysis/requirements.txt

python analysis/export_results.py runs/pilot-seed7 \
  --data data/pilot \
  --evidence evidence/pilot-seed7 \
  --web web

python analysis/summarize_results.py runs/pilot-seed7 \
  --out evidence/pilot-seed7

python analysis/plot_results.py runs/pilot-seed7/results.json \
  --out web/heldout-results.png

python -m http.server 8080 --bind 127.0.0.1 --directory web
```

`status.py` opens SQLite read-only and can inspect an active campaign. Do not
construct `Ledger` just to inspect a live run: its startup recovery marks
pending operations unknown. A started task is not necessarily completed.

Open `http://localhost:8080/`. `self-test.html` remains a
separately labelled scripted infrastructure self-test. The main page reads
real completed results and all held-out model/tool traces from `pilot.json`.

The graph uses Wilson intervals over task instances. The paired comparison
comes from the frozen experiment's bootstrap results. Neither estimates
variation across new query families or training seeds.

Keep credentials, signed download URLs, private account screenshots, and
environment files out of the evidence directory. Verify remote resources are
inactive after cleanup; successful local cleanup calls alone do not establish
their final remote state.

## Archive completed evidence in R2

After deploying the full Worker, set `CHECKPOINT_GATE_TOKEN` securely in the
environment to the deployed `CONTROL_TOKEN`. Pass the sanitized public export,
not the raw run directory:

```bash
python analysis/publish_evidence.py \
  --evidence evidence/pilot-seed7 \
  --url https://YOUR-WORKER.workers.dev \
  --campaign pilot-seed7-post-run-v1 \
  --out evidence/cloudflare-archive.json

# Authenticate Wrangler to the same account before the independent readback.
python analysis/verify_r2.py \
  --publication evidence/cloudflare-archive.json \
  --evidence evidence/pilot-seed7 \
  --wrangler worker/node_modules/.bin/wrangler \
  --download-dir runs/r2-readback \
  --out evidence/cloudflare-readback.json
```

Each source file is stored in a JSON envelope with its original text, filename,
byte count, and SHA-256. Receipts address the envelope by its own SHA-256.
The second command downloads every object from remote R2 and checks both the
envelope hash and the original file's exact bytes. The upload receipt records
that readback was not yet checked; the separate readback report establishes it.
Both scripts make zero model calls. The frozen archive manifest explicitly says
the upload occurred after training and did not coordinate the original compute.

If an upload stops, keep its campaign identity and unchanged source files.
A fresh invocation can reacquire the lease after its ten-minute expiry and
repeat identical receipt uploads safely. Conflicting file contents require a
new campaign identity. Do not edit evidence to force a conflicting archive
through an existing identity.
