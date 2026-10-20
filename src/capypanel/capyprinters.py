"""CapyPrinters: the build with only the Printers tool. `python -m capypanel.capyprinters`, or the
`capyprinters` command. It imports no other tool's code, so its own copy can leave them out."""

import sys

from capypanel.core.identity import Identity

IDENTITY = Identity(
    "CapyPrinters",
    folder="CapyPrinters",
    portable_marker="capyprinters.portable",
    windows_app_id="CapyPanel.CapyPrinters",
    rail=False,  # one tool: nothing to switch between
)


def main() -> int:
    from capypanel.ui.app import Build, run
    from capypanel.ui.printers_tool.tool import PrintersTool

    return run(Build(IDENTITY, (PrintersTool,)))


if __name__ == "__main__":
    sys.exit(main())
