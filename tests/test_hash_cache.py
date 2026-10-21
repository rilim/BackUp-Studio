"""Fast scans must reuse only path-specific, unchanged file hashes."""
from pathlib import Path
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import file_ops
from config import Settings


class HashCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.destination = self.root / 'backup'
        self.source.mkdir()
        self.destination.mkdir()
        self.cache = self.root / 'state' / 'hash_cache.sqlite3'
        self.settings = Settings(str(self.source), str(self.destination), exclusions=[])

    def write(self, root, name, content):
        path = root / name
        path.write_bytes(content)
        return path

    def scan(self, *, fast=True, **kwargs):
        return file_ops.compare(self.settings, cache_file=self.cache, use_cache=fast, **kwargs)

    def test_cold_warm_changed_and_full_scans(self):
        source = self.write(self.source, 'a.txt', b'AAAA')
        self.write(self.destination, 'a.txt', b'AAAA')
        cold = self.scan()
        self.assertEqual((cold.reused_hashes, cold.verified_hashes), (0, 2))
        self.assertEqual(cold.rows[0].status, 'identical')
        with patch.object(file_ops, 'file_hash', side_effect=AssertionError('warm scan read file')):
            warm = self.scan()
        self.assertEqual((warm.reused_hashes, warm.verified_hashes), (2, 0))
        source.write_bytes(b'BBBB')
        os.utime(source, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns + 2_000_000_000))
        changed = self.scan()
        self.assertEqual((changed.reused_hashes, changed.verified_hashes), (1, 1))
        self.assertEqual(changed.rows[0].status, 'modified')
        full = self.scan(fast=False)
        self.assertEqual((full.reused_hashes, full.verified_hashes), (0, 2))
        self.assertTrue(full.full_scan)

    def test_same_relative_name_never_uses_other_roots_digest(self):
        self.write(self.source, 'a', b'AAAA')
        self.write(self.destination, 'a', b'BBBB')
        self.assertEqual(self.scan().rows[0].status, 'modified')
        with patch.object(file_ops, 'file_hash', side_effect=AssertionError('warm scan read file')):
            result = self.scan()
        self.assertEqual(result.rows[0].status, 'modified')
        self.assertEqual(result.reused_hashes, 2)

    def test_removed_and_recreated_file_is_read_again(self):
        path = self.write(self.source, 'old', b'one')
        self.scan()
        path.unlink()
        self.scan()
        self.write(self.source, 'old', b'two')
        self.assertEqual(self.scan().reused_hashes, 0)

    def test_cancelled_scan_does_not_commit_cache(self):
        self.write(self.source, 'a', b'first')
        cancel = threading.Event()
        def stop(data):
            if data['phase'] == 'hash':
                cancel.set()
        with self.assertRaises(file_ops.Cancelled):
            self.scan(cancel=cancel, notify=stop)
        self.assertEqual(self.scan().verified_hashes, 1)

    def test_corrupt_cache_falls_back_to_full_scan_and_does_not_block(self):
        self.cache.parent.mkdir()
        self.cache.write_bytes(b'not a SQLite file')
        self.write(self.source, 'a', b'data')
        result = self.scan()
        self.assertEqual(result.verified_hashes, 1)
        self.assertTrue(result.cache_warning)
        self.assertEqual(result.rows[0].status, 'source_only')

    def test_cached_file_that_becomes_unreadable_is_reported(self):
        blocked = self.write(self.source, 'blocked', b'data')
        self.write(self.destination, 'good', b'good')
        self.scan()
        original = Path.open
        def open_file(path, *args, **kwargs):
            if path == blocked:
                raise PermissionError('AV blocked')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', open_file):
            result = self.scan()
        self.assertTrue(result.errors)
        self.assertFalse(result.blocked)
        self.assertEqual(next(row for row in result.rows if row.relative == 'blocked').status, 'unreadable')
        self.assertEqual(next(row for row in result.rows if row.relative == 'good').status, 'destination_only')

    def test_cache_inside_working_folder_is_not_written(self):
        self.write(self.source, 'a', b'data')
        cache = self.source / 'app-state' / 'hash_cache.sqlite3'
        result = file_ops.compare(self.settings, cache_file=cache, use_cache=True)
        self.assertFalse(cache.exists())
        self.assertEqual(result.verified_hashes, 1)
        self.assertIn('darbo aplanke', result.cache_warning)


if __name__ == '__main__':
    unittest.main()
