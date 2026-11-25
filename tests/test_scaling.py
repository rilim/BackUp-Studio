"""Pixel sizes follow the Windows display scale (100 %, 125 %, 150 % ...) and never exceed the screen."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui
from main import create_demo


class ScaleHelperTests(unittest.TestCase):
    def tearDown(self):
        ui.SCALE = 1.0

    def test_detect_scale_from_dpi(self):
        for dpi, expected in ((96, 1.0), (120, 1.25), (144, 1.5), (192, 2.0), (72, 1.0), (1000, 3.0)):
            root = SimpleNamespace(winfo_fpixels=lambda unit, dpi=dpi: float(dpi))
            self.assertEqual(ui.detect_scale(root), expected)

        def broken(unit):
            raise tk.TclError("no display")
        self.assertEqual(ui.detect_scale(SimpleNamespace(winfo_fpixels=broken)), 1.0)

    def test_fit_window_scales_and_clamps_to_screen(self):
        calls = {}
        window = SimpleNamespace(winfo_screenwidth=lambda: 1920, winfo_screenheight=lambda: 1080,
                                 geometry=lambda value: calls.setdefault("geometry", value),
                                 minsize=lambda w, h: calls.setdefault("minsize", (w, h)))
        ui.SCALE = 1.25  # 125 % on a 1920x1080 screen
        self.assertEqual(ui.fit_window(window, 1440, 980, 1100, 760), (1800, 968))
        self.assertEqual(calls["minsize"], (1375, 950))
        calls.clear()
        ui.SCALE = 1.5  # 150 %: the design minimum would not fit, so it is limited by the screen
        width, height = ui.fit_window(window, 1440, 980, 1100, 760)
        min_w, min_h = calls["minsize"]
        self.assertEqual((min_w, min_h), (1650, 1080 - ui.S(90)))
        self.assertLessEqual(height, 1080)
        self.assertLessEqual(width, 1920)


class ScaledAppTests(unittest.TestCase):
    def setUp(self):
        try:
            self.window = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"No GUI display: {error}")
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.window.after_cancel(self.app.poll_id)
        if self.app.density_id is not None:
            self.window.after_cancel(self.app.density_id)
        self.window.destroy()
        self.temporary.cleanup()
        ui.SCALE = 1.0

    def test_app_uses_scaled_sizes_within_screen(self):
        with patch("ui.detect_scale", return_value=1.25):
            self.app = ui.BackupApp(self.window, create_demo(self.root), data_directory=self.root / "state", demo=True)
        self.window.update()
        self.assertEqual(self.app.row_height, ui.S(38))
        self.assertEqual(int(ui.ttk.Style(self.window).lookup("Treeview", "rowheight")), ui.S(38))
        min_w, min_h = self.window.minsize()
        self.assertEqual(min_w, min(ui.S(1100), self.window.winfo_screenwidth() - ui.S(40)))
        self.assertEqual(min_h, min(ui.S(760), self.window.winfo_screenheight() - ui.S(90)))
        self.assertEqual(int(self.app.tree.column("relative", "minwidth")), ui.S(210))
        self.assertEqual(int(self.app.tree.column("#0", "width")), 72)  # icon/checkbox gutter keeps its layout

    def test_unscaled_display_keeps_design_sizes(self):
        with patch("ui.detect_scale", return_value=1.0):
            self.app = ui.BackupApp(self.window, create_demo(self.root), data_directory=self.root / "state", demo=True)
        self.window.update()
        self.assertEqual(self.app.row_height, 38)
        self.assertEqual(self.window.minsize()[0], min(1100, self.window.winfo_screenwidth() - 40))

    def test_compact_mode_slims_buttons(self):
        with patch("ui.detect_scale", return_value=1.0):
            self.app = ui.BackupApp(self.window, create_demo(self.root), data_directory=self.root / "state", demo=True)
        self.app.compact = True
        self.app.apply_density()
        self.assertTrue(self.app.density_buttons)
        self.assertTrue(all(int(widget.cget("pady")) == 4 for widget in self.app.density_buttons))
        self.app.compact = False
        self.app.apply_density()
        self.assertTrue(all(int(widget.cget("pady")) == 9 for widget in self.app.density_buttons))


if __name__ == "__main__":
    unittest.main()
