"""Native Baseten Loops 0.36.0 adapter. Imports are optional for offline use."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from .common import digest, write_json
from .ledger import Ledger, StopCampaign
from .rollout import Generation

API = "https://api.baseten.co"


def preflight(config: dict) -> dict:
    """A GET only: does not construct ServiceClient or provision anything."""
    key = os.environ.get("BASETEN_API_KEY")
    if not key:
        raise StopCampaign("Set BASETEN_API_KEY locally, then run preflight. No cloud work started.")
    params = urllib.parse.urlencode({"model": config["model"], "use_case": "rl",
                                     "max_seq_len": config["max_seq_len"]})
    request = urllib.request.Request(f"{API}/v1/loops/capabilities?{params}",
                                     headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    validate_capabilities(result, config)
    return result


def validate_capabilities(result: dict, config: dict):
    if config["scope"] != "serverless":
        raise StopCampaign("This pilot only allows explicit serverless scope")
    entries = [x for x in result.get("supported_models", []) if x["model_name"] == config["model"]]
    if len(entries) != 1:
        raise StopCampaign("Requested model unavailable in capabilities")
    model = entries[0]
    if model.get("enabled") is not True or model.get("serverless") is not True:
        raise StopCampaign("Workspace has not confirmed serverless model access")
    if model.get("max_enabled_seq_len", 0) < config["max_seq_len"]:
        raise StopCampaign("Workspace sequence-length limit is too small")
    # Capabilities do not expose rank. Creation must validate rank with explicit scope.


def prompt_ids(tokenizer, messages) -> list[int]:
    text = tokenizer.apply_chat_template(messages, tokenize=False,
                                         add_generation_prompt=True, enable_thinking=False)
    return tokenizer.encode(text, add_special_tokens=False)


def supervised_datum(tokenizer, messages, answer: str, max_seq_len: int):
    from baseten.loops import Datum, ModelInput, TensorData
    p = prompt_ids(tokenizer, messages)
    a = tokenizer.encode(answer, add_special_tokens=False)
    if tokenizer.eos_token_id is not None:
        a.append(tokenizer.eos_token_id)
    if not p or not a or len(p) + len(a) - 1 > max_seq_len:
        raise ValueError("Demonstration exceeds context limit")
    ids = p + a
    targets = [-100] * (len(p) - 1) + a
    return Datum(
        model_input=ModelInput.from_ints(ids[:-1]),
        loss_fn_inputs={"target_tokens": TensorData(data=targets, dtype="int64", shape=[len(targets)])},
    ), len(ids)


def policy_datum(g: Generation, advantage: float, max_seq_len: int):
    from baseten.loops import Datum, ModelInput, TensorData
    p, a = g.prompt_ids, g.tokens
    if not p or not a or len(a) != len(g.logprobs):
        raise ValueError("Missing sampled tokens/log probabilities")
    if len(p) + len(a) - 1 > max_seq_len:
        raise ValueError("Rollout exceeds training context")
    start, length = len(p) - 1, len(p) + len(a) - 1
    return Datum(
        model_input=ModelInput.from_ints(p + a[:-1]),
        loss_fn_inputs={
            "target_tokens": TensorData(data=[-100]*start + a, dtype="int64", shape=[length]),
            "logprobs": TensorData(data=[0.0]*start + g.logprobs, dtype="float32", shape=[length]),
            "advantages": TensorData(data=[0.0]*start + [advantage]*len(a), dtype="float32", shape=[length]),
        },
    ), len(p) + len(a)


class LoopsBackend:
    def __init__(self, sampler, tokenizer, ledger: Ledger, config: dict, *,
                 temperature: float, guard=lambda: None):
        self.sampler, self.tokenizer, self.ledger = sampler, tokenizer, ledger
        self.config, self.temperature, self.guard = config, temperature, guard

    def generate(self, messages, *, max_tokens, seed, request_id):
        from baseten.loops import ModelInput, SamplingParams
        ids = prompt_ids(self.tokenizer, messages)
        if len(ids) + max_tokens > self.config["max_seq_len"]:
            # No hidden truncation, which would change tool observations.
            raise StopCampaign("Context ceiling reached; inspect dev data before continuing")
        self.guard()
        result = self.ledger.dispatch(
            request_id, "sample", {"prefill": len(ids), "sample": max_tokens},
            {"prompt_sha256": digest(ids), "checkpoint": self.sampler.checkpoint_path,
             "temperature": self.temperature, "max_tokens": max_tokens, "seed": seed},
            lambda: self.sampler.sample(
                prompt=ModelInput.from_ints(ids), num_samples=1,
                sampling_params=SamplingParams(max_tokens=max_tokens, temperature=self.temperature, seed=seed),
                rollout_id=request_id[:80],
            ),
        )
        sequence = result.sequences[0]
        return Generation(
            text=self.tokenizer.decode(sequence.tokens, skip_special_tokens=True).strip(),
            prompt_ids=ids, tokens=list(sequence.tokens),
            logprobs=list(sequence.logprobs or []), request_id=request_id,
        )


class LoopsSession:
    def __init__(self, config: dict, ledger: Ledger, directory: Path, guard=lambda: None):
        import baseten.loops as loops
        if loops.__version__ != "0.36.0":
            raise StopCampaign("Install the audited baseten-loops==0.36.0")
        self.config, self.ledger, self.directory, self.guard = config, ledger, directory, guard
        self.trainer, self.base_sampler = None, None
        self.service = ledger.dispatch(
            "create-session", "control", {}, {}, lambda: loops.ServiceClient(base_url=API))
        write_json(directory / "session.json", {
            "session_id": self.service.session_id, "sdk": loops.__version__,
            "model": config["model"], "scope": "serverless",
        })

    def call(self, op_id, kind, units, payload, fn):
        self.guard()
        return self.ledger.dispatch(op_id, kind, units, payload, fn)

    def future(self, op_id, kind, units, payload, submit):
        def wait():
            future = submit()
            write_json(self.directory / "operations" / f"{op_id}.json",
                       {"local_id": op_id, "remote_operation_id": future.operation_id,
                        "note": "For chunked backward, SDK exposes the first chunk ID."})
            return future.result(timeout=300)
        return self.call(op_id, kind, units, payload, wait)

    def create_trainer(self):
        c = self.config
        self.trainer = self.call(
            "create-trainer", "control", {}, {"model": c["model"], "rank": c["rank"]},
            lambda: self.service.create_lora_training_client(
                base_model=c["model"], rank=c["rank"], seed=c["seed"],
                max_seq_len=c["max_seq_len"], scope="serverless", timeout=300,
                ready_timeout=300, sampler_timeout=180, with_sampler=True,
                name=f"checkpoint-gate-{self.directory.name}",
            ),
        )
        write_json(self.directory / "trainer.json", {"run_id": self.trainer.run_id})
        return self.trainer.get_tokenizer()

    def create_base(self):
        self.base_sampler = self.call(
            "create-base", "control", {}, {"model": self.config["model"]},
            lambda: self.service.create_sampling_client(
                base_model=self.config["model"], scope="serverless",
                max_seq_len=self.config["max_seq_len"], timeout=180, ready_timeout=300),
        )
        write_json(self.directory / "base.json", {"sampler_id": self.base_sampler.sampler_id,
                                                "model": self.config["model"]})
        return self.base_sampler

    def update(self, datums, token_count: int, step_id: str, *, loss="cross_entropy", lr=4e-5):
        from baseten.loops import AdamParams
        result = self.future(
            f"{step_id}-backward", "forward_backward", {"train": token_count},
            {"data_sha256": digest([d.model_dump(mode="json") for d in datums]), "loss": loss},
            lambda: self.trainer.forward_backward(datums, loss_fn=loss),
        )
        self.future(f"{step_id}-optim", "optim_step", {}, {"lr": lr},
                    lambda: self.trainer.optim_step(AdamParams(learning_rate=lr)))
        return getattr(result, "loss", None)

    def checkpoint(self, name: str, parent: str | None):
        state = self.future(
            f"{name}-state", "save_state", {}, {"name": name},
            lambda: self.trainer.save_state(name=name))
        # Persist the optimizer checkpoint before the next remote operation.
        receipt = {"name": name, "parent": parent, "run_id": self.trainer.run_id,
                   "training_state": state.path}
        write_json(self.directory / f"checkpoint-{name}.json", receipt)
        weights = self.future(
            f"{name}-weights", "save_weights", {}, {"name": name},
            lambda: self.trainer.save_weights_for_sampler(name=name))
        receipt.update(sampler_weights=weights.path, version=getattr(weights, "version", None))
        write_json(self.directory / f"checkpoint-{name}.json", receipt)
        sampler = self.call(
            f"{name}-sampler", "control", {}, {"path": weights.path},
            lambda: self.trainer.create_sampling_client(model_path=weights.path))
        return sampler, receipt

    def close(self):
        # Shutdown does not consume the experiment budget or depend on its lease.
        # Find resources whose creation response might have been lost.
        errors, paired = [], set()
        try:
            runs = self.service.list_runs()
            paired = {r.sampler.id for r in runs if r.sampler is not None}
            for resource in runs:
                try:
                    if not resource.is_inactive:
                        self.service.deactivate_run(resource.id)
                except Exception as exc:
                    errors.append(type(exc).__name__)
        except Exception as exc:
            errors.append(type(exc).__name__)
        try:
            for sampler in self.service.list_samplers():
                if sampler.id not in paired and not sampler.is_inactive:
                    try:
                        self.service.deactivate_sampler(sampler.id)
                    except Exception as exc:
                        errors.append(type(exc).__name__)
        except Exception as exc:
            errors.append(type(exc).__name__)
        for client in (self.base_sampler, self.trainer):
            if client:
                try:
                    client.close()
                except Exception as exc:
                    errors.append(type(exc).__name__)
        write_json(self.directory / "shutdown.json", {
            "deactivation_errors": errors,
            "note": "Serverless only. Idle token billing stops without deploying dedicated inference.",
        })
