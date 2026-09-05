from copy import deepcopy
from pathlib import Path
import unittest

from runtime.evaluations import compare, load


class JointEvaluationTests(unittest.TestCase):
    def fixture(self):
        return load(Path(__file__).parents[1] / "examples/evaluation-sample.json")

    def test_joint_policy_is_reported_but_synthetic_never_promoted(self):
        data = self.fixture()
        report = compare(data, minimum_pairs=2, require_joint_improvement=True)
        self.assertTrue(report["require_joint_improvement"])
        self.assertEqual(report["recommendation"], "DEMO_ONLY")
        self.assertFalse(report["version_promoted"])

    def test_faster_but_more_expensive_is_inconclusive(self):
        data = self.fixture()
        for record in data["runs"]:
            if record["variant"] == "candidate":
                record["cost_usd"] = 1000
                record["elapsed_seconds"] = 0.001
        report = compare(data, minimum_pairs=2, require_joint_improvement=True)
        self.assertEqual(report["comparison_result"], "INCONCLUSIVE")

    def test_real_joint_comparison_requires_one_line_and_prior_plan_reference(self):
        data = self.fixture(); data["synthetic"] = False
        with self.assertRaisesRegex(ValueError, "product_line"):
            compare(data, minimum_pairs=2, require_joint_improvement=True)
        data["product_line"] = "WEB_APP"
        data["comparison_plan_ref"] = "private/registered-plan-v1"
        data["runs"][0]["product_line"] = "BLOG"
        with self.assertRaisesRegex(ValueError, "Mixed product lines"):
            compare(data, minimum_pairs=2, require_joint_improvement=True)
