import unittest
from unittest.mock import patch

from checkpoint_gate.baseten_backend import policy_datum, supervised_datum, validate_capabilities
from checkpoint_gate.ledger import StopCampaign
from checkpoint_gate.rollout import Generation

try:
    import baseten.loops
    HAS_SDK = True
except ImportError:
    HAS_SDK = False


class Tokenizer:
    eos_token_id = 99
    def apply_chat_template(self, messages, **kwargs):
        return "abc"
    def encode(self, text, **kwargs):
        return [ord(c) for c in text]


class CapabilityTests(unittest.TestCase):
    def test_fail_closed(self):
        config = {"scope":"serverless","model":"model","max_seq_len":4096}
        good = {"supported_models":[{"model_name":"model","enabled":True,"serverless":True,
                                     "max_enabled_seq_len":4096}]}
        validate_capabilities(good, config)
        for key, value in [("enabled", False), ("serverless", None), ("max_enabled_seq_len", 1024)]:
            bad = {"supported_models":[{**good["supported_models"][0], key:value}]}
            with self.assertRaises(StopCampaign):
                validate_capabilities(bad, config)

    def test_preflight_without_key_is_read_only(self):
        from checkpoint_gate.baseten_backend import preflight
        with patch.dict("os.environ", {}, clear=True), patch("urllib.request.urlopen") as request:
            with self.assertRaises(StopCampaign):
                preflight({})
            request.assert_not_called()


@unittest.skipUnless(HAS_SDK, "Optional Baseten SDK not installed")
class SDKContractTests(unittest.TestCase):
    def test_sdk_pinned(self):
        self.assertEqual(baseten.loops.__version__, "0.36.0")

    def test_real_chat_template_dependency(self):
        from tokenizers import Tokenizer as FastTokenizer
        from tokenizers.models import WordLevel
        from transformers import PreTrainedTokenizerFast
        from checkpoint_gate.baseten_backend import prompt_ids
        tok = PreTrainedTokenizerFast(
            tokenizer_object=FastTokenizer(WordLevel({"[UNK]":0, "hello":1}, unk_token="[UNK]")),
            unk_token="[UNK]",
            chat_template="{% for message in messages %}{{ message['content'] }}{% endfor %}",
        )
        self.assertEqual(prompt_ids(tok, [{"role":"user","content":"hello"}]), [1])

    def test_sft_shift_and_prompt_mask(self):
        datum, count = supervised_datum(Tokenizer(), [], "xy", 1024)
        self.assertEqual(datum.model_input.to_ints(), [97,98,99,120,121])
        self.assertEqual(datum.loss_fn_inputs["target_tokens"].data, [-100,-100,120,121,99])
        self.assertEqual(count, 6)

    def test_rl_mask_logprobs_and_advantage(self):
        g = Generation("ok", [1,2,3], [4,5], [-0.3,-0.4])
        datum, count = policy_datum(g, -0.5, 1024)
        self.assertEqual(datum.model_input.to_ints(), [1,2,3,4])
        self.assertEqual(datum.loss_fn_inputs["target_tokens"].data, [-100,-100,4,5])
        self.assertEqual(datum.loss_fn_inputs["advantages"].data, [0,0,-0.5,-0.5])
        self.assertEqual(datum.loss_fn_inputs["logprobs"].data, [0,0,-0.3,-0.4])
        self.assertEqual(count, 5)

    def test_context_overflow_rejected_before_submit(self):
        with self.assertRaises(ValueError):
            supervised_datum(Tokenizer(), [], "long", 2)
        with self.assertRaises(ValueError):
            policy_datum(Generation("x", [1], [2], []), 1, 1024)


if __name__ == "__main__":
    unittest.main()
