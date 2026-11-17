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


def find_films(repo: str, branch: str, get=api) -> tuple[int, int] | None:
    """Find retained film stores directly, independent of unrelated successful runs.

    Bound pagination by the initial artifact count. Each artifact still needs a
    successful producer from one of the same approved workflows and events.
    """
    workflows = {}
    for name in ("ci.yml", "pages.yml"):
        try:
            workflow = get(f"repos/{repo}/actions/workflows/{name}")
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
        if workflow.get("path") == f".github/workflows/{name}":
            workflows[workflow["id"]] = name
    query = urlencode({"name": "tbook-film-store", "per_page": 100})
    endpoint = f"repos/{repo}/actions/artifacts?{query}"
    data = get(f"{endpoint}&page=1")
    pages = max(1, (int(data["total_count"]) + 99) // 100)
    runs, candidates = {}, []
    for page in range(1, pages + 1):
        if page > 1:
            data = get(f"{endpoint}&page={page}")
        for artifact in data.get("artifacts", []):
            if artifact.get("name") != "tbook-film-store" or artifact.get("expired", True):
                continue
            run_id = int(artifact["workflow_run"]["id"])
            if run_id not in runs:
                runs[run_id] = get(f"repos/{repo}/actions/runs/{run_id}")
            run = runs[run_id]
            name = workflows.get(run.get("workflow_id"))
            events = {"push", "workflow_dispatch", "schedule" if name == "ci.yml" else "workflow_run"}
            if (name and run.get("head_repository", {}).get("full_name") == repo and
                    run.get("head_branch") == branch and run.get("event") in events and
                    run.get("status") == "completed" and run.get("conclusion") == "success"):
                candidates.append((run.get("updated_at") or run.get("created_at", ""),
                                   run_id, int(artifact["id"])))
    return max(candidates)[1:] if candidates else None


def find(repo: str, branch: str, get=api, *, artifact_name="tbook-build-store") -> tuple[int, int] | None:
    if artifact_name == "tbook-film-store":
        return find_films(repo, branch, get)
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
    # A long Pages build can upload fresh films after a later-started CI has
    # finished. Prefer the most recently completed producer, including reruns.
    for run in sorted(runs, key=lambda r: (r.get("updated_at") or r.get("created_at", ""), int(r["id"])), reverse=True):
        artifacts = get(f"repos/{repo}/actions/runs/{int(run['id'])}/artifacts?per_page=100")
        for artifact in artifacts.get("artifacts", []):
            if artifact.get("name") == artifact_name and not artifact.get("expired", True):
                return int(run["id"]), int(artifact["id"])
    return None


def main() -> None:
    try:
        name = os.environ.get('CACHE_ARTIFACT', 'tbook-build-store')
        if name not in ('tbook-build-store', 'tbook-image-store', 'tbook-film-store'):
            raise ValueError('invalid cache artifact name')
        found = find(os.environ["GITHUB_REPOSITORY"], os.environ["DEFAULT_BRANCH"], artifact_name=name)
        scope = 'films' if name == 'tbook-film-store' else 'all'
        if not found and name == 'tbook-film-store':
            # Older producers have only the complete store. Its archive includes
            # the films/ directory, so restore it at the store root during migration.
            found = find(os.environ["GITHUB_REPOSITORY"], os.environ["DEFAULT_BRANCH"])
            scope = 'all'
    except (KeyError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"trusted build cache unavailable ({type(exc).__name__}); building missing units")
        return
    if found:
        run, artifact = found
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write(f"run-id={run}\nartifact-id={artifact}\nartifact-scope={scope}\n")
        print(f"trusted build cache: successful default-branch CI/Pages run {run}, artifact {artifact}")
    else:
        print("no unexpired build cache from a successful default-branch CI or Pages run")


if __name__ == "__main__":
    main()
