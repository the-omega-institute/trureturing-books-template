"""Connect a checkout to the image's dependencies, after verifying its inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

INPUTS = (
    "requirements.txt", "package.json", "package-lock.json",
    "theme/film/requirements.txt", "theme/film/setup.sh",
    "tools/fetch-fonts.sh", "theme/typst/fonts.sha256",
    "tools/install-tectonic.sh",
)


# Both the image contents and the workflow that certified its digest identify a release input set.
IMAGE_INPUTS = (*INPUTS, "tools/container", ".dockerignore", ".github/workflows/toolchain-image.yml")


def image_key(root: Path) -> str:
    entries = subprocess.check_output(["git", "ls-tree", "-rz", "HEAD", "--", *IMAGE_INPUTS], cwd=root)
    return hashlib.sha256(entries).hexdigest()


def image_source(root: Path) -> str:
    return subprocess.check_output(
        ["git", "log", "--first-parent", "-1", "--format=%H", "HEAD", "--", *IMAGE_INPUTS],
        cwd=root, text=True).strip()


def fingerprints(root: Path) -> dict[str, str]:
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in INPUTS}


def prepare(root: Path, toolchain: Path) -> None:
    expected = json.loads((toolchain / "inputs.json").read_text(encoding="utf-8"))
    actual = fingerprints(root)
    changed = [name for name in INPUTS if actual[name] != expected.get(name)]
    if changed:
        raise ValueError("Toolchain image does not match this checkout: " + ", ".join(changed)
                         + ". Rebuild the image from this checkout (docs/CONTAINERS.md).")
    # An existing dependency directory may belong to the host or a previous run.
    # Refuse to replace it silently; a fresh checkout is the normal CI case.
    links = []
    for relative, source in (("node_modules", "node_modules"), (".cache/fonts", ".cache/fonts")):
        dest, target = root / relative, toolchain / source
        if not target.is_dir():
            raise ValueError(f"Toolchain dependency directory is missing: {target}")
        if dest.is_symlink() and dest.resolve() == target.resolve():
            continue
        if dest.exists() or dest.is_symlink():
            raise ValueError(f"{dest} already exists; use a clean checkout or move it aside.")
        links.append((dest, target))
    for dest, target in links:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.symlink_to(target, target_is_directory=True)
    print("toolchain: using the image's verified packages, fonts, browsers and film models")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-source", action="store_true", help="find the commit that supplied the image inputs")
    parser.add_argument("--image-key", action="store_true", help="identify the tracked image and validation inputs")
    parser.add_argument("--record", action="store_true", help="record image inputs at build time")
    parser.add_argument("--toolchain", type=Path, default=Path("/opt/tbook"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    if args.image_source:
        print(image_source(args.root))
        return
    if args.image_key:
        print(image_key(args.root))
        return
    if args.record:
        (args.toolchain / "inputs.json").write_text(
            json.dumps(fingerprints(args.toolchain), indent=2) + "\n", encoding="utf-8")
        return
    try:
        prepare(args.root.resolve(), args.toolchain.resolve())
    except (ValueError, OSError) as exc:
        parser.exit(1, f"toolchain: {exc}\n")


if __name__ == "__main__":
    main()
