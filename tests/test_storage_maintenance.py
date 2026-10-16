"""CPU-only safety tests for the project-scoped storage utility."""

from __future__ import annotations

import json
import errno
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import storage_maintenance as storage  # noqa: E402


class StorageScanTests(unittest.TestCase):
    def test_root_identity_reuses_scandir_metadata_for_long_paths(self):
        info = SimpleNamespace(st_dev=7, st_ino=11)
        with mock.patch.object(Path, "stat", side_effect=FileNotFoundError(3, "path too long")):
            identity = storage._root_identity(Path("synthetic-deep-file"), info)
        self.assertEqual(identity, (7, 11))

    @unittest.skipUnless(os.name == "nt", "Windows extended-path behavior")
    def test_root_identity_uses_extended_prefix_when_windows_file_id_is_missing(self):
        info = SimpleNamespace(st_dev=7, st_ino=0)
        recovered = SimpleNamespace(st_dev=7, st_ino=11)
        with mock.patch.object(storage.os, "stat", return_value=recovered) as stat_call:
            identity = storage._root_identity(Path("C:/synthetic/deep/file"), info)
        self.assertEqual(identity, (7, 11))
        self.assertTrue(stat_call.call_args.args[0].startswith("\\\\?\\"))

    def test_scan_counts_logical_and_unique_bytes_for_hardlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "inventory"
            root.mkdir()
            source = root / "weight.bin"
            source.write_bytes(b"x" * 128)
            alias = root / "alias.bin"
            try:
                os.link(source, alias)
            except (OSError, NotImplementedError):
                self.skipTest("hard links unavailable on this filesystem")
            result = storage.scan_directory("models", root)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["logical_bytes"], 256)
        self.assertEqual(result["unique_file_bytes"], 128)
        self.assertEqual(result["hardlink_alias_bytes"], 128)

    def test_scan_output_never_contains_root_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "private-root"
            root.mkdir()
            report = storage.make_report(root, [("fixture", root)])
            serialized = json.dumps(report)
        self.assertNotIn(str(root), serialized)
        self.assertEqual(report["roots"][0]["label"], "fixture")

    def test_scan_rejects_invalid_root_label(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                storage.scan_directory("C:\\private", Path(temp))

    def test_scan_missing_root_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as temp:
            result = storage.scan_directory("missing", Path(temp) / "absent")
        self.assertEqual(result["status"], "MISSING")
        self.assertEqual(result["logical_bytes"], 0)

    def test_scan_respects_entry_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index in range(4):
                (root / f"{index}.bin").write_bytes(b"x")
            result = storage.scan_directory("bounded", root, max_entries=2)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertTrue(result["truncated"])

    def test_scan_aggregates_error_codes_without_exposing_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "inventory"
            blocked = root / "restricted"
            blocked.mkdir(parents=True)
            real_scandir = os.scandir

            def scandir_with_one_denied_directory(path):
                if Path(path) == blocked:
                    raise PermissionError(errno.EACCES, "denied", str(blocked))
                return real_scandir(path)

            with mock.patch.object(storage.os, "scandir", side_effect=scandir_with_one_denied_directory):
                result = storage.scan_directory("bounded", root)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["scan_errors"], 1)
        self.assertEqual(result["scan_error_codes"], {"EACCES": 1})
        self.assertNotIn(str(blocked), json.dumps(result))

    def test_scan_reports_allocated_size_as_unknown_when_platform_lacks_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "one").write_bytes(b"x")
            # st_blocks is platform-dependent; the assertion is that the field
            # is always present and uses an integer or null, never fabricated.
            result = storage.scan_directory("root", root)
        self.assertTrue(result["allocated_bytes"] is None or isinstance(result["allocated_bytes"], int))

    def test_verify_rejects_invalid_cleanup_baseline_shape(self):
        with tempfile.TemporaryDirectory() as temp:
            baseline = {"schema_version": storage.SCHEMA_VERSION, "drives": [], "safe_temp_preview": []}
            with self.assertRaisesRegex(ValueError, "cleanup section"):
                storage.verify_snapshot(Path(temp), baseline)


class StorageCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.root = self.repo / storage.TEMP_ROOT_NAME
        self.root.mkdir()
        self.old = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def make_task(self, name="task-1", *, state="COMPLETE", created_at=None, marked=True):
        task = self.root / name
        task.mkdir()
        (task / "data.bin").write_bytes(b"payload")
        if marked:
            storage.register_owned_temp(self.repo, task, task_id=name, purpose="synthetic test", created_at=created_at or self.old)
            if state != "ACTIVE":
                storage.complete_owned_temp(self.repo, task, completed_at=created_at or self.old)
            if state == "FAILED":
                payload = json.loads((task / storage.MARKER_NAME).read_text(encoding="utf-8"))
                payload["state"] = "FAILED"
                (task / storage.MARKER_NAME).write_text(json.dumps(payload), encoding="utf-8")
        return task

    def test_active_task_is_never_a_cleanup_candidate(self):
        self.make_task(state="ACTIVE")
        result = storage.preview_cleanup(self.repo, older_than_days=1, now=self.old + timedelta(days=90))
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["skipped"]["active"], 1)

    def test_unmarked_directory_is_never_a_cleanup_candidate(self):
        self.make_task(marked=False)
        result = storage.preview_cleanup(self.repo, older_than_days=1, now=self.old + timedelta(days=90))
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["skipped"]["unmarked"], 1)

    def test_recent_completed_task_is_retained(self):
        recent = datetime(2026, 3, 1, tzinfo=timezone.utc)
        self.make_task(created_at=recent)
        result = storage.preview_cleanup(self.repo, older_than_days=30, now=recent + timedelta(days=3))
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["skipped"]["recent"], 1)

    def test_retention_starts_at_completion_not_creation(self):
        task = self.make_task(created_at=self.old)
        recent_completion = datetime(2026, 3, 1, tzinfo=timezone.utc)
        storage.complete_owned_temp(self.repo, task, completed_at=recent_completion)
        result = storage.preview_cleanup(self.repo, older_than_days=30,
                                         now=recent_completion + timedelta(days=3))
        self.assertEqual(result["candidates"], [])

    def test_old_completed_task_is_previewed_but_not_removed(self):
        task = self.make_task()
        expected_bytes = sum(path.stat().st_size for path in task.rglob("*") if path.is_file())
        result = storage.preview_cleanup(self.repo, older_than_days=30, now=self.old + timedelta(days=90))
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["logical_bytes"], expected_bytes)
        self.assertTrue(task.exists())

    def test_clean_requires_explicit_confirmation(self):
        self.make_task()
        with self.assertRaises(PermissionError):
            storage.clean_safe_temp(self.repo, older_than_days=1, now=self.old + timedelta(days=90))

    def test_clean_removes_only_old_marked_terminal_task(self):
        eligible = self.make_task("eligible")
        expected_bytes = sum(path.stat().st_size for path in eligible.rglob("*") if path.is_file())
        active = self.make_task("active", state="ACTIVE")
        unmarked = self.make_task("unmarked", marked=False)
        result = storage.clean_safe_temp(self.repo, older_than_days=1, confirmed=True,
                                         now=self.old + timedelta(days=90))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["freed_logical_bytes"], expected_bytes)
        self.assertFalse(eligible.exists())
        self.assertTrue(active.exists())
        self.assertTrue(unmarked.exists())

    def test_cleanup_refuses_linked_content(self):
        task = self.make_task()
        outside = Path(self.temp.name).parent / (Path(self.temp.name).name + "-outside")
        outside.write_bytes(b"protected")
        try:
            try:
                (task / "linked.bin").symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            result = storage.preview_cleanup(self.repo, older_than_days=1, now=self.old + timedelta(days=90))
            self.assertEqual(result["candidates"], [])
            self.assertEqual(result["skipped"]["invalid"], 1)
            self.assertTrue(outside.exists())
        finally:
            outside.unlink(missing_ok=True)

    def test_registration_rejects_directory_outside_project_temp_root(self):
        elsewhere = self.repo / "userdata"
        elsewhere.mkdir()
        with self.assertRaises(ValueError):
            storage.register_owned_temp(self.repo, elsewhere, task_id="bad", purpose="must reject")

    def test_registration_rejects_path_traversal_task_id(self):
        task = self.make_task(marked=False)
        with self.assertRaises(ValueError):
            storage.register_owned_temp(self.repo, task, task_id="../escape", purpose="must reject")

    def test_invalid_marker_is_not_cleaned(self):
        task = self.root / "invalid"
        task.mkdir()
        (task / storage.MARKER_NAME).write_text("{}", encoding="utf-8")
        result = storage.preview_cleanup(self.repo, older_than_days=1, now=self.old + timedelta(days=90))
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["skipped"]["invalid"], 1)

    def test_cleanup_requires_positive_retention(self):
        with self.assertRaises(ValueError):
            storage.preview_cleanup(self.repo, older_than_days=0)

    def test_cli_does_not_replace_explicit_zero_retention_with_default(self):
        stderr = StringIO()
        with redirect_stderr(stderr):
            status = storage.main([
                "preview-cleanup", "--repo-root", str(self.repo), "--older-than-days", "0",
            ])
        self.assertEqual(status, 2)
        self.assertIn("ValueError", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
