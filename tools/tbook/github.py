"""Read GitHub REST data with a bounded retry for Actions rate limits."""

import json
import os
import subprocess
import sys
import time


def rate_limited(stderr: str) -> bool:
    message = stderr.lower()
    return "rate limit" in message or "http 429" in message


def _rate_limit_delay(max_wait: int) -> float | None:
    quota = subprocess.run(["gh", "api", "rate_limit"], capture_output=True, text=True, timeout=10)
    if quota.returncode:
        return None
    try:
        core = json.loads(quota.stdout)["resources"]["core"]
        delay = max(1, core["reset"] - time.time() + 2) if core["remaining"] == 0 else 60
    except (KeyError, TypeError, ValueError):
        return None
    return delay if delay <= max_wait else None


def read_json(endpoint: str, *, paginate: bool = False, timeout: int = 45, max_rate_limit_wait: int = 180):
    """Read one response or a slurped list of pages through the configured gh client."""
    command = ["gh", "api"]
    if paginate:
        command.extend(("--paginate", "--slurp"))
    command.append(endpoint)
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode and os.environ.get("GITHUB_ACTIONS") == "true" and rate_limited(result.stderr):
        try:
            delay = _rate_limit_delay(max_rate_limit_wait)
        except subprocess.TimeoutExpired:
            delay = None
        if delay is not None:
            print(f"GitHub rate limit for {endpoint}. Retrying in {delay:.0f}s.", file=sys.stderr)
            time.sleep(delay)
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    result.check_returncode()
    return json.loads(result.stdout)
