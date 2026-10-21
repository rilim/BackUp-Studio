"""Run `python main.py` or use Start_BackUp.bat on Windows."""
from pathlib import Path
import argparse
import os
import shutil
import tempfile
import time

from config import Settings, load_settings


def create_demo(directory: Path) -> Settings:
    source, destination = directory / "Mano_failai", directory / "Atsargine_kopija"
    source.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    samples = {
        "Dokumentai/Kelionės_planas.md": ("Kelionės planas\n" * 220, "Senas kelionės planas\n" * 80),
        "Dokumentai/Pastabos.txt": ("Darbo pastabos\n" * 180, None),
        "Dokumentai/Sutartis.txt": ("Sutarties tekstas\n" * 170, "Sutarties tekstas\n" * 170),
        "Projektai/BackUp/README.md": ("Nauja projekto dokumentacija\n" * 110, "Ankstesnė dokumentacija\n" * 70),
        "Projektai/BackUp/planas.json": ('{"etapas": "GUI"}\n' * 60, None),
        "Projektai/Video/shot001.md": ("Pievos kadro aprašymas\n" * 180, "Senas aprašymas\n" * 160),
        "Projektai/Video/muzika.txt": ("Muzikos idėjos\n" * 50, "Muzikos idėjos\n" * 50),
        "Nuotraukos/kelionių_sąrašas.csv": ("Vieta;Data\nKaunas;2026-09-11\n" * 200, None),
        "Nuotraukos/aprašymai.txt": ("Nuotraukų aprašymai\n" * 90, "Nuotraukų aprašymai\n" * 90),
        "Užrašai/Idėjos.md": ("Idėjos\n" * 130, None),
        "Užrašai/Naujesnis_kopijoje.txt": ("Sena versija", "Nauja versija kopijoje"),
        "Archyvas/Senas_projektas.txt": (None, "Ankstesni projekto failai\n" * 100),
        "Archyvas/Laikinas_eksportas.csv": (None, "Duomenys;2025\n" * 70),
        "Investavimas/Privatu.txt": ("Šis aplankas neįtrauktas", "Neįtrauktas ir kopijoje"),
    }
    now = time.time()
    for index, (relative, (left, right)) in enumerate(samples.items()):
        for root, content in ((source, left), (destination, right)):
            if content is not None:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                stamp = now - (4000 + index * 200) if root == source else now - (86400 + index * 500)
                os.utime(path, (stamp, stamp))
    newer = destination / "Užrašai/Naujesnis_kopijoje.txt"
    os.utime(newer, (now, now))
    (source / "Tuščias_aplankas").mkdir(exist_ok=True)
    return Settings(source=str(source), destination=str(destination), exclusions=["Investavimas", "Islaidos/Islaidos UK"])


def run():
    parser = argparse.ArgumentParser(description="BackUp Studio – darbalaukio failų kopijų programa")
    parser.add_argument("--demo", action="store_true", help="Atidaryti demonstraciją su laikinais pavyzdiniais failais")
    args = parser.parse_args()
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    import tkinter as tk
    from ui import BackupApp
    demo_directory = tempfile.TemporaryDirectory(prefix="BackUp_demo_") if args.demo else None
    try:
        settings, warning = (create_demo(Path(demo_directory.name)), "") if args.demo else load_settings()
        root = tk.Tk()
        icon = Path(__file__).with_name("app.ico")
        if os.name == "nt" and icon.is_file():
            try:
                root.iconbitmap(default=str(icon))
            except tk.TclError:
                pass
        app = BackupApp(root, settings, data_directory=Path(demo_directory.name) / "app_data" if args.demo else None,
                        demo=args.demo, startup_warning=warning)
        if args.demo:
            root.after(250, app.start_scan)
        root.mainloop()
    finally:
        if demo_directory:
            demo_directory.cleanup()


if __name__ == "__main__":
    run()
