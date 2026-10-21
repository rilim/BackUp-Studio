"""Controller checks without a display; native pointer behavior is in test_gui."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from ui import ColumnWidths, BackupApp
except ImportError:
    ColumnWidths = None


class ColumnSurface:
    """Small column/binding surface; deliberately has no native resizing."""
    def __init__(self):
        self.values = {key: {'width': width, 'minwidth': minimum, 'stretch': True}
                       for key, width, minimum in [('check', 36, 36), ('relative', 295, 210),
                           ('status', 145, 95), ('source', 113, 72), ('destination', 113, 72), ('action', 170, 100)]}
        self.tags = ('widget', 'Treeview', 'all')
        self.region, self.column_id = 'separator', '#2'
        self.handlers = {}

    def __str__(self):
        return '.!frame.!treeview'  # Real Tk widget names begin with a dot.

    def cget(self, option):
        return {'columns': tuple(key for key in self.values if key != '#0'),
                'displaycolumns': ('relative', 'status', 'source', 'destination', 'action') if '#0' in self.values else ('#all',),
                'show': ('tree', 'headings') if '#0' in self.values else ('headings',)}[option]

    def column(self, key, option=None, **values):
        self.values[key].update(values)
        return self.values[key][option] if option else self.values[key].copy()

    def bindtags(self, tags=None):
        if tags is not None:
            self.tags = tags
        return self.tags

    def bind_class(self, tag, sequence, handler):
        # Tk bind treats dot-prefixed tags as real window pathnames.
        if tag.startswith('.') and tag != str(self):
            raise ValueError(f'bad window path name "{tag}"')
        self.handlers[(tag, sequence)] = handler

    def unbind_class(self, tag, sequence):
        del self.handlers[(tag, sequence)]

    def bind(self, sequence, handler, **options):
        self.handlers[sequence] = handler

    def identify_region(self, x, y):
        return self.region

    def identify_column(self, x):
        return self.column_id


@unittest.skipIf(ColumnWidths is None, 'Tkinter module unavailable')
class ColumnControllerTests(unittest.TestCase):
    def setUp(self):
        self.tree, self.saved = ColumnSurface(), {}
        self.control = ColumnWidths(self.tree, self.saved)

    def event(self, x, **kwargs):
        return SimpleNamespace(x=x, x_root=x + 100, y=12, **kwargs)

    def test_drag_changes_only_target_and_stops_native_resize_binding(self):
        before = {key: value['width'] for key, value in self.tree.values.items()}
        self.assertNotEqual(self.tree.tags[0], 'Treeview')
        self.assertTrue(all(not value['stretch'] for value in self.tree.values.values()))
        self.assertEqual(self.control.press(self.event(331)), 'break')
        self.assertEqual(self.control.motion(self.event(831)), 'break')
        self.assertEqual(self.control.release(self.event(831)), 'break')
        self.assertEqual(self.tree.column('relative', 'width'), 795)
        for key in before:
            if key != 'relative':
                self.assertEqual(self.tree.column(key, 'width'), before[key])
        self.control.fit(SimpleNamespace(width=900))
        self.assertEqual(self.tree.column('relative', 'width'), 795)

    def test_initial_fit_then_manual_widths_survive_reopen(self):
        self.control.fit(SimpleNamespace(width=1200))
        self.assertEqual(sum(value['width'] for value in self.tree.values.values()), 1198)
        self.tree.column_id = '#3'
        self.control.press(self.event(800))
        self.control.release(self.event(850))
        self.assertEqual(self.saved['status'], 195)
        restored = ColumnSurface()
        controller = ColumnWidths(restored, self.saved)
        controller.fit(SimpleNamespace(width=850))
        self.assertEqual({key: value['width'] for key, value in restored.values.items()}, self.saved)

    def test_minimum_limit_can_expand_again_and_non_separator_clicks_pass(self):
        self.control.press(self.event(400))
        self.control.motion(self.event(-500))
        self.assertEqual(self.tree.column('relative', 'width'), 210)
        self.control.release(self.event(500))
        self.assertEqual(self.tree.column('relative', 'width'), 395)
        self.tree.region = 'heading'
        self.assertIsNone(self.control.press(self.event(50)))
        self.assertIsNone(self.control.motion(self.event(100)))
        self.assertEqual(self.tree.column('relative', 'width'), 395)

    def test_resize_bindings_removed_when_table_destroyed(self):
        self.control.destroy(SimpleNamespace(widget=self.tree))
        self.assertFalse(any(isinstance(key, tuple) for key in self.tree.handlers))

    def test_icon_gutter_and_hidden_check_column_do_not_shift_resize_target(self):
        self.tree.values['#0'] = dict(width=60, minwidth=60, stretch=False)
        control = ColumnWidths(self.tree, {})
        control.fit(SimpleNamespace(width=1200))
        visible = ('#0', 'relative', 'status', 'source', 'destination', 'action')
        self.assertEqual(sum(self.tree.column(key, 'width') for key in visible), 1198)
        before = {key: self.tree.column(key, 'width') for key in self.tree.values}
        self.tree.column_id = '#1'  # First displayed data column is now the path.
        control.press(self.event(400))
        control.release(self.event(600))
        self.assertEqual(self.tree.column('relative', 'width'), before['relative'] + 200)
        for key in before:
            if key != 'relative':
                self.assertEqual(self.tree.column(key, 'width'), before[key])
        self.tree.column_id = '#0'
        self.assertEqual(control.press(self.event(60)), 'break')
        self.assertIsNone(control.drag)

    def test_density_uses_actual_table_space_and_does_not_oscillate(self):
        app = SimpleNamespace(density_id='scheduled', compact=False, page='restore',
            root=SimpleNamespace(winfo_height=lambda: 980),
            tree=SimpleNamespace(winfo_exists=lambda: True, winfo_height=lambda: 150),
            apply_density=Mock())
        with patch('ui.tkfont.Font') as font:
            font.return_value.metrics.return_value = 18
            BackupApp.check_density(app)
            self.assertTrue(app.compact)  # Tall window but little actual table space.
            app.apply_density.assert_called_once()
            self.assertIsNone(app.density_id)
            app.tree.winfo_height = lambda: 280
            BackupApp.check_density(app)
            self.assertTrue(app.compact)  # Keep the saved space, avoid a resize loop.
            app.apply_density.assert_called_once()
            app.tree.winfo_height = lambda: 500
            BackupApp.check_density(app)
            self.assertFalse(app.compact)
            self.assertEqual(app.apply_density.call_count, 2)
            app.root.winfo_height = lambda: 760
            BackupApp.check_density(app)
            self.assertTrue(app.compact)


if __name__ == '__main__':
    unittest.main()
