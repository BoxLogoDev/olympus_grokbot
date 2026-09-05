"""Operational file/transaction tests. Fixtures never count as real Grokbot runs."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from runtime.operations import Operations, OperationError, POLICY_COMMIT, digest
from runtime.ledger import Ledger


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dbpath = self.root / "operations.sqlite"
        self.ops = Operations(self.dbpath, self.root)
        self.addCleanup(lambda: self.ops.close())
        self.evidence = self.file("evidence.txt", "TEST fixture evidence")
        self.input = self.file("input.txt", "input-v1")
        self.output = self.file("output.txt", "output-v1")
        slots = json.loads((Path(__file__).parents[1] / "spec/process-slots-v1.json").read_text(encoding="utf-8"))["slots"]
        self.slot = next(k for k in slots if k == "HEPHAESTUS-WEB-FRONTEND")
        self.slot_data = slots[self.slot]
        self.skill = {"id": "test-skill", "version": "1", "sha256": digest("test")}
        for aid in ["worker", "other", "reviewer", "reviewer2"]:
            self.ops.register({"human_id": aid, "bot_id": "TEST-" + aid, "slot_id": self.slot,
                               "owner_god": self.slot_data["department"], "single_job": self.slot_data["single_job"],
                               "status": "ACTIVE", "skill_ref": self.skill, "tools": ["file"],
                               "binding_evidence": self.evidence})
        self.ops.create(self.spec())

    def file(self, name, content):
        (self.root / name).write_text(content, encoding="utf-8")
        return {"id": name, "version": "1", "sha256": hashlib.sha256(content.encode()).hexdigest(), "path": name}

    def spec(self, pid="p", tasks=None, parent=None):
        tasks = tasks or [self.task("a"), self.task("b", ["a"]), self.task("c", owner="other")]
        return {"mode": "OPERATIONS_EVIDENCE", "data_origin": "TEST", "project_id": pid, "parent_project_id": parent,
                "root_goal_id": "goal-" + pid, "product_line": "WEB_APP", "policy_ref": {"version": "1.3", "commit": POLICY_COMMIT},
                "workflow_ref": {"id": "workflow", "version": "1", "sha256": digest("workflow")},
                "plan_ref": self.evidence, "budget_unit": "TEST_INTEGER_UNITS", "max_cost_units": 100,
                "max_active_tasks": 2, "max_pending_reviews": 2, "review_capacity": 1,
                "review_budget_reserve_units": 10, "tasks": tasks}

    def task(self, tid, deps=None, owner="worker", reviewer="reviewer"):
        return {"task_id": tid, "owner_human_id": owner, "reviewer_human_id": reviewer,
                "slot_id": self.slot, "runtime_binding": {"bot_id": "TEST-" + owner, "skill_ref": self.skill, "tools": ["file"]},
                "effect": "INTERNAL", "done_when": "Fixture output accepted", "required_checks": ["format"],
                "inputs": [self.input], "memory_refs": [], "depends_on": deps or []}

    def cost(self, n=2):
        return {"units": n, "evidence_ref": self.evidence}

    def result(self):
        return {"simulation": False, "artifacts": [self.output],
                "checks": [{"id": "format", "passed": True, "evidence_ref": self.evidence}],
                "external_job_id": None, "external_execution": "NOT_PERFORMED"}

    def claim(self, task="a", project="p", owner="worker", n=5):
        return self.ops.claim(project, task, owner, n)["attempt_id"]

    def submit(self, task="a", project="p", owner="worker", n=2):
        aid = self.claim(task, project, owner)
        result = self.ops.submit(project, task, aid, owner, self.result(), self.cost(n))
        return aid, result["result_digest"]

    def finish(self, task="a", project="p", owner="worker"):
        aid, rd = self.submit(task, project, owner)
        self.ops.claim(project, task, "reviewer", 3, phase="REVIEW")
        self.ops.review(project, task, aid, "reviewer", rd, True, self.evidence, self.cost(1))
        return aid, rd

    def state(self, task="a", project="p"):
        return self.ops.status(project)["project"]["tasks"][task]

    def test_files_review_and_dependency(self):
        self.assertEqual(self.state("b")["state"], "DRAFT")
        aid, rd = self.submit()
        self.assertEqual(self.state()["state"], "REVIEW")
        with self.assertRaises(OperationError):
            self.ops.review("p", "a", aid, "worker", rd, True, self.evidence, self.cost())
        self.ops.claim("p", "a", "reviewer", 3, phase="REVIEW")
        with self.assertRaises(OperationError):
            self.ops.review("p", "a", aid, "reviewer", "0" * 64, True, self.evidence, self.cost())
        self.ops.review("p", "a", aid, "reviewer", rd, True, self.evidence, self.cost(1))
        self.assertEqual(self.state("b")["state"], "READY")
        self.assertEqual(self.ops.status("p")["project"]["spent"], 3)

    def test_changed_file_blocks_submit_and_keeps_lease(self):
        aid = self.claim()
        (self.root / "output.txt").write_text("changed", encoding="utf-8")
        with self.assertRaises(OperationError):
            self.ops.submit("p", "a", aid, "worker", self.result(), self.cost())
        self.assertEqual(self.state()["state"], "RUNNING")
        self.assertEqual(self.ops.status("p")["project"]["reserved"], 5)

    def test_artifact_escape_and_placeholders(self):
        outside = dict(self.input, path="../outside")
        with self.assertRaises((OperationError, OSError)): self.ops.artifact(outside)
        with self.assertRaises(OperationError): self.ops.artifact(dict(self.input, path="/etc/passwd"))
        with self.assertRaises(OperationError): self.ops.register({"human_id": "<todo>"})

    def test_duplicate_submit_does_not_charge_or_append(self):
        aid, rd = self.submit()
        before = self.ops.export("p")
        self.assertTrue(self.ops.submit("p", "a", aid, "worker", self.result(), self.cost())["idempotent"])
        self.assertEqual(before, self.ops.export("p"))
        with self.assertRaises(OperationError):
            self.ops.submit("p", "a", aid, "worker", self.result(), self.cost(3))

    def test_restart_preserves_unknown_and_does_not_repeat(self):
        aid = self.claim()
        self.ops.block("p", "a", "connection lost")
        other = Operations(self.dbpath, self.root)
        try:
            self.assertEqual(other.status("p")["project"]["reserved"], 5)
            with self.assertRaises(OperationError): other.claim("p", "a", "worker", 5)
        finally: other.close()
        self.ops.reconcile("p", "a", aid, "reviewer", "SUCCEEDED", self.evidence, self.cost(), self.result())
        self.assertEqual(self.state()["state"], "REVIEW")
        self.assertEqual(self.ops.status("p")["project"]["reserved"], 0)

    def test_unknown_cost_is_not_zero(self):
        aid = self.claim()
        self.ops.submit("p", "a", aid, "worker", self.result(), None)
        self.assertEqual(self.state()["block_reason"], "COST_UNMEASURED")
        self.assertEqual(self.ops.status("p")["project"]["spent"], 0)
        self.assertEqual(self.ops.status("p")["project"]["reserved"], 5)
        self.ops.reconcile("p", "a", aid, "reviewer", "SUCCEEDED", self.evidence, self.cost(4))
        self.assertEqual(self.ops.status("p")["project"]["spent"], 4)

    def test_overrun_records_full_cost_and_halts(self):
        aid = self.claim(n=5)
        self.ops.submit("p", "a", aid, "worker", self.result(), self.cost(120))
        p = self.ops.status("p")["project"]
        self.assertEqual(p["spent"], 120)
        self.assertTrue(p["halted"])
        with self.assertRaises(OperationError): self.claim("c", owner="other")

    def test_same_failure_blocks_across_retry_cards(self):
        for _ in range(2):
            aid = self.claim()
            self.ops.block("p", "a", "timeout")
            self.ops.reconcile("p", "a", aid, "reviewer", "FAILED", self.evidence, self.cost(),
                               failure_key="tool.timeout", failure_class="TOOL")
        self.assertEqual(self.state()["state"], "BLOCKED")
        new_input = self.file("new.txt", "new")
        self.ops.change_input("p", "a", [new_input], "retry explanation", retry_card_id="card-2")
        self.assertEqual(self.state()["state"], "BLOCKED")
        self.assertEqual(len(self.state()["attempts"]), 2)
        with self.assertRaises(OperationError): self.claim()

    def test_partial_change_preserves_independent_output_and_history(self):
        self.finish(); self.finish("b"); self.finish("c", owner="other")
        before = self.state("c")
        changed = self.ops.change_input("p", "a", [self.file("v2.txt", "v2")], "new input")
        self.assertEqual(changed["affected_tasks"], ["a", "b"])
        self.assertEqual(before, self.state("c"))
        self.assertEqual(self.state()["attempts"][0]["status"], "ACCEPTED")
        self.assertEqual(self.ops.status("p")["project"]["spent"], 9)
        self.assertEqual(self.state()["state"], "READY")

    def test_inflight_change_is_rejected(self):
        self.claim()
        with self.assertRaises(OperationError):
            self.ops.change_input("p", "a", [self.input], "changed")
        self.assertEqual(self.state()["generation"], 0)

    def test_backpressure_keeps_review_drain_available(self):
        spec = self.spec("limited", [self.task("x"), self.task("y", owner="other")])
        spec["max_pending_reviews"] = 1
        self.ops.create(spec)
        aid, rd = self.submit("x", "limited")
        with self.assertRaisesRegex(OperationError, "BACKPRESSURE"):
            self.claim("y", "limited", "other")
        self.ops.claim("limited", "x", "reviewer", 3, phase="REVIEW")
        self.ops.review("limited", "x", aid, "reviewer", rd, True, self.evidence, self.cost(1))
        self.claim("y", "limited", "other")

    def test_parent_budget_and_concurrency(self):
        self.ops.create(self.spec("child", [self.task("x")], parent="p"))
        self.claim("x", "child", n=60)
        self.assertEqual(self.ops.status("p")["project"]["reserved"], 60)
        with self.assertRaises(OperationError): self.claim("c", owner="other", n=31)
        with self.assertRaises(OperationError): self.ops.create(self.spec("p"))
        duplicate = self.spec("duplicate"); duplicate["root_goal_id"] = "goal-p"
        with self.assertRaises(OperationError): self.ops.create(duplicate)

    def test_concurrent_global_claim_is_atomic(self):
        self.ops.create(self.spec("other", [self.task("x")]))
        def attempt(pid, tid):
            ledger = Operations(self.dbpath, self.root)
            try:
                ledger.claim(pid, tid, "worker", 5)
                return True
            except OperationError: return False
            finally: ledger.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt, "p", "a"), pool.submit(attempt, "other", "x")]
            self.assertEqual(sum(f.result() for f in futures), 1)

    def test_interrupted_review_cost_preserved_and_reclaimed(self):
        aid, rd = self.submit()
        self.ops.claim("p", "a", "reviewer", 3, phase="REVIEW")
        self.ops.block("p", "a", "review process interrupted")
        self.ops.reconcile("p", "a", aid, "reviewer", "FAILED", self.evidence, self.cost(1))
        self.assertEqual(self.state()["state"], "REVIEW")
        self.ops.claim("p", "a", "reviewer", 3, phase="REVIEW")
        self.ops.review("p", "a", aid, "reviewer", rd, True, self.evidence, self.cost(1))
        self.assertEqual(self.ops.status("p")["project"]["spent"], 4)

    def test_external_claim_never_dispatches_or_uses_fake_approval(self):
        t = self.task("publish"); t["effect"] = "EXTERNAL"
        self.ops.create(self.spec("external", [t]))
        with self.assertRaisesRegex(OperationError, "AUTHENTICATED_GATEWAY"):
            self.claim("publish", "external")
        self.assertEqual(self.ops.status("external")["project"]["spent"], 0)

    def test_simulation_database_cannot_be_opened_as_operations(self):
        path = self.root / "sim.sqlite"
        sim = Ledger(path); sim.close()
        with self.assertRaisesRegex(OperationError, "foreign"):
            Operations(path, self.root)

    def test_failure_review_requires_repair_scope_and_counter(self):
        aid, rd = self.submit()
        self.ops.claim("p", "a", "reviewer", 3, phase="REVIEW")
        with self.assertRaises(OperationError):
            self.ops.review("p", "a", aid, "reviewer", rd, False, self.evidence, self.cost())
        self.ops.review("p", "a", aid, "reviewer", rd, False, self.evidence, self.cost(1),
                        failed_checks=["quality"], repair_tasks=["a"], reusable_tasks=["c"],
                        failure_class="QUALITY", failure_key="meaning")
        self.assertEqual(self.state()["revision"], 1)
        self.assertEqual(self.state()["state"], "READY")

    def memory_record(self):
        return {"id": "m", "version": "1", "statement": "Test scoped procedure", "kind": "PROCEDURE",
                "evidence_refs": [self.evidence], "proposed_by": "worker", "scope": {"project_id": "p"},
                "valid_from": "2026-01-01T00:00:00+00:00", "expires_at": "2099-01-01T00:00:00+00:00"}

    def test_memory_requires_verification_and_revocation_blocks_inputs(self):
        memory = self.ops.memory("propose", self.memory_record())
        ref = {"id": "m", "version": "1", "sha256": memory["content_hash"]}
        with self.ops.transaction():
            p = self.ops.project("p"); p["tasks"]["a"]["memory_refs"] = [ref]; self.ops.save(p)
        with self.assertRaises(OperationError): self.claim()
        req = {"id": "m", "version": "1", "actor_id": "reviewer", "evidence_ref": self.evidence}
        self.ops.memory("verify", req)
        self.ops.memory("activate", dict(req, hestia_write_validation_ref=self.evidence))
        self.finish()
        self.ops.memory("revoke", dict(req, reason="counterexample"))
        with self.assertRaises(OperationError): self.claim("b")

    def test_test_data_never_becomes_manual_validation_or_real_metrics(self):
        self.finish(); self.finish("b"); self.finish("c", owner="other")
        with self.assertRaisesRegex(OperationError, "TEST"):
            self.ops.validation({"project_id": "p"})
        report = self.ops.report()
        self.assertEqual(report["excluded_test_projects"], 1)
        self.assertTrue(all(r["measurement_status"] == "UNMEASURED" for r in report["lines"].values()))

    def test_append_only_events(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.ops.db.execute("DELETE FROM events")
        with self.assertRaises(sqlite3.IntegrityError):
            self.ops.db.execute("UPDATE events SET kind='fake'")

    def test_cli_error_is_structured_nonzero(self):
        proc = subprocess.run([sys.executable, "-m", "runtime.ops", "status", "--db", str(self.dbpath),
                               "--artifact-root", str(self.root), "--project", "missing"],
                              capture_output=True, text=True, cwd=Path(__file__).parents[1])
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(json.loads(proc.stderr)["ok"])

    def test_changed_output_invalidates_completion(self):
        self.finish(); self.finish("b"); self.finish("c", owner="other")
        self.assertEqual(self.ops.status("p")["production_status"], "COMPLETED")
        (self.root / "output.txt").write_text("tampered", encoding="utf-8")
        state = self.ops.status("p")
        self.assertEqual(state["production_status"], "INCOMPLETE")
        self.assertTrue(state["review_required"])

    def test_observation_duplicate_is_not_counted_twice(self):
        record = {"observation_id": "change-1", "kind": "USER_CHANGE",
                  "change_class": "SCOPE_CHANGE", "evidence_ref": self.evidence}
        self.ops.observe("p", record)
        self.assertTrue(self.ops.observe("p", record)["idempotent"])
        with self.assertRaises(OperationError):
            self.ops.observe("p", dict(record, change_class="QUALITY_FIX"))

    def test_no_fake_deployment_from_unvalidated_version(self):
        record = {"product_line":"WEB_APP", "workflow_ref":self.spec()["workflow_ref"],
                  "policy_ref":self.spec()["policy_ref"], "hestia_decision_ref":self.evidence}
        with self.assertRaisesRegex(OperationError, "two distinct"):
            self.ops.deployment("activate", record)
        self.assertFalse(self.ops.db.execute("SELECT * FROM deployments").fetchall())

    def test_shared_reference_invalidates_all_projects_atomically(self):
        self.finish("a")
        self.ops.create(self.spec("q", [self.task("a")]))
        self.finish("a", "q")
        replacement = self.file("input-v2.txt", "new input")
        replacement["id"] = self.input["id"]; replacement["version"] = "2"
        result = self.ops.change_reference(self.input, replacement, "shared asset correction", self.evidence)
        self.assertEqual(result["affected"], {"p": ["a", "b", "c"], "q": ["a"]})
        self.assertEqual(self.ops.status("p")["project"]["spent"], 3)
        self.assertEqual(len(self.state()["attempts"]), 1)
        self.assertEqual(self.state("a", "q")["state"], "READY")

    def test_shared_change_rolls_back_when_one_consumer_is_running(self):
        self.ops.create(self.spec("q", [self.task("a")]))
        self.claim("a", "q")
        replacement = dict(self.file("v2.txt", "v2"), id=self.input["id"], version="2")
        before = self.ops.export("p")
        with self.assertRaises(OperationError):
            self.ops.change_reference(self.input, replacement, "change", self.evidence)
        self.assertEqual(before, self.ops.export("p"))

    def test_same_workflow_ref_cannot_hide_changed_real_behavior(self):
        first = self.spec("real-one", [self.task("a")]); first["data_origin"] = "REAL"
        self.ops.create(first)
        changed = self.spec("real-two", [self.task("a")]); changed["data_origin"] = "REAL"
        changed["tasks"][0]["required_checks"].append("security")
        with self.assertRaisesRegex(OperationError, "behavior changed"):
            self.ops.create(changed)

    def test_manual_validation_snapshot_does_not_follow_revised_results(self):
        # REAL flag only exercises a gate in an isolated fixture, never a real run.
        for pid in ("r1", "r2"):
            spec = self.spec(pid, [self.task("a")]); spec["data_origin"] = "REAL"
            self.ops.create(spec); self.finish("a", pid)
            self.ops.validation({"project_id": pid, "run_id": pid, "actual_manual_e2e": True,
                                 "unexpected_interventions": 0, "reviewed_by": "reviewer",
                                 "evidence_ref": self.evidence, "hestia_review_ref": self.evidence})
        deployment = {"product_line": "WEB_APP", "workflow_ref": self.spec()["workflow_ref"],
                      "policy_ref": self.spec()["policy_ref"], "hestia_decision_ref": self.evidence}
        self.assertFalse(self.ops.deployment("activate", deployment)["grokbot_settings_modified"])
        self.ops.change_input("r1", "a", [self.file("new.txt", "revised")], "revision")
        self.finish("a", "r1")
        with self.assertRaisesRegex(OperationError, "validation run changed"):
            self.ops.deployment("activate", deployment)

    def test_reuse_requires_matching_inputs_and_still_independent_review(self):
        self.finish("a")
        self.ops.create(self.spec("q", [self.task("a")]))
        result = self.ops.reuse("q", "a")
        self.assertEqual(len(result["candidates"]), 1)
        self.assertFalse(result["automatic_completion"])
        self.assertEqual(self.state("a", "q")["state"], "READY")
        (self.root / "output.txt").write_text("mutated", encoding="utf-8")
        self.assertEqual(self.ops.reuse("q", "a")["candidates"], [])

    def test_binding_version_stops_old_task_and_preserves_identity(self):
        self.ops.update_binding("worker", dict(self.skill, version="2", sha256=digest("v2")), ["file"], self.evidence)
        with self.assertRaisesRegex(OperationError, "binding skill changed"):
            self.claim()
        self.assertEqual(self.ops.actor("worker")["bot_id"], "TEST-worker")
        handoff = self.ops.handoff("p", "a")
        self.assertEqual(handoff["remaining_limits"]["p"]["cost_units"], 100)
        self.assertEqual(handoff["inputs"], [self.input])

    def test_report_excludes_invalidated_accepted_artifact(self):
        spec = self.spec("real", [self.task("a")]); spec["data_origin"] = "REAL"
        self.ops.create(spec); self.finish("a", "real")
        self.assertEqual(self.ops.report()["lines"]["WEB_APP"]["accepted_output_count"], 1)
        (self.root / "output.txt").write_text("mutated", encoding="utf-8")
        self.assertEqual(self.ops.report()["lines"]["WEB_APP"]["accepted_output_count"], 0)

    def test_input_mutation_cannot_pass_review(self):
        aid, rd = self.submit()
        self.ops.claim("p", "a", "reviewer", 3, phase="REVIEW")
        (self.root / "input.txt").write_text("changed input", encoding="utf-8")
        with self.assertRaisesRegex(OperationError, "digest mismatch"):
            self.ops.review("p", "a", aid, "reviewer", rd, True, self.evidence, self.cost())
        self.assertEqual(self.state()["state"], "REVIEWING")

    def test_expired_memory_cannot_be_injected(self):
        record = self.memory_record()
        record.update(valid_from="2000-01-01T00:00:00+00:00", expires_at="2001-01-01T00:00:00+00:00")
        memory = self.ops.memory("propose", record)
        req = {"id": "m", "version": "1", "actor_id": "reviewer", "evidence_ref": self.evidence}
        self.ops.memory("verify", req)
        self.ops.memory("activate", dict(req, hestia_write_validation_ref=self.evidence))
        self.ops.change_input("p", "a", [self.input], "memory",
                              memory_refs=[{"id": "m", "version": "1", "sha256": memory["content_hash"]}])
        with self.assertRaisesRegex(OperationError, "outside validity"):
            self.claim()
