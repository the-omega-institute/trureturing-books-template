"""Decide whether a queued Pages run has publication inputs to build."""
import json
import os
import subprocess
import sys
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


def pages_configuration(repo, get=api):
    try:
        pages = get(f"repos/{repo}/pages")
    except subprocess.CalledProcessError as error:
        if "(HTTP 404)" not in (error.stderr or ""):
            raise
        return "", "GitHub Pages is disabled. Enable it in Settings → Pages → Source: GitHub Actions."
    if pages.get("build_type") != "workflow":
        return "", "Set Settings → Pages → Source: GitHub Actions to enable deployment."
    base_url = pages["html_url"].rstrip("/")
    if not base_url or len(base_url.splitlines()) != 1 or base_url != base_url.strip():
        raise ValueError("GitHub returned an invalid Pages URL")
    return base_url, ""


def probe():
    base_url, message = pages_configuration(os.environ["GITHUB_REPOSITORY"])
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        print(f"enabled={str(bool(base_url)).lower()}", file=output)
        print(f"base_url={base_url}", file=output)
    if base_url:
        print("GitHub Pages is enabled with source: GitHub Actions.")
    else:
        print(f"::warning title=GitHub Pages not deployed::{message}")
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            print(f"### GitHub Pages not deployed\n\n{message}\n\nThe workflow still builds the site.", file=summary)


def schedule():
    selected = due(Path.cwd(), os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"],
                   os.environ["GITHUB_EVENT_NAME"], os.environ.get("PAGES_SCHEDULE", ""))
    print("Publication is due." if selected else "No Pages update is due.")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"publish={str(selected).lower()}\n")


if __name__ == "__main__":
    if sys.argv[1:] == ["--probe"]:
        probe()
    else:
        schedule()
