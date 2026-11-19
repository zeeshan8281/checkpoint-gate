"""Freeze private prospective inputs and an evaluation schedule; never calls a model."""
import argparse
import json
import random
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from checkpoint_gate.common import digest, file_hash, write_json
from checkpoint_gate.dataset import generate, load
from checkpoint_gate.rollout import demonstrations


def prepare(protocol_path, destination):
    if destination.exists():
        raise FileExistsError("Refusing to replace a frozen prospective bundle")
    protocol = json.loads(protocol_path.read_text())
    if protocol["status"] != "planned_not_executed":
        raise ValueError("Unexpected protocol state")
    destination.mkdir(parents=True, mode=0o700)
    data = destination / "data"
    dataset = generate(data, seed=secrets.randbelow(2**31))
    tasks, gold, _ = load(data)
    dev = [t for t in tasks if t["split"] == "dev"
           and int(t["id"].rsplit("-", 1)[1]) < 20]
    test = [t for t in tasks if t["split"] == "test"]
    train = [t for t in tasks if t["split"] == "train"]
    if [len(train), len(dev), len(test)] != [
        protocol["training_tasks"], protocol["development_tasks"], protocol["test_tasks"]
    ]:
        raise ValueError("Generated task counts disagree with frozen protocol")
    # Capture conditional demonstration identities, retaining each full prefix.
    turns = []
    for task in train:
        for turn, (messages, target) in enumerate(demonstrations(task, data, gold[task["id"]])):
            turns.append({"task_id": task["id"], "turn": turn,
                          "messages_sha256": digest(messages), "target_sha256": digest(target)})
    training = {}
    schedule = []
    for seed in protocol["training_seeds"]:
        rng = random.Random(seed)
        shuffled = list(turns)
        rng.shuffle(shuffled)
        training[str(seed)] = shuffled[:protocol["sft_updates"] * protocol["sft_batch_size"]]
        for phase, cases in [("development", dev), ("test", test)]:
            shuffled_cases = list(cases)
            rng.shuffle(shuffled_cases)
            for task in shuffled_cases:
                conditions = list(protocol["conditions"])
                rng.shuffle(conditions)
                for arm in conditions:
                    schedule.append({"seed": seed, "phase": phase, "task_id": task["id"],
                                     "arm": arm, "family": task["family"], "fault": task["fault"]})
    write_json(destination / "training-turns.json", training)
    write_json(destination / "evaluation-schedule.json", schedule)
    code = {str(p.relative_to(REPO)): file_hash(p)
            for p in sorted((REPO / "src/checkpoint_gate").glob("*.py"))}
    code["study/prepare.py"] = file_hash(Path(__file__))
    record = {
        "kind": "prospective_input_commitment", "status": "inputs_frozen_no_model_calls",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "protocol_sha256": file_hash(protocol_path),
        "dataset_sha256": dataset["sha256"],
        "training_turns_sha256": file_hash(destination / "training-turns.json"),
        "schedule_sha256": file_hash(destination / "evaluation-schedule.json"),
        "code_sha256": code, "training_seeds": protocol["training_seeds"],
        "planned_episodes": len(schedule), "new_model_calls": 0,
        "registry_preregistration": False,
        "test_inputs_public": False,
        "claims": "Fresh instances of existing known families. This commitment does not establish completed execution.",
        "execution_blockers": [
            "Trainer and sampler hardware provenance not yet verified for a new allocation.",
            "Prior invoice reconciliation and current all-in budget headroom not confirmed.",
            "Native execution adapter for this paired multi-seed schedule requires implementation and integration tests; the old pilot command does not implement this protocol."
        ],
    }
    write_json(destination / "commitment.json", record)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=Path(__file__).with_name("protocol.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.protocol, args.out)
    print(json.dumps(result, indent=2))
