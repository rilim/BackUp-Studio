"""Partial-scan safety and verified read-only cleanup regression tests."""
from pathlib import Path
from dataclasses import replace
import json
import os
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import file_ops as ops
from config import Settings
from path_utils import io_path


class PartialScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = io_path(self.temp.name)
        self.source, self.backup = self.root / 'source', self.root / 'backup'
        self.source.mkdir()
        self.backup.mkdir()
        self.settings = Settings(str(self.source), str(self.backup), exclusions=[], retries=1)

    def write(self, root, name, data=b'data'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def run_plan(self, plan, names=None, overwrite=False):
        selected = names if names is not None else {r.relative for r in plan.rows if ops.eligible(r, plan.mode, overwrite)}
        return ops.execute(plan, selected, self.settings, overwrite=overwrite, log_directory=self.root / 'logs')

    def hash_block(self, blocked):
        original = ops.file_hash
        def hash_file(path, *args):
            if path in blocked:
                error = PermissionError('antivirus blocked')
                error.winerror = 225
                raise error
            return original(path, *args)
        return patch.object(ops, 'file_hash', side_effect=hash_file)

    def test_347_readable_files_copy_3_blocked_files_stay_visible_and_logged(self):
        paths = [self.write(self.source, f'file-{n:03d}') for n in range(350)]
        with self.hash_block(set(paths[:3])):
            plan = ops.compare(self.settings)
            self.assertFalse(plan.blocked)
            self.assertEqual(len(plan.errors), 3)
            self.assertEqual(sum(r.status == 'unreadable' for r in plan.rows), 3)
            report = self.run_plan(plan)
        self.assertEqual(report['completed'], 347)
        self.assertEqual(report['scan_skipped'], 3)
        self.assertEqual(report['failed'], 0)
        self.assertEqual(report['state'], 'completed_with_skips')
        self.assertEqual(len(list(self.backup.iterdir())), 347)
        saved = json.loads(next((self.root / 'logs').glob('*.json')).read_text())
        self.assertEqual(len(saved['scan_errors']), 3)
        self.assertEqual(len(saved['scan_skipped_items']), 3)
        with self.assertRaises(ops.BackupError):
            self.run_plan(plan, {'file-000'})

    def test_restore_continues_but_never_overwrites_unreadable_source(self):
        blocked = self.write(self.source, 'blocked', b'original')
        self.write(self.backup, 'blocked', b'backup')
        self.write(self.backup, 'good')
        with self.hash_block({blocked}):
            plan = ops.compare(self.settings, 'restore')
            report = self.run_plan(plan, overwrite=True)
        self.assertEqual(report['completed'], 1)
        self.assertEqual(blocked.read_bytes(), b'original')
        self.assertTrue((self.source / 'good').exists())

    def test_unreadable_destination_never_overwritten_by_sync(self):
        self.write(self.source, 'blocked', b'new')
        old = self.write(self.backup, 'blocked', b'old')
        self.write(self.source, 'good')
        with self.hash_block({old}):
            report = self.run_plan(ops.compare(self.settings))
        self.assertEqual(report['completed'], 1)
        self.assertEqual(old.read_bytes(), b'old')

    def test_unreadable_source_branch_protected_but_sibling_cleanup_allowed(self):
        self.write(self.source, 'parent/blocked/hidden')
        protected = self.write(self.backup, 'parent/blocked/keep')
        self.write(self.backup, 'parent/blocked-other/remove')
        original = ops.os.scandir
        def scan(path):
            if path == self.source / 'parent/blocked':
                raise PermissionError('directory denied')
            return original(path)
        with patch.object(ops.os, 'scandir', side_effect=scan):
            plan = ops.compare(self.settings, 'cleanup')
        rows = {r.relative: r for r in plan.rows}
        self.assertEqual(rows['parent'].status, 'unreadable')
        self.assertEqual(rows['parent/blocked/keep'].status, 'unreadable')
        # Defend engine even against a caller changing the displayed status.
        forged = replace(plan, rows=[replace(r, status='destination_only') if r.relative == 'parent/blocked/keep' else r for r in plan.rows])
        with self.assertRaises(ops.BackupError):
            self.run_plan(forged, {'parent/blocked/keep'})
        report = self.run_plan(plan)
        self.assertEqual(report['completed'], 2)
        self.assertTrue(protected.exists())
        self.assertFalse((self.backup / 'parent/blocked-other').exists())

    def test_stat_failure_still_creates_visible_unknown_entry(self):
        blocked = self.write(self.source, 'unknown')
        self.write(self.source, 'good')
        original = ops.snapshot
        def read(path):
            if path == blocked:
                raise PermissionError('metadata denied')
            return original(path)
        with patch.object(ops, 'snapshot', side_effect=read):
            plan = ops.compare(self.settings)
        row = next(r for r in plan.rows if r.relative == 'unknown')
        self.assertEqual((row.status, row.kind), ('unreadable', 'unknown'))
        self.assertIn('metadata denied', row.problem)
        self.assertEqual(self.run_plan(plan)['completed'], 1)

    def test_root_scan_failure_remains_fatal(self):
        self.write(self.backup, 'keep')
        original = ops.os.scandir
        def scan(path):
            if path == self.source:
                raise PermissionError('root denied')
            return original(path)
        with patch.object(ops.os, 'scandir', side_effect=scan):
            plan = ops.compare(self.settings, 'cleanup')
        self.assertTrue(plan.blocked)
        with self.assertRaises(ops.BackupError):
            self.run_plan(plan, {'keep'})
        self.assertTrue((self.backup / 'keep').exists())

    def test_unscoped_legacy_errors_fail_closed(self):
        self.write(self.source, 'good')
        plan = ops.compare(self.settings)
        plan.errors.append('unknown error')
        self.assertTrue(plan.blocked)
        with self.assertRaises(ops.BackupError):
            self.run_plan(plan)

    def test_system_exclusions_skip_only_top_level_on_both_sides(self):
        for root in (self.source, self.backup):
            for name in ops.SYSTEM_EXCLUSIONS:
                self.write(root, name + '/private')
            self.write(root, 'documents/System Volume Information/ordinary')
        # Scan uses literal supplied rules; Windows compare supplies these rules.
        for root in (self.source, self.backup):
            found, issues = ops.scan_tree(root, ops.SYSTEM_EXCLUSIONS, None, None)
            self.assertFalse(issues)
            self.assertNotIn('System Volume Information', found)
            self.assertNotIn('$RECYCLE.BIN', found)
            self.assertIn('documents/System Volume Information/ordinary', found)
        plan = ops.compare(self.settings)
        with self.assertRaisesRegex(ops.BackupError, 'versijų aplanką'):
            ops.versions_root(self.settings, replace(plan, destination=Path(self.backup.anchor)))

    def test_unreadable_backup_branch_blocks_restore_children(self):
        self.write(self.backup, 'blocked/item')
        self.write(self.backup, 'good')
        original = ops.os.scandir
        def scan(path):
            if path == self.backup / 'blocked':
                raise PermissionError('denied')
            return original(path)
        with patch.object(ops.os, 'scandir', side_effect=scan):
            plan = ops.compare(self.settings, 'restore')
        self.assertEqual(self.run_plan(plan)['completed'], 1)
        self.assertFalse((self.source / 'blocked').exists())

    def test_cleanup_calls_removal_only_after_verified_archive(self):
        target = self.write(self.backup, 'parent/readonly', b'precious contents')
        plan = ops.compare(self.settings, 'cleanup')
        original = ops.remove_archived_file
        calls = []
        def removal(path, expected, validate, attempts, cancel):
            copies = list(self.root.glob('backup.versions/*/deleted_from_backup/parent/readonly'))
            self.assertEqual(len(copies), 1)
            self.assertEqual(copies[0].read_bytes(), b'precious contents')
            self.assertEqual(ops.file_hash(copies[0]), expected.digest)
            calls.append(path)
            return original(path, expected, validate, attempts, cancel)
        with patch.object(ops, 'remove_archived_file', side_effect=removal):
            report = self.run_plan(plan)
        self.assertEqual(calls, [target])
        self.assertEqual(report['completed'], 2)
        self.assertFalse(target.parent.exists())

    def test_failed_archive_never_calls_readonly_removal(self):
        target = self.write(self.backup, 'parent/readonly')
        plan = ops.compare(self.settings, 'cleanup')
        with (patch.object(ops, 'archive_file', side_effect=PermissionError('cannot archive')),
              patch.object(ops, 'remove_archived_file') as removal):
            report = self.run_plan(plan)
        removal.assert_not_called()
        self.assertEqual(report['failed'], 1)
        self.assertTrue(target.exists())


class ReadOnlyRemovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = io_path(self.temp.name) / 'object'
        self.path.write_bytes(b'archived bytes')
        self.expected = replace(ops.snapshot(self.path), digest=ops.file_hash(self.path))
        self.attrs = 0x23  # readonly + hidden + archive
        self.attribute_changes = []
        self.original_unlink = type(self.path).unlink
        self.event = threading.Event()

    def attributes(self, path, value=None):
        if value is None:
            return self.attrs
        self.attrs = value
        self.attribute_changes.append(value)

    def unlink(self, path, *args, **kwargs):
        if self.attrs & 1:
            error = PermissionError('access denied')
            error.winerror = 5
            raise error
        return self.original_unlink(path, *args, **kwargs)

    def run_remove(self, unlink=None, validate=None, attempts=1):
        def default_validate(expected):
            ops.assert_unchanged(self.path, expected)
        removal = unlink or self.unlink
        # Replace only this module's os namespace; do not turn pathlib into WindowsPath.
        with (patch.object(ops, 'os', types.SimpleNamespace(name='nt')),
             patch.object(ops, 'windows_attributes', side_effect=self.attributes),
             patch.object(type(self.path), 'unlink', lambda path, *args, **kwargs: removal(path, *args, **kwargs))):
            ops.remove_archived_file(self.path, self.expected, validate or default_validate, attempts, self.event)

    def test_readonly_flag_cleared_preserving_other_flags(self):
        self.run_remove()
        self.assertFalse(self.path.exists())
        self.assertEqual(self.attribute_changes, [0x22])

    def test_persistent_denial_restores_readonly(self):
        def denied(path, *args, **kwargs):
            error = PermissionError('ACL denies')
            error.winerror = 5
            raise error
        with self.assertRaises(PermissionError):
            self.run_remove(denied)
        self.assertEqual(self.path.read_bytes(), b'archived bytes')
        self.assertEqual(self.attrs, 0x23)

    def test_nonreadonly_access_denied_does_not_change_attributes(self):
        self.attrs = 0x22
        def denied(path):
            error = PermissionError('ACL denies')
            error.winerror = 5
            raise error
        with self.assertRaises(PermissionError):
            self.run_remove(denied)
        self.assertEqual(self.attribute_changes, [])

    def test_antivirus_error_does_not_change_attributes(self):
        def blocked(path):
            error = PermissionError('antivirus')
            error.winerror = 225
            raise error
        with self.assertRaises(PermissionError):
            self.run_remove(blocked)
        self.assertEqual(self.attribute_changes, [])

    def test_cancel_after_attribute_change_restores_flag(self):
        original = self.attributes
        def attributes(path, value=None):
            result = original(path, value)
            if value == 0x22:
                self.event.set()
            return result
        self.attributes = attributes
        with self.assertRaises(ops.Cancelled):
            self.run_remove()
        self.assertTrue(self.path.exists())
        self.assertEqual(self.attrs, 0x23)

    def test_revalidate_before_retry_prevents_deleting_changed_file(self):
        self.attrs = 0x22
        calls = []
        def temporary_denial(path):
            calls.append(1)
            path.write_bytes(b'changed')
            raise PermissionError('temporarily busy')
        with patch.object(ops.time, 'sleep'), patch.object(self.event, 'wait', return_value=False):
            with self.assertRaises(ops.StaleComparison):
                self.run_remove(temporary_denial, attempts=2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.path.read_bytes(), b'changed')


if __name__ == '__main__':
    unittest.main()
