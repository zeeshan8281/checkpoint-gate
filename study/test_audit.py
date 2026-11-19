"""Meaningful checks for scoring and the independent replay oracle."""
import json
import tempfile
import unittest
from pathlib import Path

from audit import extract, oracle, paired_summary, perturb
from checkpoint_gate.dataset import _construct
from checkpoint_gate.verifier import SQLiteTool, equivalent


class ReplayOracleTests(unittest.TestCase):
    def task(self, root, family, seed=91):
        db = root / f"{family}.sqlite"
        schema, question, sql, rows, ordered = _construct(db, "test", family, seed)
        return {
            "id": f"test-{family}-0000", "family": family, "schema": schema,
            "question": question, "ordered": ordered,
        }, db, sql, rows

    def test_independent_oracle_and_perturbation_agree_with_gold(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for family in ("latest_window", "anti_null", "distinct_pairs", "relational_division"):
                task, db, sql, rows = self.task(root, family)
                self.assertTrue(equivalent(oracle(task, db), rows, task["ordered"]))
                variant = root / f"{family}-variant.sqlite"
                perturb(task, variant, 0)
                expected = oracle(task, variant)
                result = SQLiteTool(variant).execute(sql)
                self.assertIn("rows", result)
                self.assertTrue(equivalent(result["rows"], expected, task["ordered"]))

    def test_timestamp_id_counterexample_is_present(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task, _, _, _ = self.task(root, "latest_window")
            variant = root / "variant.sqlite"
            perturb(task, variant, 0)
            rows = {r[0]: r for r in oracle(task, variant)}
            self.assertEqual(rows[1], [1, 65, 20])
            self.assertEqual(rows[2], [2, 68, 35])

    def test_mixed_labels_and_empty_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task, _, _, _ = self.task(root, "anti_null")
            variant = root / "variant.sqlite"
            perturb(task, variant, 0)
            ids = {r[0] for r in oracle(task, variant)}
            self.assertNotIn(3, ids)
            self.assertIn(12, ids)

    def test_exact_query_wrong_answer_is_separate(self):
        row = {"task_id": "t", "correct": False, "trace": [
            {"assistant": '{"sql":"SELECT 1"}', "tool": {"rows": [[1]]}},
            {"assistant": '{"answer":[[2]]}'},
        ]}
        self.assertEqual(extract(row, [[1]], True)[3], "wrong_final_despite_exact_last_query")

    def test_postprocessing_is_not_mislabelled_as_failure(self):
        row = {"task_id": "t", "correct": True, "trace": [
            {"assistant": '{"sql":"SELECT 1 UNION ALL SELECT 2"}',
             "tool": {"rows": [[1], [2]]}},
            {"assistant": '{"answer":[[2]]}'},
        ]}
        _, _, exact, category = extract(row, [[2]], True)
        self.assertFalse(exact)
        self.assertEqual(category, "correct_final")

    def test_rejects_tampered_original_score(self):
        row = {"task_id": "t", "correct": True, "trace": [
            {"assistant": '{"sql":"SELECT 1"}', "tool": {"rows": [[1]]}},
            {"assistant": '{"answer":[[2]]}'},
        ]}
        with self.assertRaisesRegex(ValueError, "disagrees"):
            extract(row, [[1]], True)

    def test_mcnemar_extremes_and_matched_bootstrap(self):
        rows = [{"family": "a", "fault": "none", "left": True, "right": False}
                for _ in range(10)]
        result = paired_summary(rows, "left", "right", replicates=100)
        self.assertEqual(result["delta"], -1)
        self.assertEqual(result["stratified_task_bootstrap_95"], [-1, -1])
        self.assertEqual(result["exploratory_exact_mcnemar_p"], 2 / 1024)
        for row in rows:
            row["right"] = True
        self.assertEqual(paired_summary(rows, "left", "right", replicates=100)
                         ["exploratory_exact_mcnemar_p"], 1)


if __name__ == "__main__":
    unittest.main()
