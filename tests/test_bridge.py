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
                             "input_scope": "same channel", "schedule": "weekly", "timezone": "Asia/Seoul"} for n in ["one", "two"]]
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

    def test_unknown_or_lowercase_lines_fail_instead_of_disappearing(self):
        for line in ("youtube", "OTHER", None, [], 1):
            with self.subTest(line=line):
                data = self.fixture()
                data["runs"] = [{"run_id": "test-run", "product_line": line}]
                before = deepcopy(data)
                with self.assertRaisesRegex(OperationError, "product_line"):
                    inspect_inventory(data)
                self.assertEqual(data, before)

    def test_all_records_are_accounted_for_with_missing_dates_and_per_line_limit(self):
        data = self.fixture()
        data["runs"] = [{"run_id": str(i), "product_line": "YOUTUBE", "started_at": None}
                        for i in range(25)]
        data["runs"].append({"run_id": "blog", "product_line": "BLOG",
                             "started_at": "2026-09-01T00:00:00+09:00"})
        result = inspect_inventory(data)
        self.assertEqual(result["run_count"], result["categorized_run_count"])
        self.assertEqual(result["run_count"], 26)
        youtube = result["lines"]["YOUTUBE"]
        self.assertEqual(youtube["inspected_runs"], 20)
        self.assertEqual(youtube["omitted_by_limit"], 5)
        self.assertFalse(youtube["latest_order_verified"])
        self.assertEqual(result["lines"]["BLOG"]["available_runs"], 1)

    def test_routine_coverage_is_reported_and_timezones_do_not_collide(self):
        data = self.fixture()
        data["routines"] = [
            {"routine_id": "missing", "owner_bot_id": "test"},
            *[{"routine_id": zone, "owner_bot_id": "test", "purpose": "report",
               "input_scope": "same channel", "schedule": {"time": "09:00"}, "timezone": zone}
              for zone in ("Asia/Seoul", "America/New_York")]]
        result = inspect_inventory(data)
        self.assertEqual(result["routine_comparison"]["eligible_count"], 2)
        self.assertEqual(len(result["routine_comparison"]["incomplete_records"]), 1)
        self.assertFalse(result["routine_comparison"]["absence_of_duplicates_verified"])
        self.assertFalse(any(f["finding"] == "POSSIBLE_DUPLICATE_ROUTINE" for f in result["findings"]))

    def test_missing_binding_fields_distinguish_unknown_from_known_empty_tools(self):
        data = self.fixture()
        self.assertIn("tools", inspect_inventory(data)["findings"][0]["missing_fields"])
        data["bots"][0]["tools"] = []
        self.assertNotIn("tools", inspect_inventory(data)["findings"][0]["missing_fields"])

    def test_cli_rejects_lowercase_without_writing_success_report(self):
        import json, subprocess, sys
        with tempfile.TemporaryDirectory() as td:
            source, output = Path(td) / "source.json", Path(td) / "report.json"
            data = self.fixture()
            data["runs"] = [{"run_id": "test", "product_line": "youtube"}]
            source.write_text(json.dumps(data), encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "runtime.bridge", "--input",
                                     str(source), "--output", str(output)],
                                    cwd=Path(__file__).parents[1], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("product_line", result.stderr)
            self.assertFalse(output.exists())
            self.assertEqual(json.loads(source.read_text()), data)
