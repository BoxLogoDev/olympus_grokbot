"""Safe five-line integration smoke. Creates TEST files in a new private directory.

This does not call Grokbot or count as real validation. The output directory must
not already exist. Keep it outside the public repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime.operations import Operations, POLICY_COMMIT, LINES, digest


def run(destination):
    destination.mkdir(parents=True, exist_ok=False)
    def file(name, content):
        (destination/name).write_text(content, encoding="utf-8")
        return {"id": name, "version": "1", "sha256": hashlib.sha256(content.encode()).hexdigest(), "path": name}
    evidence = file("test-evidence.txt", "Synthetic integration test evidence; not a user approval.")
    input_ref = file("test-input.txt", "TEST input")
    output = file("test-output.txt", "TEST output")
    catalog = json.loads((ROOT/"spec/process-slots-v1.json").read_text(encoding="utf-8"))["slots"]
    slot_id = "HEPHAESTUS-WEB-FRONTEND"; slot = catalog[slot_id]
    skill = {"id": "TEST-SKILL", "version": "1", "sha256": digest("TEST-SKILL")}
    db = destination/"test-operations.sqlite"
    ops = Operations(db, destination)
    try:
        for aid in ("TEST-WORKER", "TEST-REVIEWER"):
            binding = {"human_id": aid, "bot_id": aid, "slot_id": slot_id, "owner_god": slot["department"],
                       "single_job": slot["single_job"], "status": "ACTIVE", "skill_ref": skill, "tools": [],
                       "binding_evidence": evidence}
            ops.register(binding)
            (destination/(aid+".json")).write_text(json.dumps(binding, indent=2), encoding="utf-8")
        for line in sorted(LINES):
            project = {"mode": "OPERATIONS_EVIDENCE", "data_origin": "TEST", "project_id": "TEST-"+line,
                       "parent_project_id": None, "root_goal_id": "TEST-GOAL-"+line, "product_line": line,
                       "policy_ref": {"version": "1.3", "commit": POLICY_COMMIT},
                       "workflow_ref": {"id": "TEST-WORKFLOW-"+line, "version": "1", "sha256": digest(line)},
                       "plan_ref": evidence, "budget_unit": "TEST_INTEGER_UNITS", "max_cost_units": 100,
                       "max_active_tasks": 1, "max_pending_reviews": 1, "review_capacity": 1,
                       "review_budget_reserve_units": 10,
                       "tasks": [{"task_id": "test-file", "owner_human_id": "TEST-WORKER", "reviewer_human_id": "TEST-REVIEWER",
                                  "slot_id": slot_id, "runtime_binding": {"bot_id": "TEST-WORKER", "skill_ref": skill, "tools": []},
                                  "effect": "INTERNAL", "done_when": "TEST file metadata reviewed", "required_checks": ["TEST_FORMAT"],
                                  "inputs": [input_ref], "depends_on": [],
                                  "context": {"canon_ref": evidence, "canon_approval_evidence": evidence} if line in {"CHARACTER", "EMOTICON"} else {}}]}
            pid=project["project_id"]
            ops.create(project)
            aid=ops.claim(pid, "test-file", "TEST-WORKER", 5)["attempt_id"]
            result={"simulation": False, "artifacts": [output],
                    "checks": [{"id":"TEST_FORMAT", "passed":True, "evidence_ref":evidence}],
                    "external_execution":"NOT_PERFORMED"}
            cost={"units":2, "evidence_ref":evidence}
            rd=ops.submit(pid,"test-file",aid,"TEST-WORKER",result,cost)["result_digest"]
            ops.claim(pid,"test-file","TEST-REVIEWER",3,phase="REVIEW")
            ops.review(pid,"test-file",aid,"TEST-REVIEWER",rd,True,evidence,{"units":1,"evidence_ref":evidence})
            (destination/(line+"-create.json")).write_text(json.dumps(project,ensure_ascii=False,indent=2),encoding="utf-8")
            (destination/(line+"-export.json")).write_text(json.dumps(ops.export(pid),ensure_ascii=False,indent=2),encoding="utf-8")
        report=ops.report()
        assert report["excluded_test_projects"]==5
        assert all(r["measurement_status"]=="UNMEASURED" for r in report["lines"].values())
        (destination/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        return {"test_projects":5,"actual_manual_validation_runs":0,"external_calls":0,"runtime_verified":False}
    finally: ops.close()


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.output),indent=2))
