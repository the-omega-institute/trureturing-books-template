"""Published GitHub Release assets used by the download pages."""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .github import rate_limited, read_json


@dataclass(frozen=True)
class ReleaseAsset:
    url: str
    size: int


FRESH_FOR = 300
STALE_FOR = 24 * 60 * 60


def _read_snapshot(snapshot: Path) -> tuple[float, list] | None:
    try:
        data = json.loads(snapshot.read_text(encoding="utf-8"))
        age = time.time() - data["fetched_at"]
        pages = data["pages"]
        if 0 <= age <= STALE_FOR and isinstance(pages, list) and all(isinstance(page, list) for page in pages):
            return age, pages
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None


def _save_snapshot(snapshot: Path, pages: list) -> None:
    temporary = None
    try:
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=snapshot.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump({"fetched_at": time.time(), "pages": pages}, output)
        temporary.replace(snapshot)
    except OSError as error:
        print(f"Could not save the Release catalog: {error}", file=sys.stderr)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _release_pages(repo: str) -> list:
    endpoint = f"repos/{repo}/releases?per_page=100"
    directory = os.environ.get("TBOOK_RELEASE_CACHE")
    if not directory:
        return read_json(endpoint, paginate=True, timeout=90)
    key = hashlib.sha256(repo.lower().encode()).hexdigest()
    snapshot = Path(directory) / f"{key}.json"
    cached = _read_snapshot(snapshot)
    if cached is not None and cached[0] <= FRESH_FOR:
        return cached[1]
    try:
        pages = read_json(endpoint, paginate=True, timeout=90)
    except subprocess.CalledProcessError as error:
        if cached is None or not rate_limited(error.stderr or ""):
            raise
        print(f"GitHub rate limit for {repo}. Using the last successful Release catalog.", file=sys.stderr)
        return cached[1]
    _save_snapshot(snapshot, pages)
    return pages


@lru_cache(maxsize=1)
def _published(repo: str) -> list[dict]:
    if not repo:
        return []
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError(f"invalid GitHub repository: {repo!r}")
    pages = _release_pages(repo)
    return sorted(
        (release for page in pages for release in page
         if not release["draft"] and release["published_at"]),
        key=lambda release: release["published_at"], reverse=True,
    )


def _assets(repo: str, suffix: str, *, previews: bool) -> dict[str, ReleaseAsset]:
    assets = {}
    for release in _published(repo):
        if not previews and re.fullmatch(r"preview-(?:dev-)?[0-9a-f]{40}", release["tag_name"]):
            continue
        for asset in release["assets"]:
            if (asset["state"] == "uploaded" and asset["name"].endswith(suffix)
                    and asset["browser_download_url"].startswith("https://")):
                assets.setdefault(asset["name"], ReleaseAsset(asset["browser_download_url"], asset["size"]))
    return assets


PdfAsset = ReleaseAsset


@lru_cache(maxsize=1)
def pdf_assets(repo: str) -> dict[str, ReleaseAsset]:
    return _assets(repo, ".pdf", previews=False)


@lru_cache(maxsize=1)
def epub_assets(repo: str) -> dict[str, ReleaseAsset]:
    return _assets(repo, ".epub", previews=False)


@lru_cache(maxsize=1)
def film_assets(repo: str) -> dict[str, ReleaseAsset]:
    return _assets(repo, ".mp4", previews=True)


def asset_digest(assets: dict[str, ReleaseAsset]) -> str:
    entries = sorted((name, asset.url, asset.size) for name, asset in assets.items())
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


pdf_digest = asset_digest
