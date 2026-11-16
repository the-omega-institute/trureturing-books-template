"""Find a cache artifact produced by the default branch's successful CI or Pages workflow.

PR-scoped Actions caches are deliberately never read. Cross-run artifacts are addressed by
an API-verified run and artifact ID, so a previous PR run cannot plant a replacement.
Missing permissions or expired artifacts mean a cache miss.
"""
from __future__ import annotations

import json
import os
import subprocess
from urllib.parse import urlencode


def api(endpoint: str):
    result = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(result.stdout)


def find(repo: str, branch: str, get=api, *, artifact_name="tbook-build-store") -> tuple[int, int] | None:
    query = urlencode({"branch": branch, "status": "success", "per_page": 20})
    runs = []
    for name in ("ci.yml", "pages.yml"):
        try:
            workflow = get(f"repos/{repo}/actions/workflows/{name}")
            if workflow.get("path") != f".github/workflows/{name}":
                continue
            found = get(f"repos/{repo}/actions/workflows/{name}/runs?{query}").get("workflow_runs", [])
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
        events = {"push", "workflow_dispatch", *({"schedule"} if name == "ci.yml" else {"workflow_run"})}
        runs += [run for run in found if (
            run.get("workflow_id") == workflow["id"] and
            run.get("head_repository", {}).get("full_name") == repo and
            run.get("head_branch") == branch and run.get("event") in events and
            run.get("status") == "completed" and run.get("conclusion") == "success")]
    for run in sorted(runs, key=lambda r: (r.get("created_at", ""), int(r["id"])), reverse=True):
        artifacts = get(f"repos/{repo}/actions/runs/{int(run['id'])}/artifacts?per_page=100")
        for artifact in artifacts.get("artifacts", []):
            if artifact.get("name") == artifact_name and not artifact.get("expired", True):
                return int(run["id"]), int(artifact["id"])
    return None


def main() -> None:
    try:
        name = os.environ.get('CACHE_ARTIFACT', 'tbook-build-store')
        if name not in ('tbook-build-store', 'tbook-image-store'):
            raise ValueError('invalid cache artifact name')
        found = find(os.environ["GITHUB_REPOSITORY"], os.environ["DEFAULT_BRANCH"], artifact_name=name)
    except (KeyError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"trusted build cache unavailable ({type(exc).__name__}); building missing units")
        return
    if found:
        run, artifact = found
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write(f"run-id={run}\nartifact-id={artifact}\n")
        print(f"trusted build cache: successful default-branch CI/Pages run {run}, artifact {artifact}")
    else:
        print("no unexpired build cache from a successful default-branch CI or Pages run")


if __name__ == "__main__":
    main()
