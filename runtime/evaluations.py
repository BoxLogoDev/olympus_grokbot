"""Offline, paired evaluation reports. This module never promotes a version."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _number(record: dict, field: str, integer: bool = False) -> float:
    value = record.get(field)
    require(type(value) in ((int,) if integer else (int, float)), f"Invalid {field}")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    require(finite and value >= 0, f"Invalid {field}")
    return value


def _boolean(record: dict, field: str) -> bool:
    value = record.get(field)
    require(type(value) is bool, f"Missing or invalid {field}")
    return value


def _text(record: dict, field: str) -> str:
    value = record.get(field)
    require(isinstance(value, str) and bool(value.strip()), f"Missing or invalid {field}")
    return value


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load(path: Path) -> dict:
    def reject_constant(value: str) -> None:
        raise ValueError(f"Non-finite JSON number: {value}")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
                      parse_constant=reject_constant)


def compare(bundle: dict, minimum_pairs: int = 20) -> dict:
    """Compare identical case/trial pairs; 20 is a configurable triage floor, not confidence.

    Input evidence references are descriptive records, not authenticated approvals.
    Real rollout still needs the independent review required by OLYMPUS policy.
    """
    require(type(minimum_pairs) is int and minimum_pairs >= 2, "minimum_pairs must be >= 2")
    require(isinstance(bundle, dict), "Evaluation bundle must be an object")
    require(bundle.get("schema_version") == "1.0", "Unsupported evaluation schema")
    synthetic = _boolean(bundle, "synthetic")
    dataset = bundle.get("dataset")
    require(isinstance(dataset, dict), "Missing dataset")
    for key in ("id", "version", "sha256"):
        _text(dataset, key)
    cases = dataset.get("cases")
    require(isinstance(cases, list) and bool(cases), "Dataset cases must be nonempty")
    require(all(isinstance(case, dict) for case in cases), "Dataset cases must be objects")
    case_ids = [_text(case, "case_id") for case in cases]
    require(len(set(case_ids)) == len(case_ids), "Duplicate dataset case")
    require(dataset["sha256"] == canonical_hash(cases), "Dataset hash mismatch")
    runs = bundle.get("runs")
    require(isinstance(runs, list), "Missing runs")
    index: dict[str, dict[tuple, dict]] = {"baseline": {}, "candidate": {}}
    run_ids: set[str] = set()
    configurations: dict[str, set] = defaultdict(set)
    for record in runs:
        require(isinstance(record, dict), "Invalid run record")
        run_id = _text(record, "run_id")
        require(run_id not in run_ids, "Duplicate run_id")
        run_ids.add(run_id)
        variant = record.get("variant")
        require(variant in index, "variant must be baseline or candidate")
        case_id = _text(record, "case_id")
        require(case_id in case_ids, "Run references unknown case")
        trial = _number(record, "trial", integer=True)
        require(trial >= 1, "trial must be >= 1")
        key = (case_id, trial)
        require(key not in index[variant], "Duplicate variant/case/trial")
        for field in ("agent_version", "prompt_version", "model_version", "policy_version",
                      "environment_id", "grader_version", "reference_criteria_id"):
            _text(record, field)
        configurations[variant].add(tuple(record[f] for f in
            ("agent_version", "prompt_version", "model_version", "policy_version", "grader_version")))
        accepted = _boolean(record, "accepted")
        first_pass = _boolean(record, "first_attempt_pass")
        _boolean(record, "grader_pass")
        require(not first_pass or accepted, "First-attempt pass cannot have a failed final outcome")
        for field in ("cost_usd", "elapsed_seconds"):
            _number(record, field)
        for field in ("user_revisions", "unexpected_interventions", "blocker_violations"):
            _number(record, field, integer=True)
        source = record.get("outcome_source")
        require(source in ("HUMAN_REVIEW", "DETERMINISTIC_CHECK"), "Unverified outcome source")
        field = "human_pass" if source == "HUMAN_REVIEW" else "deterministic_pass"
        require(_boolean(record, field) == accepted, "Outcome disagrees with reference judgment")
        human = record.get("human_pass")
        require(human is None or type(human) is bool, "Invalid human_pass")
        evidence = record.get("evidence_refs")
        require(isinstance(evidence, list) and bool(evidence) and
                all(isinstance(item, str) and item.strip() for item in evidence), "Missing evidence references")
        index[variant][key] = record
    for variant in index:
        require(len(configurations[variant]) <= 1, f"Mixed configurations in {variant}")

    keys = set(index["baseline"]) & set(index["candidate"])
    unmatched = sorted(set(index["baseline"]) ^ set(index["candidate"]))
    for key in keys:
        baseline, candidate = index["baseline"][key], index["candidate"][key]
        require(baseline["environment_id"] == candidate["environment_id"], "Paired environment mismatch")
        require(baseline["grader_version"] == candidate["grader_version"], "Paired grader mismatch")
        require(baseline["policy_version"] == candidate["policy_version"], "Paired policy mismatch")
        require(baseline["outcome_source"] == candidate["outcome_source"], "Paired reference-judgment source mismatch")
        require(baseline["reference_criteria_id"] == candidate["reference_criteria_id"], "Paired reference criteria mismatch")

    summaries = {}
    for variant, records in index.items():
        paired = [records[key] for key in sorted(keys)]
        humans = [record for record in paired if record.get("human_pass") is not None]
        n = len(paired)
        total_cost = float(sum((Decimal(str(record["cost_usd"])) for record in paired), Decimal(0)))
        accepted = sum(record["accepted"] for record in paired)
        summaries[variant] = {
            "paired_runs": n,
            "accepted": accepted,
            "acceptance_rate": accepted / n if n else None,
            "first_attempt_pass_rate": sum(record["first_attempt_pass"] for record in paired) / n if n else None,
            "total_cost_usd": total_cost,
            "cost_per_accepted_output_usd": total_cost / accepted if accepted else None,
            "mean_elapsed_seconds": sum(record["elapsed_seconds"] for record in paired) / n if n else None,
            "user_revisions": sum(record["user_revisions"] for record in paired),
            "unexpected_interventions": sum(record["unexpected_interventions"] for record in paired),
            "blocker_violations": sum(record["blocker_violations"] for record in paired),
            "human_labeled_runs": len(humans),
            "grader_human_agreement": sum(record["grader_pass"] == record["human_pass"] for record in humans) / len(humans) if humans else None,
            "grader_false_passes": sum(record["grader_pass"] and not record["human_pass"] for record in humans),
            "grader_false_rejections": sum(not record["grader_pass"] and record["human_pass"] for record in humans),
        }

    reasons = []
    baseline, candidate = summaries["baseline"], summaries["candidate"]
    comparison = "INCONCLUSIVE"
    # Violations from any candidate record matter, including unpaired records.
    if any(record["blocker_violations"] for record in index["candidate"].values()):
        comparison = "KEEP_BASELINE"
        reasons.append("Candidate contains blocking violations; promotion is not recommended.")
    elif unmatched or len(keys) < minimum_pairs or set(case_ids) != {key[0] for key in keys}:
        reasons.append("Need complete comparable coverage and the configured minimum paired runs.")
    else:
        regressions = [key for key in sorted(keys) if index["baseline"][key]["accepted"] and not index["candidate"][key]["accepted"]]
        if candidate["accepted"] == 0:
            comparison = "KEEP_BASELINE"
            reasons.append("Candidate has no accepted outputs in this sample.")
        elif regressions or candidate["user_revisions"] > baseline["user_revisions"] or candidate["unexpected_interventions"] > baseline["unexpected_interventions"]:
            comparison = "KEEP_BASELINE"
            reasons.append("Case regressions or increased user correction/intervention require review.")
        elif candidate["accepted"] > baseline["accepted"] or candidate["total_cost_usd"] < baseline["total_cost_usd"] or candidate["mean_elapsed_seconds"] < baseline["mean_elapsed_seconds"]:
            comparison = "CANDIDATE_FOR_REVIEW"
            reasons.append("Observed improvement without a case-level acceptance regression; independent review remains required.")
        else:
            comparison = "KEEP_BASELINE"
            reasons.append("No measured improvement in the paired sample.")
    return {
        "schema_version": "1.0", "report_kind": "OFFLINE_EVALUATION",
        "dataset_ref": {key: dataset[key] for key in ("id", "version", "sha256")},
        "synthetic": synthetic, "recommendation": "DEMO_ONLY" if synthetic else comparison,
        "comparison_result": comparison, "minimum_pairs": minimum_pairs,
        "paired_runs": len(keys), "distinct_cases": len({key[0] for key in keys}),
        "unmatched_pairs": [list(key) for key in unmatched], "summaries": summaries,
        "reasons": reasons,
        "limitations": ["A sample-size floor is not a statistical confidence guarantee.",
                        "Evidence references and human labels are supplied records, not authenticated approval events.",
                        "Cost, quality and latency tradeoffs require review before any rollout."],
        "version_promoted": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--minimum-pairs", type=int, default=20)
    args = parser.parse_args()
    try:
        report = compare(load(args.input), args.minimum_pairs)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        parser.exit(2, f"Evaluation input rejected: {exc}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
