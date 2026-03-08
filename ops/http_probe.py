#!/usr/bin/env python3
"""Probe an HTTP endpoint from a local or containerized context."""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scheme", default="http", choices=("http", "https"), help="Probe scheme")
    parser.add_argument("--host", default="127.0.0.1", help="Probe host")
    parser.add_argument("--host-header", default="", help="Optional Host header override")
    parser.add_argument("--port", default="", help="Explicit port override")
    parser.add_argument("--port-env", default="APP_PORT", help="Port environment variable name")
    parser.add_argument("--path", default="", help="Explicit path override")
    parser.add_argument("--path-env", required=True, help="Path environment variable name")
    parser.add_argument("--default-port", default="8000", help="Default port when env is unset")
    parser.add_argument("--default-path", required=True, help="Default path when env is unset")
    parser.add_argument(
        "--expected-status",
        type=int,
        default=200,
        help="Expected HTTP status code",
    )
    parser.add_argument("--timeout", type=float, default=2.0, help="Request timeout in seconds")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    port = args.port or os.environ.get(args.port_env, args.default_port)
    path = args.path or os.environ.get(args.path_env, args.default_path)
    if not path.startswith("/"):
        path = f"/{path}"

    url = f"{args.scheme}://{args.host}:{port}{path}"
    request = urllib.request.Request(url)
    if args.host_header:
        request.add_header("Host", args.host_header)
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            response.read()
            if response.status != args.expected_status:
                print(
                    f"Probe failed for {url}: expected status {args.expected_status}, "
                    f"got {response.status}",
                    file=sys.stderr,
                )
                return 1
    except urllib.error.HTTPError as exc:
        print(
            f"Probe failed for {url}: expected status {args.expected_status}, got {exc.code}",
            file=sys.stderr,
        )
        return 1
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"Probe failed for {url}: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
