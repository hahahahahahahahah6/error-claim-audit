"""Command-line interface."""
import argparse
import json
import sys
from . import __version__
from .core import RULES, audit


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, "error: " + message + "\n")


def main(argv=None):
    parser = Parser(description="Audit documented Python error behaviour offline")
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fail-on", choices=("HIGH", "MEDIUM"), default="MEDIUM")
    parser.add_argument("--ignore", default="", metavar="RULE,...")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    ignored = {part.strip() for part in args.ignore.split(",") if part.strip()}
    unknown = ignored - {rule for rule, _ in RULES.values()}
    if unknown:
        parser.error("unknown rule: " + ", ".join(sorted(unknown)))
    try:
        result = audit(args.project, args.fail_on, ignored)
    except (OSError, ValueError) as exc:
        print("error: " + str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        for item in result["findings"]:
            print("{severity} {rule} {file}:{line} {claim}".format(**item))
        if args.verbose:
            for kind, values in result["verified_claims"].items():
                for value in values:
                    print("OK {} {}".format(kind, value))
        print(result["status"])
    return 2 if result["status"] == "FAIL" else 0
