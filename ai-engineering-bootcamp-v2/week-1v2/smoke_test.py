#!/usr/bin/env python3
"""No-token smoke test for the Week 1 v2 API."""

import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

WORKDIR = Path(__file__).resolve().parent


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_health(base_url: str, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=1.0)
            if response.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    return False


def main() -> int:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=WORKDIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        if not wait_for_health(base_url):
            print(f"FAIL: API did not become healthy at {base_url}")
            return 1
        print(f"PASS: /health returned 200 at {base_url}")

        docs_response = httpx.get(f"{base_url}/docs", timeout=2.0)
        if docs_response.status_code != 200:
            print(f"FAIL: /docs returned HTTP {docs_response.status_code}")
            return 1
        print(f"PASS: /docs returned 200 at {base_url}")

        return 0
    finally:
        proc.terminate()
        proc.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
