"""Entry point: `python -m capypanel`, or the `capypanel` command."""

import sys


def main() -> int:
    from capypanel.ui.app import run
    from capypanel.ui.builds import CAPYPANEL

    return run(CAPYPANEL)


if __name__ == "__main__":
    sys.exit(main())
