"""Entry point: `python -m capypanel`, or the `capypanel` command."""

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":  # see ui/selftest.py
        from capypanel.ui import selftest

        return selftest.run(Path(sys.argv[2]))
    from capypanel.ui.app import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
