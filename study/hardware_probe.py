"""Record and verify the actual CUDA device before any model work.

This probe performs one small CUDA operation. It does not download a model,
train an adapter, or establish the hardware used by a different allocation.
"""
from __future__ import annotations

import csv
import importlib.metadata
import io
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def validate(record):
    """Fail closed on unknown, partitioned, or unexpected hardware."""
    devices = record.get("devices", [])
    if len(devices) != 1:
        raise ValueError("Expected exactly one physical GPU")
    device = devices[0]
    if "H100" not in device.get("name", "") or "MIG" in device["name"]:
        raise ValueError("Expected an NVIDIA H100, not a MIG slice")
    if device.get("memory_mib", 0) < 78 * 1024:
        raise ValueError("Expected at least 78 GiB of device memory")
    if not device.get("uuid") or not device.get("driver_version"):
        raise ValueError("Missing device identity or driver version")
    if device.get("mig_mode") != "Disabled":
        raise ValueError("MIG state is unknown or enabled")
    runtime = record.get("runtime", {})
    if runtime.get("torch_device_count") != 1:
        raise ValueError("PyTorch does not see exactly one GPU")
    if runtime.get("torch_device_name") != device["name"]:
        raise ValueError("PyTorch and nvidia-smi disagree on the GPU")
    if not runtime.get("cuda") or not runtime.get("torch"):
        raise ValueError("Missing CUDA or PyTorch version")
    if record.get("cuda_smoke_passed") is not True:
        raise ValueError("CUDA operation did not pass")


def collect():
    import torch

    query = [
        "nvidia-smi",
        "--query-gpu=index,name,uuid,memory.total,driver_version,mig.mode.current",
        "--format=csv,noheader,nounits",
    ]
    raw = subprocess.run(query, check=True, text=True, capture_output=True, timeout=15).stdout
    devices = []
    for row in csv.reader(io.StringIO(raw), skipinitialspace=True):
        index, name, uuid, memory, driver, mig = [v.strip() for v in row]
        devices.append({
            "index": int(index), "name": name, "uuid": uuid,
            "memory_mib": int(memory), "driver_version": driver, "mig_mode": mig,
        })
    record = {
        "kind": "hardware_preflight", "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider": "Baseten", "allocation_scope": "training_job",
        "devices": devices, "nvidia_smi_raw": raw,
        "runtime": {
            "python": platform.python_version(), "platform": platform.platform(),
            "torch": torch.__version__, "cuda": torch.version.cuda,
            "cudnn": torch.backends.cudnn.version(),
            "torch_device_count": torch.cuda.device_count(),
            "torch_device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        },
        "provider_environment": {k: os.environ[k] for k in
                                 ("BT_TRAINING_JOB_ID", "BT_NUM_GPUS", "BT_GROUP_SIZE", "BT_NODE_RANK")
                                 if k in os.environ},
        "installed_packages": {},
        "model_calls": 0, "training_updates": 0,
        "scope_note": "Only this allocation; repeat this check inside every measured job.",
    }
    for package in ("transformers", "peft", "numpy", "triton"):
        try:
            record["installed_packages"][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            record["installed_packages"][package] = None
    record["cuda_smoke_passed"] = False
    if torch.cuda.is_available():
        x = torch.eye(16, device="cuda", dtype=torch.float32)
        record["cuda_smoke_passed"] = bool(torch.equal(x @ x, x))
        torch.cuda.synchronize()
    return record


def main():
    try:
        record = collect()
        validate(record)
        record["status"] = "verified"
    except Exception as exc:
        record = locals().get("record", {"kind": "hardware_preflight"})
        record.update(status="rejected", error_type=type(exc).__name__, error=str(exc))
    destination = Path(os.environ.get("BT_CHECKPOINT_DIR", "/tmp"))
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "hardware.json").write_text(json.dumps(record, indent=2) + "\n")
    print("CHECKPOINT_GATE_HARDWARE=" + json.dumps(record, separators=(",", ":")), flush=True)
    return 0 if record["status"] == "verified" else 1


if __name__ == "__main__":
    sys.exit(main())
