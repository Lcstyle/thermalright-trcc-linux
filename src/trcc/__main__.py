#!/usr/bin/env python3
"""Allow running as: python -m trcc"""

import sys

from trcc.cli import main

if __name__ == "__main__":
    sys.exit(main())
