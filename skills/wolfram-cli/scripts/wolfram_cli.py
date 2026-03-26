#!/usr/bin/env python3
"""Thin wrapper for the packaged Wolfram CLI."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wolfram_cli_tool.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
