"""Import a deliberately exported JSON inventory from Notion/Craft/private files.

No network calls, credentials, app changes, or automatic actor activation.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from .operations import LINES, OperationError, digest, load_json, require

BRIDGE_VERSION = "0.1.1"

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
    require(bool(blocks[0].strip()), "EXPORT_INCOMPLETE: JSON block is empty; provide the readable inventory payload")
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
    require(isinstance(bundle, dict), "inventory must be a JSON object")
    reject_secrets(bundle)
    require(bundle.get("schema_version") == "1.0", "unknown inventory version")
    require(bundle.get("source_ref") and bundle.get("collected_at"), "source and collection timestamp required")
    timestamp = datetime.fromisoformat(bundle["collected_at"])
    require(timestamp.tzinfo is not None, "timezone required")
    require(timestamp <= datetime.now(timezone.utc), "future inventory timestamp")
    require(all(k in bundle for k in ("bots", "routines", "runs")), "EXPORT_INCOMPLETE: explicit bots, routines and runs lists required")
    bots = bundle["bots"]; routines = bundle["routines"]; runs = bundle["runs"]
    require(all(isinstance(x, list) for x in [bots, routines, runs]), "inventory lists required")
    for name, values in (("bots", bots), ("routines", routines), ("runs", runs)):
        require(all(isinstance(value, dict) for value in values), f"{name}: object records required")
    for index, run in enumerate(runs):
        line = run.get("product_line")
        require(isinstance(line, str) and line in LINES,
                f"runs[{index}].product_line: expected {','.join(sorted(LINES))}; "
                "preserve original and explicitly normalize a copy; no records were imported")
    ids = [b["bot_id"] for b in bots]
    require(len(ids) == len(set(ids)), "duplicate Bot ID")
    findings = []
    for b in bots:
        if b.get("kind") == "HUMAN":
            missing = [k for k in ("owner_god", "slot_id", "single_job", "skill_ref") if not b.get(k)]
            if b.get("tools") is None: missing.append("tools")
            if missing:
                findings.append({"bot_id": b["bot_id"], "finding": "BINDING_INCOMPLETE",
                                 "missing_fields": missing, "action": "RECONFIRM_WITH_HESTIA"})
    triggers = {}; routine_eligible = 0; routine_incomplete = []
    for r in routines:
        require(r.get("routine_id") and r.get("owner_bot_id"), "routine identifiers required")
        comparison_fields = ("purpose", "input_scope", "schedule", "timezone")
        missing = [field for field in comparison_fields if not r.get(field)]
        if missing:
            routine_incomplete.append({"routine_id": r["routine_id"], "missing_fields": missing})
        else:
            signature = digest({field: r[field] for field in comparison_fields})
            routine_eligible += 1
            triggers.setdefault(signature, []).append(r["routine_id"])
    for group in triggers.values():
        if len(group) > 1: findings.append({"routine_ids": group, "finding": "POSSIBLE_DUPLICATE_ROUTINE", "action": "REVIEW_ONLY"})
    reports = {}
    for line in sorted(LINES):
        available = [r for r in runs if r["product_line"] == line]
        known_dates = []; undated = []
        for record in available:
            value = record.get("started_at")
            if value is None:
                undated.append(record)
            else:
                require(isinstance(value, str), "started_at must be a timestamp or null")
                try: timestamp_value = datetime.fromisoformat(value)
                except ValueError as exc: raise OperationError("started_at: invalid timestamp") from exc
                require(timestamp_value.tzinfo is not None, "started_at: timezone required")
                known_dates.append((timestamp_value, record))
        # Unknown dates are retained and reported, never silently treated as newest.
        selected = [record for _, record in sorted(known_dates, key=lambda pair: pair[0], reverse=True)][:20]
        selected += undated[:max(0, 20 - len(selected))]
        reports[line] = {"available_runs": len(available), "inspected_runs": len(selected),
                         "omitted_by_limit": len(available) - len(selected),
                         "unknown_started_at": len(undated),
                         "latest_order_verified": not undated, "measurement_status": "SOURCE_RECORDS_ONLY" if selected else "UNMEASURED",
                         "missing_cost_records": sum(r.get("cost_units") is None for r in selected),
                         "runtime_verified": False}
    return {"schema_version": "1.0", "bridge_version": BRIDGE_VERSION, "source_ref": bundle["source_ref"], "collected_at": bundle["collected_at"],
            "imported_at": datetime.now(timezone.utc).isoformat(), "source_sha256": digest(bundle),
            "bot_count": len(bots), "routine_count": len(routines), "run_count": len(runs),
            "categorized_run_count": sum(report["available_runs"] for report in reports.values()),
            "routine_comparison": {"eligible_count": routine_eligible, "total_count": len(routines),
                                   "incomplete_records": routine_incomplete,
                                   "absence_of_duplicates_verified": False},
            "findings": findings,
            "lines": reports, "grokbot_live_rechecked": False, "registrations_performed": 0,
            "limitations": ["Snapshot may be stale", "Supplied records are not authenticated execution evidence",
                            "Missing routine fields limit duplicate detection; zero candidates is not proof of absence",
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
