import codecs
import json
import sys
import time
from pathlib import Path

import pytest

from capypanel.core.tools import definitions, viewer_settings
from capypanel.core.tools.connect import Credential, Target, launch
from capypanel.core.tools.viewer_settings import SettingsFileError

REMOVE = ("host", "port", "password", "UseDSMPlugin", "DSMPlugin")
ULTRAVNC = (
    "[connection]\r\nhost=10.0.0.9\r\nport=5900\r\nproxyhost=\r\npassword=deadbeef\r\n"
    "[options]\r\nuse_encoding_1=0\r\nUseDSMPlugin=1\r\nDSMPlugin=SecureVNCPlugin64.dsm\r\n"
    "viewonly=1\r\nfullscreen=0\r\n"
)

# Stands in for UltraVNC: records the arguments and the -config file's content as it starts.
RECORDER = """
import json, sys
args = sys.argv[2:]
config = None
if "-config" in args:
    with open(args[args.index("-config") + 1], "rb") as f:
        config = f.read().decode("latin-1")
open(sys.argv[1], "w", encoding="utf-8").write(json.dumps({"args": args, "config": config}))
"""


def test_the_settings_capypanel_sets_are_removed_and_the_rest_kept_as_is() -> None:
    cleaned = viewer_settings.clean(ULTRAVNC.encode("cp1252"), REMOVE).decode("cp1252")
    assert cleaned == (
        "[connection]\r\nproxyhost=\r\n"
        "[options]\r\nuse_encoding_1=0\r\nviewonly=1\r\nfullscreen=0\r\n"
    )


def test_any_code_page_and_utf16_survive_unchanged() -> None:
    accented = "[options]\r\nhost=x\r\nTitle=Clínica Ação\r\n"
    assert viewer_settings.clean(accented.encode("cp1252"), REMOVE) == (
        "[options]\r\nTitle=Clínica Ação\r\n".encode("cp1252")
    )
    utf16 = accented.encode("utf-16")
    cleaned = viewer_settings.clean(utf16, REMOVE)
    assert cleaned.startswith(codecs.BOM_UTF16_LE)
    assert cleaned.decode("utf-16") == "[options]\r\nTitle=Clínica Ação\r\n"


@pytest.mark.parametrize(
    "raw",
    [b"", b"[options]\r\n; nothing set\r\n", b"just some text\r\n", b"MZ\x90\x00\x03\x00\x00"],
)
def test_something_else_is_refused(raw: bytes) -> None:
    with pytest.raises(SettingsFileError):
        viewer_settings.clean(raw, REMOVE)


def test_a_huge_file_is_refused(tmp_path: Path) -> None:
    big = tmp_path / "big.vnc"
    big.write_bytes(b"[options]\r\n" + b"a=1\r\n" * 60_000)
    with pytest.raises(SettingsFileError):
        viewer_settings.read(big, REMOVE)


def test_the_temporary_copy_is_deleted_soon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(viewer_settings, "KEEP_COPY_FOR", 0.05)
    copy = viewer_settings.temp_copy(b"[options]\r\na=1\r\n", ".vnc")
    assert copy.read_bytes() == b"[options]\r\na=1\r\n" and copy.suffix == ".vnc"
    deadline = time.monotonic() + 5
    while copy.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not copy.exists()


def test_the_viewer_gets_a_cleaned_copy_never_the_shared_file(tmp_path: Path) -> None:
    script = tmp_path / "recorder.py"
    script.write_text(RECORDER, encoding="utf-8")
    out = tmp_path / "received.json"
    tool = definitions.from_data(
        {
            "schema": 1, "id": "recorder", "name": "Recorder", "kind": "vnc", "port": 5900,
            "credentials": "arguments",
            "settings_file": {"extension": ".vnc", "remove": list(REMOVE)},
            "arguments": [[str(script), str(out)], ["-config", "{settings_file}"],
                          ["{address}::{port}"], ["-password", "{password}"]],
        }
    )  # fmt: skip
    shared = tmp_path / "clinics.vnc"
    shared.write_bytes(ULTRAVNC.encode("cp1252"))
    process = launch(tool, Path(sys.executable), Target("pc1"), Credential("", "pw"), (), shared)
    assert process.wait(30) == 0
    received = json.loads(out.read_text(encoding="utf-8"))
    config = received["args"][1]
    assert received["args"] == ["-config", config, "pc1::5900", "-password", "pw"]
    assert Path(config) != shared and Path(config).suffix == ".vnc"
    assert "viewonly=1" in received["config"] and "10.0.0.9" not in received["config"]
    assert shared.read_bytes() == ULTRAVNC.encode("cp1252")  # the shared file is untouched
    # Without a settings file the group is left out: the viewer uses its own defaults.
    launch(tool, Path(sys.executable), Target("pc1"), Credential("", "pw")).wait(30)
    assert json.loads(out.read_text(encoding="utf-8"))["args"] == ["pc1::5900", "-password", "pw"]
