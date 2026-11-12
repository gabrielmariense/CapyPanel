"""What CapyPanel.exe runs: the same entry point as the `capypanel` command."""

import sys

from capypanel.__main__ import main

sys.exit(main())
