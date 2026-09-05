import copy
import tempfile
import unittest
from pathlib import Path

from runtime.evaluations import canonical_hash, compare, load


def sample():
    cases = [{"case_id": "bam-leaf", "expected": "approved leaf shape"},
             {"case_id": "bam-expression", "expected": "approved expression range"}]
    runs = []
    for case in cases:
        for variant in ("baseline", "candidate"):
            runs.append({"run_id": f"{variant}-{case['case_id']}", "variant": variant,
                "case_id": case["case_id"], "trial": 1, "agent_version": variant,
                "prompt_version": variant, "model_version": "fixture", "policy_version": "1.3",
                "environment_id": "same-fixture", "grader_version": "fixture-1", "reference_criteria_id": "fixture-rubric-1",
                "accepted": True, "first_attempt_pass": True, "grader_pass": True,
                "human_pass": True, "outcome_source": "HUMAN_REVIEW",
                "cost_usd": 2.0 if variant == "baseline" else 1.0, "elapsed_seconds": 10,
                "user_revisions": 0, "unexpected_interventions": 0, "blocker_violations": 0,
                "evidence_refs": ["fixture:label-not-a-real-human-review"]})
    return {"schema_version": "1.0", "synthetic": True,
            "dataset": {"id": "fixture", "version": "1", "cases": cases, "sha256": canonical_hash(cases)},
            "runs": runs}


class EvaluationTests(unittest.TestCase):
    def test_synthetic_never_recommends_rollout(self):
        result = compare(sample(), 2)
        self.assertEqual(result["recommendation"], "DEMO_ONLY")
        self.assertEqual(result["comparison_result"], "CANDIDATE_FOR_REVIEW")
        self.assertFalse(result["version_promoted"])

    def test_insufficient_or_unpaired_records_are_inconclusive(self):
        data = sample(); data["synthetic"] = False
        self.assertEqual(compare(data)["recommendation"], "INCONCLUSIVE")
        data["runs"].pop()
        self.assertEqual(compare(data, 2)["recommendation"], "INCONCLUSIVE")

    def test_case_regression_not_hidden_by_aggregate_improvement(self):
        data = sample(); data["synthetic"] = False
        data["runs"][1].update(accepted=False, human_pass=False, first_attempt_pass=False)
        data["runs"][2].update(accepted=False, human_pass=False, first_attempt_pass=False)
        result = compare(data, 2)
        self.assertEqual(result["recommendation"], "KEEP_BASELINE")
        self.assertEqual(result["summaries"]["candidate"]["grader_false_passes"], 1)

    def test_blocking_violation_rejects_even_unpaired_candidate(self):
        data = sample(); data["synthetic"] = False
        record = copy.deepcopy(data["runs"][1])
        record.update(run_id="unpaired", trial=2, blocker_violations=1)
        data["runs"].append(record)
        self.assertEqual(compare(data, 2)["recommendation"], "KEEP_BASELINE")

    def test_retries_count_in_cost_per_accepted_output(self):
        data = sample()
        data["runs"][1].update(accepted=False, human_pass=False, first_attempt_pass=False, cost_usd=5)
        result = compare(data, 2)
        self.assertEqual(result["summaries"]["candidate"]["cost_per_accepted_output_usd"], 6)

    def test_comparability_and_dataset_integrity(self):
        for field in ("environment_id", "policy_version", "grader_version", "reference_criteria_id"):
            data = sample(); data["runs"][1][field] = "different"
            with self.subTest(field=field), self.assertRaises(ValueError): compare(data, 2)
        data = sample(); data["dataset"]["cases"][0]["expected"] = "silently changed"
        with self.assertRaises(ValueError): compare(data, 2)

    def test_duplicate_trials_and_invalid_numbers_rejected(self):
        data = sample(); data["runs"].append(copy.deepcopy(data["runs"][0]))
        with self.assertRaises(ValueError): compare(data)
        for value in (float("nan"), float("inf"), -1, True):
            data = sample(); data["runs"][0]["cost_usd"] = value
            with self.subTest(value=value), self.assertRaises(ValueError): compare(data)

    def test_missing_reference_judgment_cannot_be_scored(self):
        data = sample(); del data["runs"][0]["human_pass"]
        with self.assertRaises(ValueError): compare(data)

    def test_no_successes_has_no_fabricated_unit_cost(self):
        data = sample()
        for record in data["runs"]:record.update(accepted=False, human_pass=False, first_attempt_pass=False)
        self.assertIsNone(compare(data)["summaries"]["baseline"]["cost_per_accepted_output_usd"])

    def test_json_duplicate_keys_and_nonfinite_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"input.json"
            for content in ('{"a":1,"a":2}', '{"a":NaN}'):
                path.write_text(content)
                with self.subTest(content=content), self.assertRaises(ValueError):load(path)

    def test_human_and_format_checks_cannot_masquerade_as_comparable(self):
        data = sample(); data["synthetic"] = False
        data["runs"][0].update(accepted=False, human_pass=False, first_attempt_pass=False)
        data["runs"][1].update(outcome_source="DETERMINISTIC_CHECK", deterministic_pass=True, human_pass=None)
        with self.assertRaises(ValueError): compare(data, 2)

    def test_malformed_objects_and_oversized_numbers_are_rejected(self):
        with self.assertRaises(ValueError): compare([])
        data = sample(); data["dataset"]["cases"] = [None]
        with self.assertRaises(ValueError): compare(data)
        data = sample(); data["runs"][0]["cost_usd"] = 10 ** 1000
        with self.assertRaises(ValueError): compare(data)


if __name__ == "__main__":
    unittest.main()
