import copy
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from checkpoint_gate.common import read_json
from checkpoint_gate.dataset import FAMILIES, generate, load
from checkpoint_gate.evaluation import paired
from checkpoint_gate.ledger import Ledger, StopCampaign
from checkpoint_gate.rollout import Generation, ScriptedOracle, demonstrations, run
from checkpoint_gate.verifier import SQLiteTool, equivalent, parse_action

ROOT = Path(__file__).parents[1]


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "db.sqlite"
        with sqlite3.connect(self.db) as con:
            con.executescript("CREATE TABLE items(id INTEGER,value TEXT); INSERT INTO items VALUES(1,'a'),(1,'a'),(2,NULL);")
        self.tool = SQLiteTool(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_select_and_cte(self):
        self.assertEqual(self.tool.execute("WITH x AS (SELECT * FROM items) SELECT COUNT(*) FROM x")["rows"], [[3]])

    def test_no_writes_attachments_extensions_or_pragmas(self):
        before = self.db.read_bytes()
        for sql in [
            "DELETE FROM items", "DROP TABLE items", "UPDATE items SET id=10",
            "PRAGMA writable_schema=ON", "ATTACH ':memory:' AS other",
            "SELECT load_extension('/tmp/x')", "VACUUM INTO '/tmp/x'",
            "CREATE TEMP TABLE x(id)", "SELECT randomblob(1000000000)",
            "SELECT * FROM items; DELETE FROM items",
        ]:
            with self.subTest(sql=sql):
                self.assertIn("error", self.tool.execute(sql))
        self.assertEqual(before, self.db.read_bytes())

    def test_recursive_query_stops(self):
        result = self.tool.execute("WITH RECURSIVE x(n) AS (VALUES(1) UNION ALL SELECT n+1 FROM x) SELECT SUM(n) FROM x")
        self.assertIn("error", result)

    def test_row_limit_and_size(self):
        self.assertEqual(SQLiteTool(self.db, max_rows=2).execute("SELECT * FROM items")["error"], "row_limit")
        self.assertIn("error", self.tool.execute("SELECT " + "1,"*10_000 + "1"))

    def test_semantic_rows_preserve_null_types_duplicates_order(self):
        self.assertTrue(equivalent([[1.0, None], [2, "x"]], [[2, "x"], [1, None]], False))
        self.assertFalse(equivalent([[1]], [[1], [1]], False))
        self.assertFalse(equivalent([[None]], [["null"]], True))
        self.assertFalse(equivalent([[True]], [[1]], True))
        self.assertFalse(equivalent([[2], [1]], [[1], [2]], True))
        self.assertFalse(equivalent([[float("nan")]], [[1]], True))

    def test_strict_actions(self):
        for text in ['{"sql":"a","sql":"b"}', '{"answer":[[NaN]]}', '```{"sql":"SELECT 1"}```',
                     '{"sql":"SELECT 1","answer":[]}', '[]', '{"answer":"x"}']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_action(text)

    def test_only_outer_fence_is_normalized(self):
        self.assertEqual(parse_action('```json\n{"sql":"SELECT 1"}\n```', allow_outer_fence=True),
                         {"sql":"SELECT 1"})
        for text in ['Explanation\n```json\n{"sql":"SELECT 1"}\n```',
                     '```python\n{"sql":"SELECT 1"}\n```',
                     '```json\n{"sql":"SELECT 1"}\n```\nExtra text']:
            with self.assertRaises(ValueError):
                parse_action(text, allow_outer_fence=True)


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name) / "data"
        generate(cls.root, per_family=2)
        cls.tasks, cls.gold, cls.manifest = load(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_families_disjoint(self):
        self.assertFalse(set(FAMILIES["train"]) & set(FAMILIES["dev"]))
        self.assertFalse(set(FAMILIES["train"]) & set(FAMILIES["test"]))
        self.assertFalse(set(FAMILIES["dev"]) & set(FAMILIES["test"]))
        self.assertEqual(len(self.tasks), 24)

    def test_full_rollout_with_and_without_fault_recovery(self):
        for task in self.tasks:
            with self.subTest(task=task["id"]):
                gold = self.gold[task["id"]]
                good = run(task, self.root, gold["rows"], ScriptedOracle(gold["sql"]), rollout_id="test")
                self.assertTrue(good["correct"])
                self.assertEqual(good["tool_calls"], 2 if task["fault"] != "none" else 1)
                bad = run(task, self.root, gold["rows"], ScriptedOracle(gold["sql"], recover=False), rollout_id="test")
                self.assertEqual(bad["correct"], task["fault"] == "none")

    def test_gold_never_in_initial_model_messages(self):
        from checkpoint_gate.rollout import initial_messages
        for task in self.tasks:
            contents = " ".join(m["content"] for m in initial_messages(task))
            self.assertNotIn(self.gold[task["id"]]["sql"], contents)
            self.assertNotIn("private/gold", contents)

    def test_heldout_demonstrations_rejected(self):
        for task in self.tasks:
            if task["split"] != "train":
                with self.assertRaises(ValueError):
                    demonstrations(task, self.root, self.gold[task["id"]])

    def test_no_answer_without_successful_tool(self):
        class Guesser:
            def generate(inner, *args, **kwargs):
                return Generation('{"answer":[]}')
        task = self.tasks[0]
        result = run(task, self.root, [], Guesser(), rollout_id="guess")
        self.assertFalse(result["correct"])

    def test_immutable_input_detection(self):
        file = self.root / self.tasks[0]["db"]
        original = file.read_bytes()
        try:
            file.write_bytes(original + b"tamper")
            with self.assertRaisesRegex(ValueError, "Frozen input"):
                load(self.root)
        finally:
            file.write_bytes(original)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "ledger.sqlite"
        self.config = read_json(ROOT / "configs/pilot.json")
        self.config["compute_cap_usd"] = 0.00001
        self.ledger = Ledger(self.path, self.config)

    def tearDown(self):
        self.temp.cleanup()

    def test_reservation_blocks_boundary_overspend(self):
        self.ledger.dispatch("one", "sample", {"sample": 7}, {}, lambda: "ok")
        with self.assertRaisesRegex(StopCampaign, "ceiling"):
            self.ledger.reserve("two", "sample", {"sample": 1}, {})

    def test_duplicate_does_not_execute_twice(self):
        calls = []
        self.ledger.dispatch("one", "control", {}, {}, lambda: calls.append(1))
        with self.assertRaises(StopCampaign):
            self.ledger.dispatch("one", "control", {}, {}, lambda: calls.append(2))
        self.assertEqual(calls, [1])

    def test_ambiguous_call_keeps_money_and_stops(self):
        def lost_response():
            raise TimeoutError()
        with self.assertRaises(TimeoutError):
            self.ledger.dispatch("one", "sample", {"sample": 2}, {}, lost_response)
        self.assertIn("unknown", self.ledger.snapshot()["states"])
        self.assertGreater(self.ledger.snapshot()["conservative_reserved_usd"], 0)
        with self.assertRaises(StopCampaign):
            self.ledger.reserve("two", "control", {}, {})

    def test_crash_recovery_turns_pending_into_unknown(self):
        self.ledger.reserve("crash", "optim_step", {}, {})
        reopened = Ledger(self.path, self.config)
        self.assertIn("unknown", reopened.snapshot()["states"])

    def test_concurrent_reservations_cannot_overbook(self):
        def reserve(i):
            try:
                self.ledger.reserve(str(i), "sample", {"sample": 7}, {})
                return True
            except StopCampaign:
                return False
        with ThreadPoolExecutor(8) as pool:
            successes = list(pool.map(reserve, range(8)))
        self.assertEqual(sum(successes), 1)

    def test_token_caps_and_deadline(self):
        self.config["token_caps"]["sample"] = 1
        other = Ledger(Path(self.temp.name)/"other.sqlite", self.config)
        with self.assertRaisesRegex(StopCampaign, "token ceiling"):
            other.reserve("one", "sample", {"sample": 2}, {})
        with patch("checkpoint_gate.ledger.time.time", return_value=10**12):
            with self.assertRaisesRegex(StopCampaign, "deadline"):
                self.ledger.reserve("deadline", "control", {}, {})

    def test_budget_cannot_change_on_restart(self):
        changed = copy.deepcopy(self.config)
        changed["compute_cap_usd"] = 1
        with self.assertRaises(StopCampaign):
            Ledger(self.path, changed)

    def test_negative_rates_cannot_credit_the_ledger(self):
        changed = copy.deepcopy(self.config)
        changed["rates_per_million"]["train"] = "-1"
        with self.assertRaises(ValueError):
            Ledger(Path(self.temp.name)/"bad.sqlite", changed)


class EvaluationTests(unittest.TestCase):
    def test_paired_difference(self):
        a = [{"task_id":str(i), "correct":False, "status":"wrong"} for i in range(10)]
        b = [{**r, "correct":True} for r in a]
        result = paired(a, b, replicates=100)
        self.assertEqual(result["delta_accuracy"], 1)
        self.assertEqual(result["paired_bootstrap_95"], [1, 1])

    def test_mismatched_or_partial_pairs_rejected(self):
        a = [{"task_id":"one", "correct":False, "status":"not_run"}]
        with self.assertRaises(ValueError):
            paired(a, a)
        with self.assertRaises(ValueError):
            paired(a, [])


if __name__ == "__main__":
    unittest.main()
