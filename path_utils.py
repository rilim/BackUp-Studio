"""Literal paths shared by exclusions and file operations.

Windows I/O always uses the extended namespace (including for not-yet-created
paths). Display paths remain ordinary drive/UNC paths. Names are never globbed.
"""
import ntpath
import os
import ast
import re
from pathlib import Path


def windows_extended_path(value: str) -> str:
    value = value.replace('/', '\\')
    if value.startswith('\\\\?\\'):
        value = display_path(value)
    if value.startswith('\\\\.\\'):
        raise ValueError('Įrenginio kelias nepalaikomas; pasirinkite failų aplanką.')
    value = ntpath.normpath(value)
    drive, tail = ntpath.splitdrive(value)
    if value.startswith('\\\\'):
        if not drive or len(drive.strip('\\').split('\\')) != 2:
            raise ValueError('Nurodykite visą tinklo aplanko kelią.')
        return '\\\\?\\UNC\\' + value[2:]
    if len(drive) != 2 or drive[1] != ':' or not tail.startswith('\\'):
        raise ValueError('Nurodykite absoliutų aplanko kelią.')
    return '\\\\?\\' + value


def io_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if os.name == 'nt':
        return Path(windows_extended_path(os.path.abspath(path)))
    return path.absolute()


def resolve_root(value: str | Path) -> Path:
    # Resolve only configured roots, before workers create children. Preserve
    # the same namespace whether the root exists yet or not.
    return io_path(io_path(value).resolve())


def display_path(value: str | Path) -> str:
    value = str(value)
    if value.upper().startswith('\\\\?\\UNC\\'):
        return '\\\\' + value[8:]
    if value.startswith('\\\\?\\'):
        return value[4:]
    return value


_QUOTED_TEXT = re.compile(r"'(?:\\.|[^'\\\r\n])*'|\"(?:\\.|[^\"\\\r\n])*\"")


def display_text(value: str) -> str:
    """Render paths embedded in messages, including Python's quoted OSError paths.

    Only presentation uses this function. Never pass its output back to an I/O
    operation: escaped filenames in an error are text, not a new working path.
    """
    if not isinstance(value, str):
        return value

    def quoted_path(match):
        token = match.group()
        # Python's OSError repr escapes backslashes, unlike normal path fields.
        if not token[1:].startswith(repr('\\\\?\\')[1:-1]):
            return token
        try:
            path = ast.literal_eval(token)
        except (ValueError, SyntaxError):
            return token
        return token[0] + display_path(path) + token[-1]

    value = _QUOTED_TEXT.sub(quoted_path, value)
    # Handle normal paths in sentences, progress, confirmation and old logs.
    value = re.sub(re.escape('\\\\?\\UNC\\'), lambda match: '\\\\', value, flags=re.IGNORECASE)
    return value.replace('\\\\?\\', '')


def display_data(value):
    """Return a display/export copy of a report; keep working paths untouched."""
    if isinstance(value, str):
        return display_text(value)
    if isinstance(value, dict):
        return {key: display_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [display_data(item) for item in value]
    return value


def relative_parts(value: str, *, windows: bool | None = None) -> tuple[str, ...]:
    """Reject path escapes and OS-invalid components, not harmless punctuation."""
    windows = os.name == 'nt' if windows is None else windows
    parts = tuple(value.split('/'))
    if not value or any(part in ('', '.', '..') or '\0' in part for part in parts):
        raise ValueError('Netinkamas santykinis failo kelias.')
    if windows:
        for part in parts:
            if any(c in '<>:"\\|?*' or ord(c) < 32 for c in part):
                raise ValueError(f'Windows nepalaikomas simbolis pavadinime: {part}')
            stem = part.split('.')[0].rstrip(' ').upper()
            if stem in {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} or (
                len(stem) == 4 and stem[:3] in {'COM', 'LPT'} and stem[3] in '123456789¹²³'
            ):
                raise ValueError(f'Windows rezervuotas pavadinimas: {part}')
    return parts


def check_path_length(path: Path):
    if os.name == 'nt':
        # Conservative preflight; volume-specific component limits are reported
        # by the operation itself. UTF-16 units, not Python character count.
        units = len(str(path).encode('utf-16-le', errors='surrogatepass')) // 2
        if units >= 32760:
            raise ValueError(f'Per ilgas galutinis kelias: {display_path(path)}')
