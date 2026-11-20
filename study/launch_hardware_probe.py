"""Submit one bounded Baseten Training Job; never starts model training.

Requires BASETEN_API_KEY in the environment. Records every creation response.
Does not retry a job creation request after an ambiguous network failure.
The in-container command has a 90-second timeout; the local controller requests
termination after ten minutes including provisioning. Remote API availability
is required for the latter and is not a provider-side dollar spending limit.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shlex
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


TERMINAL = {"TRAINING_JOB_COMPLETED", "TRAINING_JOB_FAILED", "TRAINING_JOB_STOPPED",
            "TRAINING_JOB_CANCELED", "TRAINING_JOB_CANCELLED",
            "TRAINING_JOB_DEPLOYMENT_FAILED"}


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def request(method, path, body=None):
    key = os.environ["BASETEN_API_KEY"]
    req = urllib.request.Request(
        "https://api.baseten.co" + path,
        method=method, data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": "Api-Key " + key, "Content-Type": "application/json",
                 "User-Agent": "CheckpointGate-HardwarePreflight/1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return {"http_status": response.status, "body": json.load(response)}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode().replace(key, "[REDACTED]")
        try:
            data = json.loads(text)
        except ValueError:
            data = {"error": text}
        return {"http_status": exc.code, "body": data}


def make_payload():
    source = Path(__file__).with_name("hardware_probe.py").read_bytes()
    encoded = base64.b64encode(source).decode()
    code = f"import base64; exec(compile(base64.b64decode({encoded!r}), 'hardware_probe.py', 'exec'))"
    return {
        "training_job": {
            "name": "checkpoint-gate-hardware-probe-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "image": {"base_image": "pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime"},
            "compute": {"node_count": 1, "cpu_count": 2, "memory": "16Gi",
                        "accelerator": {"accelerator": "H100", "count": 1},
                        "availability_model": "standard"},
            "runtime": {
                "start_commands": ["timeout --signal=TERM --kill-after=10s 90s python -c " + shlex.quote(code)],
                "environment_variables": {},
                "cache_config": {"enabled": False},
                "checkpointing_config": {"enabled": False},
            },
            "interactive_session": None,
        },
    }, hashlib.sha256(source).hexdigest()


def launch(directory):
    directory.mkdir(parents=True, exist_ok=False)
    payload, source_hash = make_payload()
    write(directory / "request.json", payload)
    write(directory / "plan.json", {
        "kind": "infrastructure_preflight_not_model_experiment",
        "observed_baseten_usage_usd": 0.29,
        "observed_usage_note": "Rounded dashboard usage on 20 November 2026; no invoice issued.",
        "new_compute_envelope_usd": 10, "probe_planning_reservation_usd": 2,
        "catalog_h100_per_minute_usd": 0.10833,
        "price_reference": "https://www.baseten.co/pricing/",
        "requested_gpu": "H100", "requested_gpu_count": 1,
        "device_identity_status": "unverified_until_job_runs",
        "model_downloads": 0, "training_updates": 0,
        "container_timeout_seconds": 90, "controller_stop_after_seconds": 600,
        "probe_source_sha256": source_hash,
    })
    project = request("POST", "/v1/training_projects", {
        "training_project": {"name": "checkpoint-gate-hardware-audit", "project_accelerator": "H100"}})
    write(directory / "project-response.json", project)
    if project["http_status"] != 200:
        write(directory / "status.json", {"state": "project_creation_rejected", **project})
        print(json.dumps({"state": "project_creation_rejected", **project}), flush=True)
        return
    project_id = project["body"]["training_project"]["id"]
    started = time.monotonic()
    try:
        response = request("POST", f"/v1/training_projects/{project_id}/jobs", payload)
    except Exception as exc:
        write(directory / "status.json", {"state": "creation_ambiguous_do_not_retry",
              "project_id": project_id, "job_name": payload["training_job"]["name"],
              "error_type": type(exc).__name__})
        raise
    write(directory / "job-response.json", response)
    if response["http_status"] != 200:
        write(directory / "status.json", {"state": "job_creation_rejected", "project_id": project_id, **response})
        print(json.dumps({"state": "job_creation_rejected", **response}), flush=True)
        return
    job_id = response["body"]["training_job"]["id"]
    path = f"/v1/training_projects/{project_id}/jobs/{job_id}"
    write(directory / "identity.json", {"project_id": project_id, "job_id": job_id})
    print(json.dumps({"state": "submitted", "project_id": project_id, "job_id": job_id}), flush=True)
    previous = None
    terminal = False
    try:
        while time.monotonic() - started < 600:
            current = request("GET", path)
            write(directory / "job-latest.json", current)
            if current["http_status"] != 200:
                raise RuntimeError("Cannot observe the job; request shutdown")
            job = current["body"]["training_job"]
            state = job["current_status"]
            if state != previous:
                print(json.dumps({"state": state, "instance_type": job.get("instance_type"),
                                  "error_message": job.get("error_message")}), flush=True)
                previous = state
            instance = job.get("instance_type") or {}
            if instance and (instance.get("gpu_type") != "H100" or instance.get("gpu_count") != 1):
                raise RuntimeError("Provider allocation does not match the requested one H100")
            if state in TERMINAL:
                terminal = True
                break
            time.sleep(10)
    finally:
        if not terminal:
            result = request("POST", path + "/stop", {})
            write(directory / "stop-response.json", result)
            print(json.dumps({"state": "stop_requested", "http_status": result["http_status"]}), flush=True)
        logs = request("GET", path + "/logs?limit=1000&direction=asc")
        write(directory / "logs.json", logs)
        last = request("GET", path)
        write(directory / "job-final.json", last)
        write(directory / "status.json", {
            "state": "terminal" if terminal else "shutdown_requested_verify_remote_status",
            "project_id": project_id, "job_id": job_id,
            "remote_response": last, "training_updates": 0,
        })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--submit", action="store_true", help="Actually submit the billable hardware probe")
    args = parser.parse_args()
    if args.submit:
        launch(args.out)
    else:
        payload, source_hash = make_payload()
        args.out.mkdir(parents=True, exist_ok=False)
        write(args.out / "request.json", payload)
        print(json.dumps({"state": "prepared_not_submitted", "source_sha256": source_hash}))
