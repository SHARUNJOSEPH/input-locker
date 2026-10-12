"""Package entry point for `python -m input_locker`."""

from __future__ import annotations

import sys

from input_locker.main import main

if __name__ == "__main__":
    sys.exit(main())
