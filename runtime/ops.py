"""JSON-in/JSON-out CLI: python -m runtime.ops --help."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

from .operations import Operations, OperationError, load_json

COMMANDS = {"register", "create", "claim", "submit", "review", "block", "reconcile",
            "change-input", "change-reference", "update-binding", "handoff", "reuse", "retry", "memory", "status", "export", "report", "observe", "validation", "deployment"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--db", required=True, help="Private operational SQLite file (not simulation DB)")
    parser.add_argument("--artifact-root", required=True, help="Private root containing referenced files")
    parser.add_argument("--request", type=Path, help="UTF-8 JSON request; never credentials")
    parser.add_argument("--project", help="Project ID for status/export")
    args = parser.parse_args(argv)
    ledger = None
    try:
        request = load_json(args.request) if args.request else {}
        if not isinstance(request, dict): raise OperationError("request must be an object")
        ledger = Operations(args.db, args.artifact_root)
        if args.command in {"status", "export"}:
            if not args.project: raise OperationError("--project is required")
            result = getattr(ledger, args.command)(args.project)
        elif args.command in {"register", "create"}:
            result = getattr(ledger, args.command)(request)
        elif args.command in {"change-input", "retry"}:
            if args.command == "retry" and not request.get("retry_card_id"):
                raise OperationError("retry_card_id required; original task lineage is retained")
            result = ledger.change_input(**request)
        elif args.command == "report":
            result = ledger.report()
        else:
            result = getattr(ledger, args.command.replace("-", "_"))(**request)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (OperationError, OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        print(json.dumps({"ok": False, "error": str(exc), "external_action_performed": False}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        if ledger: ledger.close()


if __name__ == "__main__":
    sys.exit(main())
