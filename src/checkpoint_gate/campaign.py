from __future__ import annotations

import fcntl
import copy
import platform
import random
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .baseten_backend import LoopsBackend, LoopsSession, policy_datum, preflight, supervised_datum
from .cloud import CloudMirror
from .common import digest, read_json, write_json
from .dataset import load
from .evaluation import paired, summarize
from .ledger import Ledger, StopCampaign
from .rollout import ScriptedOracle, demonstrations, public_result, run
from .verifier import equivalent, parse_action


def validate_config(c: dict):
    if c["scope"] != "serverless":
        raise ValueError("Only serverless is allowed")
    if c.get("action_normalization") != "single_outer_markdown_fence":
        raise ValueError("Freeze the common action normalization rule")
    if c["compute_cap_usd"] <= 0 or c["compute_cap_usd"] + sum(c["other_budget_usd"].values()) > 25:
        raise ValueError("Total planning allocation must be within $25")
    for key in ("rank", "max_seq_len", "max_output_tokens", "sft_steps",
                "sft_batch_size", "rl_steps", "rl_group_size", "rl_max_groups", "max_seconds"):
        if type(c[key]) is not int or c[key] <= 0:
            raise ValueError(f"Invalid {key}")
    if c["max_seconds"] > 14400 or c["max_tool_calls"] != 2:
        raise ValueError("Pilot allows four hours and two tool calls")
    if c["rl_group_size"] < 2 or c["rl_max_groups"] < c["rl_steps"]:
        raise ValueError("Invalid RL group bounds")


@contextmanager
def runner_lock(directory: Path):
    with (directory / "runner.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise StopCampaign("Another runner owns this local campaign") from exc
        yield


def evaluate(tasks, gold, data, backend, config, label, directory):
    rows = []
    for i, task in enumerate(tasks):
        try:
            result = run(task, data, gold[task["id"]]["rows"], backend,
                         rollout_id=f"{label}-{task['id']}",
                         max_output_tokens=config["max_output_tokens"], seed=config["seed"])
            rows.append(public_result(result))
        except BaseException:
            rows.extend({
                "task_id": t["id"], "family": t["family"], "fault": t["fault"],
                "correct": False, "status": "not_run", "tool_calls": 0, "output_tokens": 0,
            } for t in tasks[i:])
            write_json(directory / f"{label}.json", {"complete": False, "rows": rows,
                       "summary": summarize(rows), "label": label})
            raise
    output = {"complete": True, "label": label, "rows": rows, "summary": summarize(rows)}
    write_json(directory / f"{label}.json", output)
    return output


def regression(backend, label: str, directory: Path):
    """Separate 100-case elementary instruction/format suite; not broad capability."""
    rows = []
    for i in range(100):
        expected = [[i * 17 - 13]] if i < 50 else [[f"code-{i:03}"]]
        question = (f"Compute {i} * 17 - 13." if i < 50 else f"Copy this string exactly: code-{i:03}")
        g = backend.generate(
            [{"role": "user", "content": question + ' Reply only as {"answer":[[value]]}.'}],
            max_tokens=64, seed=7, request_id=f"{label}-reg-{i}")
        try:
            correct = equivalent(parse_action(g.text).get("answer"), expected, True)
        except ValueError:
            correct = False
        rows.append({"id": i, "correct": correct, "reply": g.text})
    output = {"n": len(rows), "correct": sum(r["correct"] for r in rows), "rows": rows,
              "limitation": "Elementary arithmetic/copy-format regression only."}
    write_json(directory / f"{label}-regression.json", output)
    return output


def demo(data: Path, output: Path):
    output.mkdir(parents=True, exist_ok=False)
    tasks, gold, manifest = load(data, "test")
    conditions = {}
    for label, recover in (("scripted_no_retry", False), ("scripted_retry", True)):
        rows = [public_result(run(t, data, gold[t["id"]]["rows"],
                                  ScriptedOracle(gold[t["id"]]["sql"], recover=recover),
                                  rollout_id=f"{label}-{t['id']}")) for t in tasks]
        conditions[label] = {"summary": summarize(rows), "rows": rows}
    result = {
        "kind": "infrastructure_self_test", "model_calls": 0, "cloud_spend_usd": 0,
        "warning": "SCRIPTED ORACLES WITH GOLD SQL. These are software checks, not AI performance or training gains.",
        "dataset_sha256": manifest["sha256"], "conditions": conditions,
    }
    write_json(output / "demo.json", result)
    return result


def smoke(data: Path, output: Path, config: dict):
    """Eight dev tasks, base sampler only, no optimizer or dedicated deployment."""
    config = copy.deepcopy(config)
    config["compute_cap_usd"] = min(config["compute_cap_usd"], 0.25)
    config["max_seconds"] = min(config["max_seconds"], 900)
    config["token_caps"] = {"train": 1, "prefill": 50_000, "sample": 10_000}
    validate_config(config)
    tasks, gold, manifest = load(data, "dev")
    tasks = [t for t in tasks if int(t["id"].rsplit("-", 1)[1]) < 2]
    capabilities = preflight(config)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "manifest.json", {"config": config, "dataset_sha256": manifest["sha256"],
                                        "kind": "real_base_model_smoke", "split": "development"})
    write_json(output / "capabilities.json", capabilities)
    with runner_lock(output):
        ledger, session = Ledger(output/"ledger.sqlite", config), None
        status = {"state": "running", "kind": "real_base_model_smoke"}
        try:
            session = LoopsSession(config, ledger, output)
            sampler = session.create_base()
            backend = LoopsBackend(sampler, sampler.get_tokenizer(), ledger, config,
                                   temperature=config["eval_temperature"])
            result = evaluate(tasks, gold, data, backend, config, "dev-smoke", output)
            status.update(state="complete", summary=result["summary"])
            return status
        except BaseException as exc:
            status.update(state="stopped", reason_type=type(exc).__name__, reason=str(exc)[:500])
            raise
        finally:
            if session:
                session.close()
            status["budget"] = ledger.snapshot()
            write_json(output/"status.json", status)


def execute(data: Path, output: Path, config: dict, *, cloud_url: str | None = None):
    validate_config(config)
    tasks, gold, manifest = load(data)
    capabilities = preflight(config)
    output.mkdir(parents=True, exist_ok=False)
    with runner_lock(output):
        frozen = {"config": config, "dataset_sha256": manifest["sha256"], "version": __version__,
                  "python": platform.python_version(), "platform": platform.platform(),
                  "design": "Single training seed; final checkpoints prespecified. No test-based selection."}
        write_json(output / "manifest.json", frozen)
        write_json(output / "capabilities.json", capabilities)
        mirror = CloudMirror(cloud_url, output.name, uuid.uuid4().hex, frozen) if cloud_url else None
        ledger = Ledger(output / "ledger.sqlite", config)
        service = None
        status = {"state": "running", "paid_run": True}
        try:
            service = LoopsSession(config, ledger, output, guard=mirror.guard if mirror else lambda: None)
            tokenizer = service.create_trainer()
            write_json(output / "tokenizer.json", {
                "name_or_path": tokenizer.name_or_path,
                "commit_hash": tokenizer.init_kwargs.get("_commit_hash"),
                "chat_template_sha256": digest(tokenizer.chat_template),
                "base_weights_note": "Provider model ID recorded; immutable base weight digest is not exposed here.",
            })
            base = service.create_base()
            guard = mirror.guard if mirror else lambda: None
            backend = lambda sampler, temp: LoopsBackend(sampler, tokenizer, ledger, config,
                                                         temperature=temp, guard=guard)
            train = [t for t in tasks if t["split"] == "train"]
            dev = [t for t in tasks if t["split"] == "dev"]
            test = [t for t in tasks if t["split"] == "test"]
            # Fixed dev calibration slice, one clean and one error task per family.
            calibration = [t for t in dev if int(t["id"].rsplit("-", 1)[1]) < 2]
            calibration_result = evaluate(calibration, gold, data, backend(base, 0), config, "dev-base", output)
            if calibration_result["summary"]["accuracy"] >= 0.95:
                raise StopCampaign("Dev ceiling gate: redesign task difficulty before spending on training")
            pairs = [pair for t in train for pair in demonstrations(t, data, gold[t["id"]])]
            rng = random.Random(config["seed"])
            rng.shuffle(pairs)
            prepared = [supervised_datum(tokenizer, m, a, config["max_seq_len"]) for m, a in pairs]
            if config["sft_steps"] * config["sft_batch_size"] > len(prepared):
                raise StopCampaign("Not enough distinct demonstrations for this pilot; reduce SFT steps")
            training = []
            for step in range(config["sft_steps"]):
                batch = prepared[step*config["sft_batch_size"]:(step+1)*config["sft_batch_size"]]
                loss = service.update([b[0] for b in batch], sum(b[1] for b in batch),
                                      f"sft-{step}", lr=config["sft_learning_rate"])
                training.append({"stage": "sft", "step": step+1, "loss": loss})
                write_json(output / "training.json", training)
            sft, sft_receipt = service.checkpoint("sft-final", parent=None)
            if mirror:
                mirror.publish("checkpoint-sft", sft_receipt)
            current, completed = sft, 0
            for group in range(config["rl_max_groups"]):
                if completed >= config["rl_steps"]:
                    break
                task = rng.choice(train)
                rollouts = [
                    run(task, data, gold[task["id"]]["rows"], backend(current, config["rl_temperature"]),
                        rollout_id=f"rl-g{group}-s{sample}", seed=config["seed"]+group*100+sample*10,
                        max_output_tokens=config["max_output_tokens"])
                    for sample in range(config["rl_group_size"])
                ]
                rewards = [r["reward"] for r in rollouts]
                mean = sum(rewards)/len(rewards)
                write_json(output / f"rl-group-{group}.json", [public_result(r) for r in rollouts])
                write_json(output / f"rl-token-data-{group}.json", [
                    {"rollout_id": r["rollout_id"], "reward": r["reward"],
                     "checkpoint": current.checkpoint_path,
                     "generations": [asdict(g) for g in r["generations"]]}
                    for r in rollouts
                ])
                if max(rewards) == min(rewards):
                    training.append({"stage": "rl", "group": group, "skipped": "equal_rewards", "mean_reward": mean})
                    write_json(output / "training.json", training)
                    continue
                datums = [policy_datum(g, r["reward"]-mean, config["max_seq_len"])
                          for r in rollouts for g in r["generations"]]
                service.update([d[0] for d in datums], sum(d[1] for d in datums),
                               f"rl-{completed}", loss="cispo", lr=config["rl_learning_rate"])
                completed += 1
                previous = current
                current, receipt = service.checkpoint(f"rl-{completed}", parent=current.checkpoint_path)
                if previous is not sft:
                    previous.close()
                training.append({"stage": "rl", "step": completed, "mean_reward": mean,
                                 "checkpoint": receipt})
                write_json(output / "training.json", training)
            if completed == 0:
                status["rl_note"] = "No informative reward group; no RL improvement can be claimed."
            conditions = [("base", base), ("sft", sft)]
            if completed:
                conditions.append(("sft_rl", current))
            # Frozen order is randomized once; record it. No test-time checkpoint selection.
            rng.shuffle(conditions)
            write_json(output / "evaluation_order.json", [label for label, _ in conditions])
            results, regressions = {}, {}
            for label, sampler in conditions:
                results[label] = evaluate(test, gold, data, backend(sampler, config["eval_temperature"]),
                                          config, label, output)
                regressions[label] = regression(backend(sampler, config["eval_temperature"]), label, output)
                if mirror:
                    mirror.publish(f"evaluation-{label}", results[label])
            comparisons = {label: paired(results["base"]["rows"], result["rows"])
                           for label, result in results.items() if label != "base"}
            summary = {
                "kind": "baseten_experiment", "complete": True,
                "conditions": {label: r["summary"] for label, r in results.items()},
                "paired_vs_base": comparisons,
                "regression": {label: {"n": r["n"], "correct": r["correct"]} for label, r in regressions.items()},
                "rl_updates": completed, "single_seed": True,
                "budget": ledger.snapshot(),
            }
            write_json(output / "results.json", summary)
            if mirror:
                mirror.publish("results", summary)
            status["state"] = "complete"
            return summary
        except BaseException as exc:
            status.update(state="stopped", reason_type=type(exc).__name__, reason=str(exc)[:500])
            raise
        finally:
            if service:
                service.close()
            status["budget"] = ledger.snapshot()
            write_json(output / "status.json", status)
