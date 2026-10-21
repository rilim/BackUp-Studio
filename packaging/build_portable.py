"""Build the Windows x64 portable ZIP on Linux with MinGW-w64 and msitools.

No build tools are needed on the recipient's Windows computer.
Python >=3.10 is required only on the build machine.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile, ZIP_DEFLATED

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent
ARTIFACTS = {
    "python-3.14.7-embed-amd64.zip": (
        "https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-amd64.zip",
        "d297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15"),
    "tcltk.msi": (
        "https://www.python.org/ftp/python/3.14.7/amd64/tcltk.msi",
        "4ae542ab046b3a1b2f10e6c1ee91a215cb4d0638aae373d6e0687472eb7170bd"),
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_zip(archive, destination):
    with ZipFile(archive) as source:
        for item in source.infolist():
            name = PurePosixPath(item.filename)
            if name.is_absolute() or ".." in name.parts or ":" in item.filename or "\\" in item.filename:
                raise ValueError(f"Unsafe ZIP entry: {item.filename}")
        source.extractall(destination)


def build(args):
    cache, destination = args.cache.resolve(), args.output.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    unpacked = destination / "BackUpStudio"
    if unpacked.exists():
        raise FileExistsError(f"Unpacked build already exists: {unpacked}. Move it before rebuilding.")
    env = os.environ.copy()
    if args.tools_root:
        tools_root = args.tools_root.resolve() / "usr"
        env["PATH"] = str(tools_root / "bin") + os.pathsep + env.get("PATH", "")
        env["LD_LIBRARY_PATH"] = str(tools_root / "lib/x86_64-linux-gnu") + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    def tool(name):
        result = shutil.which(name, path=env["PATH"])
        if not result:
            raise RuntimeError(f"Build tool missing: {name}")
        return result
    gcc = tool("x86_64-w64-mingw32-gcc-posix")
    windres = tool("x86_64-w64-mingw32-windres")
    msiextract = tool("msiextract")
    for name, (url, expected) in ARTIFACTS.items():
        path = cache / name
        if not path.exists():
            temporary = path.with_suffix(path.suffix + ".download")
            with urlopen(url, timeout=90) as response, temporary.open("wb") as target:
                shutil.copyfileobj(response, target)
            if sha256(temporary) != expected:
                raise ValueError(f"Downloaded file checksum mismatch: {name}")
            temporary.replace(path)
        if sha256(path) != expected:
            raise ValueError(f"Cached file checksum mismatch: {name}")
        print(f"Verified {name}", flush=True)

    with tempfile.TemporaryDirectory(prefix="backup-build-", dir=cache) as temporary:
        work = Path(temporary)
        package = work / "BackUpStudio"
        runtime = package / "_internal"
        app = runtime / "app"
        app.mkdir(parents=True)
        extract_zip(cache / "python-3.14.7-embed-amd64.zip", runtime)
        tcltk = work / "tcltk"
        subprocess.run([msiextract, "-C", str(tcltk), str(cache / "tcltk.msi")],
                       check=True, env=env, stdout=subprocess.DEVNULL)
        shutil.copytree(tcltk / "DLLs", runtime / "DLLs")
        shutil.copytree(tcltk / "Lib/tkinter", runtime / "Lib/tkinter")
        # The official Tcl/Tk 9 distribution stores scripts in these ZIPs.
        # Expand them and use explicit library paths, independent of installation.
        for archive in (tcltk / "tcl").glob("lib*.zip"):
            extract_zip(archive, runtime / "tcl")
        for extra in ("dde1.4", "registry1.3"):
            shutil.copytree(tcltk / "tcl" / extra, runtime / "tcl" / extra)
        for filename in ("main.py", "ui.py", "config.py", "utils.py", "file_ops.py", "i18n.py", "path_utils.py", "file_icons.py"):
            shutil.copy2(SOURCE / filename, app / filename)
        shutil.copytree(SOURCE / "tests", app / "tests", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(HERE / "portable_bootstrap.py", app)
        shutil.copy2(HERE / "app.ico", app)
        (runtime / "python314._pth").write_text(
            "# Private BackUp Studio runtime; no system/user packages.\n"
            "python314.zip\n.\nDLLs\nLib\napp\n", encoding="ascii")
        # Runtime executables are not used: the native launcher calls Py_Main.
        for name in ("python.exe", "pythonw.exe", "python.cat"):
            (runtime / name).unlink()
        for path in ("tcl/tcl_library/init.tcl", "tcl/tk_library/tk.tcl", "DLLs/_tkinter.pyd"):
            if not (runtime / path).is_file():
                raise RuntimeError(f"Incomplete GUI runtime: {path}")
        resource = work / "launcher.res"
        subprocess.run([windres, "--codepage=65001", "--preprocessor", gcc,
                        "--preprocessor-arg=-E", "--preprocessor-arg=-xc", "--preprocessor-arg=-DRC_INVOKED",
                        "-i", "launcher.rc", "-o", str(resource), "-O", "coff"],
                       cwd=HERE, env=env, check=True)
        executable = package / "BackUpStudio.exe"
        subprocess.run([gcc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-municode", "-mwindows", "-static", "-static-libgcc", "-s",
                        "-finput-charset=UTF-8", "-Wl,--dynamicbase,--nxcompat,--high-entropy-va",
                        "-Wl,--no-insert-timestamp", str(HERE / "launcher.c"), str(resource),
                        "-o", str(executable), "-lshell32", "-luser32"], env=env, check=True)
        shutil.copy2(HERE / "SKAITYTI.txt", package)
        shutil.copy2(SOURCE / "README_LT.md", package / "Naudojimo_instrukcija.md")
        shutil.copy2(SOURCE / "README_EN.md", package / "Instructions_EN.md")
        (package / "Demonstracija.bat").write_bytes(
            b'@echo off\r\nstart "" "%~dp0BackUpStudio.exe" --demo\r\n')
        metadata = {
            "application": "BackUp Studio", "version": "2.6.0", "package_revision": 13,
            "target": "Windows 10/11 x64", "python": "3.14.7", "tcl_tk": "9.0.4",
            "sources": [{"url": url, "sha256": digest} for url, digest in ARTIFACTS.values()],
            "build": "Native MinGW-w64 GUI launcher + official CPython embedded runtime",
            "requires_installed_python": False,
            "windows_execution_tested": False,
        }
        (package / "Komponentai.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        hashes = {str(p.relative_to(package)).replace(os.sep, "/"): sha256(p)
                  for p in sorted(package.rglob("*")) if p.is_file()}
        (package / "SHA256SUMS.txt").write_text("".join(f"{value}  {name}\n" for name, value in hashes.items()), encoding="utf-8")
        zip_path = destination / "BackUp_Studio_Windows_x64.zip"
        with ZipFile(zip_path.with_suffix(".zip.tmp"), "w", ZIP_DEFLATED, compresslevel=9) as output:
            for path in sorted(package.rglob("*")):
                if path.is_file():
                    output.write(path, path.relative_to(work))
        zip_path.with_suffix(".zip.tmp").replace(zip_path)
        shutil.copytree(package, unpacked)
        print(f"Built {zip_path} ({zip_path.stat().st_size:,} bytes)", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=SOURCE.parent / "packaging-cache")
    parser.add_argument("--output", type=Path, default=SOURCE.parent / "dist")
    parser.add_argument("--tools-root", type=Path, help="Optional extracted Debian build packages root")
    build(parser.parse_args())
