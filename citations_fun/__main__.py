# Command-line entry point: python -m citations_fun <stage>
# Run from the repository root (paths under Results/ are relative to it).

import argparse
import sys

from citations_fun.pipeline import STAGES


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m citations_fun",
        description="Run one stage of the NERC dataset citations pipeline.",
    )
    parser.add_argument("stage", choices=list(STAGES),
                        help="dois -> datacite / scholix / overton -> merge")
    args = parser.parse_args(argv)

    STAGES[args.stage]()


if __name__ == "__main__":
    sys.exit(main())
