"""Integration checks for real Tk widgets and real temporary-file operations."""
from pathlib import Path
from dataclasses import replace
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import tkinter as tk
    import ui
    from ui import BackupApp
except ImportError:
    tk = None
from config import load_settings
from main import create_demo


@unittest.skipIf(tk is None, "tkinter unavailable")
class GuiFlowTests(unittest.TestCase):
    def setUp(self):
        try:
            self.window = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"No GUI display: {error}")
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.callback_errors = []
        self.window.report_callback_exception = lambda kind, error, trace: self.callback_errors.append(str(error))
        self.errors = patch('ui.messagebox.showerror')
        self.error_mock = self.errors.start()
        self.info = patch('ui.messagebox.showinfo')
        self.info.start()
        self.confirm = patch('ui.messagebox.askyesno', return_value=True)
        self.confirm.start()
        self.app = BackupApp(self.window, create_demo(self.root), data_directory=self.root / 'state', demo=True)
        self.window.update()

    def tearDown(self):
        if self.app.busy:
            self.app.cancel_work()
            self.drain()
        self.window.after_cancel(self.app.poll_id)
        self.window.destroy()
        self.confirm.stop()
        self.info.stop()
        self.errors.stop()
        self.temporary.cleanup()
        self.assertEqual(self.callback_errors, [])

    def drain(self):
        deadline = time.monotonic() + 10
        while self.app.busy and time.monotonic() < deadline:
            self.window.update()
            time.sleep(.01)
        self.window.update()
        self.assertFalse(self.app.busy, 'Background operation did not finish')

    def scan(self):
        self.app.start_scan()
        self.drain()
        self.assertIsNotNone(self.app.comparison)
        self.assertFalse(self.app.comparison.errors)
        self.error_mock.assert_not_called()

    def test_comparison_filters_selection_export_and_exclusion_editor(self):
        self.scan()
        self.assertEqual(self.app.stat_values['source_only'].cget('text'), '4')
        self.assertNotIn('Užrašai/Naujesnis_kopijoje.txt', self.app.selected)
        self.app.search_var.set('BackUp/')
        self.assertEqual(len(self.app.visible_rows), 2)
        self.app.clear_selection()
        self.app.select_visible()
        self.assertEqual(len(self.app.selected), 2)
        exported = self.root / 'export.csv'
        with patch('ui.filedialog.asksaveasfilename', return_value=str(exported)):
            self.app.export_differences()
        self.assertTrue(exported.is_file())
        self.app.open_exclusions()
        dialog = self.app.exclusion_window
        dialog.entry_value.set('Projektai/BackUp')
        dialog.add_typed()
        dialog.apply()
        self.assertIn('Projektai/BackUp', self.app.settings.exclusions)
        self.assertIsNone(self.app.comparison)
        self.assertEqual(self.app.execute_button.cget('state'), 'disabled')
        self.scan()
        self.assertFalse(self.app.visible_rows)

    def test_exclusions_filter_remove_keeps_hidden_entries_and_scrolls(self):
        self.app.settings.exclusions = [f'folder-{n:03d}/' + 'long-path-' * 20 for n in range(120)]
        self.app.open_exclusions()
        dialog = self.app.exclusion_window
        self.window.update()
        self.assertLess(dialog.listbox.yview()[1], 1)
        self.assertLess(dialog.listbox.xview()[1], 1)
        self.assertIn('120', dialog.count_label.cget('text'))
        dialog.search_value.set('folder-099')
        self.assertEqual(dialog.listbox.size(), 1)
        removed = dialog.listbox.get(0)
        dialog.listbox.selection_set(0)
        dialog.remove()
        self.assertEqual(len(dialog.values), 119)
        self.assertNotIn(removed, dialog.values)
        self.assertTrue(any(value.startswith('folder-000/') for value in dialog.values))
        dialog.search_value.set('')
        self.assertEqual(dialog.listbox.size(), 119)
        dialog.apply()
        self.assertEqual(len(self.app.settings.exclusions), 119)

    def test_problem_window_scroll_count_and_copy_all_in_both_themes(self):
        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)
        for theme, language in [('light', 'lt'), ('dark', 'en')]:
            ui.set_appearance(language, theme)
            errors = [f'path-{n}: Access denied' for n in range(90)]
            dialog = self.app.show_errors(errors)
            self.window.update()
            children = list(widgets(dialog))
            text = next(child for child in children if isinstance(child, tk.Text))
            self.assertLess(text.yview()[1], 1)
            self.assertTrue(any(isinstance(child, tk.Label) and '90' in child.cget('text') for child in children))
            copy = next(child for child in children if isinstance(child, tk.Button)
                        and child.cget('text') == ui.T('Kopijuoti klaidas'))
            copy.invoke()
            self.assertEqual(dialog.clipboard_get(), '\n\n'.join(errors))
            self.assertEqual(copy.cget('text'), ui.T('Nukopijuota'))
            dialog.destroy()
        ui.set_appearance(self.app.settings.language, self.app.settings.theme)

    def test_partial_scan_good_rows_actionable_unknown_rows_visible(self):
        import file_ops
        original = file_ops.snapshot
        bad = Path(self.app.settings.source) / 'blocked-test'
        bad.write_bytes(b'blocked')
        def snapshot(path):
            if path.name == 'blocked-test':
                raise PermissionError('AV blocked')
            return original(path)
        with patch.object(file_ops, 'snapshot', side_effect=snapshot), patch.object(self.app, 'show_errors'):
            self.app.start_scan()
            self.drain()
        self.assertTrue(self.app.comparison.errors)
        self.assertFalse(self.app.comparison.blocked)
        self.assertNotIn('blocked-test', self.app.selected)
        self.assertTrue(self.app.selected)
        self.assertEqual(self.app.execute_button.cget('state'), 'normal')
        self.app.toggle_row('blocked-test')
        self.assertNotIn('blocked-test', self.app.selected)
        self.app.filter_var.set('Skaitymo problemos')
        self.app.render_rows()
        self.assertEqual([row.relative for row in self.app.visible_rows], ['blocked-test'])
        self.app.open_expanded_list()
        self.window.update()
        self.assertEqual(len(self.app.expanded_list.tree.get_children()), 1)
        self.app.close_expanded_list()

    def test_confirmed_copy_history_and_saved_settings(self):
        self.scan()
        self.app.clear_selection()
        name = 'Dokumentai/Pastabos.txt'
        self.app.toggle_row(name)
        self.app.confirm_execute()
        self.drain()
        target = Path(self.app.settings.destination)
        self.assertTrue((target / name).is_file())
        self.assertFalse((target / 'Užrašai/Idėjos.md').exists())
        self.assertEqual(self.app.last_report['completed'], 1)
        self.app.show_page('history')
        self.window.update()
        self.assertEqual(len(self.app.history_reports), 1)
        first = self.app.history_tree.get_children()[0]
        self.app.history_tree.selection_set(first)
        self.app.show_history_details()
        self.assertIn(name, self.app.history_detail.get('1.0', 'end'))
        self.app.show_page('settings')
        self.app.workers_var.set('2')
        self.app.save_preferences()
        loaded, error = load_settings(self.root / 'state')
        self.assertEqual(loaded.workers, 2)
        self.assertFalse(error)
        self.app.show_page('sync')
        self.window.update()

    def test_restore_modes_and_cleanup_are_separate_explicit_actions(self):
        self.app.show_page('restore')
        self.scan()
        name = 'Dokumentai/Kelionės_planas.md'
        self.assertNotIn(name, self.app.selected)
        self.app.overwrite_var.set(True)
        self.assertIn(name, self.app.selected)
        self.app.clear_selection()
        self.app.toggle_row(name)
        self.app.confirm_execute()
        self.drain()
        self.assertEqual((Path(self.app.settings.source) / name).read_bytes(), (Path(self.app.settings.destination) / name).read_bytes())
        self.app.show_page('cleanup')
        self.scan()
        self.app.clear_selection()
        item = 'Archyvas/Senas_projektas.txt'
        self.app.toggle_row(item)
        self.app.confirm_execute()
        self.drain()
        self.assertFalse((Path(self.app.settings.destination) / item).exists())
        self.assertTrue((Path(self.app.last_report['archive']) / 'deleted_from_backup' / item).exists())

    def test_path_edit_invalidates_results_and_missing_source_cannot_run(self):
        self.scan()
        self.app.source_var.set(str(self.root / 'does_not_exist'))
        self.assertIsNone(self.app.comparison)
        self.assertEqual(self.app.execute_button.cget('state'), 'disabled')
        self.app.start_scan()
        self.drain()
        self.assertIsNone(self.app.comparison)
        self.error_mock.assert_called_once()

    def test_quick_full_scan_and_same_button_restart_after_cancel(self):
        self.app.full_scan_button.invoke()
        self.drain()
        self.assertTrue(self.app.comparison.full_scan)
        self.assertEqual(self.app.comparison.reused_hashes, 0)
        self.app.scan_button.invoke()
        self.drain()
        self.assertGreater(self.app.comparison.reused_hashes, 0)

        import file_ops
        def wait_for_cancel(settings, mode, cancel, notify, cache_file, use_cache):
            while not cancel.is_set():
                time.sleep(.001)
            raise file_ops.Cancelled('Stopped')
        with patch('ui.compare', side_effect=wait_for_cancel):
            self.app.start_scan()
            self.assertEqual(self.app.cancel_button.cget('text'), ui.T('Nutraukti tikrinimą'))
            self.app.cancel_button.invoke()
            self.drain()
        self.assertEqual(self.app.cancel_button.cget('text'), ui.T('Tikrinti iš naujo'))
        self.assertEqual(self.app.cancel_button.cget('state'), 'normal')
        self.app.cancel_button.invoke()
        self.drain()
        self.assertIsNotNone(self.app.comparison)
        self.assertEqual(self.app.cancel_button.cget('state'), 'disabled')
        self.assertEqual(self.app.tree.column('#0', 'width'), 72)
        self.assertEqual(self.app.file_icons.get('a.pdf', 'file', '☐').width(), 60)

    def test_appearance_switch_preserves_selection_and_survives_restart(self):
        self.scan()
        selected = self.app.selected.copy()
        self.app.show_page('settings')
        self.app.language_var.set('en')
        self.app.theme_var.set('dark')
        self.app.save_preferences()
        self.window.update()
        self.assertEqual(self.app.heading_var.get(), 'Settings')
        self.assertEqual(self.app.language_var.get(), 'en')
        self.assertEqual(self.app.theme_var.get(), 'dark')
        self.app.show_page('sync')
        self.assertEqual(self.app.selected, selected)
        self.assertIsNotNone(self.app.comparison)
        self.assertEqual(self.app.filter_combo.get(), 'All differences')
        self.app.filter_display_var.set('New in source')
        self.assertEqual(self.app.filter_var.get(), 'Nauji šaltinyje')
        self.assertTrue(all(row.status == 'source_only' for row in self.app.visible_rows))
        self.assertEqual(self.app.tree.heading('source')['text'], 'SOURCE')
        self.assertNotEqual(self.app.main.cget('bg').lower(), '#f3f6f8')
        self.app.show_page('history')
        self.assertEqual(self.app.history_tree.heading('mode')['text'], 'ACTION')
        loaded, warning = load_settings(self.root / 'state')
        self.assertFalse(warning)
        self.assertEqual((loaded.language, loaded.theme), ('en', 'dark'))
        self.app.show_page('settings')
        self.app.language_var.set('lt')
        self.app.theme_var.set('light')
        self.app.save_preferences()
        self.window.update()
        self.assertEqual(self.app.heading_var.get(), 'Nustatymai')
        self.assertEqual(self.app.main.cget('bg').lower(), '#f3f6f8')

    def test_expanded_list_shares_filters_selection_and_lifecycle(self):
        self.scan()
        self.app.open_expanded_list()
        expanded = self.app.expanded_list
        self.window.update()
        self.assertEqual(expanded.tree.get_children(), self.app.tree.get_children())
        self.app.clear_selection()
        self.app.select_visible()
        self.assertTrue(self.app.selected)
        item = next(iter(self.app.selected))
        expanded.tree.focus(item)
        expanded.tree.selection_set(item)
        expanded.toggle()
        self.window.update()
        self.assertNotIn(item, self.app.selected)
        self.assertEqual(expanded.tree.item(item, 'values'), self.app.tree.item(item, 'values'))
        self.app.search_var.set(item)
        self.window.update()
        self.assertEqual(expanded.tree.get_children(), self.app.tree.get_children())
        self.app.sort_rows('relative')
        self.assertEqual(expanded.tree.get_children(), self.app.tree.get_children())
        self.app.set_busy(True)
        self.assertEqual(expanded.controls[0].cget('state'), 'disabled')
        self.app.set_busy(False)
        selected = self.app.selected.copy()
        self.app.close_expanded_list()
        self.assertEqual(selected, self.app.selected)
        self.app.open_expanded_list()
        self.app.show_page('settings')
        self.assertIsNone(self.app.expanded_list)

    def test_column_drag_keeps_other_widths_and_scroll_after_list_refresh(self):
        self.scan()
        self.app.open_expanded_list()
        self.window.update()
        expanded_widths = None
        for tree in (self.app.tree, self.app.expanded_list.tree):
            tree.xview_moveto(0)
            self.window.update()
            before = {key: int(tree.column(key, 'width')) for key in tree.cget('columns')}
            item = tree.get_children()[0]
            x, y, width, height = tree.bbox(item, 'relative')
            edge = x + width
            separator = next(px for px in range(edge - 4, edge + 5)
                             if tree.identify_region(px, 10) == 'separator' and tree.identify_column(px) == '#1')
            for event, px in [('<ButtonPress-1>', separator), ('<B1-Motion>', separator + 400),
                              ('<ButtonRelease-1>', separator + 400)]:
                tree.event_generate(event, x=px, y=10, rootx=tree.winfo_rootx() + px, rooty=tree.winfo_rooty() + 10)
                self.window.update()
            self.assertEqual(int(tree.column('relative', 'width')), before['relative'] + 400)
            for key in before:
                if key != 'relative':
                    self.assertEqual(int(tree.column(key, 'width')), before[key])
            self.assertLess(tree.xview()[1], 1)
            tree.xview_moveto(.2)
            self.window.update()
            offset = tree.xview()[0]
            self.app.sort_rows('relative')
            self.window.update()
            self.assertAlmostEqual(tree.xview()[0], offset, places=2)
            self.assertEqual(int(tree.column('relative', 'width')), before['relative'] + 400)
            expanded_widths = {key: int(tree.column(key, 'width')) for key in tree.cget('columns')}
        self.app.close_expanded_list()
        self.app.open_expanded_list()
        self.window.update()
        self.assertEqual({key: int(self.app.expanded_list.tree.column(key, 'width')) for key in expanded_widths}, expanded_widths)

    def test_detail_strip_does_not_resize_file_list(self):
        for mode in ('sync', 'restore', 'cleanup'):
            self.app.show_page(mode)
            for geometry in ('1100x760', '1440x980'):
                self.window.geometry(geometry)
                self.window.update()
                height = self.app.tree.winfo_height()
                self.app.detail_var.set('Very long path / ' * 80 + '\nDetails ' * 20)
                self.window.update()
                self.assertEqual(self.app.tree.winfo_height(), height)
                self.assertGreaterEqual(height, 5 * 38 + 30)
                self.assertIn('Very long path', self.app.detail_label.get('1.0', 'end'))
                self.app.detail_var.set('Short text')

    def test_expanded_list_handles_thousands_without_growing_window(self):
        self.scan()
        example = next(row for row in self.app.comparison.rows if row.status == 'source_only' and row.kind == 'file')
        self.app.comparison.rows[:] = [replace(example, relative=f'example/{i:04}.txt') for i in range(2000)]
        self.app.selected.clear()
        self.app.render_rows()
        self.app.open_expanded_list()
        self.window.update()
        expanded = self.app.expanded_list
        height = expanded.window.winfo_height()
        self.assertEqual(len(expanded.tree.get_children()), 2000)
        expanded.tree.yview_moveto(1)
        self.window.update()
        self.assertGreater(expanded.tree.yview()[0], .9)
        self.app.select_visible()
        self.assertEqual(len(self.app.selected), 2000)
        self.assertEqual(expanded.window.winfo_height(), height)
        self.app.source_var.set(str(self.root / 'different'))
        self.window.update()
        self.assertEqual(expanded.tree.get_children(), ())
        self.assertFalse(self.app.selected)

    def test_equal_list_height_across_modes_languages_and_themes(self):
        for theme, language in [('light', 'lt'), ('dark', 'en')]:
            self.app.show_page('settings')
            self.app.theme_var.set(theme)
            self.app.language_var.set(language)
            self.app.save_preferences()
            for geometry in ('1100x760', '1440x980'):
                self.window.geometry(geometry)
                heights = []
                for mode in ('sync', 'restore', 'cleanup'):
                    self.app.show_page(mode)
                    self.window.update()
                    heights.append(self.app.tree.winfo_height())
                    self.assertGreaterEqual(heights[-1], 5 * 38 + 30)
                    self.assertTrue(self.app.scan_button.winfo_ismapped())
                    self.assertTrue(self.app.expand_button.winfo_ismapped())
                    self.assertTrue(self.app.exclusion_label.winfo_ismapped())
                    self.assertTrue(self.app.execute_button.winfo_ismapped())
                self.assertLessEqual(max(heights) - min(heights), 2)

    def test_icons_and_mouse_selection_in_main_and_expanded_list_all_modes(self):
        for mode in ('sync', 'restore', 'cleanup'):
            self.app.show_page(mode)
            self.scan()
            self.app.open_expanded_list()
            self.window.update()
            self.app.clear_selection()
            item = next(row.relative for row in self.app.visible_rows
                        if row.kind == 'file' and ui.eligible(row, mode, False))
            row = self.app.row_map[item]
            for tree in (self.app.tree, self.app.expanded_list.tree):
                tree.see(item)
                tree.xview_moveto(0)
                self.window.update()
                original = tree.item(item, 'image')
                self.assertTrue(original)
                x, y, width, height = tree.bbox(item, '#0')
                # The icon selects/focuses; it must not check the row.
                tree.event_generate('<ButtonPress-1>', x=x + 47, y=y + height // 2)
                tree.event_generate('<ButtonRelease-1>', x=x + 47, y=y + height // 2)
                self.window.update()
                self.assertNotIn(item, self.app.selected)
                tree.event_generate('<ButtonPress-1>', x=x + 20, y=y + height // 2)
                tree.event_generate('<ButtonRelease-1>', x=x + 20, y=y + height // 2)
                self.window.update()
                self.assertIn(item, self.app.selected)
                self.assertNotEqual(tree.item(item, 'image'), original)
                self.assertEqual(self.app.tree.item(item, 'image'), self.app.expanded_list.tree.item(item, 'image'))
                self.assertIs(self.app.row_map[item], row)
                self.app.clear_selection()
            self.app.close_expanded_list()

    def test_dark_spinbox_arrows_have_explicit_contrast(self):
        self.app.show_page('settings')
        self.app.theme_var.set('dark')
        self.app.save_preferences()
        style = ui.ttk.Style(self.window)
        self.assertEqual(style.lookup('TSpinbox', 'arrowcolor'), ui.INK)
        self.assertEqual(style.lookup('TSpinbox', 'arrowcolor', ('active',)), ui.TEAL)
        self.assertEqual(style.lookup('TSpinbox', 'arrowcolor', ('disabled',)), ui.DISABLED_FG)

    def test_settings_save_stays_visible_on_small_window(self):
        self.window.geometry('1100x760')
        self.app.show_page('settings')
        self.window.update()
        footer = self.app.settings_save_button
        bottom = self.window.winfo_rooty() + self.window.winfo_height()
        self.assertTrue(footer.winfo_ismapped())
        self.assertLessEqual(footer.winfo_rooty() + footer.winfo_height(), bottom)
        self.app.settings_canvas.yview_moveto(1.0)
        self.window.update()
        viewport_bottom = self.app.settings_canvas.winfo_rooty() + self.app.settings_canvas.winfo_height()
        self.assertLessEqual(self.app.settings_dark_radio.winfo_rooty() + self.app.settings_dark_radio.winfo_height(), viewport_bottom)
        self.assertLessEqual(footer.winfo_rooty() + footer.winfo_height(), bottom)
        self.app.theme_var.set('dark')
        footer.invoke()
        self.window.update()
        loaded, warning = load_settings(self.root / 'state')
        self.assertFalse(warning)
        self.assertEqual(loaded.theme, 'dark')

    def assert_disabled_button(self, widget):
        self.assertEqual(widget.cget('state'), 'disabled')
        self.assertEqual(widget.cget('bg'), ui.DISABLED_BG)
        self.assertEqual(widget.cget('disabledforeground'), ui.DISABLED_FG)
        self.assertEqual(widget.cget('highlightbackground'), ui.DISABLED_BORDER)
        self.assertEqual(widget.cget('activebackground'), ui.DISABLED_BG)
        self.assertEqual(widget.cget('cursor'), 'arrow')
        self.assertGreater(int(widget.cget('highlightthickness')), 0)

    def test_disabled_buttons_and_busy_state_restore_in_both_themes(self):
        for language, theme in [('lt', 'light'), ('en', 'dark')]:
            with self.subTest(theme=theme):
                self.app.show_page('settings')
                self.app.language_var.set(language)
                self.app.theme_var.set(theme)
                self.app.save_preferences()
                self.app.show_page('sync')
                self.window.update()
                self.app.clear_selection()
                self.assert_disabled_button(self.app.execute_button)
                self.assert_disabled_button(self.app.cancel_button)
                text = self.app.execute_button.cget('text')
                self.app.execute_button.event_generate('<Enter>')
                self.window.update()
                self.assert_disabled_button(self.app.execute_button)
                self.assertEqual(self.app.execute_button.cget('text'), text)
                with patch('ui.messagebox.askyesno') as invoked:
                    self.app.execute_button.invoke()
                    invoked.assert_not_called()
                self.app.execute_button.event_generate('<Leave>')
                self.scan()
                self.assertEqual(self.app.execute_button.cget('state'), 'normal')
                self.assertEqual(self.app.execute_button.cget('bg'), ui.TEAL)
                self.assertEqual(self.app.execute_button.cget('fg'), ui.ON_ACCENT)
                self.assertEqual(self.app.execute_button.cget('cursor'), 'hand2')
                nav_colors = {key: {option: nav.cget(option) for option in ('bg', 'fg', 'highlightbackground')}
                              for key, nav in self.app.nav_buttons.items()}
                self.app.set_busy(True)
                for widget in [self.app.scan_button, self.app.execute_button, self.app.select_all_button,
                               self.app.clear_button, self.app.export_button]:
                    self.assert_disabled_button(widget)
                for key, nav in self.app.nav_buttons.items():
                    self.assertEqual(nav.cget('state'), 'disabled')
                    for option, color in nav_colors[key].items():
                        self.assertEqual(nav.cget(option), color)
                    self.assertEqual(nav.cget('disabledforeground'), nav_colors[key]['fg'])
                    with patch.object(self.app, 'show_page') as navigate:
                        nav.invoke()
                        navigate.assert_not_called()
                self.assertEqual(self.app.cancel_button.cget('state'), 'normal')
                self.assertEqual(self.app.cancel_button.cget('bg'), ui.WHITE)
                self.app.set_busy(False)
                self.assertEqual(self.app.scan_button.cget('bg'), ui.TEAL)
                self.assertEqual(self.app.nav_buttons['sync'].cget('bg'), ui.NAV_ACTIVE)
                for key, nav in self.app.nav_buttons.items():
                    self.assertEqual(nav.cget('state'), 'normal')
                    for option, color in nav_colors[key].items():
                        self.assertEqual(nav.cget(option), color)
                self.assert_disabled_button(self.app.cancel_button)
                self.app.clear_selection()
                self.assert_disabled_button(self.app.execute_button)

    def test_disabled_button_contrast_and_configure_apis(self):
        def luminance(hex_color):
            channels = [int(hex_color[i:i+2], 16) / 255 for i in (1, 3, 5)]
            linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
            return sum(c * weight for c, weight in zip(linear, (.2126, .7152, .0722)))
        for theme in ('light', 'dark'):
            ui.set_appearance('lt', theme)
            widget = ui.button(self.window, 'Test', lambda: self.fail('Disabled button invoked'), primary=True,
                               state='disabled')
            try:
                self.assert_disabled_button(widget)
                ratio = (luminance(ui.DISABLED_FG) + .05) / (luminance(ui.DISABLED_BG) + .05)
                self.assertGreaterEqual(max(ratio, 1 / ratio), 4.5)
                widget.invoke()
                self.assertIn('state', widget.configure())
                self.assertEqual(widget.configure('state')[-1], 'disabled')
                widget.config({'text': 'Updated', 'state': 'normal'})
                self.assertEqual(widget.cget('bg'), ui.TEAL)
                widget['state'] = 'disabled'
                self.assert_disabled_button(widget)
            finally:
                widget.destroy()
        ui.set_appearance(self.app.settings.language, self.app.settings.theme)


if __name__ == '__main__':
    unittest.main()
