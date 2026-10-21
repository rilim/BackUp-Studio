"""Readable Windows paths at presentation boundaries; I/O paths stay intact."""
from pathlib import Path
import json
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import Settings
import file_ops
from path_utils import display_data, display_path, display_text, io_path, windows_extended_path

SLASH = chr(92)
PREFIX = SLASH * 2 + '?' + SLASH


class DisplayTests(unittest.TestCase):
    def test_drive_and_unc_plain_and_quoted_os_errors(self):
        drive = 'D:' + SLASH + SLASH.join(['Backup', "O'Connor", 'Ąžuolas [EP]', 'file.txt'])
        unc = SLASH * 2 + SLASH.join(['server', 'share', '日本語', 'file.txt'])
        for original in (drive, unc):
            path = windows_extended_path(original)
            self.assertEqual(display_path(path), original)
            self.assertEqual(display_text('Path: ' + path), 'Path: ' + original)
            error = PermissionError(13, 'Access denied', path)
            rendered = display_text(str(error))
            self.assertNotIn(PREFIX, rendered)
            self.assertIn(original, rendered)
            self.assertIn('[Errno 13]', rendered)
            self.assertEqual(path, windows_extended_path(original))

    def test_multiple_paths_rename_errors_and_repeated_rendering(self):
        first = PREFIX + 'D:' + SLASH + 'folder' + SLASH + 'source.txt'
        second = PREFIX + 'UNC' + SLASH + 'server' + SLASH + 'share' + SLASH + 'target.txt'
        error = OSError(13, 'Denied', first, None, second)
        message = f'Source: {first}\n{error}\nBackup: {second}'
        cleaned = display_text(message)
        self.assertIn(display_path(first), cleaned)
        self.assertIn(display_path(second), cleaned)
        self.assertNotIn(PREFIX, cleaned)
        self.assertNotIn(repr(PREFIX)[1:-1], cleaned)
        self.assertEqual(display_text(cleaned), cleaned)

    def test_normal_paths_and_real_escape_like_names_remain_unchanged(self):
        values = ['D:' + SLASH + 'new' + SLASH + 'test.txt',
                  SLASH * 2 + 'server' + SLASH + 'share',
                  'C:/data/keep.txt', '/tmp/example', '', 'BackUp Studio',
                  "D:" + SLASH + "O'Connor/keep [EP].txt"]
        for value in values:
            self.assertEqual(display_text(value), value)
        path = PREFIX + 'D:' + SLASH + 'new' + SLASH + 'test.txt'
        self.assertEqual(display_text(f'Error: {path!r}'), "Error: '" + display_path(path) + "'")

    def test_report_export_copy_cleans_old_logs_without_mutation(self):
        path = PREFIX + 'D:' + SLASH + 'Backup' + SLASH + 'test.txt'
        report = {'source': path, 'items': [{'message': str(PermissionError(13, 'Denied', path))}],
                  'completed': 0, 'failed': 1, 'cancelled': False}
        cleaned = display_data(report)
        encoded = json.dumps(cleaned, ensure_ascii=False)
        decoded = json.loads(encoded)
        self.assertEqual(decoded['source'], display_path(path))
        self.assertIn(display_path(path), decoded['items'][0]['message'])
        self.assertEqual(report['source'], path)
        self.assertIsNot(cleaned['items'], report['items'])
        self.assertIs(decoded['cancelled'], False)
        self.assertEqual(decoded['failed'], 1)

    def test_new_scan_errors_and_operation_logs_have_readable_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = io_path(temporary)
            source, backup = root / 'source', root / 'backup'
            source.mkdir()
            backup.mkdir()
            (source / 'bad').write_bytes(b'bad')
            (source / 'good').write_bytes(b'good')
            settings = Settings(str(source), str(backup), exclusions=[], retries=1)
            windows_path = PREFIX + 'D:' + SLASH + 'long' + SLASH + 'file.txt'
            original = file_ops.file_hash
            def read(path, *args):
                if path.name == 'bad':
                    raise PermissionError(13, 'Denied', windows_path)
                return original(path, *args)
            with patch.object(file_ops, 'file_hash', side_effect=read):
                plan = file_ops.compare(settings)
            self.assertEqual(len(plan.errors), 1)
            self.assertIn(display_path(windows_path), plan.errors[0])
            self.assertNotIn(repr(PREFIX)[1:-1], plan.errors[0])
            with patch.object(file_ops, 'verified_temporary', side_effect=PermissionError(13, 'Denied', windows_path)):
                report = file_ops.execute(plan, {'good'}, settings, log_directory=root / 'logs')
            self.assertEqual(report['failed'], 1)
            saved = json.loads(next((root / 'logs').glob('*.json')).read_text())
            self.assertIn(display_path(windows_path), saved['items'][0]['message'])
            self.assertNotIn(PREFIX, saved['items'][0]['message'])
            self.assertEqual(saved['scan_errors'][0]['relative'], 'bad')

    def test_custom_errors_render_paths_without_altering_arguments(self):
        path = PREFIX + 'D:' + SLASH + 'folder' + SLASH + 'file.txt'
        error = file_ops.StaleComparison('Changed: ' + path)
        self.assertEqual(str(error), 'Changed: ' + display_path(path))
        self.assertIn(PREFIX, error.args[0])


class UiPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import tkinter as tk
            import ui
            cls.tk, cls.ui = tk, ui
        except ImportError as error:
            raise unittest.SkipTest(str(error))

    def test_path_entries_normalize_initial_value_set_and_direct_tcl_paste(self):
        interpreter = self.tk.Tcl()  # no display or sockets needed
        path = PREFIX + 'D:' + SLASH + 'folder' + SLASH + 'file.txt'
        unc = PREFIX + 'UNC' + SLASH + 'server' + SLASH + 'share'
        value = self.ui.PathTextVar(master=interpreter, value=path)
        self.assertEqual(value.get(), display_path(path))
        value.set(unc)
        self.assertEqual(value.get(), display_path(unc))
        interpreter.globalsetvar(value._name, path)
        self.assertEqual(value.get(), display_path(path))

    def test_error_text_in_lt_en_and_legacy_history_details(self):
        path = PREFIX + 'D:' + SLASH + 'folder' + SLASH + 'file.txt'
        report = {'source': path, 'destination': path, 'archive': path,
                  'completed': 0, 'failed': 1, 'skipped': 0, 'cancelled': 0,
                  'items': [{'status': 'failed', 'path': 'file.txt',
                             'message': str(PermissionError(13, 'Denied', path))}]}
        for language in ['lt', 'en']:
            with patch.object(self.ui, '_language', language):
                self.assertIn(display_path(path), self.ui.T('Kelias: ' + path))
                details = Mock()
                app = types.SimpleNamespace(history_selection=lambda: (report, None), history_detail=details)
                self.ui.BackupApp.show_history_details(app)
                displayed = details.insert.call_args.args[1]
                self.assertNotIn(PREFIX, displayed)
                self.assertNotIn(repr(PREFIX)[1:-1], displayed)
                self.assertIn(display_path(path), displayed)
        self.assertEqual(report['source'], path)


if __name__ == '__main__':
    unittest.main()
