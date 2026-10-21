"""Entry script for the native Windows launcher; no downloads or installation."""
from pathlib import Path
import os
import sys
import tempfile
import traceback

APP = Path(__file__).resolve().parent
RUNTIME = APP.parent
_dll_handles = []


def configure_runtime():
    if os.name != "nt":
        raise RuntimeError("Šis paketas skirtas Windows x64.")
    for directory in (RUNTIME, RUNTIME / "DLLs"):
        _dll_handles.append(os.add_dll_directory(str(directory)))
    os.environ["TCL_LIBRARY"] = str(RUNTIME / "tcl" / "tcl_library")
    os.environ["TK_LIBRARY"] = str(RUNTIME / "tcl" / "tk_library")
    os.environ.pop("TCLLIBPATH", None)
    sys.dont_write_bytecode = True
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BackUpStudio.Desktop.2")


def self_test(log_path):
    """Opt-in checks use temporary files; they never open the user's backup."""
    import tkinter as tk
    import unittest
    import ctypes
    root = tk.Tk()  # Fail explicitly instead of allowing all GUI checks to skip.
    root.withdraw()
    print("Tcl:", root.tk.call("info", "patchlevel"), "Tk:", root.tk.call("package", "provide", "Tk"))
    root.destroy()
    suite = unittest.defaultTestLoader.discover(str(APP / "tests"))
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
    if not result.wasSuccessful() or result.testsRun < 33:
        raise RuntimeError("Diagnostikos testai nepraėjo. Žr. startup.log.")
    sys.stderr.flush()
    ctypes.windll.user32.MessageBoxW(None,
        f"Patikrinta: {result.testsRun} testai. Praleista: {len(result.skipped)}.\n"
        f"Ataskaita: {log_path}", "BackUp Studio – diagnostika", 0x40)


def run():
    from config import state_directory
    log_path = state_directory() / "startup.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        output = log_path.open("w", encoding="utf-8", buffering=1)
    except OSError:
        log_path = Path(tempfile.gettempdir()) / f"BackUpStudio-startup-{os.getpid()}.log"
        output = log_path.open("w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = output
    try:
        print("BackUp Studio portable /", sys.version)
        print("Executable:", sys.executable)
        configure_runtime()
        if sys.argv[1:] == ["--self-test"]:
            self_test(log_path)
        else:
            from main import run as run_gui
            run_gui()
    except Exception:
        traceback.print_exc()
        output.flush()
        return 1
    finally:
        output.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
