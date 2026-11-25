"""Read-only folders (OneDrive marks synced folders read-only) must not block cleanup.
All operations use disposable temporary folders."""
from datetime import datetime, timedelta
from pathlib import Path
import errno
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import file_ops
import retention
from config import Settings

READ_ONLY = 1


def mark_read_only(path):
    file_ops.windows_attributes(file_ops.io_path(path), file_ops.windows_attributes(file_ops.io_path(path)) | READ_ONLY)


def is_read_only(path):
    return bool(file_ops.windows_attributes(file_ops.io_path(path)) & READ_ONLY)


@unittest.skipUnless(os.name == "nt", "Windows folder attributes")
class ReadOnlyFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.clear_flags)
        self.root = Path(self.temp.name)
        self.source = self.root / "Original"
        self.backup = self.root / "Copy"
        self.source.mkdir()
        self.backup.mkdir()
        self.logs = self.root / "logs"
        self.settings = Settings(str(self.source), str(self.backup), exclusions=[])

    def clear_flags(self):
        for current, folders, _ in os.walk(self.root):
            for name in folders:
                path = Path(current) / name
                try:
                    attributes = file_ops.windows_attributes(path)
                    file_ops.windows_attributes(path, attributes & ~READ_ONLY)
                except OSError:
                    pass

    def cleanup(self, names):
        comparison = file_ops.compare(self.settings, "cleanup")
        return file_ops.execute(comparison, set(names), self.settings, log_directory=self.logs)

    def test_windows_refuses_plain_rmdir_of_read_only_folder(self):
        # Documents the root cause seen with OneDrive: "[WinError 5] Access is denied".
        folder = self.backup / "locked"
        folder.mkdir()
        mark_read_only(folder)
        with self.assertRaises(PermissionError):
            os.rmdir(file_ops.io_path(folder))

    def test_cleanup_removes_nested_read_only_empty_folders(self):
        deep = self.backup / "Project - Copy" / "Emulation" / "Data"
        deep.mkdir(parents=True)
        (deep / "file.txt").write_text("old", encoding="utf-8")
        for path in (deep, deep.parent, deep.parent.parent):
            mark_read_only(path)
        report = self.cleanup(["Project - Copy", "Project - Copy/Emulation", "Project - Copy/Emulation/Data",
                               "Project - Copy/Emulation/Data/file.txt"])
        self.assertEqual((report["completed"], report["failed"], report["skipped"]), (4, 0, 0), report["items"])
        self.assertFalse((self.backup / "Project - Copy").exists())

    def test_folder_that_gains_content_is_kept_with_read_only_flag(self):
        folder = self.backup / "kept"
        folder.mkdir()
        mark_read_only(folder)
        comparison = file_ops.compare(self.settings, "cleanup")
        (folder / "new-after-scan.txt").write_text("new", encoding="utf-8")
        report = file_ops.execute(comparison, {"kept"}, self.settings, log_directory=self.logs)
        self.assertEqual((report["completed"], report["skipped"]), (0, 1))
        self.assertTrue((folder / "new-after-scan.txt").exists())
        self.assertTrue(is_read_only(folder))

    def test_access_denied_without_read_only_flag_is_still_reported(self):
        folder = self.backup / "acl"
        folder.mkdir()
        denied = PermissionError(errno.EACCES, "Access is denied")
        denied.winerror = 5
        with patch.object(Path, "rmdir", side_effect=denied), patch.object(file_ops, "windows_attributes") as attributes:
            attributes.return_value = 0x10  # directory, not read-only
            with self.assertRaises(PermissionError):
                file_ops.remove_empty_directory(folder)
            attributes.assert_called_once()  # read, never changed

    def test_flag_is_restored_when_second_attempt_fails(self):
        folder = self.backup / "stubborn"
        folder.mkdir()
        mark_read_only(folder)
        denied = PermissionError(errno.EACCES, "Access is denied")
        denied.winerror = 5
        with patch.object(Path, "rmdir", side_effect=denied):
            with self.assertRaises(PermissionError):
                file_ops.remove_empty_directory(folder)
        self.assertTrue(folder.exists())
        self.assertTrue(is_read_only(folder))

    def test_validation_failure_leaves_flag_untouched(self):
        folder = self.backup / "changed"
        folder.mkdir()
        mark_read_only(folder)
        def validate():
            raise file_ops.StaleComparison("changed")
        with self.assertRaises(file_ops.StaleComparison):
            file_ops.remove_empty_directory(folder, validate)
        self.assertTrue(is_read_only(folder))

    def test_version_cleanup_removes_read_only_run_folders(self):
        archive = self.root / "Copy.versions"
        runs = []
        for day in (0, 100):
            started = datetime.now() - timedelta(days=day)
            run_id = started.strftime("%Y%m%d_%H%M%S") + "_" + f"{day:08x}"
            data = archive / run_id / "deleted_from_backup" / "a"
            data.mkdir(parents=True)
            (data / "x.txt").write_text("x", encoding="utf-8")
            (archive / run_id / "manifest.json").write_text(json.dumps(
                {"id": run_id, "started": started.isoformat(timespec="seconds"), "mode": "cleanup", "state": "completed"}),
                encoding="utf-8")
            for path in (data, data.parent, archive / run_id):
                mark_read_only(path)
            runs.append(archive / run_id)
        found, _ = retention.list_archive_runs(archive)
        plan = retention.plan_prune(found, keep_runs=1)
        report = retention.prune(archive, plan, self.settings, log_directory=self.logs)
        self.assertEqual((report["completed"], report["failed"]), (1, 0), report["items"])
        self.assertTrue(runs[0].exists())
        self.assertFalse(runs[1].exists())


if __name__ == "__main__":
    unittest.main()
