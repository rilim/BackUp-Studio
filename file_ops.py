"""Conservative file comparison and explicitly selected, recoverable operations.

Optional per-root hash cache accelerates scans; a full scan always reads bytes.
The GUI only supplies a selection from a completed, immutable comparison.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import closing
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
import errno
import hashlib
import os
import shutil
import sqlite3
import stat
import tempfile
import threading
import time
import uuid

from config import Settings, state_directory, write_json
from utils import excluded, normalize_exclusion, within
from path_utils import check_path_length, display_path, display_text, display_data, io_path, relative_parts, resolve_root

CHUNK_SIZE = 1024 * 1024
SYSTEM_EXCLUSIONS = ("System Volume Information", "$RECYCLE.BIN")


class BackupError(Exception):
    def __str__(self):
        return display_text(super().__str__())


class Cancelled(BackupError):
    pass


class StaleComparison(BackupError):
    pass


def check_cancel(event):
    if event is not None and event.is_set():
        raise Cancelled("Veiksmas sustabdytas.")


@dataclass(frozen=True)
class Snapshot:
    kind: str
    size: int
    mtime_ns: int
    ctime_ns: int
    device: int
    inode: int
    digest: str = ""


def snapshot(path: Path) -> Snapshot | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise BackupError(f"Simbolinė nuoroda arba junction: {path}. Pridėkite ją prie išimčių.")
    if stat.S_ISREG(info.st_mode):
        kind = "file"
    elif stat.S_ISDIR(info.st_mode):
        kind = "directory"
    else:
        raise BackupError(f"Nepalaikomas failo tipas: {path}")
    return Snapshot(kind, info.st_size if kind == "file" else 0, info.st_mtime_ns,
                    info.st_ctime_ns, info.st_dev, info.st_ino)


def matches(actual: Snapshot | None, expected: Snapshot | None) -> bool:
    if actual is None or expected is None:
        return actual is expected
    if actual.kind != expected.kind:
        return False
    if actual.kind == "directory":
        # Creating/removing a child changes directory timestamps during our own run.
        return (actual.device, actual.inode) == (expected.device, expected.inode)
    return replace(actual, digest="") == replace(expected, digest="")


def assert_unchanged(path: Path, expected: Snapshot | None):
    if not matches(snapshot(path), expected):
        raise StaleComparison(f"Po palyginimo pasikeitė: {path}. Patikrinkite skirtumus iš naujo.")


def file_hash(path: Path, cancel=None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            check_cancel(cancel)
            data = stream.read(CHUNK_SIZE)
            if not data:
                break
            digest.update(data)
    return digest.hexdigest()


def validated_roots(settings: Settings, mode: str) -> tuple[Path, Path]:
    settings.validate()
    if mode not in ("sync", "restore", "cleanup"):
        raise BackupError("Neatpažintas veiksmas.")
    if not settings.source.strip() or not settings.destination.strip():
        raise BackupError("Pasirinkite šaltinio ir atsarginės kopijos aplankus.")
    source = resolve_root(settings.source)
    destination = resolve_root(settings.destination)
    if within(source, destination) or within(destination, source):
        raise BackupError("Aplankai negali sutapti arba būti vienas kito viduje.")
    for path, required, label in ((source, mode != "restore", "Šaltinio"),
                                  (destination, mode != "sync", "Atsarginės kopijos")):
        try:
            info = path.stat()
        except FileNotFoundError:
            if required:
                raise BackupError(f"{label} aplanko nėra: {path}") from None
        except OSError as error:
            raise BackupError(f"{label} aplankas nepasiekiamas: {error}") from error
        else:
            if not stat.S_ISDIR(info.st_mode):
                raise BackupError(f"{label} kelias nėra aplankas: {path}")
    return source, destination


@dataclass(frozen=True)
class Difference:
    relative: str
    status: str
    source: Snapshot | None
    destination: Snapshot | None
    problem: str = ""

    @property
    def kind(self):
        info = self.source or self.destination
        return info.kind if info else "unknown"


@dataclass(frozen=True)
class ScanIssue:
    relative: str
    side: str
    message: str
    subtree: bool = True


def affected(relative, issue):
    name, prefix = relative, issue.relative
    if os.name == "nt":
        name, prefix = name.casefold(), prefix.casefold()
    return (not prefix or name == prefix or
            (issue.subtree and name.startswith(prefix + "/")) or prefix.startswith(name + "/"))


@dataclass
class Comparison:
    source: Path
    destination: Path
    source_root: Snapshot | None
    destination_root: Snapshot | None
    exclusions: tuple[str, ...]
    rows: list[Difference]
    errors: list[str]
    mode: str
    source_input: str
    destination_input: str
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    issues: list[ScanIssue] = field(default_factory=list)
    fatal_errors: list[str] = field(default_factory=list)
    automatic_exclusions: tuple[str, ...] = ()
    reused_hashes: int = 0
    verified_hashes: int = 0
    cache_warning: str = ""
    full_scan: bool = False

    @property
    def blocked(self):
        # Legacy/unscoped errors remain fail-closed.
        return bool(self.fatal_errors or len(self.errors) != len(self.issues))


def scan_tree(root: Path, exclusions: tuple[str, ...], cancel, notify, side="source"):
    found = {}
    errors = []
    if not root.exists():
        return found, errors
    pending = [(root, "")]
    while pending:
        check_cancel(cancel)
        directory, relative = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = list(iterator)
            for entry in entries:
                check_cancel(cancel)
                name = f"{relative}/{entry.name}".lstrip("/")
                if excluded(name, exclusions):
                    continue
                try:
                    info = snapshot(Path(entry.path))
                    if info is None:
                        raise BackupError(f"Failas dingo skaitant: {entry.path}")
                    found[name] = info
                    if info.kind == "directory":
                        pending.append((Path(entry.path), name))
                except (OSError, BackupError) as error:
                    errors.append(ScanIssue(name, side, display_text(f"{display_path(entry.path)}: {error}")))
            if notify:
                notify({"phase": "scan", "path": display_path(directory), "found": len(found)})
        except OSError as error:
            errors.append(ScanIssue(relative, side, display_text(f"Nepavyko perskaityti {display_path(directory)}: {error}")))
    return found, errors


def _cache_key(info: Snapshot):
    return info.size, info.mtime_ns, info.ctime_ns, info.device, info.inode


def _hash_cache(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=0.5)
    try:
        connection.execute("""CREATE TABLE IF NOT EXISTS file_hashes (
            root TEXT NOT NULL, relative TEXT NOT NULL, size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL, ctime_ns INTEGER NOT NULL,
            device TEXT NOT NULL, inode TEXT NOT NULL, digest TEXT NOT NULL,
            PRIMARY KEY (root, relative))""")
        connection.commit()
    except BaseException:
        connection.close()
        raise
    return connection


def compare(settings: Settings, mode="sync", cancel=None, notify=None,
            cache_file: Path | None = None, use_cache=False) -> Comparison:
    source, destination = validated_roots(settings, mode)
    if cache_file is not None:
        cache_file = io_path(cache_file)
    cache_warning = ""
    if cache_file and (within(cache_file, source) or within(cache_file, destination)):
        cache_file = None
        cache_warning = "Indeksas yra darbo aplanke; greita patikra išjungta."
    exclusions = tuple(sorted(set(normalize_exclusion(x, source) for x in settings.exclusions)))
    source_root, destination_root = snapshot(source), snapshot(destination)
    automatic = SYSTEM_EXCLUSIONS if os.name == "nt" else ()
    source_items, issues = scan_tree(source, exclusions + automatic, cancel, notify)
    destination_items, destination_errors = scan_tree(destination, exclusions + automatic, cancel, notify, "destination")
    issues.extend(destination_errors)
    work = [(root, name, info, items) for root, items in ((source, source_items), (destination, destination_items))
            for name, info in items.items() if info.kind == "file"]
    cached = {}
    if cache_file and use_cache:
        try:
            with closing(_hash_cache(cache_file)) as connection:
                for root in (source, destination):
                    root_name = str(root)
                    for name, size, mtime, ctime, device, inode, digest in connection.execute(
                            "SELECT relative, size, mtime_ns, ctime_ns, device, inode, digest "
                            "FROM file_hashes WHERE root=?", (root_name,)):
                        cached[(root_name, name)] = ((size, mtime, ctime, int(device), int(inode)), digest)
        except (OSError, sqlite3.Error, TypeError, ValueError) as error:
            cached.clear()
            cache_warning = f"Ankstesnių patikrų indeksas nepasiekiamas: {error}. Atliekamas pilnas tikrinimas."
    uncached = []
    reused = 0
    for item in work:
        root, name, info, items = item
        previous = cached.get((str(root), name))
        if (previous and previous[0] == _cache_key(info) and isinstance(previous[1], str)
                and len(previous[1]) == 64 and all(c in "0123456789abcdef" for c in previous[1])):
            try:
                # A cached digest never hides a newly denied or missing file.
                check_cancel(cancel)
                with (root / name).open("rb") as stream:
                    stream.read(1)
                assert_unchanged(root / name, info)
                items[name] = replace(info, digest=previous[1])
                reused += 1
            except (OSError, BackupError) as error:
                if isinstance(error, Cancelled):
                    raise
                issues.append(ScanIssue(name, "source" if root == source else "destination",
                                        display_text(f"{display_path(root / name)}: {error}"), False))
        else:
            uncached.append(item)

    def hash_one(item):
        root, name, info, _ = item
        path = root / name
        assert_unchanged(path, info)
        value = file_hash(path, cancel)
        assert_unchanged(path, info)
        return value

    done = reused
    if notify:
        notify({"phase": "hash", "done": done, "total": len(work), "path": "", "reused": reused})
    with ThreadPoolExecutor(max_workers=settings.workers) as pool:
        pending = {}
        remaining = iter(uncached)
        def fill_queue():
            for item in remaining:
                pending[pool.submit(hash_one, item)] = item
                if len(pending) >= max(16, settings.workers * 4):
                    break
        fill_queue()
        while pending:
            check_cancel(cancel)
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                root, name, info, items = pending.pop(future)
                try:
                    items[name] = replace(info, digest=future.result())
                except Cancelled:
                    for other in pending:
                        other.cancel()
                    raise
                except (OSError, BackupError) as error:
                    issues.append(ScanIssue(name, "source" if root == source else "destination",
                                            display_text(f"{display_path(root / name)}: {error}"), False))
                done += 1
                if notify:
                    notify({"phase": "hash", "done": done, "total": len(work), "path": name, "reused": reused})
            fill_queue()
    check_cancel(cancel)
    # Detect missing/replaced roots even when an empty tree was returned.
    fatal_errors = []
    for root, expected in ((source, source_root), (destination, destination_root)):
        try:
            assert_unchanged(root, expected)
        except (OSError, BackupError) as error:
            fatal_errors.append(str(error))
    fatal_errors.extend(issue.message for issue in issues if not issue.relative)
    if cache_file and not issues and not fatal_errors:
        try:
            with closing(_hash_cache(cache_file)) as connection:
                with connection:
                    if use_cache and cached:
                        current = {(str(root), name) for root, items in ((source, source_items), (destination, destination_items))
                                   for name, info in items.items() if info.kind == "file"}
                        connection.executemany(
                            "DELETE FROM file_hashes WHERE root=? AND relative=?", cached.keys() - current)
                        changed = uncached
                    else:
                        for root in (source, destination):
                            connection.execute("DELETE FROM file_hashes WHERE root=?", (str(root),))
                        changed = work
                    connection.executemany(
                        "INSERT OR REPLACE INTO file_hashes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        ((str(root), name, items[name].size, items[name].mtime_ns, items[name].ctime_ns,
                          str(items[name].device), str(items[name].inode), items[name].digest)
                         for root, name, _, items in changed if items[name].digest))
        except (OSError, sqlite3.Error) as error:
            cache_warning = f"Nepavyko išsaugoti tikrinimo indekso: {error}. Kitą kartą failai bus perskaityti iš naujo."
    rows = []
    names = source_items.keys() | destination_items.keys() | {i.relative for i in issues if i.relative}
    for name in sorted(names, key=str.casefold):
        src, dst = source_items.get(name), destination_items.get(name)
        problems = [issue.message for issue in issues if affected(name, issue)]
        if problems:
            status = "unreadable"
        elif src is None:
            status = "destination_only"
        elif dst is None:
            status = "source_only"
        elif src.kind != dst.kind:
            status = "conflict"
        elif src.kind == "directory" or (src.digest and src.digest == dst.digest):
            status = "identical"
        else:
            status = "modified"
        rows.append(Difference(name, status, src, dst, "\n".join(problems)))
    conflicts = [row.relative for row in rows if row.status == "conflict"]
    rows = [replace(row, status="conflict") if row.status != "unreadable" and any(row.relative.startswith(prefix + "/") for prefix in conflicts)
            else row for row in rows]
    return Comparison(source, destination, source_root, destination_root, exclusions, rows,
                      [i.message for i in issues] + [e for e in fatal_errors if e not in [i.message for i in issues]],
                      mode, settings.source, settings.destination, issues=issues,
                      fatal_errors=fatal_errors, automatic_exclusions=automatic,
                      reused_hashes=reused, verified_hashes=len(work)-reused,
                      cache_warning=cache_warning, full_scan=not use_cache)


def eligible(row: Difference, mode: str, overwrite=False) -> bool:
    if row.status in ("conflict", "unreadable"):
        return False
    if mode == "sync":
        return row.status in ("source_only", "modified")
    if mode == "restore":
        return row.status == "destination_only" or (overwrite and row.status == "modified")
    return mode == "cleanup" and row.status == "destination_only"


def recommended(row: Difference, mode: str, overwrite=False) -> bool:
    if not eligible(row, mode, overwrite):
        return False
    if mode == "sync" and row.status == "modified":
        return row.source.mtime_ns >= row.destination.mtime_ns
    return True


def action_label(row: Difference, mode: str, overwrite=False) -> str:
    if row.status == "unreadable":
        return "Skaitymo klaida – praleisti"
    if not eligible(row, mode, overwrite):
        return "Konfliktas – praleisti" if row.status == "conflict" else "Jokio veiksmo"
    if mode == "cleanup":
        return "Pašalinti tuščią aplanką" if row.kind == "directory" else "Perkelti į archyvą"
    if row.kind == "directory":
        return "Sukurti aplanką"
    if row.status == "modified":
        return "Perrašyti kopiją" if mode == "sync" else "Perrašyti šaltinyje"
    return "Kopijuoti →" if mode == "sync" else "← Atkurti"


def versions_root(settings: Settings, comparison: Comparison) -> Path:
    if not settings.versions_directory.strip() and not comparison.destination.name:
        raise BackupError("Pasirinkus visą diską, nustatymuose nurodykite atskirą versijų aplanką už abiejų darbo diskų.")
    root = (resolve_root(settings.versions_directory) if settings.versions_directory.strip()
            else comparison.destination.with_name(comparison.destination.name + ".versions"))
    for protected in (comparison.source, comparison.destination):
        if within(root, protected) or within(protected, root):
            raise BackupError("Versijų archyvas turi būti atskirai nuo abiejų pasirinktų aplankų.")
    return root


def guarded_path(root: Path, relative: str) -> Path:
    root = io_path(root)
    try:
        parts = relative_parts(relative)
    except ValueError as error:
        raise BackupError(str(error)) from error
    target = root.joinpath(*parts)
    # A validated sequence of names cannot escape lexically. Checking lstat on
    # every ancestor below detects links/junctions without resolving a missing
    # leaf (whose Windows namespace can differ from that of an existing root).
    if not within(target, root):
        raise BackupError(f"Kelias išeina už pasirinkto aplanko: {relative}")
    try:
        check_path_length(target)
    except ValueError as error:
        raise BackupError(str(error)) from error
    for current in (*reversed(target.parents), target):
        info = snapshot(current)
        if info is not None and current != target and info.kind != "directory":
            raise BackupError(f"Kelyje rastas failas vietoje aplanko: {current}")
    return target


def retry_io(function, attempts, cancel):
    for attempt in range(attempts):
        check_cancel(cancel)
        try:
            return function()
        except (PermissionError, OSError) as error:
            if attempt + 1 == attempts or error.errno in (errno.ENOSPC, errno.ENOENT, errno.ENOTDIR):
                raise
            if cancel is not None:
                if cancel.wait(min(2 ** attempt, 4)):
                    raise Cancelled("Veiksmas sustabdytas.") from error
            else:
                time.sleep(min(2 ** attempt, 4))


def remove_temporary(path: Path):
    """Our own temporary may have inherited Windows read-only attributes."""
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        path.chmod(path.stat().st_mode | stat.S_IWRITE)
        path.unlink(missing_ok=True)


def windows_attributes(path, value=None):
    """Read/set Windows attributes without changing ACLs or unrelated flags."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    if value is None:
        call = kernel.GetFileAttributesW
        call.argtypes, call.restype = [wintypes.LPCWSTR], wintypes.DWORD
        result = call(str(path))
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return result
    call = kernel.SetFileAttributesW
    call.argtypes, call.restype = [wintypes.LPCWSTR, wintypes.DWORD], wintypes.BOOL
    if not call(str(path), value or 0x80):  # FILE_ATTRIBUTE_NORMAL when no flags remain
        raise ctypes.WinError(ctypes.get_last_error())


def remove_archived_file(path, expected, validate, attempts, cancel):
    """Only call after a verified archive exists. Retry with revalidation."""
    current = expected
    cleared = False

    def remove():
        nonlocal current, cleared
        check_cancel(cancel)
        validate(current)
        try:
            path.unlink()
        except PermissionError as error:
            if os.name != "nt" or getattr(error, "winerror", None) != 5 or cleared:
                raise
            attributes = windows_attributes(path)
            if not attributes & 1 or attributes & 0x410:  # never directories/reparse points
                raise
            validate(current)
            windows_attributes(path, attributes & ~1)
            cleared = True
            after = snapshot(path)
            # Changing attributes can change ctime; all other metadata and bytes
            # must still match the archived file before deletion is allowed.
            if after is None or replace(after, ctime_ns=current.ctime_ns, digest=current.digest) != current:
                raise StaleComparison(f"Po palyginimo pasikeitė: {path}")
            current = replace(after, digest=expected.digest)
            if file_hash(path, cancel) != expected.digest:
                raise StaleComparison(f"Po palyginimo pasikeitė failo turinys: {path}")
            validate(current)
            check_cancel(cancel)
            path.unlink()

    try:
        retry_io(remove, attempts, cancel)
    finally:
        if cleared:
            remaining = snapshot(path)
            if remaining and (remaining.device, remaining.inode) == (expected.device, expected.inode):
                # Restore only our changed bit if the original file survived.
                windows_attributes(path, windows_attributes(path) | 1)


def verified_temporary(source: Path, destination: Path, expected: Snapshot, cancel, on_bytes=None) -> Path:
    """Keep the old destination untouched until a fully verified file exists."""
    assert_unchanged(source, expected)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".backup-part-", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as incoming:
            digest = hashlib.sha256()
            while True:
                check_cancel(cancel)
                chunk = incoming.read(CHUNK_SIZE)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
                if on_bytes:
                    on_bytes(len(chunk))
            output.flush()
            os.fsync(output.fileno())
        assert_unchanged(source, expected)
        if not expected.digest or digest.hexdigest() != expected.digest:
            raise StaleComparison(f"Po palyginimo pasikeitė failo turinys: {source}")
        if file_hash(temporary, cancel) != expected.digest:
            raise BackupError(f"Kopijos turinio patikra nepavyko: {destination}")
        shutil.copystat(source, temporary, follow_symlinks=False)
        return temporary
    except BaseException:
        remove_temporary(temporary)
        raise


def archive_file(source: Path, archive: Path, expected: Snapshot, cancel):
    if archive.exists():
        raise BackupError(f"Versijos failas jau egzistuoja: {archive}")
    temporary = verified_temporary(source, archive, expected, cancel)
    try:
        check_cancel(cancel)
        assert_unchanged(source, expected)
        os.replace(temporary, archive)
    finally:
        remove_temporary(temporary)


def check_space(requirements: list[tuple[Path, int]]):
    devices = {}
    for path, size in requirements:
        existing = path
        while not existing.exists():
            if existing.parent == existing:
                raise BackupError(f"Diskas arba tinklo vieta nepasiekiami: {display_path(path)}")
            existing = existing.parent
        key = existing.stat().st_dev
        anchor, total = devices.get(key, (existing, 0))
        devices[key] = (anchor, total + size)
    for anchor, total in devices.values():
        if shutil.disk_usage(anchor).free < total:
            raise BackupError(f"Nepakanka vietos pasirinktiems veiksmams diske: {anchor}. Reikia bent {total:,} B.")


def execute(comparison: Comparison, selected: set[str], settings: Settings, overwrite=False,
            cancel=None, notify=None, log_directory: Path | None = None) -> dict:
    """Execute exactly the eligible selection. Cleanup never recursively removes folders."""
    if comparison.blocked:
        raise BackupError("Palyginimas turi skaitymo klaidų. Sutvarkykite jas arba pridėkite išimtis ir tikrinkite iš naujo.")
    roots = validated_roots(settings, comparison.mode)
    if roots != (comparison.source, comparison.destination):
        raise StaleComparison("Pasikeitė aplankų keliai. Patikrinkite skirtumus iš naujo.")
    rules = tuple(sorted(set(normalize_exclusion(x, roots[0]) for x in settings.exclusions)))
    if rules != comparison.exclusions:
        raise StaleComparison("Pasikeitė išimtys. Patikrinkite skirtumus iš naujo.")
    for root, expected in zip(roots, (comparison.source_root, comparison.destination_root)):
        assert_unchanged(root, expected)
    by_name = {row.relative: row for row in comparison.rows}
    if any(name not in by_name or not eligible(by_name[name], comparison.mode, overwrite)
           or any(affected(name, issue) for issue in comparison.issues) for name in selected):
        raise BackupError("Pasirinktas failas netinka šiam veiksmui. Patikrinkite skirtumus iš naujo.")
    rows = [by_name[name] for name in sorted(selected)]
    if not rows:
        raise BackupError("Nepažymėtas nė vienas tinkamas failas arba aplankas.")
    # Preflight every selected item before making any change.
    for row in rows:
        check_cancel(cancel)
        for root, expected in ((roots[0], row.source), (roots[1], row.destination)):
            assert_unchanged(guarded_path(root, row.relative), expected)
    cleanup = comparison.mode == "cleanup"
    target_root = roots[0] if comparison.mode == "restore" else roots[1]
    incoming_root = roots[1] if comparison.mode == "restore" else roots[0]
    files = [row for row in rows if row.kind == "file"]
    folders = [row for row in rows if row.kind == "directory"]
    needs_archive = cleanup and bool(files) or settings.keep_versions and any(row.status == "modified" for row in files)
    archive_root = versions_root(settings, comparison) if needs_archive else None
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    archive_run = archive_root / run_id if archive_root else None
    archive_prefix = "deleted_from_backup" if cleanup else "before_restore" if comparison.mode == "restore" else "before_sync"
    archive_paths = {}
    if archive_run:
        for row in files:
            if cleanup or row.status == "modified":
                archive_paths[row.relative] = guarded_path(archive_run, archive_prefix + "/" + row.relative)

    def states(row):
        return ((row.destination, row.source) if comparison.mode == "restore" else (row.source, row.destination))

    requirements = []
    for row in files:
        incoming, old = states(row)
        if not cleanup:
            requirements.append((target_root, incoming.size))
        if archive_run and old:
            requirements.append((archive_run, old.size))
    check_space(requirements)
    report = {"id": run_id, "started": datetime.now().isoformat(timespec="seconds"), "mode": comparison.mode,
              "source": display_path(roots[0]), "destination": display_path(roots[1]), "archive": display_path(archive_run or ""),
              "selected": len(rows), "completed": 0, "failed": 0, "skipped": 0, "cancelled": 0,
              "bytes": 0, "items": []}
    report["scan_errors"] = [asdict(issue) for issue in comparison.issues]
    report["scan_skipped"] = sum(row.status == "unreadable" for row in comparison.rows)
    report["automatic_exclusions"] = list(comparison.automatic_exclusions)
    report["scan_skipped_items"] = [{"path": row.relative, "kind": row.kind, "message": row.problem}
                                     for row in comparison.rows if row.status == "unreadable"]
    logs = log_directory or state_directory() / "logs"
    # Ensure the audit log can be created before modifying user data.
    write_json(logs / f"{run_id}.json", display_data({**report, "state": "running"}))
    try:
        if archive_run:
            archive_run.mkdir(parents=True, exist_ok=False)
            write_json(archive_run / "manifest.json", display_data({**report, "state": "running"}))
            # Build shared parents serially before file workers start. Every path
            # is checked again during the actual write; an intervening link fails.
            for parent in sorted({path.parent for path in archive_paths.values()}, key=lambda p: (len(p.parts), str(p))):
                check_cancel(cancel)
                guarded_path(archive_run, parent.relative_to(archive_run).as_posix())
                retry_io(lambda p=parent: p.mkdir(parents=True, exist_ok=True), settings.retries, cancel)
                guarded_path(archive_run, parent.relative_to(archive_run).as_posix())
    except (OSError, BackupError) as error:
        report.update(state="cancelled" if isinstance(error, Cancelled) else "errors",
                      finished=datetime.now().isoformat(timespec="seconds"), preparation_error=str(error))
        report["cancelled" if isinstance(error, Cancelled) else "failed"] = len(rows)
        report["items"] = [{"path": row.relative, "kind": row.kind,
                            "status": "cancelled" if isinstance(error, Cancelled) else "failed",
                            "message": f"Archyvo paruošimas: {error}"} for row in rows]
        report = display_data(report)
        write_json(logs / f"{run_id}.json", report)
        # Do not retry writes into an archive whose preparation was rejected.
        return report
    archive_snapshot = snapshot(archive_run) if archive_run else None

    def checked_archive(row):
        assert_unchanged(archive_run, archive_snapshot)
        return guarded_path(archive_run, archive_prefix + "/" + row.relative)
    total_bytes = sum((row.destination.size if cleanup else states(row)[0].size) for row in files)
    lock = threading.Lock()
    started = time.monotonic()

    def publish(delta=0):
        with lock:
            report["bytes"] += delta
            data = {"phase": "execute", "done": len(report["items"]), "total": len(rows),
                    "bytes": report["bytes"], "total_bytes": total_bytes, "elapsed": time.monotonic() - started}
        if notify:
            notify(data)

    def record(row, status, message="", *, error=None, stage="", path=None):
        with lock:
            report[status] += 1
            item = {"path": row.relative, "kind": row.kind, "status": status, "message": display_text(message)}
            if error is not None:
                item.update(stage=stage, operation_path=display_path(path or ""),
                            error_type=type(error).__name__, errno=getattr(error, "errno", None),
                            winerror=getattr(error, "winerror", None))
                item["message"] = display_text(f"{stage}: {message}\nKelias: {display_path(path or row.relative)}")
            report["items"].append(item)
        publish()

    def process_folder(row):
        try:
            check_cancel(cancel)
            if cleanup:
                def remove_empty_folder():
                    # Revalidate after every retry delay: roots/ancestors may have
                    # changed or the source folder may have reappeared meanwhile.
                    for root, expected in zip(roots, (comparison.source_root, comparison.destination_root)):
                        assert_unchanged(root, expected)
                    assert_unchanged(guarded_path(roots[0], row.relative), None)
                    target = guarded_path(target_root, row.relative)
                    assert_unchanged(target, row.destination)
                    check_cancel(cancel)
                    try:
                        # Never recursively delete: even newly created or excluded
                        # children must keep the folder intact.
                        target.rmdir()
                    except OSError as error:
                        if error.errno in (errno.ENOTEMPTY, errno.EEXIST) or getattr(error, "winerror", 0) == 145:
                            if next(target.iterdir(), None) is not None:
                                return False
                            # The filesystem still reports 'not empty' but no
                            # entries remain. Retry, revalidating on each attempt.
                        raise
                    return True

                if not retry_io(remove_empty_folder, settings.retries, cancel):
                    failed_child = any(item["status"] == "failed" and item["path"].startswith(row.relative + "/")
                                       for item in report["items"])
                    record(row, "skipped", "Aplankas paliktas: nepavyko archyvuoti arba pašalinti jo turinio."
                           if failed_child else "Aplanke liko nepažymėtų arba neįtrauktų elementų; jie išsaugoti.")
                    return
            else:
                target = guarded_path(target_root, row.relative)
                incoming, old = states(row)
                assert_unchanged(guarded_path(incoming_root, row.relative), incoming)
                assert_unchanged(target, old)
                target.mkdir(parents=True, exist_ok=True)
            record(row, "completed")
        except Cancelled as error:
            record(row, "cancelled", str(error))
        except (OSError, BackupError) as error:
            record(row, "failed", str(error), error=error,
                   stage="Aplanko šalinimas" if cleanup else "Aplanko kūrimas", path=target_root / row.relative)

    def process_file(row):
        temporary = None
        stage, operation_path = "Kelio patikra", target_root / row.relative
        try:
            check_cancel(cancel)
            target = guarded_path(target_root, row.relative)
            incoming, old = states(row)
            assert_unchanged(target, old)
            if cleanup:
                # A source file created after the scan must never trigger deletion.
                assert_unchanged(guarded_path(roots[0], row.relative), None)
                stage, operation_path = "Archyvavimas", archive_paths[row.relative]
                retry_io(lambda: archive_file(target, checked_archive(row), old, cancel), settings.retries, cancel)
                stage, operation_path = "Failo šalinimas", target
                def validate_removal(expected):
                    for root, state in zip(roots, (comparison.source_root, comparison.destination_root)):
                        assert_unchanged(root, state)
                    assert_unchanged(guarded_path(roots[0], row.relative), None)
                    assert_unchanged(guarded_path(target_root, row.relative), expected)
                remove_archived_file(target, old, validate_removal, settings.retries, cancel)
                publish(old.size)
            else:
                stage, operation_path = "Kopijavimas", target
                incoming_path = guarded_path(incoming_root, row.relative)
                temporary = retry_io(lambda: verified_temporary(incoming_path, target, incoming, cancel, publish),
                                     settings.retries, cancel)
                assert_unchanged(target, old)
                if old and settings.keep_versions:
                    stage, operation_path = "Archyvavimas", archive_paths[row.relative]
                    retry_io(lambda: archive_file(target, checked_archive(row), old, cancel), settings.retries, cancel)
                elif old and file_hash(target, cancel) != old.digest:
                    raise StaleComparison(f"Po palyginimo pasikeitė paskirties turinys: {target}")
                check_cancel(cancel)
                stage, operation_path = "Failo pakeitimas", target
                assert_unchanged(incoming_path, incoming)
                # Recheck ancestors and the destination immediately before replacing it.
                guarded_path(target_root, row.relative)
                assert_unchanged(target, old)
                retry_io(lambda: os.replace(temporary, target), settings.retries, cancel)
            record(row, "completed")
        except Cancelled as error:
            record(row, "cancelled", str(error))
        except (OSError, BackupError) as error:
            record(row, "failed", str(error), error=error, stage=stage, path=operation_path)
        finally:
            if temporary is not None:
                remove_temporary(temporary)

    if not cleanup:
        # Roots are only created by an explicitly confirmed operation.
        target_root.mkdir(parents=True, exist_ok=True)
        for row in sorted(folders, key=lambda item: item.relative.count("/")):
            process_folder(row)
    with ThreadPoolExecutor(max_workers=settings.workers) as pool:
        list(pool.map(process_file, files))
    if cleanup:
        for row in sorted(folders, key=lambda item: item.relative.count("/"), reverse=True):
            process_folder(row)
    report["finished"] = datetime.now().isoformat(timespec="seconds")
    report["state"] = ("cancelled" if report["cancelled"] else "errors" if report["failed"] else
                       "completed_with_skips" if report["scan_skipped"] or report["skipped"] else "completed")
    report["items"].sort(key=lambda item: item["path"].casefold())
    report = display_data(report)
    try:
        write_json(logs / f"{run_id}.json", report)
        if archive_run:
            write_json(archive_run / "manifest.json", report)
    except OSError as error:
        report["log_error"] = display_text(f"Nepavyko išsaugoti galutinio žurnalo: {error}")
    return report
