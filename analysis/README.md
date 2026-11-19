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
