"""Import a deliberately exported JSON inventory from Notion/Craft/private files.

No network calls, credentials, app changes, or automatic actor activation.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from .operations import LINES, OperationError, digest, load_json, require

SECRET_KEYS = {"password", "token", "access_token", "refresh_token", "api_key", "secret",
               "authorization", "cookie", "credentials", "connection_string"}


def reject_secrets(value):
    if isinstance(value, dict):
        require(not any(k.lower().replace("-", "_") in SECRET_KEYS for k in value), "credential field forbidden in inventory")
        for item in value.values(): reject_secrets(item)
    elif isinstance(value, list):
        for item in value: reject_secrets(item)


def read_export(path):
    raw = Path(path).read_text(encoding="utf-8")
    if raw.lstrip().startswith("{"):
        return load_json(path)
    blocks = re.findall(r"```json\s*\n(.*?)\n```", raw, re.S)
    require(len(blocks) == 1, "provide exactly one JSON inventory block")
    # Reuse duplicate/nonfinite detection without temporary files.
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, "duplicate JSON key")
            result[k] = v
        return result
    def constant(_): raise OperationError("nonfinite JSON number")
    return json.loads(blocks[0], object_pairs_hook=pairs, parse_constant=constant)


def inspect_inventory(bundle):
    reject_secrets(bundle)
    require(bundle.get("schema_version") == "1.0", "unknown inventory version")
    require(bundle.get("source_ref") and bundle.get("collected_at"), "source and collection timestamp required")
    timestamp = datetime.fromisoformat(bundle["collected_at"])
    require(timestamp.tzinfo is not None, "timezone required")
    require(timestamp <= datetime.now(timezone.utc), "future inventory timestamp")
    bots = bundle.get("bots", []); routines = bundle.get("routines", []); runs = bundle.get("runs", [])
    require(all(isinstance(x, list) for x in [bots, routines, runs]), "inventory lists required")
    ids = [b["bot_id"] for b in bots]
    require(len(ids) == len(set(ids)), "duplicate Bot ID")
    findings = []
    for b in bots:
        if b.get("kind") == "HUMAN" and not all(b.get(k) for k in ("owner_god", "slot_id", "single_job", "skill_ref")):
            findings.append({"bot_id": b["bot_id"], "finding": "BINDING_INCOMPLETE", "action": "RECONFIRM_WITH_HESTIA"})
    triggers = {}
    for r in routines:
        require(r.get("routine_id") and r.get("owner_bot_id"), "routine identifiers required")
        signature = (r.get("purpose"), r.get("input_scope"), r.get("schedule"))
        if all(signature):
            triggers.setdefault(signature, []).append(r["routine_id"])
    for group in triggers.values():
        if len(group) > 1: findings.append({"routine_ids": group, "finding": "POSSIBLE_DUPLICATE_ROUTINE", "action": "REVIEW_ONLY"})
    reports = {}
    for line in sorted(LINES):
        selected = sorted([r for r in runs if r.get("product_line") == line],
                          key=lambda r: r.get("started_at", ""), reverse=True)[:20]
        reports[line] = {"inspected_runs": len(selected), "measurement_status": "SOURCE_RECORDS_ONLY" if selected else "UNMEASURED",
                         "missing_cost_records": sum(r.get("cost_units") is None for r in selected),
                         "runtime_verified": False}
    return {"schema_version": "1.0", "source_ref": bundle["source_ref"], "collected_at": bundle["collected_at"],
            "imported_at": datetime.now(timezone.utc).isoformat(), "source_sha256": digest(bundle),
            "bot_count": len(bots), "routine_count": len(routines), "findings": findings,
            "lines": reports, "grokbot_live_rechecked": False, "registrations_performed": 0,
            "limitations": ["Snapshot may be stale", "Supplied records are not authenticated execution evidence",
                            "No names, permissions, routines or human identities changed"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="PRIVATE new JSON report")
    args = parser.parse_args()
    try:
        report = inspect_inventory(read_export(args.input))
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
        print(json.dumps({"report_created": True, "registrations_performed": 0}))
    except (OperationError, OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__": main()
