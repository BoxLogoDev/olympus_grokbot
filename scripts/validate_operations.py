"""Check every shipped process Skill, blueprint, CLI contract and slot reference."""
import inspect
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime.operations import LINES, Operations, POLICY_COMMIT
from runtime.ops import COMMANDS


def main():
    import yaml
    catalog = json.loads((ROOT / "spec/process-slots-v1.json").read_text(encoding="utf-8"))
    source = yaml.safe_load((ROOT / "registry/slots.yaml").read_text(encoding="utf-8"))["slots"]
    expected = {s["slot_id"]: {"department": s["department"], "single_job": s["single_job"]} for s in source}
    assert catalog["slots"] == expected and len(expected) == 89
    assert catalog["policy_commit"] == POLICY_COMMIT
    blueprint = json.loads((ROOT / "templates/process-blueprints-v1.json").read_text(encoding="utf-8"))
    assert set(blueprint["lines"]) == LINES
    for line, item in blueprint["lines"].items():
        assert item["status"] == "DRAFT" and item["validation_runs"] == []
        seen = set()
        for stage in item["stages"]:
            assert stage["slot_id"] in expected and stage["review_slot_id"] in expected
            assert stage["stage_id"] not in seen and set(stage["depends_on"]) <= seen
            assert stage["required_checks"]
            seen.add(stage["stage_id"])
        skill = ROOT / item["skill_path"]
        content = skill.read_text(encoding="utf-8")
        assert content.startswith("---\nname: ") and "OLY-OPS-" in content
        assert all(stage["stage_id"] in content for stage in item["stages"])
    contract = json.loads((ROOT / "spec/process-cli-v1.json").read_text(encoding="utf-8"))
    assert set(contract["commands"]) == COMMANDS
    for command, fields in contract["commands"].items():
        method = "change_input" if command in {"retry", "change-input"} else command.replace("-", "_")
        actual = inspect.signature(getattr(Operations, method))
        assert set(fields["parameters"]) == set(actual.parameters) - {"self"}, command
    print(json.dumps({"result": "PASS", "lines": len(LINES), "slots": len(expected),
                      "runtime_verified": False}))


if __name__ == "__main__": main()
