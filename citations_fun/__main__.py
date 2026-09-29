# Command-line entry point: python -m citations_fun run <stage|all>
# Run from the repository root (paths under Results/ are relative to it).

import argparse
import sys

from citations_fun.pipeline import STAGES, run_all


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m citations_fun",
        description="Run the NERC dataset citations pipeline.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run one stage, or all of them in order")
    run.add_argument("stage", choices=[*STAGES, "all"],
                     help="dois -> datacite / scholix / overton -> merge, or all")
    args = parser.parse_args(argv)

    if args.stage == "all":
        run_all()
    else:
        STAGES[args.stage]()


if __name__ == "__main__":
    sys.exit(main())
