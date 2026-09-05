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


def main():
    paths = list(ROOT.glob("spec/*.yaml")) + list(ROOT.glob("templates/*.yaml")) + list(ROOT.glob("registry/*.yaml")) + list(ROOT.glob("characters/*/*.yaml"))
    for path in paths:
        list(yaml.load_all(path.read_text(encoding="utf-8"), Loader=UniqueLoader))
    core = read("spec/olympus-contracts-v1.yaml")["olympus"]
    ops = read("spec/operations-v1.yaml")["operations"]
    require(core["architecture_version"] == ops["architecture_version"] == "1.3", "Architecture version mismatch")
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
    require(len(by_id) == len(slots) == 89, "Slot count or ID uniqueness mismatch")
    architecture = (ROOT/"OLYMPUS_Agent_Architecture_v1.3.md").read_text(encoding="utf-8")
    prompts = (ROOT/"prompts/OLYMPUS_Bot_Prompts_v1.3.md").read_text(encoding="utf-8")
    for slot in slots:
        require(slot["department"] in core["gods"], f"Unknown department: {slot['slot_id']}")
        require(slot["slot_id"] in architecture, f"Missing slot catalog entry: {slot['slot_id']}")
    for rule_id in ops["rule_bindings"]:
        require(rule_id in architecture and rule_id in prompts, f"Missing rule in architecture/prompts: {rule_id}")
    templates = read("templates/character-production.yaml")["templates"]
    required = set(core["execution_template_policy"]["required_fields"])
    for template in templates:
        require(required <= set(template), f"Incomplete template: {template.get('template_id')}")
        slot = by_id[template["slot_id"]]
        require(template["single_job"] == slot["single_job"] and template["parent_god"] == slot["department"], "Template/slot mismatch")
        for field in ("max_attempts_per_revision", "max_same_failure_occurrences", "max_revision_rounds", "max_total_attempts"):
            require(template["failure_policy"][field] == core["retry_policy"][field], f"Retry contract mismatch: {field}")
    character = read("characters/bam/character.yaml")
    sources = {source["source_id"] for source in character["sources"]}
    variants = character["variants"]
    require(len(variants) == len({v["variant_id"] for v in variants}) == 36, "Bam variant count/ID mismatch")
    require(all(v["source_id"] in sources for v in variants), "Unknown character source")
    require(all(ref in sources for ref in character["canon"]["candidate_reference_source_ids"]), "Unknown canon reference")
    current_docs = [ROOT/"README.md", ROOT/"OLYMPUS_Agent_Architecture_v1.3.md", ROOT/"prompts/OLYMPUS_Bot_Prompts_v1.3.md", ROOT/"runtime/README.md"] + list((ROOT/"playbooks").glob("*.md")) + list((ROOT/"docs/decisions").glob("*.md"))
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
