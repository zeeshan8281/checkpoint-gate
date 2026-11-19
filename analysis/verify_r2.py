"""Read every archived evidence object from remote R2 and compare exact bytes.

Requires Wrangler to be authenticated. This reads objects without making the
bucket public. Downloads are retained in --download-dir for inspection.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--wrangler", required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    archive = json.loads(args.publication.read_text())
    bucket = archive["bucket"]
    if not re.fullmatch(r"[a-z0-9-]{3,63}", bucket):
        raise SystemExit("Invalid bucket")
    for entry in archive["files"]:
        if Path(entry["path"]).name != entry["path"]:
            raise SystemExit("Evidence path must be a plain filename")
        if not re.fullmatch(r"sha256/[0-9a-f]{64}\.json", entry["receipt"]["key"]):
            raise SystemExit("Invalid object key")
    if args.download_dir.resolve().is_relative_to(args.evidence.resolve()):
        raise SystemExit("Download outside the source evidence directory")
    args.download_dir.mkdir(parents=True, exist_ok=True)

    def verify(entry):
        receipt = entry["receipt"]
        output = args.download_dir / (receipt["sha256"] + ".json")
        result = subprocess.run(
            [args.wrangler, "r2", "object", "get", bucket + "/" + receipt["key"],
             "--remote", "--file", str(output)],
            capture_output=True, text=True, timeout=90,
        )
        if result.returncode:
            raise RuntimeError(f"R2 read failed for {entry['path']}; Wrangler exit {result.returncode}")
        data = output.read_bytes()
        if sha(data) != receipt["sha256"]:
            raise RuntimeError(f"Envelope digest mismatch: {entry['path']}")
        envelope = json.loads(data)
        raw = envelope["text"].encode("utf-8")
        local = (args.evidence / entry["path"]).read_bytes()
        if (envelope["path"] != entry["path"] or raw != local
                or sha(raw) != entry["content_sha256"] or len(raw) != entry["bytes"]):
            raise RuntimeError(f"Source bytes mismatch: {entry['path']}")
        return {"path": entry["path"], "content_sha256": sha(raw),
                "object_sha256": sha(data), "bytes": len(raw), "verified": True}

    verified = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for record in pool.map(verify, archive["files"]):
            verified.append(record)
            print(f"Read back {len(verified)}/{len(archive['files'])}: {record['path']}", flush=True)
    report = {
        "campaign": archive["campaign"], "bucket": bucket, "remote": True,
        "files_verified": len(verified),
        "source_bytes": sum(item["bytes"] for item in verified),
        "exact_byte_match": True,
        "publication_sha256": sha(args.publication.read_bytes()),
        "files": verified,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Every remote object matches; receipt: {args.out}")


if __name__ == "__main__":
    main()
