"""Run metadata-only Bam fixtures, persist them, then invalidate one branch."""

import argparse
import json
from pathlib import Path

from .ledger import Ledger, digest


def run(db_path):
    spec_path = Path(__file__).resolve().parents[1] / "examples" / "bam-workflow.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    ledger = Ledger(db_path)
    try:
        project = spec["project_id"]
        exists = ledger.db.execute("SELECT 1 FROM projects WHERE id=?", (project,)).fetchone()
        if not exists:
            for task in spec["tasks"]:
                ledger.register_actor(task["owner"], "WORKER")
                ledger.register_actor(task["reviewer"], "REVIEWER")
            ledger.create_workflow(spec)

            def simulate(task):
                attempt = ledger.start(project, task["id"], task["owner"], max_cost_units=5)
                result = {"asset_id": f"placeholder:{attempt}", "simulation": True}
                ledger.stage_result(attempt, task["owner"], result, actual_cost_units=3)
                ledger.review(project, task["id"], task["reviewer"], accepted=True,
                              evidence="Fixture metadata only: schema and dependency journal checked; no art quality or canon approval.",
                              expected_attempt_id=attempt, expected_result_digest=digest(result))

            for task in spec["tasks"]:
                simulate(task)
            affected = ledger.change_input(project, "expression-surprised",
                                           {"expression": "당황", "leaf_fixture_version": 2, "fixture_only": True},
                                           reason="Demo partial invalidation: change only surprised-expression fixture.")
            for task in spec["tasks"]:
                if task["id"] in affected:
                    simulate(task)
        snapshot = ledger.snapshot(project)
        return {
            "mode": "LOCAL_SIMULATION",
            "message": "밤 작업의 자리표시자 메타데이터만 처리했습니다. 그림·영상 생성, 원형 승인, 외부 게시, 운영 검증은 수행하지 않았습니다.",
            "reopened_existing": bool(exists),
            "policy_version": snapshot["policy_version"],
            "policy_commit": snapshot["policy_commit"],
            "workflow_version": snapshot["workflow_version"],
            "budget": snapshot["budget"],
            "tasks": snapshot["tasks"],
            "attempt_count": len(snapshot["attempts"]),
            "event_count": len(snapshot["events"]),
            "unresolved_attempts": [a["id"] for a in snapshot["attempts"] if a["status"] in ("RUNNING", "UNKNOWN")],
            "approval_issued": False,
            "production_verified": False,
        }
    finally:
        ledger.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Local SQLite path; existing history is preserved")
    args = parser.parse_args()
    print(json.dumps(run(args.db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
