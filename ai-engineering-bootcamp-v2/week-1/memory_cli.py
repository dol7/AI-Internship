"""CLI demonstrating cross-session durable memory recall.

Talks to the deployed API, not the local package -- each invocation of this
script is its own fresh Python process, with no shared state whatsoever
between runs except what's durably stored server-side. Run `write` in one
terminal session, close it, open a new one, run `read` -- or restart the
Render service entirely in between -- and the fact is still there.

Usage:
  python memory_cli.py write <key> <value> [--category=preference]
  python memory_cli.py read <key>
  python memory_cli.py list
  python memory_cli.py forget <key>
  python memory_cli.py gated-write "<free text>"   # runs the write gate

  python memory_cli.py --base-url https://ai-internship-5euv.onrender.com write ...
"""

import argparse
import json
import os
import sys

import httpx

DEFAULT_BASE_URL = os.environ.get("API_BASE_URL", "https://ai-internship-5euv.onrender.com")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    sub = parser.add_subparsers(dest="command", required=True)

    p_write = sub.add_parser("write")
    p_write.add_argument("key")
    p_write.add_argument("value")
    p_write.add_argument("--category", default="preference")

    p_read = sub.add_parser("read")
    p_read.add_argument("key")

    sub.add_parser("list")

    p_forget = sub.add_parser("forget")
    p_forget.add_argument("key")

    p_gated = sub.add_parser("gated-write")
    p_gated.add_argument("text")

    args = parser.parse_args()

    if args.command == "write":
        r = httpx.put(
            f"{args.base_url}/memory/{args.key}",
            json={"key": args.key, "value": args.value, "category": args.category},
            timeout=30.0,
        )
        print(f"HTTP {r.status_code}")
        print(json.dumps(r.json(), indent=2))

    elif args.command == "read":
        r = httpx.get(f"{args.base_url}/memory/{args.key}", timeout=30.0)
        print(f"HTTP {r.status_code}")
        print(json.dumps(r.json(), indent=2))
        if r.status_code == 404:
            sys.exit(1)

    elif args.command == "list":
        r = httpx.get(f"{args.base_url}/memory", timeout=30.0)
        print(f"HTTP {r.status_code}")
        print(json.dumps(r.json(), indent=2))

    elif args.command == "forget":
        r = httpx.delete(f"{args.base_url}/memory/{args.key}", timeout=30.0)
        print(f"HTTP {r.status_code}")
        print(json.dumps(r.json(), indent=2))

    elif args.command == "gated-write":
        r = httpx.post(f"{args.base_url}/memory/write-gated", json={"text": args.text}, timeout=30.0)
        print(f"HTTP {r.status_code}")
        print(json.dumps(r.json(), indent=2))


if __name__ == "__main__":
    main()
