"""Decide whether a queued Pages run has publication inputs to build."""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

from ci.plan import Tree, ancestor, api, changed_paths, impact
from tbook import config, lean, pin, releases


def live_commit(repo, get=api):
    endpoint = f"repos/{repo}/deployments?environment=github-pages&per_page=100"
    page = 1
    while True:
        deployments = get(f"{endpoint}&page={page}")
        for item in deployments:
            statuses = get(f"repos/{repo}/deployments/{int(item['id'])}/statuses?per_page=1")
            if statuses and statuses[0]["state"] == "success":
                return item["sha"]
        if len(deployments) < 100:
            return None
        page += 1


def site_changed(root, live, sha):
    if not live:
        return True
    paths = changed_paths(root, live, sha)
    return bool(paths and impact(Tree(root, sha), Tree(root, live), paths)["site"])


def live_manifest(url):
    req = Request(url.rstrip("/") + "/manifest.json", headers={"Cache-Control": "no-cache"})
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def due(root, repo, sha, event, schedule, *, get=api, read_live=live_manifest):
    live = live_commit(repo, get)
    if live and not ancestor(root, live, sha):
        print("A newer or divergent commit is already live.")
        return False
    if event == "workflow_dispatch" or site_changed(root, live, sha):
        return True
    if event != "schedule":
        return False
    daily = schedule == "17 5 * * *"
    site = config.load_site()
    if not daily and not (site.pdf_release_only or site.epub_release_only or site.film_release_only):
        return False
    manifest = read_live(get(f"repos/{repo}/pages")["html_url"])
    if daily:
        spec = lean.Lock.read_spec()
        if isinstance(spec, lean.BranchLock):
            deployed = manifest.get("trureturing") or {}
            if (deployed.get("repo"), deployed.get("branch"), deployed.get("commit")) != (
                    spec.repo, spec.branch, pin.branch_head(spec)):
                return True
    for enabled, key, assets in (
        (site.pdf_release_only, "release_pdf_digest", releases.pdf_assets),
        (site.epub_release_only, "release_epub_digest", releases.epub_assets),
        (site.film_release_only, "release_film_digest", releases.film_assets),
    ):
        if enabled and key in manifest and manifest[key] != releases.asset_digest(assets(repo)):
            return True
    return False


if __name__ == "__main__":
    selected = due(Path.cwd(), os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"],
                   os.environ["GITHUB_EVENT_NAME"], os.environ.get("PAGES_SCHEDULE", ""))
    print("Publication is due." if selected else "No Pages update is due.")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"publish={str(selected).lower()}\n")
