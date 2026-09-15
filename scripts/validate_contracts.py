"""Static repository contract checks; not a production policy enforcement engine."""

from pathlib import Path
import json
import re
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def read(path):
    return yaml.load((ROOT/path).read_text(encoding="utf-8"), Loader=UniqueLoader)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def resolve(value, dotted):
    for key in dotted.split("."):
        require(isinstance(value, dict) and key in value, f"Unresolved contract reference: {dotted}")
        value = value[key]
    return value


def validate_current_policies(core, slots):
    """Reject inconsistent policy configurations; does not authorize live actions."""
    role = core["role_boundary_policy"]
    by_id = {slot["slot_id"]: slot for slot in slots}
    require(len(by_id) == len(slots) == role["slot_catalog_count"], "Slot count or ID uniqueness mismatch")
    eligible = [s for s in slots if s.get("assignable", True)
                and s["status"] not in role["non_assignable_statuses"]]
    require(len(eligible) == role["assignable_slot_count"], "Assignable slot count mismatch")
    for old_id, new_id in role["retired_slots"].items():
        old, new = by_id[old_id], by_id[new_id]
        require(old["status"] == "SUPERSEDED" and old.get("assignable") is False,
                f"Legacy artwork slot still assignable: {old_id}")
        require(old["superseded_by"] == new_id and new["replaces_slot_id"] == old_id,
                f"Broken slot migration: {old_id}")
        require(new["department"] == "APHRODITE" and new in eligible,
                f"Artwork routed outside Aphrodite: {new_id}")
    require(set(role["artwork_slots"]) == set(role["retired_slots"].values()), "Artwork slot mapping mismatch")
    require(all(by_id[x]["department"] == role["artwork_owner"] == "APHRODITE"
                for x in role["artwork_slots"]), "Artwork owner mismatch")
    require(role["creative_character_motion_owner"] == "APHRODITE", "Motion owner mismatch")
    require(role["file_conversion_owner"] == role["video_assembly_owner"] == "HEPHAESTUS",
            "File processing owner mismatch")
    require(not role["conversion_allows_redraw"] and not role["conversion_allows_generative_fill"],
            "Conversion must not authorize artwork")
    require(not role["existing_human_auto_reparent"] and not role["existing_human_delete"],
            "Human retention mismatch")

    queue, batch = core["youtube_queue_policy"], core["batch_approval_policy"]
    require(queue["admission_review_states"] == ["PASS"] and queue["review_must_match_current_artifact_hash"],
            "Queue admits unreviewed or conditional artifacts")
    require({"CONDITIONAL_PASS", "FAIL", "UNREVIEWED"} <= set(queue["hold_review_states"]), "Missing hold states")
    require(not queue["admission_asks_zeus"] and not queue["admission_grants_publication"],
            "Queue admission and publication authority are conflated")
    require(queue["slots"] == core["youtube_playbook"]["scoped_channels"]["publication_slots_preserve_existing"],
            "Conflicting publication slots")
    require(not queue["gap_filling_allowed"] and not queue["fatal_giggle_allowed"], "Retired content or gaps reactivated")
    require(batch["mode"] == "FINITE_IMMUTABLE_MANIFEST_LIST" and batch["authenticated_zeus_event_required"],
            "Batch approval has no authenticated finite scope")
    require(batch["per_item_token_max_executions"] == core["risk_classes"]["R2"]["max_executions"] == 1,
            "Batch token permits repeated external actions")
    require(not batch["new_items_inherit_approval"] and not batch["review_pass_is_approval"],
            "Unapproved items inherit publication authority")
    require(batch["mutations_require_new_batch_approval"] and batch["replacement_revokes_unused_old_tokens"]
            and batch["replacement_revocation_and_issuance_atomic"] and batch["idempotency_survives_batch_replacement"],
            "Batch replacement permits stale or duplicate publication")
    require(batch["unknown_outcome"] == core["approval_execution_policy"]["unknown_outcome"],
            "Batch unknown outcome bypasses reconciliation")
    handoff = core["execution_handoff_policy"]
    require(handoff["normal_gateway"] == core["invariants"]["zeus_gateway"] == "HESTIA",
            "Execution handoff changed the normal gateway")
    require(not handoff["permission_denial_bypass_allowed"] and not handoff["agent_message_is_user_approval"]
            and handoff["completion_requires_remote_receipt"], "Unsafe execution handoff")
    emo = core["emoticon_project_policy"]
    require(emo["distinct_product_project_id"] and not emo["name_match_implies_shared_canon"], "Product/canon conflation")
    require(not emo["generative_allowed_implies_submission_pass"] and not emo["blanket_generative_ban"],
            "Draft method policy conflates permission and submission quality")
    require({"APPROVED_CANON", "EXACT_ARTIFACT_REVIEW_PASS", "ZEUS_SUBMISSION_APPROVAL"}
            <= set(emo["submission_requires"]), "Submission gates missing")


def main():
    paths = list(ROOT.glob("spec/*.yaml")) + list(ROOT.glob("templates/*.yaml")) + list(ROOT.glob("registry/*.yaml")) + list(ROOT.glob("characters/*/*.yaml"))
    for path in paths:
        list(yaml.load_all(path.read_text(encoding="utf-8"), Loader=UniqueLoader))
    core = read("spec/olympus-contracts-v1.yaml")["olympus"]
    ops = read("spec/operations-v1.yaml")["operations"]
    require(core["architecture_version"] == ops["architecture_version"] == "1.4", "Architecture version mismatch")
    require(core["runtime_status"] == ops["runtime_status"] == "LOCAL_SIMULATION_ONLY", "Runtime status mismatch")
    for paths in core["rule_bindings"].values():
        for path in paths:
            resolve(core, path)
    for rule_id, path in ops["rule_bindings"].items():
        require(resolve(ops, path)["rule_id"] == rule_id, f"Operations rule mismatch: {rule_id}")
        require(rule_id in core["rule_bindings"], f"Missing core binding: {rule_id}")
    for item in core["operations_policy"].values():
        if isinstance(item, dict) and "contract_ref" in item:
            resolve({"operations": ops}, item["contract_ref"])
    examples = list(yaml.load_all((ROOT/"templates/contracts.example.yaml").read_text(encoding="utf-8"), Loader=UniqueLoader))
    example_contracts = {
        "WORKFLOW_PROPOSAL": ("workflow", ops["workflow_reuse"]["required_fields"]),
        "PROJECT_RESOURCE_POLICY": ("resource_policy", ops["resource_control"]["required_project_fields"]),
        "CHECKPOINT": ("checkpoint", ops["checkpoint_and_invalidation"]["required_fields"]),
        "MEMORY_PROPOSAL": ("memory", ops["curated_memory"]["required_fields"]),
        "VERSION_CHANGE_PROPOSAL": ("change", ops["version_change"]["required_fields"]),
    }
    for example in examples:
        if example and example.get("kind") in example_contracts:
            payload, fields = example_contracts[example["kind"]]
            require(set(fields) <= set(example[payload]), f"Incomplete example: {example['kind']}")
    require(set(core["project_lines"]) == {"YOUTUBE", "EMOTICON", "WEB_APP", "BLOG", "CHARACTER"}, "Project line mismatch")
    slots = read("registry/slots.yaml")["slots"]
    by_id = {slot["slot_id"]: slot for slot in slots}
    validate_current_policies(core, slots)
    architecture = (ROOT/"OLYMPUS_Agent_Architecture_v1.4.md").read_text(encoding="utf-8")
    prompts = (ROOT/"prompts/OLYMPUS_Bot_Prompts_v1.4.md").read_text(encoding="utf-8")
    for slot in slots:
        require(slot["department"] in core["gods"], f"Unknown department: {slot['slot_id']}")
        require(slot["slot_id"].startswith(core["gods"][slot["department"]]["allowed_slot_prefix"]),
                f"Slot prefix/department mismatch: {slot['slot_id']}")
        require(slot["slot_id"] in architecture, f"Missing slot catalog entry: {slot['slot_id']}")
    for rule_id in ops["rule_bindings"]:
        require(rule_id in architecture and rule_id in prompts, f"Missing rule in architecture/prompts: {rule_id}")
    for field in ("decision_precedence_policy", "role_boundary_policy", "execution_handoff_policy",
                  "emoticon_project_policy", "youtube_production_policy", "youtube_queue_policy", "batch_approval_policy"):
        rule_id = core[field]["rule_id"]
        require(rule_id in architecture and rule_id in prompts, f"Missing current rule: {rule_id}")
        require(field in core["rule_bindings"][rule_id], f"Unbound current policy: {field}")
    templates = read("templates/character-production.yaml")["templates"] + read("templates/emoticon-draft.yaml")["templates"]
    required = set(core["execution_template_policy"]["required_fields"])
    for template in templates:
        require(required <= set(template), f"Incomplete template: {template.get('template_id')}")
        slot = by_id[template["slot_id"]]
        require(slot.get("assignable", True) and slot["status"] != "SUPERSEDED", "Template uses retired slot")
        require(template["single_job"] == slot["single_job"] and template["parent_god"] == slot["department"], "Template/slot mismatch")
        for field in ("max_attempts_per_revision", "max_same_failure_occurrences", "max_revision_rounds", "max_total_attempts"):
            require(template["failure_policy"][field] == core["retry_policy"][field], f"Retry contract mismatch: {field}")
    emo_example = read("templates/emoticon-project.yaml")["project"]
    require(set(core["emoticon_project_policy"]["required_fields"]) <= set(emo_example), "Incomplete emoticon example")
    require(emo_example["submit_requires_zeus"] is True and emo_example["canon_ref"] is None,
            "Draft example claims submission or canon approval")
    require(by_id[emo_example["artwork_source"]["slot_id"]]["department"] == "APHRODITE", "Draft example owner mismatch")
    character = read("characters/bam/character.yaml")
    sources = {source["source_id"] for source in character["sources"]}
    variants = character["variants"]
    require(len(variants) == len({v["variant_id"] for v in variants}) == 36, "Bam variant count/ID mismatch")
    require(all(v["source_id"] in sources for v in variants), "Unknown character source")
    require(all(ref in sources for ref in character["canon"]["candidate_reference_source_ids"]), "Unknown canon reference")
    current_docs = [ROOT/"README.md", ROOT/"OLYMPUS_Agent_Architecture_v1.4.md", ROOT/"prompts/OLYMPUS_Bot_Prompts_v1.4.md", ROOT/"runtime/README.md"] + list((ROOT/"playbooks").glob("*.md")) + list((ROOT/"docs/decisions").glob("*.md"))
    for path in current_docs:
        text = path.read_text(encoding="utf-8")
        require(text.count("```") % 2 == 0, f"Unclosed fenced block: {path.name}")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if target.startswith(("https://", "http://", "#")):
                continue
            require((path.parent/target.split("#")[0]).exists(), f"Missing document link: {path.name}: {target}")
    print(json.dumps({"result": "PASS", "scope": "STATIC_REPOSITORY_CONTRACTS_ONLY", "slots": len(slots),
                      "project_lines": len(core["project_lines"]), "operation_rules": len(ops["rule_bindings"]),
                      "runtime_verified": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, yaml.YAMLError) as exc:
        print(f"Contract validation failed: {exc}", file=sys.stderr)
        sys.exit(1)
