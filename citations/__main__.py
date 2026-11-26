"""Entry point for ``python -m citations``.

Hands the command line to `citations.cli.main` and exits with its status.
"""

import sys

from .cli import main

sys.exit(main())
