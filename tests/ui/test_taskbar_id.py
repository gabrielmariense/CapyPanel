"""Which taskbar identity CapyPanel takes: its own from source, the exe's own as CapyPanel.exe."""

import sys

import pytest

from capypanel.ui import branding


def test_the_exe_opens_on_its_pinned_taskbar_button(monkeypatch: pytest.MonkeyPatch) -> None:
    set_ids: list[str] = []
    monkeypatch.setattr(branding, "_set_app_id", set_ids.append)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    branding.use_own_taskbar_icon()
    assert set_ids == []  # Windows' own id for the exe: the one a pinned button has
    monkeypatch.delattr(sys, "frozen")
    branding.use_own_taskbar_icon()
    assert set_ids == [branding.APP_ID]  # from Python: its own, so not Python's icon
