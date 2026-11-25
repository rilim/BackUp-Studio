"""Optional retention for the version archive.

Only whole archive runs created by this program are ever removed, and only after
the user has reviewed the exact plan. Nothing here runs without a confirmation.

Safety rules:
- a run folder must match the run-id pattern AND contain a manifest.json whose
  "id" equals the folder name; anything else in the archive is never touched;
- the newest run and unfinished ("running") runs are always kept;
- a run containing links/junctions or unsupported entries is always kept;
- before deleting, the run is re-inspected; any change keeps the rest intact;
- links are never followed; manifest.json is removed last so an interrupted
  deletion remains recognisable and can be finished later.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import json
import os
import re
import stat
import uuid

from config import Settings, state_directory, write_json
from file_ops import (BackupError, Cancelled, check_cancel, file_hash, matches, remove_empty_directory,
                      retry_io, snapshot, windows_attributes)
from path_utils import display_path, display_text, display_data, io_path, resolve_root
from utils import within

RUN_PATTERN = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{8}$")
GB = 1024 ** 3
# What the first folder inside a run means (named by file_ops.execute).
CONTENT_LABELS = {
    "deleted_from_backup": "Failai, pašalinti iš kopijos valymo metu",
    "before_sync": "Senos versijos, perrašytos sinchronizuojant",
    "before_restore": "Senos versijos, perrašytos atkuriant",
}


@dataclass(frozen=True)
class ArchiveRun:
    id: str
    path: Path
    started: datetime
    mode: str
    state: str
    files: int
    size: int
    folder: object  # Snapshot of the run folder when it was inspected
    problem: str = ""  # Non-empty: the run is protected and never deleted
    entries: tuple = ()  # (relative path with "/", size) of every archived file, manifest excluded
    finished: datetime | None = None  # When the operation ended (Explorer may show a later OneDrive sync time)


@dataclass(frozen=True)
class PlanItem:
    run: ArchiveRun
    action: str  # "keep", "delete" or "protected"
    reason: str = ""


def archive_root(settings: Settings) -> Path | None:
    """The version archive configured for the current folders (None if not determinable)."""
    if settings.versions_directory.strip():
        root = resolve_root(settings.versions_directory)
    else:
        if not settings.destination.strip():
            return None
        destination = resolve_root(settings.destination)
        if not destination.name:
            return None
        root = destination.with_name(destination.name + ".versions")
    for value in (settings.source, settings.destination):
        if value.strip():
            protected = resolve_root(value)
            if within(root, protected) or within(protected, root):
                raise BackupError("Versijų archyvas turi būti atskirai nuo abiejų pasirinktų aplankų.")
    return root


def _read_manifest(folder: Path) -> dict:
    manifest = folder / "manifest.json"
    info = snapshot(manifest)
    if info is None or info.kind != "file":
        raise ValueError("nėra manifest.json")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("id") != folder.name:
        raise ValueError("manifest.json nepriklauso šiam aplankui")
    return data


def _started(data: dict, name: str) -> datetime:
    try:
        return datetime.fromisoformat(str(data["started"]))
    except (KeyError, ValueError):
        return datetime.strptime(name[:15], "%Y%m%d_%H%M%S")


def _walk(folder: Path, cancel=None):
    """Yield (path, Snapshot) below folder, children before parents. Never follows links."""
    pending = [folder]
    directories = []
    while pending:
        check_cancel(cancel)
        current = pending.pop()
        directories.append(current)
        with os.scandir(current) as iterator:
            entries = list(iterator)
        for entry in entries:
            path = Path(entry.path)
            info = snapshot(path)  # Raises BackupError for links/junctions/unsupported types.
            if info is None:
                raise BackupError(f"Failas dingo skaitant: {path}")
            if info.kind == "directory":
                pending.append(path)
            else:
                yield path, info
    for directory in reversed(directories):
        yield directory, None


def inspect_run(folder: Path, cancel=None) -> ArchiveRun:
    folder_info = snapshot(folder)
    if folder_info is None or folder_info.kind != "directory":
        raise ValueError("ne aplankas")
    data = _read_manifest(folder)
    files = size = 0
    problem = ""
    entries = []
    try:
        for path, info in _walk(folder, cancel):
            if info is not None:
                files += 1
                size += info.size
                relative = path.relative_to(folder).as_posix()
                if relative != "manifest.json":
                    entries.append((relative, info.size))
    except Cancelled:
        raise
    except (OSError, BackupError) as error:
        problem = display_text(str(error))
    state = str(data.get("state", ""))
    entries.sort(key=lambda item: item[0].casefold())
    try:
        finished = datetime.fromisoformat(str(data["finished"]))
    except (KeyError, ValueError):
        finished = None
    return ArchiveRun(folder.name, folder, _started(data, folder.name), str(data.get("mode", "")), state,
                      files, size, folder_info, problem, tuple(entries), finished)


def find_unique_files(runs, roots, cancel=None, notify=None, found=None) -> dict[str, list[tuple[str, int]]]:
    """For each run, the archived files whose exact content exists nowhere under roots.

    Read-only. Only files with a matching size are hashed; links are not followed.
    If `found` is a dict, it receives {(run id, relative): location} for every archived file
    whose identical copy was located (location = root folder name, a backslash, the path inside it).
    """
    wanted = {size for run in runs for _, size in run.entries}
    candidates = defaultdict(list)
    origin = {}
    for root in roots:
        root = io_path(root)
        if not root.is_dir():
            continue
        root_label = root.name or display_path(root)
        for current, _, names in os.walk(root, onerror=lambda error: None):
            check_cancel(cancel)
            for name in names:
                path = Path(current) / name
                try:
                    info = path.lstat()
                except OSError:
                    continue
                if stat.S_ISREG(info.st_mode) and info.st_size in wanted:
                    candidates[info.st_size].append(path)
                    origin[path] = root_label + "\\" + str(path.relative_to(root))
    hashes = {}

    def digest(path):
        if path not in hashes:
            try:
                hashes[path] = file_hash(path, cancel)
            except OSError:
                hashes[path] = None
        return hashes[path]

    known = {}
    total = sum(len(run.entries) for run in runs)
    done = 0
    result = {}
    for run in runs:
        unique = []
        for relative, size in run.entries:
            check_cancel(cancel)
            done += 1
            if notify and done % 25 == 0:
                notify(done, total)
            if size not in candidates:
                unique.append((relative, size))
                continue
            if size not in known:
                known[size] = {}
                for path in candidates[size]:
                    value = digest(path)
                    if value is not None:
                        known[size].setdefault(value, path)
            own = digest(run.path.joinpath(*relative.split("/")))
            if own is None or own not in known[size]:
                unique.append((relative, size))
            elif found is not None:
                found[(run.id, relative)] = origin[known[size][own]]
        result[run.id] = unique
    if notify:
        notify(total, total)
    return result


def list_archive_runs(root: Path, cancel=None, notify=None) -> tuple[list[ArchiveRun], list[str]]:
    """Return recognised runs (newest first) and warnings about entries that are ignored."""
    root = io_path(root)
    runs, warnings = [], []
    info = snapshot(root)
    if info is None:
        return runs, warnings
    if info.kind != "directory":
        raise BackupError(f"Versijų archyvo kelias nėra aplankas: {root}")
    with os.scandir(root) as iterator:
        entries = sorted(iterator, key=lambda entry: entry.name)
    for index, entry in enumerate(entries):
        check_cancel(cancel)
        if notify:
            notify({"phase": "inspect", "done": index, "total": len(entries), "path": entry.name})
        if not RUN_PATTERN.match(entry.name):
            warnings.append(f"Nepažįstamas elementas paliktas: {entry.name}")
            continue
        try:
            runs.append(inspect_run(Path(entry.path), cancel))
        except Cancelled:
            raise
        except (OSError, ValueError, BackupError) as error:
            warnings.append(display_text(f"{entry.name} paliktas: {error}"))
    runs.sort(key=lambda run: (run.started, run.id), reverse=True)
    return runs, warnings


def rules_enabled(settings: Settings) -> bool:
    return bool(settings.keep_runs or settings.keep_days or settings.max_versions_gb)


def plan_prune(runs, keep_runs=0, keep_days=0, max_bytes=0, now=None) -> list[PlanItem]:
    """Pure decision function. Rules set to 0 are disabled. Returns one item per run, newest first.

    keep_runs is a guarantee: the newest keep_runs runs are never deleted, whatever the
    other rules say. Older runs are deleted when they break the age or size rule; when
    neither of those rules is set, every run older than the newest keep_runs is deleted.
    """
    now = now or datetime.now()
    runs = sorted(runs, key=lambda run: (run.started, run.id), reverse=True)
    count_only = not keep_days and not max_bytes
    plan, kept_bytes, over_size = [], 0, False
    for index, run in enumerate(runs):
        if index == 0:
            action, reason = "protected", "Naujausia operacija"
        elif run.state == "running":
            action, reason = "protected", "Nebaigta operacija"
        elif run.problem:
            action, reason = "protected", "Netikėtas turinys"
        elif keep_runs and index < keep_runs:
            action, reason = "protected", "Tarp paskutinių saugomų"
        elif keep_runs and count_only:
            action, reason = "delete", "Viršija operacijų skaičių"
        elif keep_days and now - run.started > timedelta(days=keep_days):
            action, reason = "delete", "Senesnė nei nustatyta"
        elif max_bytes and (over_size or kept_bytes + run.size > max_bytes):
            # Keep the newest runs that fit; once the limit is reached, older runs go.
            over_size = True
            action, reason = "delete", "Viršija archyvo dydį"
        else:
            action, reason = "keep", ""
        if action != "delete":
            kept_bytes += run.size
        plan.append(PlanItem(run, action, reason))
    return plan


def plan_for_settings(settings: Settings, runs, now=None) -> list[PlanItem]:
    return plan_prune(runs, settings.keep_runs, settings.keep_days, settings.max_versions_gb * GB, now)


def _remove_file(path: Path, expected, attempts, cancel):
    def remove():
        check_cancel(cancel)
        if not matches(snapshot(path), expected):
            raise BackupError(f"Po peržiūros pasikeitė: {path}")
        try:
            path.unlink()
        except PermissionError as error:
            # Archived copies keep the original read-only flag; clear only that bit.
            if os.name != "nt" or getattr(error, "winerror", None) != 5:
                raise
            attributes = windows_attributes(path)
            if not attributes & 1 or attributes & 0x410:
                raise
            windows_attributes(path, attributes & ~1)
            path.unlink()
    retry_io(remove, attempts, cancel)


def delete_run(run: ArchiveRun, attempts=3, cancel=None, on_file=None):
    """Delete one previously inspected run. Raises if anything differs from the inspection."""
    check_cancel(cancel)
    if not matches(snapshot(run.path), run.folder):
        raise BackupError(f"Po peržiūros pasikeitė: {run.path}")
    current = inspect_run(run.path, cancel)
    if current.problem:
        raise BackupError(current.problem)
    if current.state == "running":
        raise BackupError("Operacija pažymėta kaip nebaigta.")
    if (current.files, current.size) != (run.files, run.size):
        raise BackupError("Po peržiūros pasikeitė archyvo turinys.")
    manifest = run.path / "manifest.json"
    entries = list(_walk(run.path, cancel))
    manifest_info = None
    for path, info in entries:
        if info is None:
            continue
        if path == manifest:
            manifest_info = info
            continue
        _remove_file(path, info, attempts, cancel)
        if on_file:
            on_file(info.size)
    if manifest_info is not None:
        _remove_file(manifest, manifest_info, attempts, cancel)
    for path, info in entries:
        if info is None:
            check_cancel(cancel)
            retry_io(lambda folder=path: remove_empty_directory(folder), attempts, cancel)


def prune(root: Path, items: list[PlanItem], settings: Settings, cancel=None, notify=None,
          log_directory: Path | None = None) -> dict:
    """Delete the runs marked "delete" and record the result in the activity history."""
    targets = [item.run for item in items if item.action == "delete"]
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    total_bytes = sum(run.size for run in targets)
    report = {"id": run_id, "started": datetime.now().isoformat(timespec="seconds"), "mode": "prune",
              "source": "", "destination": "", "archive": display_path(root),
              "selected": len(targets), "completed": 0, "failed": 0, "skipped": 0, "cancelled": 0,
              "bytes": 0, "items": [],
              "rules": {"keep_runs": settings.keep_runs, "keep_days": settings.keep_days,
                        "max_versions_gb": settings.max_versions_gb}}
    logs = log_directory or state_directory() / "logs"
    write_json(logs / f"{run_id}.json", display_data({**report, "state": "running"}))

    def progress(delta=0):
        report["bytes"] += delta
        if notify:
            notify({"phase": "prune", "done": len(report["items"]), "total": len(targets),
                    "bytes": report["bytes"], "total_bytes": total_bytes})

    stopped = False
    for run in targets:
        item = {"path": run.id, "kind": "directory", "files": run.files, "size": run.size,
                "mode": run.mode, "started": run.started.isoformat(timespec="seconds")}
        if stopped:
            report["cancelled"] += 1
            report["items"].append({**item, "status": "cancelled", "message": "Veiksmas sustabdytas."})
            continue
        try:
            delete_run(run, settings.retries, cancel, progress)
            report["completed"] += 1
            report["items"].append({**item, "status": "completed", "message": ""})
        except Cancelled as error:
            stopped = True
            report["cancelled"] += 1
            report["items"].append({**item, "status": "cancelled",
                                    "message": f"{error} Dalis šios operacijos failų galėjo būti ištrinta."})
        except (OSError, BackupError) as error:
            report["failed"] += 1
            report["items"].append({**item, "status": "failed", "message": display_text(str(error))})
        progress()
    report["finished"] = datetime.now().isoformat(timespec="seconds")
    report["state"] = "cancelled" if report["cancelled"] else "errors" if report["failed"] else "completed"
    report = display_data(report)
    try:
        write_json(logs / f"{run_id}.json", report)
    except OSError as error:
        report["log_error"] = display_text(f"Nepavyko išsaugoti galutinio žurnalo: {error}")
    return report
