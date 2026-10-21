"""Regression coverage for literal names, long paths and archive containment."""
from pathlib import Path, PureWindowsPath
import errno
import os
import json
import ntpath
import runpy
import types
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import Settings
import file_ops
from file_ops import BackupError, compare, eligible, execute, guarded_path
from path_utils import display_path, io_path, relative_parts, windows_extended_path
from utils import excluded, normalize_exclusion, within


class PathBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = io_path(self.temporary.name)
        self.source = self.root / 'Origin'
        self.backup = self.root / 'Copy'
        self.source.mkdir()
        self.backup.mkdir()
        self.settings = Settings(str(self.source), str(self.backup), exclusions=[], workers=8, retries=2)

    def tearDown(self):
        # Extended paths also cover cleaning up the deliberately long fixtures.
        shutil.rmtree(self.root)
        self.temporary.cleanup()

    def write(self, root, name, content=b'test'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def run_action(self, mode, names=None, overwrite=False):
        result = compare(self.settings, mode=mode)
        self.assertEqual(result.errors, [])
        selection = set(names) if names is not None else {r.relative for r in result.rows if eligible(r, mode, overwrite)}
        return execute(result, selection, self.settings, overwrite=overwrite, log_directory=self.root / 'logs')

    def test_literal_exclusion_accepts_brackets_and_does_not_match_patterns(self):
        name = 'Jon Lajoie/Jon Lajoie/2010 - Yes [EP]'
        self.write(self.source, name + '/song.mp3', b'original')
        self.write(self.backup, name + '/song.mp3', b'backup')
        rule = normalize_exclusion(display_path(self.source / name), display_path(self.source))
        self.assertEqual(rule, name)
        self.assertFalse(excluded('Jon Lajoie/Jon Lajoie/2010 - Yes E/song.mp3', [rule]))
        self.settings.exclusions = [rule]
        for mode in ('sync', 'restore', 'cleanup'):
            result = compare(self.settings, mode=mode)
            self.assertFalse(result.errors)
            self.assertFalse(any(r.relative.startswith(name) for r in result.rows))

    def test_punctuation_unicode_names_survive_copy_restore_and_cleanup(self):
        names = ["Jon Lajoie/2010 - Yes [EP]/01 - Song (Live).mp3", "Ąžuolas/ąčęėįšųūž.txt",
                 "O'Connor/R&B + 50% #1!.txt", '.idea/compiler.xml', '日本語/音楽.txt',
                 '  leading spaces/keep.txt', 'emoji 🎵/🎵.txt', '~/literal.txt']
        for i, name in enumerate(names):
            self.write(self.source, name, f'original {i}'.encode())
        self.assertEqual(self.run_action('sync')['failed'], 0)
        shutil.rmtree(self.source)
        self.source.mkdir()
        self.assertEqual(self.run_action('restore')['failed'], 0)
        for i, name in enumerate(names):
            self.assertEqual((self.source / name).read_bytes(), f'original {i}'.encode())
        shutil.rmtree(self.source)
        self.source.mkdir()
        report = self.run_action('cleanup')
        self.assertEqual((report['failed'], report['skipped']), (0, 0))
        self.assertEqual(list(self.backup.iterdir()), [])
        for i, name in enumerate(names):
            self.assertEqual((io_path(report['archive']) / 'deleted_from_backup' / name).read_bytes(), f'original {i}'.encode())

    def test_deep_long_paths_copy_overwrite_archive_and_cleanup(self):
        name = '/'.join(['nested [EP] Ąžuolas ' + 'x' * 35] * 7) + '/music.txt'
        self.write(self.source, name, b'v1')
        self.assertGreater(len(str(self.source / name)), 260)
        self.assertEqual(self.run_action('sync')['failed'], 0)
        (self.source / name).write_bytes(b'version two')
        report = self.run_action('sync')
        self.assertEqual(report['failed'], 0)
        self.assertEqual((io_path(report['archive']) / 'before_sync' / name).read_bytes(), b'v1')
        shutil.rmtree(self.source)
        self.source.mkdir()
        report = self.run_action('cleanup')
        self.assertEqual((report['failed'], report['skipped']), (0, 0))
        self.assertEqual(list(self.backup.iterdir()), [])
        self.assertEqual((io_path(report['archive']) / 'deleted_from_backup' / name).read_bytes(), b'version two')

    def test_parallel_archive_has_existing_parents_and_preserves_all_bytes(self):
        names = [f'Akademija.IT/Automatinis testavimas - Copy/project {i % 6}/.idea/file {i}.xml' for i in range(96)]
        for i, name in enumerate(names):
            self.write(self.backup, name, f'file {i}'.encode())
        original = file_ops.archive_file
        def archive(source, destination, expected, cancel):
            self.assertTrue(destination.parent.is_dir())
            return original(source, destination, expected, cancel)
        with patch.object(file_ops, 'archive_file', side_effect=archive):
            report = self.run_action('cleanup')
        self.assertEqual((report['failed'], report['skipped']), (0, 0))
        self.assertEqual(list(self.backup.iterdir()), [])
        for i, name in enumerate(names):
            self.assertEqual((io_path(report['archive']) / 'deleted_from_backup' / name).read_bytes(), f'file {i}'.encode())

    def test_guarded_path_handles_missing_leaf_without_resolving_it(self):
        # Model the inconsistent Windows resolution: the missing leaf retains
        # the extended prefix while its existing parent does not.
        root = PureWindowsPath('D:/Backup/Copy.versions/run')
        leaf = PureWindowsPath('\\\\?\\D:\\Backup\\Copy.versions\\run\\missing\\a.txt')
        self.assertFalse(within(leaf, root))  # Old resolved-string check rejects it.
        expected = self.backup / 'new [EP]/.idea/compiler.xml'
        with patch.object(Path, 'resolve', side_effect=AssertionError('Do not resolve a changing leaf')):
            self.assertEqual(guarded_path(self.backup, 'new [EP]/.idea/compiler.xml'), expected)

    def test_windows_namespace_roundtrip_local_and_unc(self):
        for value in ('D:\\Backup\\Origin\\2010 - Yes [EP]', '\\\\server\\share\\Ąžuolas\\song.txt'):
            extended = windows_extended_path(value)
            self.assertEqual(windows_extended_path(extended), extended)
            self.assertEqual(display_path(extended), value)
        self.assertEqual(relative_parts('Ąžuolas/[EP]/.idea/a.txt', windows=True), ('Ąžuolas', '[EP]', '.idea', 'a.txt'))
        for name in ('../escape', '/absolute', 'C:/outside', 'a/C:relative', 'a\\..\\escape', 'a/stream:data', 'NUL.txt', 'COM1', 'a?b', 'a*b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                relative_parts(name, windows=True)

    @unittest.skipIf(os.name == 'nt', 'Emulates Windows resolver using the host standard library')
    def test_windows_resolver_can_retain_prefix_when_missing_error_changes(self):
        # Parent creation by another worker changes PATH_NOT_FOUND (3) into
        # FILE_NOT_FOUND (2) while realpath checks whether to remove \\?\.
        root = 'D:\\Backup\\Copy.versions\\run'
        full = root + '\\new\\.idea\\compiler.xml'
        attempts = 0
        def missing(code):
            error = FileNotFoundError(errno.ENOENT, 'simulated Windows missing path')
            error.winerror = code
            return error
        def final_name(path):
            nonlocal attempts
            if path == root:
                return '\\\\?\\' + root
            if path == full:
                attempts += 1
                raise missing(2 if attempts >= 3 else 3)
            raise missing(3)
        def readlink(path):
            raise missing(3)
        fake_nt = types.ModuleType('nt')
        fake_nt._getfinalpathname = final_name
        fake_nt.readlink = readlink
        with patch.dict(sys.modules, nt=fake_nt):
            resolver = runpy.run_path(ntpath.__file__)['realpath']
            leaf, parent = resolver(full), resolver(root)
        self.assertTrue(leaf.startswith('\\\\?\\'))
        self.assertFalse(parent.startswith('\\\\?\\'))
        self.assertFalse(within(PureWindowsPath(leaf), PureWindowsPath(parent)))
        self.assertTrue(within(PureWindowsPath(windows_extended_path(leaf)),
                               PureWindowsPath(windows_extended_path(parent))))

    def test_failed_archive_preparation_changes_no_backup_data(self):
        self.write(self.backup, 'folder/file.txt', b'keep')
        original = Path.mkdir
        def mkdir(path, *args, **kwargs):
            if 'deleted_from_backup' in path.parts:
                raise PermissionError(errno.EACCES, 'preparation denied')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'mkdir', mkdir), patch.object(file_ops.time, 'sleep'):
            report = self.run_action('cleanup')
        self.assertEqual(report['state'], 'errors')
        self.assertEqual(report['completed'], 0)
        self.assertEqual((self.backup / 'folder/file.txt').read_bytes(), b'keep')
        saved = json.loads(next((self.root / 'logs').glob('*.json')).read_text(encoding='utf-8'))
        self.assertEqual(saved['state'], 'errors')

    @unittest.skipIf(os.name == 'nt', 'Windows link creation may require privileges')
    def test_guarded_path_blocks_ancestor_and_leaf_links_and_traversal(self):
        outside = self.root / 'outside'
        outside.mkdir()
        self.write(outside, 'secret', b'private')
        (self.backup / 'link').symlink_to(outside, target_is_directory=True)
        (self.backup / 'filelink').symlink_to(outside / 'secret')
        for name in ('link/secret', 'link/new/file', 'filelink', '../outside/secret', '/outside/secret'):
            with self.subTest(name=name), self.assertRaises(BackupError):
                guarded_path(self.backup, name)
        self.assertEqual((outside / 'secret').read_bytes(), b'private')
        self.assertEqual(normalize_exclusion(str(self.backup / 'link'), self.backup), 'link')

    def test_archive_failure_keeps_file_and_explains_remaining_folder(self):
        self.write(self.backup, 'folder/file.txt', b'keep')
        error = PermissionError(errno.EACCES, 'denied')
        error.winerror = 5
        with patch.object(file_ops, 'archive_file', side_effect=error), patch.object(file_ops.time, 'sleep'):
            report = self.run_action('cleanup')
        failed = next(item for item in report['items'] if item['status'] == 'failed')
        folder = next(item for item in report['items'] if item['kind'] == 'directory')
        self.assertEqual(failed['stage'], 'Archyvavimas')
        self.assertEqual(failed['winerror'], 5)
        self.assertIn('deleted_from_backup', failed['operation_path'])
        self.assertIn('nepavyko archyvuoti', folder['message'])
        self.assertEqual((self.backup / 'folder/file.txt').read_bytes(), b'keep')

    def test_empty_folder_temporarily_reported_nonempty_is_retried(self):
        target = self.backup / 'empty'
        target.mkdir()
        original = Path.rmdir
        calls = []
        def remove(path):
            if path == target:
                calls.append(path)
                if len(calls) == 1:
                    raise OSError(errno.ENOTEMPTY, 'transient')
            return original(path)
        with patch.object(Path, 'rmdir', remove), patch.object(file_ops.time, 'sleep') as pause:
            report = self.run_action('cleanup')
        self.assertEqual(report['failed'], 0)
        self.assertEqual(len(calls), 2)
        pause.assert_called_once_with(1)
        self.assertFalse(target.exists())
