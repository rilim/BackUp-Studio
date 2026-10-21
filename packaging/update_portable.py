"""Update a previously delivered portable package after verifying its entire manifest.

No runtime downloads or changes to upstream checksum pins are made.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

from build_portable import HERE, SOURCE, sha256
sys.path.insert(0, str(SOURCE))
from config import APP_VERSION


def update(previous, output, tools_root=None, reuse_launcher=False):
    previous, output = previous.resolve(), output.resolve()
    tools_root = tools_root.resolve() if tools_root else None
    if not reuse_launcher and tools_root is None:
        raise ValueError('Supply --tools-root to rebuild or --reuse-launcher for a code-only update')
    manifest = previous / 'SHA256SUMS.txt'
    expected = {}
    for line in manifest.read_text().splitlines():
        digest, name = line.split('  ', 1)
        target = (previous / name).resolve()
        if not target.is_relative_to(previous) or not target.is_file() or sha256(target) != digest:
            raise ValueError(f'Previous package verification failed: {name}')
        expected[name] = digest
    actual = {p.relative_to(previous).as_posix() for p in previous.rglob('*') if p.is_file()}
    if actual != set(expected) | {'SHA256SUMS.txt'}:
        raise ValueError('Unexpected files in previous package')
    print(f'Verified all {len(expected)} previous package files', flush=True)
    output.mkdir(parents=True, exist_ok=True)
    destination = output / 'BackUpStudio'
    if destination.exists():
        raise FileExistsError(destination)
    with tempfile.TemporaryDirectory(prefix='portable-update-') as temporary:
        package = Path(temporary) / 'BackUpStudio'
        shutil.copytree(previous, package)
        app = package / '_internal/app'
        for name in ('main.py', 'ui.py', 'config.py', 'utils.py', 'file_ops.py', 'i18n.py', 'path_utils.py', 'file_icons.py'):
            shutil.copy2(SOURCE / name, app / name)
        shutil.copytree(SOURCE / 'tests', app / 'tests', dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__'))
        if not reuse_launcher:
            env = os.environ.copy()
            env['PATH'] = str(tools_root / 'usr/bin') + os.pathsep + env['PATH']
            env['LD_LIBRARY_PATH'] = str(tools_root / 'usr/lib/x86_64-linux-gnu')
            gcc = str(tools_root / 'usr/bin/x86_64-w64-mingw32-gcc-posix')
            windres = str(tools_root / 'usr/bin/x86_64-w64-mingw32-windres')
            resource = Path(temporary) / 'launcher.res'
            subprocess.run([windres, '--codepage=65001', '--preprocessor', gcc,
                            '--preprocessor-arg=-E', '--preprocessor-arg=-xc', '--preprocessor-arg=-DRC_INVOKED',
                            '-i', 'launcher.rc', '-o', str(resource), '-O', 'coff'], cwd=HERE, env=env, check=True)
            subprocess.run([gcc, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-municode', '-mwindows',
                            '-static', '-static-libgcc', '-s', '-finput-charset=UTF-8',
                            '-Wl,--dynamicbase,--nxcompat,--high-entropy-va', '-Wl,--no-insert-timestamp',
                            str(HERE / 'launcher.c'), str(resource), '-o', str(package / 'BackUpStudio.exe'),
                            '-lshell32', '-luser32'], env=env, check=True)
        for source, target in ((SOURCE / 'README_LT.md', 'Naudojimo_instrukcija.md'),
                               (SOURCE / 'README_EN.md', 'Instructions_EN.md'), (HERE / 'SKAITYTI.txt', 'SKAITYTI.txt')):
            shutil.copy2(source, package / target)
        metadata_path = package / 'Komponentai.json'
        metadata = json.loads(metadata_path.read_text())
        if reuse_launcher:
            metadata['launcher_reused_from_version'] = metadata.get('launcher_reused_from_version', metadata['version'])
        metadata.update(version=APP_VERSION, package_revision=13,
                        runtime_reused_from_version=metadata['version'],
                        previous_manifest_sha256=sha256(manifest), windows_execution_tested=False)
        metadata_path.write_text(json.dumps(metadata, indent=2) + '\n')
        paths = sorted(p for p in package.rglob('*') if p.is_file() and p.name != 'SHA256SUMS.txt')
        (package / 'SHA256SUMS.txt').write_text(''.join(
            f'{sha256(p)}  {p.relative_to(package).as_posix()}\n' for p in paths))
        archive = output / 'BackUp_Studio_Windows_x64.zip'
        with ZipFile(archive, 'w', ZIP_DEFLATED, compresslevel=9) as zip_file:
            for path in sorted(package.rglob('*')):
                if path.is_file():
                    zip_file.write(path, path.relative_to(package.parent))
        shutil.copytree(package, destination)
        print(f'Built {archive} ({archive.stat().st_size:,} bytes)', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tools-root', type=Path)
    parser.add_argument('--reuse-launcher', action='store_true', help='Reuse the verified launcher and runtime; update app code only')
    args = parser.parse_args()
    update(args.previous, args.output, args.tools_root, args.reuse_launcher)
