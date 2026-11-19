"""Archive completed, already-public evidence through a deployed Worker.

No training calls. Uploads are explicitly post-run, not evidence that Cloudflare
coordinated the experiment. Use only the sanitized export, never a raw run folder.
CHECKPOINT_GATE_TOKEN is read from the environment and never written to receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
import uuid


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    parsed = urllib.parse.urlparse(args.url)
    if parsed.scheme != "https" or parsed.username or parsed.query or parsed.fragment:
        raise SystemExit("Use a credential-free HTTPS Worker URL")
    if not args.campaign or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in args.campaign):
        raise SystemExit("Invalid campaign name")
    token = os.environ["CHECKPOINT_GATE_TOKEN"]
    if args.out.resolve().is_relative_to(args.evidence.resolve()):
        raise SystemExit("Write the publication receipt outside the uploaded directory")
    required = ["results.json", "shutdown-verified.json", "ACCOUNTING.json", "source-provenance.json"]
    if not all((args.evidence / name).is_file() for name in required):
        raise SystemExit("A completed, sanitized evidence export is required")
    files, envelopes = [], []
    for path in sorted(args.evidence.iterdir()):
        if not path.is_file() or path.is_symlink() or path.suffix not in (".json", ".md"):
            raise SystemExit(f"Unexpected evidence path: {path.name}")
        raw = path.read_bytes()
        if token.encode() in raw:
            raise SystemExit("Credential found in evidence")
        item = {"path": path.name, "content_sha256": digest(raw), "bytes": len(raw)}
        data = encode({**item, "encoding": "utf-8", "text": raw.decode("utf-8")})
        if len(encode({"data": data}).encode()) > 1_900_000:
            raise SystemExit(f"Evidence too large for one receipt: {path.name}")
        files.append(item)
        envelopes.append(data)
    manifest = {
        "schema": "checkpoint-gate-post-run-archive-v1",
        "purpose": "Archive already-public completed pilot evidence",
        "upload_timing": "after training and evaluation completed",
        "coordinated_original_compute": False,
        "source": json.loads((args.evidence / "source-provenance.json").read_text()),
        "files": files,
    }
    if len(encode(manifest).encode()) > 31_000:
        raise SystemExit("Archive manifest exceeds Worker limit")
    base = args.url.rstrip("/") + "/api/campaigns/" + args.campaign

    def call(action, payload=None):
        request = urllib.request.Request(
            base + "/" + action,
            data=None if payload is None else encode(payload).encode(),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                     "User-Agent": "CheckpointGate/0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            # Do not print request headers or credential-bearing objects.
            raise SystemExit(f"Worker {action} failed: HTTP {error.code}") from None

    initialized = call("init", {"manifest": manifest})
    owner = "post-run-" + uuid.uuid4().hex
    lease = call("lease", {"owner": owner})
    records = []
    for index, (item, data) in enumerate(zip(files, envelopes)):
        lease = call("lease", {"owner": owner, "fence": lease["fence"]})
        name = f"file-{index:03d}"
        sha = digest(data.encode())
        receipt = call("receipt", {"owner": owner, "fence": lease["fence"],
                                  "name": name, "sha256": sha, "data": data})
        if receipt["sha256"] != sha:
            raise SystemExit("Receipt digest differs from uploaded envelope")
        records.append({**item, "receipt_name": name, "receipt": receipt})
        print(f"Archived {index + 1}/{len(files)}: {item['path']}", flush=True)
    state = call("status")
    for record in records:
        actual = state["receipts"]["receipt:" + record["receipt_name"]]
        if actual["sha256"] != record["receipt"]["sha256"]:
            raise SystemExit("Final Durable Object receipt mismatch")
    result = {
        "schema": "checkpoint-gate-post-run-publication-v1",
        "url": args.url,
        "campaign": args.campaign,
        "bucket": "checkpoint-gate-evidence",
        "upload_timing": "after training and evaluation completed",
        "coordinated_original_compute": False,
        "manifest_hash": initialized["manifestHash"],
        "files": records,
        "source_bytes": sum(item["bytes"] for item in files),
        "receipts_verified": True,
        "r2_readback_verified": False,
        "note": "Receipt verification checks Durable Object state; independently read R2 objects to verify storage bytes.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Verified {len(records)} committed receipts; saved {args.out}")


if __name__ == "__main__":
    main()
