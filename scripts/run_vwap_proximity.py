"""
VWAP Proximity Scanner entry point — delegates to the CLI.

Usage:
    python scripts/run_vwap_proximity.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nse_relative.cli import main

if __name__ == "__main__":
    sys.argv = ["nse-relative", "vwap"]
    main()
