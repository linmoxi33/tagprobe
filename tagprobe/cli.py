"""Command line entry point for tagprobe."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import SpecError, load_spec, run


def build_parser():
    parser = argparse.ArgumentParser(
        prog="tagprobe",
        description="Run one probe spec against two source trees and diff runtime behaviour.",
    )
    parser.add_argument("--a", required=True, metavar="DIR", help="source tree of the baseline revision")
    parser.add_argument("--b", required=True, metavar="DIR", help="source tree of the candidate revision")
    parser.add_argument("--spec", required=True, metavar="FILE", help="probe spec JSON")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    parser.add_argument("--only-drift", action="store_true", help="keep only drifting cases in the report")
    parser.add_argument("--report", metavar="FILE", help="write the full report to FILE")
    parser.add_argument("--timeout", type=float, default=30.0, help="per-tree runner timeout in seconds")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        spec = load_spec(args.spec)
        report = run(args.a, args.b, spec, timeout=args.timeout)
    except SpecError as exc:
        print(f"tagprobe: {exc}", file=sys.stderr)
        return 2

    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    shown = report
    if args.only_drift:
        shown = {**report, "cases": [c for c in report["cases"] if c["status"] == "drift"]}

    if args.json:
        print(json.dumps(shown, indent=2, sort_keys=True))
    else:
        for case in shown["cases"]:
            if case["status"] == "drift":
                print(f"DRIFT {case['id']} [{','.join(case['kinds'])}] {case['module']}.{case['function']}")
        summary = report["summary"]
        print(f"{summary['same']}/{summary['total']} cases identical, {summary['drift']} drifted")
        print(f"digest {report['digest']}")

    return 1 if report["summary"]["drift"] else 0
