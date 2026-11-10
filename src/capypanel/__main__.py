"""Entry point: `python -m capypanel`, or the `capypanel` command."""

import sys


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--relay":  # see core/remote/relay.py
        from capypanel.core.remote import relay

        relay.main(sys.argv[2])
    from capypanel.ui.app import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
