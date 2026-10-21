"""Entry point: `python -m capypanel`, or the `capypanel` command."""

import sys


def main() -> int:
    from capypanel.ui.app import run
    from capypanel.ui.tool_catalog import TOOLS

    return run(TOOLS)


if __name__ == "__main__":
    sys.exit(main())
