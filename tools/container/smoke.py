"""Exercise the image's binaries and browser without downloading anything."""

from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path
import subprocess
import tempfile


def run(*args: str, **kwargs) -> None:
    subprocess.run(args, check=True, **kwargs)


def main() -> None:
    import pypandoc
    import typst
    from kokoro_onnx import Kokoro

    root = Path(os.environ.get("TBOOK_TOOLCHAIN", "/opt/tbook"))
    run("mdbook", "--version")
    run("tectonic", "--version")
    run("java", "-version")
    run("ffmpeg", "-version", stdout=subprocess.DEVNULL)
    run("gh", "--version", stdout=subprocess.DEVNULL)
    assert importlib.metadata.version("epubcheck") == "5.3.0"
    assert pypandoc.get_pandoc_version()
    with tempfile.TemporaryDirectory(prefix="tbook-image-") as tmp:
        tmp = Path(tmp)
        source = tmp / "smoke.typ"
        beamer = tmp / "smoke.tex"
        beamer.write_text(r"\documentclass{beamer}\usepackage{amssymb,xurl,appendixnumberbeamer}\begin{document}\begin{frame}{Academic slides}Toolchain\end{frame}\end{document}")
        run("tectonic", "-X", "compile", "--only-cached", "--bundle",
            "https://relay.fullyjustified.net/default_bundle_v33.tar", str(beamer),
            env=dict(os.environ, SOURCE_DATE_EPOCH="946684800"))
        assert beamer.with_suffix(".pdf").read_bytes().startswith(b"%PDF")
        source.write_text('#set text(font: "Noto Sans CJK SC")\n容器构建 $x^2 + y^2 = 1$\n')
        pdf = typst.compile(str(source))
        assert pdf.startswith(b"%PDF"), "Typst did not produce a PDF"
        epub = tmp / "smoke.epub"
        pypandoc.convert_text("# Toolchain\n\nAn EPUB built in the container.", "epub3", format="md",
                             outputfile=str(epub), extra_args=["--metadata=title:Toolchain", "--metadata=lang:en"])
        run("epubcheck", str(epub))
    # Load the real voice model and synthesize a short clip; imports alone do not
    # catch a missing shared library, incompatible ONNX runtime, or corrupt model.
    model = root / "film/models"
    kokoro = Kokoro(str(model / "kokoro-v1.0.onnx"), str(model / "voices-v1.0.bin"))
    samples, rate = kokoro.create("A book.", voice="af_sarah", speed=1.0, lang="en-us")
    assert len(samples) > 0 and rate > 0
    run("node", "--input-type=module", "-e", """
        import { chromium } from 'playwright-chromium';
        import { createRequire } from 'node:module';
        const require = createRequire(import.meta.url);
        const version = require('./package.json').devDependencies['playwright-chromium'];
        if (version !== '1.56.1') throw new Error('Update the Docker base to match Playwright');
        const browser = await chromium.launch({ headless: true });
        const page = await browser.newPage();
        await page.setContent('<title>tbook</title><p>容器构建</p>');
        if (await page.title() !== 'tbook') throw new Error('Chromium failed');
        await browser.close();
    """, cwd=root)
    print("toolchain: PDF, EPUB, speech synthesis and Chromium passed")


if __name__ == "__main__":
    main()
