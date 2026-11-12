"""Builds the download: dist/CapyPanel/ (CapyPanel.exe and its libraries), then
dist/CapyPanel-<version>-windows-x64.zip and the zip's SHA-256 beside it.

    uv sync --locked --group build
    uv run python scripts/build_exe.py

The GitHub Actions release job runs exactly this from the version's tag. The steps:
1. write build.txt (version, build number, commit) and the exe's Windows version info;
2. PyInstaller, by packaging/capypanel.spec;
3. the built exe's own self-test (`CapyPanel.exe --self-test`): no zip unless it passes;
4. the zip, with one folder "CapyPanel" inside, and its SHA-256.
"""

import hashlib
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import capypanel  # noqa: E402 -- after the path above, so it's this checkout's
from capypanel.ui.about import CREATOR  # noqa: E402

DIST, WORK = ROOT / "dist", ROOT / "build"
NAME = "CapyPanel"


def version_info(version: str, number: str, build: str) -> str:
    """What Windows shows under the exe's Properties > Details, and SmartScreen beside its
    name: a file with none of it reads as an unnamed program."""
    parts = [int(n) for n in version.split(".")[:3]] + [int(number or 0)]
    numbers = tuple(parts + [0] * (4 - len(parts)))
    strings = {
        "CompanyName": CREATOR,
        "FileDescription": NAME,
        "FileVersion": ".".join(str(n) for n in numbers),
        "InternalName": NAME,
        "LegalCopyright": f"© {CREATOR}. GPL-3.0-only.",
        "OriginalFilename": f"{NAME}.exe",
        "ProductName": NAME,
        "ProductVersion": build,
    }
    table = ",\n        ".join(f"StringStruct({k!r}, {v!r})" for k, v in strings.items())
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3F, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
        {table}])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ],
)
"""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    version, number, commit = capypanel.__version__, capypanel._NUMBER, capypanel._COMMIT
    if not (number and commit):
        print("No build number: build from a git checkout with its whole history.")
        return 1
    print(f"Building {NAME} {capypanel.BUILD}")
    WORK.mkdir(exist_ok=True)
    stamp = WORK / capypanel.STAMP
    stamp.write_text(f"{version} {number} {commit}\n", encoding="utf-8")
    info = WORK / "version_info.txt"
    info.write_text(version_info(version, number, capypanel.BUILD), encoding="utf-8")

    env = {**os.environ, "CAPYPANEL_STAMP": str(stamp), "CAPYPANEL_VERSION_INFO": str(info)}
    spec = ROOT / "packaging" / "capypanel.spec"
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(spec), "--noconfirm", "--clean",
         "--distpath", str(DIST), "--workpath", str(WORK / "pyinstaller")],
        check=True, env=env, cwd=ROOT,
    )  # fmt: skip

    exe, report = DIST / NAME / f"{NAME}.exe", WORK / "self-test.txt"
    report.unlink(missing_ok=True)
    tested = subprocess.run([str(exe), "--self-test", str(report)], timeout=300, check=False)
    print(report.read_text(encoding="utf-8") if report.exists() else "The exe wrote no report.")
    if tested.returncode != 0 or not report.exists():
        print(f"The built exe failed its self-test (exit code {tested.returncode}): no zip.")
        return 1

    archive = DIST / f"{NAME}-{version}-windows-x64.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as packed:
        for path in sorted((DIST / NAME).rglob("*")):
            if path.is_file():
                packed.write(path, Path(NAME) / path.relative_to(DIST / NAME))
    digest = sha256_of(archive)
    # As `sha256sum` writes it; in PowerShell: (Get-FileHash <zip>).Hash is the same letters.
    Path(f"{archive}.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"{archive.name}: {archive.stat().st_size / 1e6:.1f} MB, SHA-256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
