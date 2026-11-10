"""The log's line about how long the start took, part by part."""

from capypanel.ui import app


def test_the_start_line_names_each_part_and_their_total() -> None:
    assert app._process_age() > 0  # Windows says when this process was made
    stages = app._Stages()
    stages._parts = [("before the app's own code", 1.5)]
    stages.done("Qt and the log")
    stages._parts[-1] = ("Qt and the log", 0.25)
    assert stages.text() == (
        "Started in 1.75 s (before the app's own code 1.50, Qt and the log 0.25)"
    )
