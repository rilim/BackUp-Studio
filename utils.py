"""Formatting and validated path utilities shared by the engine and GUI."""
from datetime import datetime
from pathlib import Path, PurePosixPath
import csv
import os
import subprocess
import sys
from path_utils import io_path, relative_parts

STATUS_LABELS = {
    "source_only": "Naujas šaltinyje",
    "destination_only": "Tik kopijoje",
    "modified": "Pakeistas",
    "identical": "Vienodas",
    "conflict": "Tipo konfliktas",
    "unreadable": "Neperskaityta / apsaugota",
}
MODE_LABELS = {"sync": "Sinchronizavimas", "restore": "Atkūrimas", "cleanup": "Kopijos valymas"}


def format_size(size: int | None) -> str:
    if size is None:
        return "—"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return (f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}").replace(".", ",")
        value /= 1024
    return ""


def format_date(mtime_ns: int | None, compact=False) -> str:
    if mtime_ns is None:
        return "—"
    return datetime.fromtimestamp(mtime_ns / 1e9).strftime("%m-%d %H:%M" if compact else "%Y-%m-%d %H:%M:%S")


def within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def normalize_exclusion(value: str, source: str | Path) -> str:
    value = value.replace("\\", "/")
    if not value.strip():
        raise ValueError("Įveskite aplanko kelią.")
    # Check before Path can silently collapse '.' components. Square brackets
    # and other punctuation are literal; exclusions never use glob matching.
    if any(part in (".", "..") for part in value.split('/')):
        raise ValueError("Nurodykite aplanką šaltinio viduje, pvz., Dokumentai/Laikina.")
    path = Path(value)
    if path.is_absolute():
        root = io_path(source)
        try:
            # Do not follow the excluded entry: links pointing outside the root
            # must themselves be excludable without reading their targets.
            value = io_path(path).relative_to(root).as_posix()
        except ValueError:
            raise ValueError("Išimtis turi būti šaltinio aplanko viduje.") from None
    relative = PurePosixPath(value)
    if relative.is_absolute() or relative == PurePosixPath(".") or ".." in relative.parts:
        raise ValueError("Nurodykite aplanką šaltinio viduje, pvz., Dokumentai/Laikina.")
    relative_parts(value)
    return relative.as_posix()


def excluded(relative: str, patterns: tuple[str, ...] | list[str]) -> bool:
    name = relative.casefold() if os.name == "nt" else relative
    for item in patterns:
        item = item.casefold() if os.name == "nt" else item
        if name == item or name.startswith(item + "/"):
            return True
    return False


def open_folder(path: str | Path):
    path = Path(path)
    if not path.is_dir():
        raise ValueError(f"Aplanko dar nėra: {path}")
    if os.name == "nt":
        os.startfile(str(path))
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


def export_csv(path: str | Path, headers, rows):
    """UTF-8 BOM and semicolons work well in Lithuanian Excel installations."""
    def safe_cell(value):
        text = str(value) if value is not None else ""
        return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text
    with open(path, "w", encoding="utf-8-sig", newline="") as output:
        writer = csv.writer(output, delimiter=";")
        writer.writerow(headers)
        writer.writerows([[safe_cell(cell) for cell in row] for row in rows])
