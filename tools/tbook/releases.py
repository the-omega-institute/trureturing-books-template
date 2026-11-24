"""Published GitHub Release assets used by the download pages."""

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class ReleaseAsset:
    url: str
    size: int


@lru_cache(maxsize=1)
def _published(repo: str) -> list[dict]:
    if not repo:
        return []
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError(f"invalid GitHub repository: {repo!r}")
    data = subprocess.check_output(
        ["gh", "api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100"],
        text=True, timeout=90,
    )
    return sorted(
        (release for page in json.loads(data) for release in page
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
def film_assets(repo: str) -> dict[str, ReleaseAsset]:
    return _assets(repo, ".mp4", previews=True)


def asset_digest(assets: dict[str, ReleaseAsset]) -> str:
    entries = sorted((name, asset.url, asset.size) for name, asset in assets.items())
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


pdf_digest = asset_digest
