"""File type detection, bounded image reuse and checkbox hit testing."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from file_icons import file_type, icon_pixels, FileIcons, COLORS
from ui import checkbox_hit


class IconTests(unittest.TestCase):
    def test_literal_unicode_windows_and_posix_paths_and_case(self):
        for name, expected in [(r'D:\Ilgas [EP]\Ataskaita.PDF', 'pdf'),
                               ('muzika/Žodžiai.FLAC', 'audio'), ('photo.JpEg', 'image'),
                               ('archive.tar.gz', 'archive'), ('budget.xlsx', 'sheet'),
                               ('meeting.docx', 'word'), ('a.pptx', 'slides'),
                               ('video.mkv', 'video'), ('test.py', 'code'),
                               ('readme.md', 'text'), ('setup.exe', 'app'),
                               ('unknown.xyz', 'file'), ('.gitignore', 'file'), ('README', 'file')]:
            with self.subTest(name=name):
                self.assertEqual(file_type(name), expected)
        self.assertEqual(file_type('folder.pdf', 'directory'), 'folder')
        self.assertEqual(file_type('blocked.pdf', 'unknown'), 'file')

    def test_all_icons_are_distinct_and_checkbox_does_not_overwrite_type(self):
        for dark in (False, True):
            signatures = set()
            for category in COLORS:
                frames = [icon_pixels(category, mark, dark) for mark in ('☐', '☑', '—')]
                for pixels in frames:
                    self.assertEqual((len(pixels), {len(row) for row in pixels}), (22, {48}))
                    self.assertIsNone(pixels[0][0])
                type_parts = [tuple(tuple(row[24:]) for row in pixels) for pixels in frames]
                self.assertEqual(type_parts[0], type_parts[1])
                self.assertEqual(type_parts[0], type_parts[2])
                signatures.add(type_parts[0])
                self.assertNotEqual(frames[0], frames[1])
                self.assertNotEqual(frames[1], frames[2])
            # Plain text and generic documents intentionally share a symbol.
            self.assertEqual(len(signatures), len(COLORS) - 1)
        self.assertNotEqual(icon_pixels('pdf', '☑', False), icon_pixels('pdf', '☑', True))

    def test_thousands_of_names_share_images_without_opening_files(self):
        with patch('file_icons.tk.PhotoImage') as photo, patch('builtins.open', side_effect=AssertionError('No I/O')):
            icons = FileIcons(None)
            for index in range(3000):
                icons.get(f'nonexistent/{index}.pdf', 'file', '☐')
            self.assertEqual(photo.call_count, 1)
            icons.get('other.PDF', 'file', '☑')
            icons.get('folder.pdf', 'directory', '☐')
            icons.get('bad.pdf', 'unknown', '—')
            self.assertEqual(photo.call_count, 4)
            self.assertEqual(len(icons.cache), 4)

    def test_checkbox_hit_is_separate_from_icon_path_heading_and_horizontal_scroll(self):
        tree = SimpleNamespace(identify_region=lambda x, y: 'tree' if y > 30 else 'heading',
            identify_column=lambda x: '#0' if x < 72 else '#1',
            identify_row=lambda y: 'file' if 30 < y < 68 else '',
            bbox=lambda row, column: (2, 30, 72, 38))
        for x, y, expected in [(8, 40, False), (19, 40, True), (45, 40, False), (100, 40, False),
                                (8, 12, False), (8, 90, False)]:
            self.assertEqual(checkbox_hit(tree, SimpleNamespace(x=x, y=y)), expected)
        tree.bbox = lambda row, column: (-25, 30, 72, 38)
        self.assertTrue(checkbox_hit(tree, SimpleNamespace(x=5, y=40)))
        self.assertFalse(checkbox_hit(tree, SimpleNamespace(x=15, y=40)))


if __name__ == '__main__':
    unittest.main()
