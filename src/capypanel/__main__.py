"""Entry point: `python -m capypanel`, or the `capypanel` command."""

import sys


def main() -> int:
    from capypanel.ui.app import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
