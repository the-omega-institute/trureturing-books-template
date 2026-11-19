"""Choose the latest tested main commit within the Pages deployment cadence."""
from datetime import datetime, timedelta, timezone
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ci.plan import Tree, ancestor, api, changed_paths, git, impact
from ci.trusted_cache import PAGES_PUSH_TITLE
from tbook import config, lean, pin


INTERVAL = timedelta(minutes=20)


def when(value):
    return datetime.fromisoformat(value)


def deployment_window(repo, now, get):
    """Return the live SHA and time of the most recent Pages attempt or success."""
    endpoint = f"repos/{repo}/deployments?environment=github-pages&per_page=100"
    latest = None
    page = 1
    while True:
        deployments = get(endpoint if page == 1 else f"{endpoint}&page={page}")
        for deployment in deployments:
            started = when(deployment["created_at"])
            latest = max(latest or started, started)
            if now - latest < INTERVAL:
                return None, latest
            statuses = get(f"repos/{repo}/deployments/{int(deployment['id'])}/statuses?per_page=1")
            if statuses and statuses[0]["state"] == "success":
                finished = when(statuses[0]["created_at"])
                return deployment["sha"], max(latest, finished)
        if len(deployments) < 100:
            return None, latest
        page += 1


def push_runs(repo, branch, workflow, get, **filters):
    query = urlencode(dict(branch=branch, event="push", per_page=100, **filters))
    runs = get(f"repos/{repo}/actions/workflows/{workflow}.yml/runs?{query}")["workflow_runs"]
    return [run for run in runs if run["head_branch"] == branch and run["event"] == "push"
            and (run.get("head_repository") or {}).get("full_name") == repo]


def follows_branch(site):
    enabled = site.raw.get("trureturing", {}).get("pages_follow_branch", False)
    if not isinstance(enabled, bool):
        raise ValueError("site.toml: trureturing.pages_follow_branch must be a boolean")
    return enabled


def live_trureturing(url):
    # A cached copy could mask a new deployment. This endpoint is only used to
    # detect changes; the pin is always resolved against the upstream repository.
    req = Request(url.rstrip("/") + "/manifest.json", headers={"Cache-Control": "no-cache"})
    with urlopen(req, timeout=30) as response:
        return json.load(response).get("trureturing") or {}


def refresh_due(root, repo, branch, head, now, get=api):
    live, last_attempt = deployment_window(repo, now, get)
    if not live or (last_attempt and now - last_attempt < INTERVAL):
        return False
    if not re.fullmatch(r"[a-f0-9]{40}", live) or not ancestor(root, live, head):
        return False
    return any(run["head_sha"] == head and run["status"] == "completed" and run["conclusion"] == "success"
               for run in push_runs(repo, branch, "ci", get, status="success", head_sha=head))


def prepare_snapshot(site, repo, branch, head, *, refresh=False, get=api, read_live=live_trureturing):
    """Write the lock used by all Pages jobs and return its immutable commit."""
    if not follows_branch(site):
        return ""
    if refresh and not refresh_due(site.root, repo, branch, head, datetime.now(timezone.utc), get):
        return ""
    target = lean.ls_remote(site.trureturing_repo, f"refs/heads/{site.trureturing_branch}")
    if refresh:
        url = get(f"repos/{repo}/pages")["html_url"]
        if read_live(url) == dict(repo=site.trureturing_repo, branch=site.trureturing_branch, commit=target):
            return ""
    report = pin.pin(target)
    print(report.markdown())
    if not report.written:
        raise ValueError(f"cannot publish with trureturing at {target}")
    return target


def select(root, repo, branch, head, now, get=api):
    live, last_attempt = deployment_window(repo, now, get)
    if last_attempt and now - last_attempt < INTERVAL:
        return None
    if live and (not re.fullmatch(r"[a-f0-9]{40}", live) or not ancestor(root, live, head)):
        return None

    verified = {run["head_sha"] for run in push_runs(repo, branch, "ci", get, status="success")
                if run["status"] == "completed" and run["conclusion"] == "success"}
    if not verified:
        return None
    revision = f"{live}..{head}" if live else head
    for sha in git(root, "rev-list", "--first-parent", revision).decode().splitlines():
        if sha not in verified:
            continue
        for run in push_runs(repo, branch, "pages", get, head_sha=sha):
            # Runs created under an earlier policy would replay its workflow on rerun.
            if run["head_sha"] == sha and run["display_title"] == PAGES_PUSH_TITLE + sha:
                if live:
                    changes = changed_paths(root, live, sha)
                    if not changes or not impact(Tree(root, sha), Tree(root, live), changes)["site"]:
                        return None
                return run
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("schedule", "verify", "snapshot", "refresh"))
    args = parser.parse_args()
    if args.operation == "snapshot" or args.operation == "refresh":
        commit = prepare_snapshot(config.load_site(), os.environ["GITHUB_REPOSITORY"],
                                  os.environ["DEFAULT_BRANCH"], os.environ["GITHUB_SHA"],
                                  refresh=args.operation == "refresh")
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write(f"commit={commit}\n")
        return
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.environ["DEFAULT_BRANCH"]
    root = Path.cwd()
    git(root, "fetch", "--no-tags", "origin", f"refs/heads/{branch}")
    now = datetime.now(timezone.utc)
    run = select(root, repo, branch, "FETCH_HEAD", now)
    if not run:
        print("No verified Pages update is due.")
        return

    sha = run["head_sha"]
    if args.operation == "verify":
        if sha == os.environ["GITHUB_SHA"]:
            print(f"Publishing verified commit {sha}.")
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
                out.write("publish=true\n")
        else:
            print(f"The newest verified Pages update is {sha}.")
        return

    if run["status"] != "completed":
        print(f"Pages run for {sha} is {run['status']}.")
        return
    if run["run_attempt"] > 1 and now - when(run["updated_at"]) < INTERVAL:
        print(f"Pages recently attempted {sha}.")
        return
    print(f"Preparing publication of verified commit {sha}.")
    run_id = int(run["id"])
    subprocess.run(["gh", "api", "--method", "POST", f"repos/{repo}/actions/runs/{run_id}/rerun"],
                   check=True, timeout=45)


if __name__ == "__main__":
    main()
