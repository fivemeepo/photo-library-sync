#!/usr/bin/env python3
"""Direct launcher for photo-sync — no install required."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from photo_sync.cli import main

if __name__ == "__main__":
    sys.exit(main())
