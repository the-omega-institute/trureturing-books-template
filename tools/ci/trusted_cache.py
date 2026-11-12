"""Find a cache artifact produced by the default branch's successful Pages workflow.

PR-scoped Actions caches are deliberately never read. Cross-run artifacts are addressed by
an API-verified run and artifact ID, so a previous PR run cannot plant a replacement.
Missing permissions, expired artifacts and repositories without Pages all mean a cache miss.
"""
from __future__ import annotations

import json
import os
import subprocess
from urllib.parse import urlencode


def api(endpoint: str):
    result = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(result.stdout)


def find(repo: str, branch: str, get=api) -> tuple[int, int] | None:
    workflow = get(f"repos/{repo}/actions/workflows/pages.yml")
    if workflow.get("path") != ".github/workflows/pages.yml":
        return None
    query = urlencode({"branch": branch, "status": "success", "per_page": 20})
    runs = get(f"repos/{repo}/actions/workflows/pages.yml/runs?{query}").get("workflow_runs", [])
    for run in runs:
        if not (run.get("workflow_id") == workflow["id"] and
                run.get("head_repository", {}).get("full_name") == repo and
                run.get("head_branch") == branch and run.get("event") in {"push", "workflow_dispatch"} and
                run.get("status") == "completed" and run.get("conclusion") == "success"):
            continue
        artifacts = get(f"repos/{repo}/actions/runs/{int(run['id'])}/artifacts?per_page=100")
        for artifact in artifacts.get("artifacts", []):
            if artifact.get("name") == "tbook-build-store" and not artifact.get("expired", True):
                return int(run["id"]), int(artifact["id"])
    return None


def main() -> None:
    try:
        found = find(os.environ["GITHUB_REPOSITORY"], os.environ["DEFAULT_BRANCH"])
    except (KeyError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"trusted build cache unavailable ({type(exc).__name__}); building missing units")
        return
    if found:
        run, artifact = found
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write(f"run-id={run}\nartifact-id={artifact}\n")
        print(f"trusted build cache: Pages run {run}, artifact {artifact}")
    else:
        print("no unexpired build cache from a successful default-branch Pages run")


if __name__ == "__main__":
    main()
