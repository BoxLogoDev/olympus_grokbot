"""Behavior checks for local journal invariants, not production certification."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from runtime.demo import run
from runtime.ledger import Ledger, LedgerError


def workflow(project="test", budget=100, concurrency=4):
    return {
        "project_id": project, "mode": "LOCAL_SIMULATION", "workflow_version": "fixture-1",
        "policy_version": "1.2", "policy_commit": "a6e7a8b1f1624c40ee2712e825f4c853439d028e",
        "budget_units": budget, "concurrency_limit": concurrency, "review_limit": concurrency,
        "tasks": [
            {"id": name, "owner": f"SIM-{name}", "reviewer": "SIM-review",
             "action_kind": "LOCAL_SIMULATION", "external_action": False,
             "dependencies": deps, "input": {"version": 1},
             "output_schema": {"asset_id": "str", "simulation": "bool"},
             "done_when": "Fixture metadata is valid."}
            for name, deps in [("a", []), ("b", ["a"]), ("c", []), ("d", ["b", "c"])]
        ],
    }


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ledger.sqlite"
        self.ledger = Ledger(self.path)
        self.addCleanup(lambda: self.ledger.close())
        for actor in ("SIM-a", "SIM-b", "SIM-c", "SIM-d"):
            self.ledger.register_actor(actor, "WORKER")
        self.ledger.register_actor("SIM-review", "REVIEWER")
        self.ledger.create_workflow(workflow())

    def complete(self, task, cost=2):
        attempt = self.ledger.start("test", task, f"SIM-{task}", 3)
        self.ledger.stage_result(attempt, f"SIM-{task}", {"asset_id": attempt, "simulation": True}, cost)
        self.review_attempt(attempt, True, "Fixture-only check passed.")
        return attempt

    def review_attempt(self, attempt_id, accepted, evidence, failure_key=None, reviewer="SIM-review"):
        # Capture the exact attempted output before submitting a review request.
        attempt = self.ledger.db.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        return self.ledger.review(attempt["project_id"], attempt["task_id"], reviewer, accepted, evidence, failure_key,
                                  expected_attempt_id=attempt_id, expected_result_digest=attempt["result_digest"])

    def snapshot(self):
        return self.ledger.snapshot("test")

    def state(self, task):
        return next(t for t in self.snapshot()["tasks"] if t["id"] == task)

    def test_dependency_needs_independent_review_and_valid_schema(self):
        self.assertEqual(self.state("b")["state"], "DRAFT")
        attempt = self.ledger.start("test", "a", "SIM-a", 3)
        with self.assertRaises(LedgerError):
            self.ledger.stage_result(attempt, "SIM-a", {"simulation": True}, 2)
        with self.assertRaises(LedgerError):
            self.ledger.stage_result(attempt, "SIM-a", {"asset_id": "x", "simulation": False}, 2)
        with self.assertRaises(LedgerError):
            self.ledger.stage_result(attempt, "SIM-c", {"asset_id": "x", "simulation": True}, 2)
        self.ledger.stage_result(attempt, "SIM-a", {"asset_id": "x", "simulation": True}, 2)
        with self.assertRaises(LedgerError):
            self.ledger.start("test", "b", "SIM-b", 3)
        with self.assertRaises(LedgerError):
            self.review_attempt(attempt, True, "Self assertion.", reviewer="SIM-a")
        self.review_attempt(attempt, True, "Independent fixture check.")
        self.assertEqual(self.state("a")["state"], "DONE")
        self.assertEqual(self.state("b")["state"], "READY")
        self.ledger.start("test", "b", "SIM-b", 3)

    def test_rejects_cycles_unknown_edges_and_external_tasks(self):
        variants = []
        cyclic = workflow("cycle")
        cyclic["tasks"][0]["dependencies"] = ["b"]
        variants.append(cyclic)
        unknown = workflow("unknown")
        unknown["tasks"][0]["dependencies"] = ["missing"]
        variants.append(unknown)
        external = workflow("external")
        external["tasks"][0]["external_action"] = True
        variants.append(external)
        publish = workflow("publish")
        publish["tasks"][0]["action_kind"] = "PUBLISH"
        variants.append(publish)
        missing_owner = workflow("missing-owner")
        missing_owner["tasks"][0]["owner"] = "unregistered"
        variants.append(missing_owner)
        no_version = workflow("no-version")
        no_version["policy_commit"] = ""
        variants.append(no_version)
        for spec in variants:
            with self.subTest(project=spec["project_id"]), self.assertRaises(LedgerError):
                self.ledger.create_workflow(spec)
        self.assertEqual(self.ledger.db.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 1)

    def test_project_and_task_identity_cannot_reset_history(self):
        self.complete("a")
        changed = workflow()
        changed["tasks"][0]["id"] = "replacement"
        changed["tasks"][1]["dependencies"] = ["replacement"]
        with self.assertRaises(LedgerError):
            self.ledger.create_workflow(changed)
        with self.assertRaises(LedgerError):
            self.ledger.start("test", "replacement", "SIM-a", 3)
        self.assertEqual(len(self.snapshot()["attempts"]), 1)

    def test_partial_invalidation_preserves_sibling_cost_and_history(self):
        old = {task: self.complete(task) for task in ("a", "b", "c", "d")}
        affected = self.ledger.change_input("test", "b", {"version": 2}, "Change one branch.")
        self.assertEqual(affected, ["b", "d"])
        self.assertEqual(self.state("a")["current_attempt"], old["a"])
        self.assertEqual(self.state("c")["current_attempt"], old["c"])
        self.assertEqual(self.state("b")["state"], "READY")
        self.assertIsNone(self.state("d")["current_attempt"])
        self.assertEqual(self.state("d")["state"], "DRAFT")
        self.assertEqual(self.snapshot()["budget"]["spent"], 8)
        self.assertEqual(len(self.snapshot()["attempts"]), 4)
        new_b = self.complete("b")
        self.complete("d")
        rows = {a["id"]: a for a in self.snapshot()["attempts"]}
        self.assertEqual(rows[old["b"]]["lineage_id"], rows[new_b]["lineage_id"])
        self.assertNotEqual(rows[old["b"]]["input_digest"], rows[new_b]["input_digest"])
        self.assertEqual(rows[old["b"]]["status"], "ACCEPTED")
        self.assertEqual(self.snapshot()["budget"]["spent"], 12)
        self.assertEqual(self.state("c")["generation"], 0)

    def test_no_stale_completion_or_change_while_affected_task_active(self):
        attempt = self.ledger.start("test", "a", "SIM-a", 3)
        with self.assertRaises(LedgerError):
            self.ledger.change_input("test", "a", {"version": 2}, "Unsafe in-flight edit.")
        self.ledger.stage_result(attempt, "SIM-a", {"asset_id": "old", "simulation": True}, 2)
        with self.assertRaises(LedgerError):
            self.ledger.change_input("test", "a", {"version": 2}, "Review still pending.")
        self.review_attempt(attempt, True, "Fixture evidence.")
        self.ledger.change_input("test", "a", {"version": 2}, "New fixture input.")
        with self.assertRaises(LedgerError):
            self.ledger.stage_result(attempt, "SIM-a", {"asset_id": "late", "simulation": True}, 2)
        self.assertEqual(self.snapshot()["budget"]["spent"], 2)

    def test_delayed_review_cannot_accept_a_newer_attempt(self):
        old = self.ledger.start("test", "a", "SIM-a", 3)
        self.ledger.stage_result(old, "SIM-a", {"asset_id": "old", "simulation": True}, 2)
        old_digest = self.ledger.db.execute("SELECT result_digest FROM attempts WHERE id=?", (old,)).fetchone()[0]
        self.review_attempt(old, False, "Old fixture has a defect.", "first-defect")
        new = self.ledger.start("test", "a", "SIM-a", 3)
        self.ledger.stage_result(new, "SIM-a", {"asset_id": "new", "simulation": True}, 2)
        before = self.snapshot()
        with self.assertRaisesRegex(LedgerError, "attempt changed"):
            self.ledger.review("test", "a", "SIM-review", True, "Delayed acceptance of the old fixture.",
                               expected_attempt_id=old, expected_result_digest=old_digest)
        with self.assertRaisesRegex(LedgerError, "result digest changed"):
            self.ledger.review("test", "a", "SIM-review", True, "Mismatched output evidence.",
                               expected_attempt_id=new, expected_result_digest=old_digest)
        after = self.snapshot()
        self.assertEqual(after, before)
        self.assertEqual(self.state("a")["state"], "REVIEW")
        self.assertEqual(self.state("a")["current_attempt"], new)
        self.assertEqual(self.ledger.db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0], 1)
        self.review_attempt(new, True, "New output independently checked.")
        self.assertEqual(self.state("a")["state"], "DONE")

    def test_snapshot_uses_one_database_version_during_concurrent_commit(self):
        second = Ledger(self.path)
        committed = []

        def commit_between_reads(statement):
            if statement.startswith("SELECT id,lineage_id,state") and not committed:
                committed.append(second.start("test", "a", "SIM-a", 3))

        try:
            self.ledger.db.set_trace_callback(commit_between_reads)
            snapshot = self.snapshot()
        finally:
            self.ledger.db.set_trace_callback(None)
            second.close()
        self.assertEqual(len(committed), 1)
        # The earlier project read pins the whole report before the writer commit.
        self.assertEqual(snapshot["budget"]["reserved"], 0)
        self.assertEqual(snapshot["attempts"], [])
        self.assertEqual(next(t for t in snapshot["tasks"] if t["id"] == "a")["state"], "READY")
        current = self.snapshot()
        self.assertEqual(current["budget"]["reserved"], 3)
        self.assertEqual([a["id"] for a in current["attempts"]], committed)

    def test_parallel_connections_reserve_budget_atomically(self):
        spec = workflow("small-budget", budget=5, concurrency=2)
        self.ledger.create_workflow(spec)
        barrier = threading.Barrier(2)

        def reserve(task):
            ledger = Ledger(self.path)
            try:
                barrier.wait(timeout=5)
                try:
                    return ledger.start("small-budget", task, f"SIM-{task}", 4)
                except LedgerError:
                    return None
            finally:
                ledger.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, ("a", "c")))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(self.ledger.snapshot("small-budget")["budget"], {"limit": 5, "spent": 0, "reserved": 4})

    def test_separate_connections_cannot_double_lease_worker(self):
        spec = workflow("other")
        self.ledger.create_workflow(spec)
        second = Ledger(self.path)
        try:
            self.ledger.start("test", "a", "SIM-a", 3)
            with self.assertRaisesRegex(LedgerError, "already owns"):
                second.start("other", "a", "SIM-a", 3)
            self.assertEqual(second.snapshot("other")["budget"]["reserved"], 0)
            self.assertEqual(len(second.snapshot("other")["attempts"]), 0)
        finally:
            second.close()

    def test_concurrency_and_review_backpressure(self):
        spec = workflow("one", concurrency=1)
        self.ledger.create_workflow(spec)
        attempt = self.ledger.start("one", "a", "SIM-a", 3)
        self.ledger.stage_result(attempt, "SIM-a", {"asset_id": "x", "simulation": True}, 2)
        with self.assertRaises(LedgerError):
            self.ledger.start("one", "c", "SIM-c", 3)
        self.review_attempt(attempt, True, "Fixture check.")
        self.ledger.start("one", "c", "SIM-c", 3)

    def test_reopening_unresolved_attempt_retains_reservation_and_requires_reconciliation(self):
        attempt = self.ledger.start("test", "a", "SIM-a", 7)
        self.ledger.close()
        self.ledger = Ledger(self.path)
        with self.assertRaises(LedgerError):
            self.ledger.start("test", "a", "SIM-a", 7)
        self.assertEqual(self.snapshot()["budget"]["reserved"], 7)
        self.assertEqual(self.ledger.mark_interrupted("test", "Process stopped; result unknown."), [attempt])
        with self.assertRaises(LedgerError):
            self.ledger.start("test", "a", "SIM-a", 7)
        with self.assertRaises(LedgerError):
            self.ledger.change_input("test", "a", {"version": 2}, "Cannot erase uncertainty.")
        with self.assertRaises(LedgerError):
            self.ledger.stage_result(attempt, "SIM-a", {"asset_id": "late", "simulation": True}, 3)
        self.ledger.reconcile(attempt, "SIM-review", "FAILED", "Fixture log confirms no result; three units used.", 3, failure_key="interrupted")
        self.assertEqual(self.snapshot()["budget"], {"limit": 100, "spent": 3, "reserved": 0})
        self.assertEqual(self.state("a")["state"], "READY")
        self.complete("a")
        self.assertEqual(len(self.snapshot()["attempts"]), 2)

    def test_reconciled_result_still_needs_review(self):
        attempt = self.ledger.start("test", "a", "SIM-a", 3)
        self.ledger.mark_interrupted("test", "Disconnected local process.")
        self.ledger.reconcile(attempt, "SIM-review", "STAGED", "Recovered fixture output and cost log.", 2,
                              result={"asset_id": "recovered", "simulation": True})
        self.assertEqual(self.state("a")["state"], "REVIEW")
        with self.assertRaises(LedgerError):
            self.ledger.start("test", "b", "SIM-b", 3)
        self.review_attempt(attempt, True, "Recovered metadata reviewed.")
        self.ledger.start("test", "b", "SIM-b", 3)

    def test_same_failure_circuit_survives_quality_revision_and_input_change(self):
        first = self.ledger.start("test", "a", "SIM-a", 3)
        self.ledger.fail(first, "SIM-a", "leaf-mismatch", 1)
        second = self.ledger.start("test", "a", "SIM-a", 3)
        self.ledger.stage_result(second, "SIM-a", {"asset_id": "bad", "simulation": True}, 2)
        self.review_attempt(second, False, "Same fixture failure.", "leaf-mismatch")
        self.assertEqual(self.state("a")["state"], "BLOCKED")
        self.ledger.change_input("test", "a", {"version": 2}, "Counter must not reset.")
        self.assertEqual(self.state("a")["state"], "BLOCKED")
        with self.assertRaises(LedgerError):
            self.ledger.start("test", "a", "SIM-a", 3)
        self.assertEqual(self.snapshot()["budget"]["spent"], 3)

    def test_six_total_attempts_and_two_per_revision(self):
        for revision in range(3):
            first = self.ledger.start("test", "a", "SIM-a", 3)
            self.ledger.fail(first, "SIM-a", f"transient-{revision}", 1)
            second = self.ledger.start("test", "a", "SIM-a", 3)
            self.ledger.stage_result(second, "SIM-a", {"asset_id": second, "simulation": True}, 2)
            self.review_attempt(second, revision == 2, "Fixture quality comparison.", f"quality-{revision}")
        self.assertEqual(self.state("a")["state"], "DONE")
        self.ledger.change_input("test", "a", {"version": 2}, "Input edits preserve lifetime attempts.")
        self.assertEqual(self.state("a")["state"], "BLOCKED")
        self.assertEqual(len(self.snapshot()["attempts"]), 6)
        self.assertEqual(self.snapshot()["budget"]["spent"], 9)
        self.assertEqual([a["revision"] for a in self.snapshot()["attempts"]], [0, 0, 1, 1, 2, 2])

    def test_third_quality_rejection_cannot_be_reset_by_input_edit(self):
        for revision in range(3):
            attempt = self.ledger.start("test", "a", "SIM-a", 3)
            self.ledger.stage_result(attempt, "SIM-a", {"asset_id": attempt, "simulation": True}, 2)
            self.review_attempt(attempt, False, "Distinct fixture defect.", f"quality-{revision}")
        self.assertEqual(self.state("a")["state"], "BLOCKED")
        self.ledger.change_input("test", "a", {"version": 2}, "Still needs manual escalation.")
        self.assertEqual(self.state("a")["state"], "BLOCKED")

    def test_cost_overrun_rejected_without_losing_reservation(self):
        attempt = self.ledger.start("test", "a", "SIM-a", 3)
        with self.assertRaises(LedgerError):
            self.ledger.stage_result(attempt, "SIM-a", {"asset_id": "x", "simulation": True}, 4)
        self.assertEqual(self.snapshot()["budget"]["reserved"], 3)
        self.assertEqual(self.snapshot()["budget"]["spent"], 0)
        self.assertEqual(self.state("a")["state"], "RUNNING")

    def test_append_only_events_and_pinned_versions(self):
        self.complete("a")
        snapshot = self.snapshot()
        self.assertEqual(snapshot["workflow_version"], "fixture-1")
        self.assertFalse(snapshot["production_verified"])
        self.assertFalse(snapshot["approval_issued"])
        kinds = [e["kind"] for e in snapshot["events"]]
        self.assertEqual(kinds, ["WORKFLOW_REGISTERED", "ATTEMPT_STARTED", "RESULT_STAGED", "SIMULATION_REVIEW", "READINESS_CHANGED"])
        for sql in ("DELETE FROM events", "UPDATE events SET kind='changed'", "DELETE FROM reviews"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.ledger.db.execute(sql)

    def test_demo_reopen_is_read_only_and_produces_no_artwork(self):
        path = Path(self.temp.name) / "demo.sqlite"
        first = run(path)
        second = run(path)
        self.assertFalse(first["reopened_existing"])
        self.assertTrue(second["reopened_existing"])
        self.assertEqual(first["attempt_count"], 6)
        self.assertEqual(first["event_count"], second["event_count"])
        self.assertEqual(first["budget"], {"limit": 100, "spent": 18, "reserved": 0})
        self.assertFalse(first["approval_issued"])
        self.assertFalse(first["production_verified"])
        generations = {t["id"]: t["generation"] for t in first["tasks"]}
        self.assertEqual(generations["expression-calm"], 0)
        self.assertEqual(generations["expression-surprised"], 1)
        self.assertEqual(generations["package-fixture"], 1)


if __name__ == "__main__":
    unittest.main()
