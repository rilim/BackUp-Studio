"""Behavioral regression tests. All operations use disposable temporary folders."""
from pathlib import Path
import errno
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import Settings, load_settings, save_settings
import file_ops
from file_ops import BackupError, Cancelled, StaleComparison, compare, eligible, execute
from utils import normalize_exclusion, export_csv
from path_utils import io_path


class BackupBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = io_path(self.temporary.name)
        self.source, self.destination = self.root / "source", self.root / "backup"
        self.source.mkdir()
        self.destination.mkdir()
        self.settings = Settings(str(self.source), str(self.destination), exclusions=[], retries=1)
        self.logs = self.root / "logs"

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, root, relative, content=b"data", timestamp=1700000000):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        os.utime(path, (timestamp, timestamp))
        return path

    def run_action(self, mode="sync", names=None, overwrite=False):
        comparison = compare(self.settings, mode=mode)
        selected = set(names) if names is not None else {row.relative for row in comparison.rows if eligible(row, mode, overwrite)}
        return execute(comparison, selected, self.settings, overwrite=overwrite, log_directory=self.logs)

    def test_equal_size_equal_timestamp_different_contents_are_detected_and_copied(self):
        self.write(self.source, "same.txt", b"AAAA")
        self.write(self.destination, "same.txt", b"BBBB")
        self.assertEqual(compare(self.settings).rows[0].status, "modified")
        result = self.run_action()
        self.assertEqual(result["completed"], 1)
        self.assertEqual((self.destination / "same.txt").read_bytes(), b"AAAA")
        self.assertEqual((Path(result["archive"]) / "before_sync/same.txt").read_bytes(), b"BBBB")

    def test_newer_backup_is_detected_but_not_recommended_for_overwrite(self):
        self.write(self.source, "a", b"old")
        self.write(self.destination, "a", b"new", timestamp=1800000000)
        row = compare(self.settings).rows[0]
        self.assertEqual(row.status, "modified")
        self.assertFalse(file_ops.recommended(row, "sync"))
        self.assertTrue(eligible(row, "sync"))

    def test_identical_content_with_different_dates_is_skipped(self):
        self.write(self.source, "a", b"same")
        self.write(self.destination, "a", b"same", timestamp=1800000000)
        self.assertEqual(compare(self.settings).rows[0].status, "identical")

    def test_missing_source_blocks_cleanup_and_preserves_backup(self):
        self.write(self.destination, "valuable.txt")
        self.source.rmdir()
        with self.assertRaises(BackupError):
            compare(self.settings, mode="cleanup")
        self.assertTrue((self.destination / "valuable.txt").exists())

    def test_missing_source_can_be_restored(self):
        self.source.rmdir()
        self.write(self.destination, "folder/a.txt", b"backup")
        result = self.run_action("restore")
        self.assertEqual(result["failed"], 0)
        self.assertEqual((self.source / "folder/a.txt").read_bytes(), b"backup")

    def test_missing_backup_not_created_during_comparison(self):
        self.destination.rmdir()
        self.write(self.source, "a")
        compare(self.settings)
        self.assertFalse(self.destination.exists())
        self.run_action()
        self.assertTrue((self.destination / "a").is_file())

    def test_excluded_folders_are_ignored_on_both_sides(self):
        self.settings.exclusions = ["private"]
        self.write(self.source, "private/a.txt", b"original")
        self.write(self.destination, "private/a.txt", b"old backup")
        self.write(self.source, "private_other/keep.txt")
        for mode in ("sync", "restore", "cleanup"):
            comparison = compare(self.settings, mode=mode)
            self.assertFalse(any(row.relative.startswith("private/") or row.relative == "private" for row in comparison.rows))
            self.assertTrue(any(row.relative == "private_other/keep.txt" for row in comparison.rows))

    def test_safe_restore_preserves_existing_and_excluded_files(self):
        self.settings.exclusions = ["private"]
        self.write(self.source, "private/a", b"secret current")
        self.write(self.destination, "private/a", b"secret old")
        self.write(self.source, "current", b"current")
        self.write(self.destination, "current", b"old")
        self.write(self.destination, "missing", b"recover")
        self.run_action("restore")
        self.assertEqual((self.source / "private/a").read_bytes(), b"secret current")
        self.assertEqual((self.source / "current").read_bytes(), b"current")
        self.assertEqual((self.source / "missing").read_bytes(), b"recover")

    def test_force_restore_archives_the_previous_source(self):
        self.write(self.source, "a", b"current")
        self.write(self.destination, "a", b"old")
        report = self.run_action("restore", overwrite=True)
        self.assertEqual((self.source / "a").read_bytes(), b"old")
        self.assertEqual((Path(report["archive"]) / "before_restore/a").read_bytes(), b"current")

    def test_only_selected_files_are_copied(self):
        self.write(self.source, "first")
        self.write(self.source, "second")
        self.run_action(names=["first"])
        self.assertTrue((self.destination / "first").exists())
        self.assertFalse((self.destination / "second").exists())

    def test_cleanup_archives_selected_files_and_keeps_unselected_children(self):
        self.settings.retries = 3
        self.write(self.destination, "folder/remove", b"recoverable")
        self.write(self.destination, "folder/keep", b"keep")
        with patch.object(file_ops.time, "sleep") as pause:
            report = self.run_action("cleanup", names=["folder", "folder/remove"])
        pause.assert_not_called()
        self.assertEqual(report["completed"], 1)
        self.assertEqual(report["skipped"], 1)
        self.assertTrue((self.destination / "folder/keep").exists())
        self.assertFalse((self.destination / "folder/remove").exists())
        self.assertEqual((Path(report["archive"]) / "deleted_from_backup/folder/remove").read_bytes(), b"recoverable")

    def denied_directory(self, path):
        error = PermissionError(errno.EACCES, "Access is denied", str(path))
        error.winerror = 5  # Exercise the reported Windows failure on any OS.
        return error

    def test_cleanup_retries_empty_directory_after_files_are_archived(self):
        self.settings.retries = 3
        self.write(self.destination, "folder/file", b"recoverable")
        target = self.destination / "folder"
        original = Path.rmdir
        attempts = []
        def remove(path):
            if path == target:
                self.assertFalse((target / "file").exists())
                attempts.append(path)
                if len(attempts) < 3:
                    raise self.denied_directory(path)
            return original(path)
        with patch.object(Path, "rmdir", remove), patch.object(file_ops.time, "sleep") as pause:
            report = self.run_action("cleanup")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(pause.call_args_list, [call(1), call(2)])
        self.assertEqual((report["completed"], report["failed"]), (2, 0))
        self.assertFalse(target.exists())
        self.assertEqual((Path(report["archive"]) / "deleted_from_backup/folder/file").read_bytes(), b"recoverable")

    def test_cleanup_removes_nested_empty_directories_deepest_first(self):
        (self.destination / "folder/child/grandchild").mkdir(parents=True)
        report = self.run_action("cleanup")
        self.assertEqual((report["completed"], report["failed"]), (3, 0))
        self.assertFalse((self.destination / "folder").exists())

    def test_cleanup_persistent_directory_denial_obeys_retry_limit(self):
        self.settings.retries = 3
        target = self.destination / "folder"
        target.mkdir()
        with patch.object(Path, "rmdir", side_effect=self.denied_directory(target)) as remove, \
                patch.object(file_ops.time, "sleep") as pause:
            report = self.run_action("cleanup")
        self.assertEqual(remove.call_count, 3)
        self.assertEqual(pause.call_args_list, [call(1), call(2)])
        self.assertEqual((report["completed"], report["failed"]), (0, 1))
        self.assertIn("Access is denied", report["items"][0]["message"])
        self.assertTrue(target.is_dir())

    def test_cleanup_retry_rechecks_source_folder(self):
        self.settings.retries = 3
        target = self.destination / "folder"
        target.mkdir()
        with patch.object(Path, "rmdir", side_effect=self.denied_directory(target)) as remove, \
                patch.object(file_ops.time, "sleep", side_effect=lambda _: (self.source / "folder").mkdir()):
            report = self.run_action("cleanup")
        self.assertEqual(remove.call_count, 1)
        self.assertEqual(report["failed"], 1)
        self.assertTrue(target.is_dir())
        self.assertTrue((self.source / "folder").is_dir())

    def test_cleanup_retry_preserves_new_children(self):
        self.settings.retries = 3
        target = self.destination / "folder"
        target.mkdir()
        original = Path.rmdir
        attempts = []
        def remove(path):
            attempts.append(path)
            if len(attempts) == 1:
                raise self.denied_directory(path)
            return original(path)
        with patch.object(Path, "rmdir", remove), \
                patch.object(file_ops.time, "sleep", side_effect=lambda _: self.write(target, "new", b"keep")) as pause:
            report = self.run_action("cleanup")
        self.assertEqual(len(attempts), 2)
        pause.assert_called_once_with(1)
        self.assertEqual((report["skipped"], report["failed"]), (1, 0))
        self.assertEqual((target / "new").read_bytes(), b"keep")

    def test_cleanup_retry_rejects_replaced_target_or_roots(self):
        self.settings.retries = 3
        target = self.destination / "folder"
        for changed in (target, self.source, self.destination):
            with self.subTest(changed=changed):
                target.mkdir(exist_ok=True)
                saved = self.root / ("saved-" + changed.name)
                def replace_during_pause(_):
                    changed.rename(saved)
                    changed.mkdir()
                with patch.object(Path, "rmdir", side_effect=self.denied_directory(target)) as remove, \
                        patch.object(file_ops.time, "sleep", side_effect=replace_during_pause):
                    report = self.run_action("cleanup")
                self.assertEqual(remove.call_count, 1)
                self.assertEqual(report["failed"], 1)
                self.assertTrue(changed.is_dir())
                changed.rmdir()
                saved.rename(changed)

    def test_cleanup_retry_stops_if_source_root_disappears(self):
        self.settings.retries = 3
        target = self.destination / "folder"
        target.mkdir()
        with patch.object(Path, "rmdir", side_effect=self.denied_directory(target)) as remove, \
                patch.object(file_ops.time, "sleep", side_effect=lambda _: self.source.rename(self.root / "moved-source")):
            report = self.run_action("cleanup")
        self.assertEqual(remove.call_count, 1)
        self.assertEqual(report["failed"], 1)
        self.assertTrue(target.is_dir())

    def test_cleanup_can_be_cancelled_during_directory_retry_pause(self):
        self.settings.retries = 3
        target = self.destination / "folder"
        target.mkdir()
        comparison = compare(self.settings, mode="cleanup")
        cancel = threading.Event()
        def cancel_wait(_):
            cancel.set()
            return True
        with patch.object(Path, "rmdir", side_effect=self.denied_directory(target)) as remove, \
                patch.object(cancel, "wait", side_effect=cancel_wait) as pause:
            report = execute(comparison, {"folder"}, self.settings, cancel=cancel, log_directory=self.logs)
        self.assertEqual(remove.call_count, 1)
        pause.assert_called_once_with(1)
        self.assertEqual((report["cancelled"], report["failed"]), (1, 0))
        self.assertTrue(target.is_dir())

    def test_empty_directories_are_copied_and_restored(self):
        (self.source / "empty/nested").mkdir(parents=True)
        self.run_action()
        self.assertTrue((self.destination / "empty/nested").is_dir())
        shutil.rmtree(self.source / "empty")
        self.run_action("restore")
        self.assertTrue((self.source / "empty/nested").is_dir())

    def test_stale_source_is_rejected_before_any_copy(self):
        self.write(self.source, "first")
        self.write(self.source, "second")
        comparison = compare(self.settings)
        (self.source / "second").write_bytes(b"changed")
        with self.assertRaises(StaleComparison):
            execute(comparison, {"first", "second"}, self.settings, log_directory=self.logs)
        self.assertFalse((self.destination / "first").exists())

    def test_new_destination_file_is_never_silently_overwritten(self):
        self.write(self.source, "a", b"from source")
        comparison = compare(self.settings)
        self.write(self.destination, "a", b"appeared after scan")
        with self.assertRaises(StaleComparison):
            execute(comparison, {"a"}, self.settings, log_directory=self.logs)
        self.assertEqual((self.destination / "a").read_bytes(), b"appeared after scan")

    def test_source_appearing_after_cleanup_scan_blocks_deletion(self):
        self.write(self.destination, "a", b"backup")
        comparison = compare(self.settings, mode="cleanup")
        self.write(self.source, "a", b"appeared")
        with self.assertRaises(StaleComparison):
            execute(comparison, {"a"}, self.settings, log_directory=self.logs)
        self.assertEqual((self.destination / "a").read_bytes(), b"backup")

    def test_copy_failure_is_reported_and_old_destination_preserved(self):
        self.write(self.source, "a", b"new content")
        self.write(self.destination, "a", b"old content")
        with patch.object(file_ops, "verified_temporary", side_effect=PermissionError("simulated")):
            report = self.run_action()
        self.assertEqual(report["completed"], 0)
        self.assertEqual(report["failed"], 1)
        self.assertEqual((self.destination / "a").read_bytes(), b"old content")
        self.assertEqual(json.loads(next(self.logs.glob("*.json")).read_text())["state"], "errors")

    def test_archive_failure_blocks_overwrite(self):
        self.write(self.source, "a", b"new")
        self.write(self.destination, "a", b"old")
        with patch.object(file_ops, "archive_file", side_effect=PermissionError("archive denied")):
            report = self.run_action()
        self.assertEqual(report["failed"], 1)
        self.assertEqual((self.destination / "a").read_bytes(), b"old")
        self.assertFalse(list(self.destination.glob(".backup-part-*")))

    def test_cancel_during_copy_preserves_old_file_and_removes_partial(self):
        self.write(self.source, "a", b"N" * (file_ops.CHUNK_SIZE * 3))
        self.write(self.destination, "a", b"old")
        comparison = compare(self.settings)
        event = threading.Event()
        def notify(data):
            if data.get("bytes", 0):
                event.set()
        result = execute(comparison, {"a"}, self.settings, cancel=event, notify=notify, log_directory=self.logs)
        self.assertEqual(result["cancelled"], 1)
        self.assertEqual((self.destination / "a").read_bytes(), b"old")
        self.assertFalse(list(self.destination.glob(".backup-part-*")))

    def test_unreadable_file_prevents_execution(self):
        self.write(self.source, "a")
        with patch.object(file_ops, "file_hash", side_effect=PermissionError("cannot read")):
            comparison = compare(self.settings)
        self.assertTrue(comparison.errors)
        with self.assertRaises(BackupError):
            execute(comparison, {"a"}, self.settings, log_directory=self.logs)
        self.assertFalse((self.destination / "a").exists())

    def test_conflicting_file_directory_and_descendants_are_not_actionable(self):
        self.write(self.source, "thing/child")
        self.write(self.destination, "thing")
        rows = compare(self.settings).rows
        self.assertTrue(all(row.status == "conflict" for row in rows))
        self.assertFalse(any(eligible(row, "sync") for row in rows))

    def test_nested_or_identical_roots_are_rejected(self):
        for destination in [self.source, self.source / "nested", self.root]:
            self.settings.destination = str(destination)
            with self.assertRaises(BackupError):
                compare(self.settings)

    def test_changed_exclusions_invalidate_old_plan(self):
        self.write(self.source, "a")
        comparison = compare(self.settings)
        self.settings.exclusions = ["new-exclusion"]
        with self.assertRaises(StaleComparison):
            execute(comparison, {"a"}, self.settings, log_directory=self.logs)

    def test_versions_cannot_be_inside_either_working_root(self):
        self.write(self.source, "a", b"new")
        self.write(self.destination, "a", b"old")
        self.settings.versions_directory = str(self.source / "versions")
        with self.assertRaises(BackupError):
            self.run_action()
        self.assertEqual((self.destination / "a").read_bytes(), b"old")

    def test_space_is_checked_only_for_selected_changes(self):
        self.write(self.source, "same", b"x" * 20000)
        self.write(self.destination, "same", b"x" * 20000)
        self.write(self.source, "small", b"x")
        real = shutil.disk_usage(self.root)
        with patch.object(file_ops.shutil, "disk_usage", return_value=type(real)(real.total, real.used, 10)):
            report = self.run_action(names=["small"])
        self.assertEqual(report["completed"], 1)

    def test_not_enough_space_does_not_change_destination(self):
        self.write(self.source, "a", b"new data")
        self.write(self.destination, "a", b"old")
        real = shutil.disk_usage(self.root)
        with patch.object(file_ops.shutil, "disk_usage", return_value=type(real)(real.total, real.used, 0)):
            with self.assertRaises(BackupError):
                self.run_action()
        self.assertEqual((self.destination / "a").read_bytes(), b"old")

    @unittest.skipIf(os.name == "nt", "Symlink creation may require elevated Windows privileges")
    def test_symlink_entries_are_blocked_unless_explicitly_excluded(self):
        outside = self.write(self.root, "external", b"private")
        (self.source / "link").symlink_to(outside)
        self.assertTrue(compare(self.settings).errors)
        self.settings.exclusions = ["link"]
        self.assertFalse(compare(self.settings).errors)

    def test_settings_roundtrip_and_corrupt_file_fallback(self):
        self.settings.exclusions = ["Lietuviškas aplankas"]
        save_settings(self.settings, self.root / "settings")
        restored, warning = load_settings(self.root / "settings")
        self.assertFalse(warning)
        self.assertEqual(restored, self.settings)
        (self.root / "settings/settings.json").write_text("broken")
        restored, warning = load_settings(self.root / "settings")
        self.assertTrue(warning)

    def test_exclusion_normalization_and_escape_rejection(self):
        self.assertEqual(normalize_exclusion(str(self.source / "nested/private"), self.source), "nested/private")
        self.assertEqual(normalize_exclusion("nested\\private", self.source), "nested/private")
        for value in ["..", "a/../b", ".", str(self.destination), "bad\0name"]:
            with self.assertRaises(ValueError):
                normalize_exclusion(value, self.source)

    def test_csv_export_preserves_unicode_and_blocks_spreadsheet_formulas(self):
        path = self.root / "list.csv"
        export_csv(path, ["Kelias"], [["ąčęėįšųūž.txt"], ["=danger.txt"]])
        content = path.read_text(encoding="utf-8-sig")
        self.assertIn("ąčęėįšųūž.txt", content)
        self.assertIn("'=danger.txt", content)


if __name__ == "__main__":
    unittest.main()
