"""Mutation checks for policy regressions; no live approval or runtime certification."""

from copy import deepcopy
import unittest

from scripts.validate_contracts import read, validate_current_policies


class PolicyContractTests(unittest.TestCase):
    def setUp(self):
        self.core = read("spec/olympus-contracts-v1.yaml")["olympus"]
        self.slots = read("registry/slots.yaml")["slots"]

    def reject(self, core=None, slots=None):
        with self.assertRaises(ValueError):
            validate_current_policies(core or self.core, slots or self.slots)

    def test_current_bundle_is_consistent(self):
        validate_current_policies(self.core, self.slots)

    def test_retired_slot_cannot_be_reactivated_by_flag(self):
        slot = next(s for s in self.slots if s["slot_id"] == "HEPHAESTUS-CHARACTER-ILLUSTRATOR")
        slot["assignable"] = True
        self.reject()

    def test_artwork_cannot_return_to_build_department(self):
        slot = next(s for s in self.slots if s["slot_id"] == "APHRODITE-CHARACTER-ILLUSTRATOR")
        slot["department"] = "HEPHAESTUS"
        self.reject()

    def test_conditional_review_and_stale_hash_cannot_enter_queue(self):
        for key, value in [("admission_review_states", ["PASS", "CONDITIONAL_PASS"]),
                           ("review_must_match_current_artifact_hash", False)]:
            with self.subTest(key=key):
                mutated = deepcopy(self.core)
                mutated["youtube_queue_policy"][key] = value
                self.reject(core=mutated)

    def test_queue_and_quality_cannot_grant_publication(self):
        for policy, key in [("youtube_queue_policy", "admission_grants_publication"),
                            ("batch_approval_policy", "review_pass_is_approval"),
                            ("batch_approval_policy", "new_items_inherit_approval")]:
            with self.subTest(key=key):
                mutated = deepcopy(self.core)
                mutated[policy][key] = True
                self.reject(core=mutated)

    def test_batch_replacement_cannot_replay_old_tokens(self):
        for key in ["replacement_revokes_unused_old_tokens", "replacement_revocation_and_issuance_atomic",
                    "idempotency_survives_batch_replacement"]:
            with self.subTest(key=key):
                mutated = deepcopy(self.core)
                mutated["batch_approval_policy"][key] = False
                self.reject(core=mutated)

    def test_handoff_cannot_impersonate_user_approval(self):
        self.core["execution_handoff_policy"]["agent_message_is_user_approval"] = True
        self.reject()

    def test_draft_method_permission_cannot_become_submission_pass(self):
        self.core["emoticon_project_policy"]["generative_allowed_implies_submission_pass"] = True
        self.reject()
