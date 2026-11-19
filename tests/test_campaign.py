"""Exercise the complete controller against an in-process fake remote service.

This is a protocol integration test, never evidence about an actual model.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from checkpoint_gate.campaign import execute
from checkpoint_gate.common import canonical, read_json
from checkpoint_gate.dataset import generate, load

try:
    import baseten.loops
    HAS_SDK = True
except ImportError:
    HAS_SDK = False


class FakeTokenizer:
    eos_token_id = 0
    name_or_path = "fake-tokenizer"
    init_kwargs = {}
    chat_template = "fake-chat"
    def apply_chat_template(self, messages, **kwargs):
        return json.dumps(messages)
    def encode(self, text, **kwargs):
        return list(text.encode())
    def decode(self, tokens, **kwargs):
        return bytes(tokens).decode()


@unittest.skipUnless(HAS_SDK, "Optional SDK required")
class CampaignTests(unittest.TestCase):
    def test_all_three_conditions_reach_evaluation_and_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root, out = Path(temp)/"data", Path(temp)/"run"
            generate(root, per_family=2)
            tasks, gold, _ = load(root)
            sql = {t["question"]: gold[t["id"]]["sql"] for t in tasks}
            calls = []
            tokenizer = FakeTokenizer()

            class Future:
                operation_id = "fake-remote-op"
                def __init__(self, value):
                    self.value = value
                def result(self, **kwargs):
                    return self.value

            class Sampler:
                sampler_id = "base-sampler"
                def __init__(self, path=None):
                    self.checkpoint_path = path
                def close(self):
                    pass
                def sample(self, prompt, sampling_params, rollout_id, **kwargs):
                    messages = json.loads(tokenizer.decode(prompt.to_ints()))
                    last = messages[-1]["content"]
                    if rollout_id.startswith("dev-") or (rollout_id.startswith("rl-") and "-s0-" in rollout_id):
                        text = "invalid"
                    elif "-reg-" in rollout_id:
                        text = '{"answer":[]}'
                    elif last.startswith("SQL tool result:\n"):
                        feedback = json.loads(last.split("\n", 1)[1])
                        if "rows" in feedback:
                            text = canonical({"answer": feedback["rows"]})
                        elif self.checkpoint_path is None:
                            text = '{"answer":[]}'
                        else:
                            question = messages[1]["content"].split("Question:\n", 1)[1]
                            text = canonical({"sql": sql[question]})
                    else:
                        question = last.split("Question:\n", 1)[1]
                        text = canonical({"sql": sql[question]})
                    tokens = tokenizer.encode(text)[:sampling_params.max_tokens]
                    return SimpleNamespace(sequences=[SimpleNamespace(tokens=tokens, logprobs=[-0.5]*len(tokens))])

            class Trainer:
                run_id = "fake-run"
                def get_tokenizer(self):
                    return tokenizer
                def forward_backward(self, data, **kwargs):
                    calls.append(("backward", kwargs["loss_fn"], len(data)))
                    return Future(SimpleNamespace(loss=0.5))
                def optim_step(self, params):
                    calls.append(("optim", params.learning_rate))
                    return Future(SimpleNamespace())
                def save_state(self, name):
                    return Future(SimpleNamespace(path=f"bt://loops:fake/weights/{name}"))
                def save_weights_for_sampler(self, name):
                    return Future(SimpleNamespace(path=f"bt://loops:fake/sampler_weights/{name}", version=1))
                def create_sampling_client(self, model_path):
                    return Sampler(model_path)
                def close(self):
                    calls.append(("close", "trainer"))

            class Service:
                session_id = "fake-session"
                def __init__(self, **kwargs):
                    pass
                def create_lora_training_client(self, **kwargs):
                    self.assert_scope(kwargs)
                    return Trainer()
                def create_sampling_client(self, **kwargs):
                    self.assert_scope(kwargs)
                    return Sampler()
                def assert_scope(self, kwargs):
                    if kwargs["scope"] != "serverless":
                        raise AssertionError("Dedicated fallback")
                def list_runs(self):
                    return [SimpleNamespace(id="fake-run", is_inactive=False,
                                            sampler=SimpleNamespace(id="paired"))]
                def list_samplers(self):
                    return [SimpleNamespace(id="paired", is_inactive=False),
                            SimpleNamespace(id="base-sampler", is_inactive=False)]
                def deactivate_run(self, id):
                    calls.append(("deactivate", id))
                def deactivate_sampler(self, id):
                    if id == "paired":
                        raise AssertionError("Cannot deactivate paired sampler independently")
                    calls.append(("deactivate", id))

            config = read_json(Path(__file__).parents[1]/"configs/pilot.json")
            config.update(sft_steps=1, sft_batch_size=2, rl_steps=1, rl_max_groups=2)
            with patch("checkpoint_gate.campaign.preflight", return_value={"mock": True}), \
                 patch("baseten.loops.ServiceClient", Service):
                result = execute(root, out, config)
            self.assertEqual(set(result["conditions"]), {"base", "sft", "sft_rl"})
            self.assertEqual(result["rl_updates"], 1)
            self.assertEqual(read_json(out/"status.json")["state"], "complete")
            self.assertIn(("deactivate", "fake-run"), calls)
            self.assertIn(("deactivate", "base-sampler"), calls)
            self.assertTrue(any(c[:2] == ("backward", "cispo") for c in calls))
            self.assertTrue((out/"operations/rl-0-optim.json").exists())
            self.assertEqual(read_json(out/"shutdown.json")["deactivation_errors"], [])


if __name__ == "__main__":
    unittest.main()
