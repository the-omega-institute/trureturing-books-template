"""Published GitHub Release assets used by the download pages."""

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class PdfAsset:
    url: str
    size: int


@lru_cache(maxsize=1)
def pdf_assets(repo: str) -> dict[str, PdfAsset]:
    """Index uploaded PDFs by filename, preferring the most recently published copy."""
    if not repo:
        return {}
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError(f"invalid GitHub repository: {repo!r}")
    data = subprocess.check_output(
        ["gh", "api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100"],
        text=True, timeout=90,
    )
    published = sorted(
        (release for page in json.loads(data) for release in page
         if not release["draft"] and release["published_at"]),
        key=lambda release: release["published_at"], reverse=True,
    )
    assets = {}
    for release in published:
        for asset in release["assets"]:
            if (asset["state"] == "uploaded" and asset["name"].endswith(".pdf")
                    and asset["browser_download_url"].startswith("https://")):
                assets.setdefault(asset["name"], PdfAsset(asset["browser_download_url"], asset["size"]))
    return assets


def pdf_digest(assets: dict[str, PdfAsset]) -> str:
    entries = sorted((name, asset.url, asset.size) for name, asset in assets.items())
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()
