"""Gate automatic Pages publication on CI and the active deployment."""
import argparse
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlencode

from plan import active_deployment, ancestor, api, git


def push_runs(repo, workflow, branch, sha, get=api):
    query = urlencode(dict(branch=branch, head_sha=sha, event="push", per_page=100))
    runs = get(f"repos/{repo}/actions/workflows/{workflow}.yml/runs?{query}")["workflow_runs"]
    return [run for run in runs
            if run.get("head_sha") == sha and run.get("head_branch") == branch
            and run.get("event") == "push"
            and (run.get("head_repository") or {}).get("full_name") == repo]


def wait_for_push(repo, workflow, branch, sha, minutes):
    deadline = time.monotonic() + minutes * 60
    while time.monotonic() < deadline:
        runs = push_runs(repo, workflow, branch, sha)
        if runs:
            run = max(runs, key=lambda item: int(item["id"]))
            if run["status"] == "completed":
                return run
        time.sleep(30)
    raise TimeoutError(f"Timed out waiting for {workflow} for {sha}")


def is_newer(root, repo, main, candidate, get=api):
    if not ancestor(root, candidate, main):
        return False
    live = active_deployment(root, repo, get=get)
    return live is None or (live != candidate and ancestor(root, live, candidate))


def resume(repo, branch, sha):
    # A push from before this workflow was installed has no Pages run to resume.
    if not push_runs(repo, "pages", branch, sha):
        return
    run = wait_for_push(repo, "pages", branch, sha, minutes=290)
    # A new attempt of that run preserves the push SHA in GitHub's deployment metadata.
    run_id = int(run["id"])
    jobs = api(f"repos/{repo}/actions/runs/{run_id}/attempts/{int(run['run_attempt'])}/jobs")["jobs"]
    gating_steps = {step["name"]: step["conclusion"]
                    for job in jobs if job["name"] == "Plan affected work" for step in job["steps"]}
    if (run["conclusion"] == "cancelled"
            or gating_steps.get("Wait for successful CI and compare with the live site") == "failure"
            or gating_steps.get("Select before installing or downloading caches") == "skipped"):
        subprocess.run(["gh", "api", "--method", "POST", f"repos/{repo}/actions/runs/{run_id}/rerun"],
                       check=True, timeout=45)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    repo, branch = (os.environ[key] for key in ("GITHUB_REPOSITORY", "DEFAULT_BRANCH"))
    if args.resume:
        resume(repo, branch, os.environ["VERIFIED_SHA"])
        return

    sha = os.environ["GITHUB_SHA"]
    run = wait_for_push(repo, "ci", branch, sha, minutes=240)
    print(f'CI for {sha}: {run["conclusion"]} ({run["html_url"]})')
    if run["conclusion"] != "success":
        return
    # The entire publication holds the Pages concurrency group, including this check.
    root = Path.cwd()
    git(root, "fetch", "--no-tags", "origin", f"refs/heads/{branch}")
    if not is_newer(root, repo, "FETCH_HEAD", sha):
        print(f"Skipping {sha}: it does not advance the active Pages deployment from {branch}.")
        return
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        out.write("publish=true\n")


if __name__ == "__main__":
    main()
