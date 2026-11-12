# PyInstaller's recipe for CapyPanel.exe. Run through scripts/build_exe.py, which makes the two
# files named by the environment variables below and zips what comes out.
#
# One folder, not one file: a one-file exe unpacks itself into Temp on every start, which is
# slower and what antivirus on company PCs flags most. No UPX either, for the same reason.

import os
import sys
from pathlib import Path

import pefile
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

from capypanel.core.i18n import LANGUAGES

ROOT = Path(SPECPATH).parent  # noqa: F821 -- PyInstaller gives the spec its own folder
STAMP = Path(os.environ["CAPYPANEL_STAMP"])  # build.txt: version, build number, commit
VERSION_INFO = os.environ["CAPYPANEL_VERSION_INFO"]  # what the exe's Properties > Details says

# Everything in the package that isn't code: translations, themes, icons, licenses, presets.
# Named by kind, so a tool's cache or a stray file in the source folder never comes along.
KINDS = ("mo", "json", "svg", "png", "ico", "txt")
datas = collect_data_files("capypanel", includes=[f"**/*.{kind}" for kind in KINDS])
datas += collect_data_files("capypanel", includes=["**/LICENSE"])
datas += [(str(STAMP), "capypanel")]
# About names the version of each library that came along.
datas += copy_metadata("pywin32")

analysis = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "run_capypanel.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    # The tools are loaded by name (ui/tool_catalog.py), which PyInstaller can't follow.
    hiddenimports=collect_submodules("capypanel"),
    # pywin32's window toolkit (win32ui) would bring Microsoft's MFC library along.
    excludes=["tkinter", "unittest", "pydoc", "doctest", "win32ui", "dde"],
    noarchive=False,
)
# Parts of Qt that come along and CapyPanel never loads, a third of the folder: the software
# OpenGL driver, the on-screen keyboard with the QML engine it brings, the PDF reader, Qt's
# OpenSSL plugin (CapyPanel's web requests are Python's) and Qt's own words in the languages
# CapyPanel doesn't have. The built exe's self-test (ui/selftest.py) checks that what it does
# need is still there.
UNUSED = (
    "opengl32sw.dll", "Qt6Quick", "Qt6Qml", "Qt6VirtualKeyboard", "qtvirtualkeyboardplugin",
    "Qt6Pdf", "qpdf.dll", "qopensslbackend", "mfc140u.dll",
)  # fmt: skip
QT_WORDS = {f"qtbase_{code}.qm" for code in LANGUAGES}


def imports_of(library: str) -> set[str]:
    """The DLLs a compiled library asks Windows for, in lower case."""
    image = pefile.PE(library, fast_load=True)
    image.parse_data_directories([pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
    return {entry.dll.decode().lower() for entry in getattr(image, "DIRECTORY_ENTRY_IMPORT", [])}


# OpenSSL: only the one Python itself came with, which its _ssl and _hashlib ask for by name.
# Qt's plugin asks for one too, under another name on some PCs: that one stays out.
OPENSSL = ("libcrypto", "libssl")
pythons_own = set()
for dest, source, _kind in analysis.binaries:
    if Path(dest).name.lower() in ("_ssl.pyd", "_hashlib.pyd"):
        pythons_own |= {name for name in imports_of(source) if name.startswith(OPENSSL)}
assert pythons_own, "Python's _ssl names no OpenSSL library"


def needed(entry: tuple[str, str, str]) -> bool:
    name = Path(entry[0]).name
    if Path(entry[0]).parent.name == "translations" and name.endswith(".qm"):
        return name in QT_WORDS
    if name.lower().startswith(OPENSSL):
        return name.lower() in pythons_own
    return not name.startswith(UNUSED)


analysis.binaries = [entry for entry in analysis.binaries if needed(entry)]

# Every library in the folder comes from Python itself, a package in uv.lock or Windows: never
# from another program that happens to be on the building PC's PATH (a Java or Git folder
# gave this build its C runtime and its OpenSSL once). build_exe.py runs this with a PATH of
# Windows' own folders only; this stops the build if one still slips in.
TRUSTED = [Path(p).resolve() for p in (sys.base_prefix, sys.prefix, os.environ["SYSTEMROOT"])]
foreign = [
    f"{dest} <- {source}"
    for dest, source, _kind in analysis.binaries
    if not any(Path(source).resolve().is_relative_to(root) for root in TRUSTED)
]
if foreign:
    raise SystemExit("Libraries from outside Python, the packages and Windows:\n" + "\n".join(foreign))
analysis.datas = [entry for entry in analysis.datas if needed(entry)]
archive = PYZ(analysis.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    archive,
    analysis.scripts,
    exclude_binaries=True,  # one folder: the libraries sit beside the exe, in _internal
    name="CapyPanel",
    icon=str(ROOT / "src" / "capypanel" / "ui" / "branding" / "capypanel.ico"),
    version=VERSION_INFO,
    console=False,
    upx=False,
)
COLLECT(  # noqa: F821
    exe,
    analysis.binaries,
    analysis.datas,
    name="CapyPanel",
    upx=False,
)
