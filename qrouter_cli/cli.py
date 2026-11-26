"""Command-line entry point."""

import argparse
import json
import sys

from .collectors import CollectorError, kuma_status, router_read, router_status


def main() -> None:
    parser = argparse.ArgumentParser(prog="qurouter", description="Read-only QuRouter diagnostics")
    sub = parser.add_subparsers(dest="area", required=True)
    router = sub.add_parser("router", help="Read QHora router via fixed SSH queries")
    router.add_argument("action", choices=["status", "interfaces", "addresses", "routes", "neighbors", "wifi", "listeners", "filesystems"])
    kuma = sub.add_parser("kuma", help="Read Uptime Kuma published status page")
    kuma.add_argument("action", choices=["status"])
    args = parser.parse_args()
    try:
        result = (router_status() if args.action == "status" else router_read(args.action)) if args.area == "router" else kuma_status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except CollectorError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
