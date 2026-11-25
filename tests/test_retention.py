"""Version archive retention: decisions, safety guards and the review dialog.
All operations use disposable temporary folders."""
from datetime import datetime, timedelta
from pathlib import Path
import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import file_ops
import retention
from config import Settings, load_settings, save_settings
from retention import ArchiveRun, GB, archive_root, list_archive_runs, plan_prune, prune


NOW = datetime(2026, 11, 25, 12, 0, 0)


def run(day, size=10, state="completed", problem="", mode="sync"):
    started = NOW - timedelta(days=day)
    run_id = started.strftime("%Y%m%d_%H%M%S") + "_" + f"{day:08x}"
    return ArchiveRun(run_id, Path(run_id), started, mode, state, 1, size, None, problem)


def actions(plan):
    return [item.action for item in plan]


class PlanTests(unittest.TestCase):
    def test_no_rules_keeps_everything(self):
        plan = plan_prune([run(d) for d in range(5)], now=NOW)
        self.assertEqual(actions(plan), ["protected"] + ["keep"] * 4)

    def test_keep_last_runs_alone_deletes_older(self):
        plan = plan_prune([run(d) for d in range(5)], keep_runs=2, now=NOW)
        self.assertEqual(actions(plan), ["protected", "protected", "delete", "delete", "delete"])
        self.assertEqual(plan[1].reason, "Tarp paskutinių saugomų")

    def test_last_runs_are_never_deleted_by_size_or_age(self):
        # The user's case: keep 4, archive limit 1 GB, newest run 820 MB, then 74.5 MB runs.
        mb = 1024 ** 2
        runs = [run(0, 820 * mb)] + [run(d, int(74.5 * mb)) for d in range(1, 11)]
        plan = plan_prune(runs, keep_runs=4, keep_days=120, max_bytes=1 * GB, now=NOW)
        self.assertEqual(actions(plan)[:4], ["protected"] * 4)
        self.assertEqual(set(actions(plan)[4:]), {"delete"})
        self.assertEqual(plan[4].reason, "Viršija archyvo dydį")
        # Very old recent runs are kept too: the guarantee also beats the age rule.
        old = [run(d) for d in (500, 600, 700)]
        self.assertEqual(actions(plan_prune(old, keep_runs=3, keep_days=30, now=NOW)), ["protected"] * 3)

    def test_older_runs_within_limits_are_kept_when_size_or_age_rule_is_set(self):
        runs = [run(d, 10) for d in range(6)]
        plan = plan_prune(runs, keep_runs=2, max_bytes=45, now=NOW)
        # Two guaranteed (20 B), then older runs while the total stays within 45 B.
        self.assertEqual(actions(plan), ["protected", "protected", "keep", "keep", "delete", "delete"])
        plan = plan_prune(runs, keep_runs=2, keep_days=3, now=NOW)
        self.assertEqual(actions(plan), ["protected", "protected", "keep", "keep", "delete", "delete"])

    def test_keep_days(self):
        plan = plan_prune([run(d) for d in (0, 10, 89, 91, 400)], keep_days=90, now=NOW)
        self.assertEqual(actions(plan), ["protected", "keep", "keep", "delete", "delete"])

    def test_size_limit_keeps_newest_that_fit_then_deletes_all_older(self):
        runs = [run(0, 4 * GB), run(1, 4 * GB), run(2, 4 * GB), run(3, 1)]
        plan = plan_prune(runs, max_bytes=10 * GB, now=NOW)
        # 4 + 4 fit; the third would exceed; once exceeded, older ones go even if small.
        self.assertEqual(actions(plan), ["protected", "keep", "delete", "delete"])

    def test_newest_unfinished_and_unexpected_runs_are_never_deleted(self):
        runs = [run(500, 100 * GB), run(600, state="running"), run(700, problem="link"), run(800)]
        plan = plan_prune(runs, keep_runs=1, keep_days=1, max_bytes=1, now=NOW)
        self.assertEqual(actions(plan), ["protected", "protected", "protected", "delete"])
        self.assertEqual([item.reason for item in plan[:3]],
                         ["Naujausia operacija", "Nebaigta operacija", "Netikėtas turinys"])

    def test_plan_is_ordered_newest_first_regardless_of_input(self):
        plan = plan_prune([run(3), run(1), run(2)], now=NOW)
        self.assertEqual([item.run.started for item in plan], sorted((r.started for r in (run(1), run(2), run(3))), reverse=True))


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "Copy.versions"
        self.archive.mkdir()
        self.logs = self.root / "logs"
        self.settings = Settings(str(self.root / "Original"), str(self.root / "Copy"), exclusions=[])

    def make_run(self, day, files=("before_sync/a.txt",), state="completed", mode="sync", read_only=False):
        started = NOW - timedelta(days=day)
        run_id = started.strftime("%Y%m%d_%H%M%S") + "_" + f"{day:08x}"
        folder = self.archive / run_id
        for name in files:
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{run_id}:{name}", encoding="utf-8")
            if read_only:
                path.chmod(stat.S_IREAD)
        (folder / "manifest.json").write_text(json.dumps(
            {"id": run_id, "started": started.isoformat(timespec="seconds"), "mode": mode, "state": state}),
            encoding="utf-8")
        return folder

    def listed(self):
        runs, warnings = list_archive_runs(self.archive)
        return {r.id: r for r in runs}, warnings

    def test_only_program_runs_are_recognised(self):
        good = self.make_run(1)
        (self.archive / "Mano užrašai").mkdir()
        (self.archive / "readme.txt").write_text("x", encoding="utf-8")
        no_manifest = self.archive / "20260101_101010_0badc0de"
        no_manifest.mkdir()
        wrong_id = self.make_run(2)
        (wrong_id / "manifest.json").write_text(json.dumps({"id": "something-else"}), encoding="utf-8")
        runs, warnings = self.listed()
        self.assertEqual(list(runs), [good.name])
        self.assertEqual(len(warnings), 4)
        self.assertEqual(runs[good.name].files, 2)  # data file + manifest

    def test_prune_deletes_only_planned_runs_and_logs_history(self):
        newest = self.make_run(0)
        old = self.make_run(100, files=("before_sync/a.txt", "before_sync/deep/er/b.txt"), read_only=True)
        older = self.make_run(200, mode="cleanup", files=("deleted_from_backup/x.txt",))
        stranger = self.archive / "Mano užrašai"
        stranger.mkdir()
        runs, _ = list_archive_runs(self.archive)
        plan = retention.plan_for_settings(Settings(keep_days=30), runs, now=NOW)
        self.assertEqual([i.run.id for i in plan if i.action == "delete"], [old.name, older.name])
        report = prune(self.archive, plan, self.settings, log_directory=self.logs)
        self.assertEqual((report["completed"], report["failed"], report["state"]), (2, 0, "completed"))
        self.assertTrue(newest.exists())
        self.assertTrue(stranger.exists())
        self.assertFalse(old.exists())
        self.assertFalse(older.exists())
        log = json.loads((self.logs / f"{report['id']}.json").read_text(encoding="utf-8"))
        self.assertEqual((log["mode"], log["state"]), ("prune", "completed"))
        self.assertEqual({item["path"] for item in log["items"]}, {old.name, older.name})

    def test_changed_run_is_not_deleted(self):
        self.make_run(0)
        old = self.make_run(100)
        runs, _ = list_archive_runs(self.archive)
        plan = plan_prune(runs, keep_runs=1, now=NOW)
        (old / "before_sync" / "new-after-review.txt").write_text("new", encoding="utf-8")
        report = prune(self.archive, plan, self.settings, log_directory=self.logs)
        self.assertEqual((report["completed"], report["failed"]), (0, 1))
        self.assertTrue((old / "before_sync" / "a.txt").exists())
        self.assertTrue((old / "manifest.json").exists())

    def test_unfinished_run_found_at_deletion_time_is_kept(self):
        self.make_run(0)
        old = self.make_run(100)
        runs, _ = list_archive_runs(self.archive)
        plan = plan_prune(runs, keep_runs=1, now=NOW)
        manifest = json.loads((old / "manifest.json").read_text(encoding="utf-8"))
        manifest["state"] = "running"
        (old / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        report = prune(self.archive, plan, self.settings, log_directory=self.logs)
        self.assertEqual(report["failed"], 1)
        self.assertTrue(old.exists())

    @unittest.skipUnless(os.name == "nt", "Windows junction")
    def test_run_containing_junction_is_protected_and_target_untouched(self):
        import _winapi
        self.make_run(0)
        old = self.make_run(100)
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "precious.txt").write_text("keep", encoding="utf-8")
        _winapi.CreateJunction(str(outside), str(old / "link"))
        runs, _ = list_archive_runs(self.archive)
        plan = plan_prune(runs, keep_runs=1, now=NOW)
        self.assertEqual([i.action for i in plan if i.run.id == old.name], ["protected"])
        prune(self.archive, plan, self.settings, log_directory=self.logs)
        self.assertTrue((outside / "precious.txt").exists())
        self.assertTrue(old.exists())

    def test_cancel_stops_before_next_run(self):
        self.make_run(0)
        first, second = self.make_run(100), self.make_run(200)
        runs, _ = list_archive_runs(self.archive)
        plan = plan_prune(runs, keep_runs=1, now=NOW)
        cancel = threading.Event()
        cancel.set()
        report = prune(self.archive, plan, self.settings, cancel=cancel, log_directory=self.logs)
        self.assertEqual((report["completed"], report["cancelled"], report["state"]), (0, 2, "cancelled"))
        self.assertTrue(first.exists() and second.exists())

    def test_real_cleanup_archive_is_recognised(self):
        source, destination = self.root / "Original", self.root / "Copy"
        source.mkdir()
        destination.mkdir()
        (destination / "old.txt").write_text("old", encoding="utf-8")
        comparison = file_ops.compare(self.settings, "cleanup")
        report = file_ops.execute(comparison, {"old.txt"}, self.settings, log_directory=self.logs)
        self.assertEqual(report["completed"], 1)
        runs, warnings = list_archive_runs(archive_root(self.settings))
        self.assertEqual(warnings, [])
        self.assertEqual([(r.id, r.mode, r.state) for r in runs], [(report["id"], "cleanup", "completed")])
        self.assertIsNotNone(runs[0].finished)
        self.assertGreaterEqual(runs[0].finished, runs[0].started)


class UniqueFilesTests(unittest.TestCase):
    def test_entries_and_content_based_uniqueness(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, backup, archive = root / "Original", root / "Copy", root / "Copy.versions"
            (source / "moved").mkdir(parents=True)
            backup.mkdir()
            run_id = "20261125_101028_2a91ad9f"
            data = archive / run_id / "deleted_from_backup" / "Projektas"
            data.mkdir(parents=True)
            (data / "renamed-elsewhere.txt").write_text("same content", encoding="utf-8")
            (source / "moved" / "other-name.txt").write_text("same content", encoding="utf-8")
            (data / "same-name-different.txt").write_text("archived version", encoding="utf-8")
            (source / "same-name-different.txt").write_text("archived VERSION", encoding="utf-8")  # same size, other bytes
            (data / "only-here.txt").write_text("unique", encoding="utf-8")
            (archive / run_id / "manifest.json").write_text(json.dumps(
                {"id": run_id, "started": "2026-11-25T10:10:28", "mode": "cleanup", "state": "completed"}), encoding="utf-8")
            runs, _ = list_archive_runs(archive)
            run_info = runs[0]
            self.assertEqual([relative for relative, _ in run_info.entries], [
                "deleted_from_backup/Projektas/only-here.txt",
                "deleted_from_backup/Projektas/renamed-elsewhere.txt",
                "deleted_from_backup/Projektas/same-name-different.txt"])
            progress = []
            found = {}
            unique = retention.find_unique_files(runs, [str(source), str(backup)],
                                                 notify=lambda d, t: progress.append((d, t)), found=found)
            self.assertEqual(sorted(relative for relative, _ in unique[run_id]), [
                "deleted_from_backup/Projektas/only-here.txt",
                "deleted_from_backup/Projektas/same-name-different.txt"])
            self.assertEqual(progress[-1], (3, 3))
            # The identical copy's location is reported as "<root folder>\<path>".
            self.assertEqual(found, {(run_id, "deleted_from_backup/Projektas/renamed-elsewhere.txt"):
                                     "Original\\" + str(Path("moved") / "other-name.txt")})
            self.assertEqual(runs[0].finished, None)  # manifest without "finished" stays unknown
            self.assertTrue((data / "only-here.txt").exists())  # read-only check


class SettingsTests(unittest.TestCase):
    def test_old_settings_file_loads_with_unlimited_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "settings.json").write_text(json.dumps({"source": "C:/a", "destination": "C:/b"}), encoding="utf-8")
            loaded, warning = load_settings(Path(temp))
            self.assertEqual(warning, "")
            self.assertEqual((loaded.keep_runs, loaded.keep_days, loaded.max_versions_gb, loaded.prune_prompt), (0, 0, 0, False))
            self.assertFalse(retention.rules_enabled(loaded))

    def test_round_trip_and_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            save_settings(Settings(keep_runs=20, keep_days=90, max_versions_gb=10, prune_prompt=True), Path(temp))
            loaded, _ = load_settings(Path(temp))
            self.assertEqual((loaded.keep_runs, loaded.keep_days, loaded.max_versions_gb, loaded.prune_prompt), (20, 90, 10, True))
        for bad in (dict(keep_runs=-1), dict(keep_days=5000), dict(max_versions_gb="5"), dict(prune_prompt=1)):
            with self.assertRaises(ValueError):
                Settings(**bad).validate()

    def test_archive_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            default = archive_root(Settings(str(root / "Original"), str(root / "Copy")))
            self.assertEqual(default.name, "Copy.versions")
            custom = archive_root(Settings(str(root / "Original"), str(root / "Copy"), versions_directory=str(root / "V")))
            self.assertEqual(custom.name, "V")
            with self.assertRaises(file_ops.BackupError):
                archive_root(Settings(str(root / "Original"), str(root / "Copy"), versions_directory=str(root / "Copy" / "v")))


def ui_font_width(text):
    import ui
    return ui.tkfont.Font(family=ui.FONT, size=10).measure(text)


class DialogTests(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
            self.window = tk.Tk()
        except Exception as error:
            self.skipTest(f"No GUI display: {error}")
        import ui
        from main import create_demo
        self.ui = ui
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.callback_errors = []
        self.window.report_callback_exception = lambda kind, error, trace: self.callback_errors.append(str(error))
        self.patches = [patch("ui.messagebox.showerror"), patch("ui.messagebox.showinfo"),
                        patch("ui.messagebox.askyesno", return_value=True)]
        for item in self.patches:
            item.start()
        settings = create_demo(self.root)
        settings.keep_runs = 1
        self.app = ui.BackupApp(self.window, settings, data_directory=self.root / "state", demo=True)
        self.window.update()
        self.archive = archive_root(self.app.current_settings())

    def tearDown(self):
        if self.app.prune_window is not None and self.app.prune_window.winfo_exists():
            self.app.prune_window.destroy_dialog()
        self.window.after_cancel(self.app.poll_id)
        if self.app.density_id is not None:
            self.window.after_cancel(self.app.density_id)
        self.window.destroy()
        for item in self.patches:
            item.stop()
        self.temporary.cleanup()
        self.assertEqual(self.callback_errors, [])

    def make_run(self, day):
        started = datetime.now() - timedelta(days=day)
        run_id = started.strftime("%Y%m%d_%H%M%S") + "_" + f"{day:08x}"
        folder = self.archive / run_id / "before_sync"
        folder.mkdir(parents=True)
        (folder / "a.txt").write_text(run_id, encoding="utf-8")
        (self.archive / run_id / "manifest.json").write_text(json.dumps(
            {"id": run_id, "started": started.isoformat(timespec="seconds"), "mode": "sync", "state": "completed"}),
            encoding="utf-8")
        return self.archive / run_id

    def pump(self, condition, timeout=10):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.window.update()
            time.sleep(0.02)
        self.window.update()
        self.assertTrue(condition(), "Dialog did not reach the expected state")

    def test_prompt_with_nothing_to_delete_closes_silently(self):
        self.make_run(0)
        self.app.open_prune(prompt=True)
        dialog = self.app.prune_window
        self.assertIsNotNone(dialog)
        self.assertEqual(dialog.state(), "withdrawn")
        self.pump(lambda: self.app.prune_window is None)

    def test_prompt_with_old_runs_is_shown_and_deletes_only_after_confirmation(self):
        newest, old = self.make_run(0), self.make_run(40)
        self.app.open_prune(prompt=True)
        dialog = self.app.prune_window
        self.pump(lambda: dialog.winfo_viewable())
        self.assertEqual(str(dialog.delete_button.cget("state")), "normal")
        self.assertTrue(old.exists())  # Shown, but nothing deleted yet.
        dialog.delete_button.invoke()
        self.pump(lambda: not old.exists() and not dialog.busy())
        self.assertTrue(newest.exists())
        self.app.show_page("history")
        modes = [self.app.history_tree.item(item, "values")[1] for item in self.app.history_tree.get_children()]
        self.assertIn("Senų versijų valymas", modes)

    def test_prompt_is_offered_after_operation_only_when_enabled(self):
        self.make_run(40)
        self.make_run(0)
        with patch.object(self.app, "open_prune") as opened:
            self.app.settings.prune_prompt = False
            self.app.events.put(("completed", {"completed": 1, "failed": 0, "skipped": 0, "cancelled": 0, "items": []}))
            with patch.object(self.app, "start_scan"):
                self.window.after_cancel(self.app.poll_id)
                self.app.poll_events()
            opened.assert_not_called()
            self.app.settings.prune_prompt = True
            self.app.events.put(("completed", {"completed": 1, "failed": 0, "skipped": 0, "cancelled": 0, "items": []}))
            with patch.object(self.app, "start_scan"):
                self.window.after_cancel(self.app.poll_id)
                self.app.poll_events()
            opened.assert_called_once_with(prompt=True)

    def test_stat_cards_count_folders_beside_files(self):
        # Only empty folders left must not look like "nothing to do" (all zeros).
        self.app.show_page("sync")
        self.app.start_scan()
        self.pump(lambda: not self.app.busy and self.app.comparison is not None)
        self.assertEqual(self.app.stat_values["source_only"].cget("text"), "4")
        self.assertIn("APLANKŲ: 1", self.app.stat_captions["source_only"].cget("text"))
        self.assertIn("APLANKŲ: 1", self.app.stat_captions["destination_only"].cget("text"))
        self.assertNotIn("APLANKŲ", self.app.stat_captions["modified"].cget("text"))

    def test_stat_card_filter_toggles_and_can_be_cleared(self):
        self.app.show_page("sync")
        self.app.start_scan()
        self.pump(lambda: not self.app.busy and self.app.comparison is not None)
        everything = len(self.app.visible_rows)
        card, color, _ = self.app.stat_cards["modified"]
        self.assertFalse(self.app.show_all_button.winfo_ismapped())
        self.app.toggle_stat_filter("Pakeisti")
        self.window.update()
        self.assertEqual(self.app.filter_var.get(), "Pakeisti")
        self.assertTrue(all(row.status == "modified" for row in self.app.visible_rows))
        self.assertEqual(card.cget("highlightbackground"), color)
        self.assertTrue(self.app.show_all_button.winfo_ismapped())
        # The reset button sits left of the filter box.
        self.assertLess(self.app.show_all_button.winfo_rootx(), self.app.filter_combo.winfo_rootx())
        self.app.toggle_stat_filter("Pakeisti")  # Clicking the active card again shows everything.
        self.window.update()
        self.assertEqual((self.app.filter_var.get(), len(self.app.visible_rows)), ("Visi skirtumai", everything))
        self.assertNotEqual(card.cget("highlightbackground"), color)
        self.assertFalse(self.app.show_all_button.winfo_ismapped())
        self.app.toggle_stat_filter("Nauji šaltinyje")
        self.window.update()
        self.app.show_all_button.invoke()
        self.window.update()
        self.assertEqual((self.app.filter_var.get(), len(self.app.visible_rows)), ("Visi skirtumai", everything))

    def test_dialog_shows_folder_contents_and_unique_files_before_delete(self):
        self.make_run(0)
        started = datetime.now() - timedelta(days=40)
        run_id = started.strftime("%Y%m%d_%H%M%S") + "_00000c1e"
        data = self.archive / run_id / "deleted_from_backup" / "Projektai"
        data.mkdir(parents=True)
        (data / "lost.txt").write_text("exists nowhere else", encoding="utf-8")
        source_file = next(Path(self.app.settings.source).rglob("*.md"))
        (data / "kept-elsewhere.md").write_bytes(source_file.read_bytes())
        (self.archive / run_id / "manifest.json").write_text(json.dumps(
            {"id": run_id, "started": started.isoformat(timespec="seconds"), "mode": "cleanup", "state": "completed"}),
            encoding="utf-8")
        self.app.open_prune()
        dialog = self.app.prune_window
        self.pump(lambda: dialog.unique is not None)
        rows = {dialog.tree.set(row, "folder"): row for row in dialog.tree.get_children()}
        self.assertIn(run_id, rows)
        self.assertEqual(dialog.tree.selection(), (rows[run_id],))  # run with unique files is preselected
        self.assertIn("tik archyve: 1", dialog.tree.set(rows[run_id], "plan"))
        listed = [dialog.files.item(row, "values") for row in dialog.files.get_children()]
        self.assertEqual([(values[0], values[2]) for values in listed], [
            ("Projektai/lost.txt", "Tik archyve"),
            ("Projektai/kept-elsewhere.md", Path(self.app.settings.source).name + "\\" +
             str(source_file.relative_to(Path(self.app.settings.source))))])
        self.assertEqual(dialog.tree.heading("date", "text"), "PRADĖTA")
        # Long paths: the file list scrolls sideways and a selected row shows both full paths.
        self.assertTrue(str(dialog.files.cget("xscrollcommand")))
        found_row = dialog.files.get_children()[1]
        location = dialog.files.set(found_row, "where")
        self.assertGreaterEqual(int(dialog.files.column("where", "width")),
                                ui_font_width(location))
        dialog.files.selection_set(found_row)
        self.window.update()
        detail = dialog.file_detail.cget("text")
        self.assertIn("Kur dar yra: " + location, detail)
        self.assertIn(str(Path("Projektai") / "kept-elsewhere.md"), detail)
        self.assertIn(run_id, dialog.detail_title.cget("text"))
        self.assertIn("Failai, pašalinti iš kopijos valymo metu", dialog.detail_info.cget("text"))
        self.assertIn("Failų, kurių daugiau niekur nėra: 1", dialog.warning.cget("text"))
        self.assertEqual(str(dialog.delete_button.cget("state")), "normal")
        with patch.object(self.app, "open_path") as opened:
            dialog.open_button.invoke()
        opened.assert_called_once()
        self.assertTrue(opened.call_args[0][0].endswith(run_id))

    def test_settings_page_saves_retention(self):
        self.app.show_page("settings")
        self.app.keep_runs_var.set("15")
        self.app.keep_days_var.set("60")
        self.app.max_versions_var.set("5")
        self.app.prune_prompt_var.set(True)
        self.app.save_preferences()
        loaded, warning = load_settings(self.root / "state")
        self.assertEqual(warning, "")
        self.assertEqual((loaded.keep_runs, loaded.keep_days, loaded.max_versions_gb, loaded.prune_prompt), (15, 60, 5, True))


if __name__ == "__main__":
    unittest.main()
