"""Reserve one of ten hourly Pages publication starts while holding the workflow lock."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import subprocess
import time

from ci.plan import ancestor, api
from ci.pages_schedule import live_commit


LIMIT = 10
WINDOW = timedelta(hours=1)
ENVIRONMENT = "tbook-pages-build"
TASK = "pages-build"


def reserve(repo, sha, attempt, *, get=api, post=None, now=None, sleep=time.sleep):
    # Deployment records survive build failures, cancellations and runner changes.
    # Use a distinct task/environment so build starts never become live-site baselines.
    endpoint = f"repos/{repo}/deployments"
    recent = get(f"{endpoint}?environment={ENVIRONMENT}&task={TASK}&per_page={LIMIT}")
    if any(item["payload"] == {"attempt": attempt} for item in recent):
        return
    if len(recent) == LIMIT:
        oldest = min(datetime.fromisoformat(item["created_at"]) for item in recent)
        delay = (oldest + WINDOW - (now or datetime.now(timezone.utc))).total_seconds()
        if delay > 0:
            # No other publisher can claim a slot while this workflow holds concurrency: pages.
            print(f"Ten Pages starts in the last hour. Waiting {delay:.0f}s for the next slot.", flush=True)
            sleep(delay + 1)
    body = dict(ref=sha, task=TASK, environment=ENVIRONMENT, auto_merge=False,
                required_contexts=[], transient_environment=True, production_environment=False,
                description="Reserve a Pages build start", payload={"attempt": attempt})
    post = post or post_json
    receipt = post(endpoint, body)
    post(f"{endpoint}/{int(receipt['id'])}/statuses", {"state": "success", "description": "Pages build admitted"})


def post_json(endpoint, body):
    result = subprocess.run(["gh", "api", "--method", "POST", endpoint, "--input", "-"],
                            input=json.dumps(body), text=True, capture_output=True, check=True, timeout=45)
    return json.loads(result.stdout)


if __name__ == "__main__":
    if "--retry" in sys.argv:
        live = live_commit(os.environ["GITHUB_REPOSITORY"])
        if live and not ancestor(Path.cwd(), live, os.environ["GITHUB_SHA"]):
            sys.exit("A newer or divergent commit is already live.")
    reserve(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"],
            f"{os.environ['GITHUB_RUN_ID']}/{os.environ['GITHUB_RUN_ATTEMPT']}")
