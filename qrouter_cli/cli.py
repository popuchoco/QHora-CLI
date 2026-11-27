"""Command-line entry point."""

import argparse
import json
import sys

from .collectors import CollectorError, integrated_router_status, kuma_monitor_status, kuma_status, router_read, router_status
from .web_api import RouterAPIError, router_web_status
from .logging_utils import emit_log


def main() -> None:
    parser = argparse.ArgumentParser(prog="qurouter", description="Read-only QuRouter diagnostics")
    sub = parser.add_subparsers(dest="area", required=True)
    router = sub.add_parser("router", help="Read QHora router via fixed SSH queries")
    router.add_argument("action", choices=["status", "web-status", "integrated-status", "interfaces", "addresses", "routes", "neighbors", "wifi", "listeners", "filesystems"])
    kuma = sub.add_parser("kuma", help="Read Uptime Kuma published status page")
    kuma.add_argument("action", choices=["status", "monitor"])
    kuma.add_argument("--name", help="Exact monitor name when using `kuma monitor`")
    args = parser.parse_args()
    try:
        if args.area == "router":
            result = router_status() if args.action == "status" else router_web_status() if args.action == "web-status" else integrated_router_status() if args.action == "integrated-status" else router_read(args.action)
        elif args.action == "status":
            result = kuma_status()
        else:
            if not args.name:
                parser.error("kuma monitor requires --name")
            result = kuma_monitor_status(args.name)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (CollectorError, RouterAPIError) as exc:
        emit_log("command_failed", "ERROR", component="cli", operation=f"{args.area}.{args.action}", error_type=type(exc).__name__)
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
