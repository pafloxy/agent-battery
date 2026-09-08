#!/usr/bin/env python3
"""GNOME entry point for the shared engine.

Example (source root): python3 extension/quota.py --config example.json
"""
from pathlib import Path
import signal
import sys
from typing import Any

# Installation bundles the engine here; the source tree keeps it one level up.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE if (HERE / "usagebar").is_dir() else HERE.parent))
from usagebar.core import main


def stop(_signum: int, _frame: Any) -> None:
    """Unwind provider cleanup on shutdown. Example: stop(signal.SIGTERM, None)."""
    raise SystemExit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    raise SystemExit(main())
