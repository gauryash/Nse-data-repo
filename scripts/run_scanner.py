"""
Unified scanner entry point — delegates to the CLI.

Usage:
    python scripts/run_scanner.py [scanner ...]
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nse_relative.cli import main

if __name__ == "__main__":
    # Pass "scan" plus any extra args
    sys.argv = ["nse-relative", "scan"] + sys.argv[1:]
    main()
