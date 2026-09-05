from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from runtime.bridge import inspect_inventory, read_export
from runtime.operations import OperationError


class BridgeTests(unittest.TestCase):
    def fixture(self):
        return {"schema_version": "1.0", "source_ref": "private:export", "collected_at": "2026-09-03T15:50:00+09:00",
                "bots": [{"bot_id": "test", "kind": "HUMAN"}], "routines": [], "runs": []}

    def test_incomplete_binding_is_not_activated(self):
        result = inspect_inventory(self.fixture())
        self.assertEqual(result["registrations_performed"], 0)
        self.assertEqual(result["findings"][0]["finding"], "BINDING_INCOMPLETE")
        self.assertTrue(all(x["measurement_status"] == "UNMEASURED" for x in result["lines"].values()))

    def test_secret_fields_rejected_recursively(self):
        data = self.fixture(); data["bots"][0]["connection"] = {"access_token": "test"}
        with self.assertRaises(OperationError): inspect_inventory(data)

    def test_duplicate_routines_only_reported(self):
        data = self.fixture()
        data["routines"] = [{"routine_id": n, "owner_bot_id": "test", "purpose": "weekly metrics",
                             "input_scope": "same channel", "schedule": "weekly"} for n in ["one", "two"]]
        result = inspect_inventory(data)
        self.assertEqual(result["findings"][-1]["finding"], "POSSIBLE_DUPLICATE_ROUTINE")

    def test_reads_notion_or_craft_json_block(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "export.md"
            path.write_text("Export\n```json\n" + json.dumps(self.fixture()) + "\n```", encoding="utf-8")
            self.assertEqual(read_export(path), self.fixture())
            path.write_text("```json\n{}\n```\n```json\n{}\n```", encoding="utf-8")
            with self.assertRaises(OperationError): read_export(path)

    def test_empty_notion_payload_is_incomplete_transfer(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "empty.md"
            path.write_text("Summary and remote path\n```json\n\n```", encoding="utf-8")
            with self.assertRaisesRegex(OperationError, "EXPORT_INCOMPLETE"):
                read_export(path)

    def test_summary_without_explicit_lists_is_not_empty_inventory(self):
        data = self.fixture()
        del data["runs"]
        with self.assertRaisesRegex(OperationError, "EXPORT_INCOMPLETE"):
            inspect_inventory(data)
