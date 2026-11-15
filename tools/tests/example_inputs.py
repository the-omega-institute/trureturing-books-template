"""Source-only example inputs for structure tests; browser/export tests capture real scenes."""
from pathlib import Path
import json
import shutil

from tbook import config, figure, model, paths


def prepare():
    directory = paths.ROOT / "books/example-monograph"
    if not (directory / "book.toml").is_file():
        return
    book = config.load_book(str(directory))
    changed, errors = figure.build(book)
    if errors:
        raise RuntimeError("; ".join(errors))
    # Structural tests need valid image files, not scene pixels. Reuse the fixture's
    # editorial poster; never create a provenance manifest for these placeholders.
    poster = next(directory.glob("films/*/poster.jpg"), None)
    registry = book.viz_dir / "visualizations.json"
    if not poster or not registry.is_file():
        return
    outputs = [book.viz_dir / v["thumbnail"] for v in json.loads(registry.read_text())["visualizations"]]
    for edition in book.editions:
        for doc in model.load_edition(edition).chapters:
            for env in doc.media:
                if env.kind == "viz" and env.attrs.get("preset"):
                    outputs.append(book.viz_dir / env.attrs.get("src") / f'fig-{env.attrs.get("preset")}.{edition.lang}.jpg')
    for output in outputs:
        if not output.is_file():
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(poster, output)
