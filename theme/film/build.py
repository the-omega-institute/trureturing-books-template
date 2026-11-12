"""Assemble <film dir>/out/index.html: the page every frame is captured from.

Usage: python3 theme/film/build.py <film dir> [--strict | --timeline-only]

The page inlines, in order: the palette and font stacks (theme/generated/tokens.mjs, sections
"film", "font", "semantic"), window.DATA (timeline, film and book metadata, Lean citations at
the pinned commit, in-frame strings, data/*.json), theme/film/engine.js, the film's scenes.js,
and the boot call. Fonts are @fontsource WOFF2 subsets copied to out/fonts/ (only the
unicode-range subsets the film's text needs) and referenced by relative URL, so the page is
served over local http (render.js, poster.js and shot.js start their own server).

A film with solid shots (film.json "solid": true) also gets out/solid/: the modelling core theme/viz/solid-core.js
and the pinned three.js of theme/viz/vendor/, which the page imports before it boots (DATA.solid); a film without
solid shots loads no three.js. The scripts film.json "scripts" lists (paths relative to the book, e.g. the model of
a visualization page) are inlined before scenes.js.

Timing calls in scenes.js whose literal phrase is not in the narration of their line (tbook.film.phrase_issues)
are warnings, and errors under --strict / FILM_STRICT=1.

The timeline is out/timeline.json from tts.py; without it (or when it no longer matches
script.json) a provisional timeline at a fixed speaking rate is used, unless --strict (or FILM_STRICT=1,
which the site build sets), which also refuses to fall back to system fonts.
Adapted from trureturing-film films/*/build.py (Apache-2.0, the-omega-institute).
"""

from __future__ import annotations

import bisect
import json
import os
import re
import shutil
import sys
from pathlib import Path

from common import ROOT, HERE, fail, film_dir_arg, load, out_dir, timeline, tfilm

TOKENS_MJS = ROOT / "theme" / "generated" / "tokens.mjs"
# (npm package under @fontsource, CSS family, weights): tools/tbook/film.py, which also checks the packages are
# present before a build renders, and keys the build on their versions in package-lock.json.
FONT_PLAN = tfilm.FONT_PLAN
font_package = tfilm.font_package
# Semantic roles (tokens "semantic", named by the screen palette) → the film palette's names.
SCREEN_TO_FILM = {"ok": "green", "warn": "red", "violet": "vio", "amber": "gold", "cyan": "cyan",
                  "magenta": "mag", "blue": "blue", "orange": "orange", "dim": "dim"}
FACE_RE = re.compile(r"@font-face\s*\{(?P<body>[^}]*)\}", re.S)


def film_tokens() -> dict:
    """{film, font, sem} from theme/generated/tokens.mjs (the generated, checked-in source of truth)."""
    try:
        text = TOKENS_MJS.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read {TOKENS_MJS}: {exc}; run ./tbook theme")
    m = re.search(r"export const TOKENS = (\{.*?\});\s*export default", text, re.S)
    if not m:
        fail(f"{TOKENS_MJS}: unexpected format (expected `export const TOKENS = {{…}};`); run ./tbook theme")
    tokens = json.loads(m.group(1))
    film, font, semantic = tokens.get("film"), tokens.get("font"), tokens.get("semantic", {})
    if not film or not font:
        fail(f"{TOKENS_MJS}: missing the 'film' or 'font' section")
    sem = {}
    for role in ("lean", "open", "argued", "now"):
        name = SCREEN_TO_FILM.get(semantic.get(role, ""), "")
        if name not in film:
            fail(f"tokens: semantic.{role} = {semantic.get(role)!r} has no film colour")
        sem[role] = film[name]
    return {"film": film, "font": font, "sem": sem}


def _ranges(spec: str) -> list[tuple[int, int]]:
    out = []
    for part in spec.split(","):
        part = part.strip().upper().removeprefix("U+")
        if not part:
            continue
        if "?" in part:
            lo, hi = int(part.replace("?", "0"), 16), int(part.replace("?", "F"), 16)
        elif "-" in part:
            a, b = part.split("-", 1)
            lo, hi = int(a, 16), int(b, 16)
        else:
            lo = hi = int(part, 16)
        out.append((lo, hi))
    return out


def font_faces(chars: set[int], out: Path, *, strict: bool = False) -> tuple[str, list[list]]:
    """@font-face CSS for the subsets covering ``chars``; copies the WOFF2 files to out/fonts/. A missing
    font package is a warning (system fonts stand in), or an error with ``strict`` (a render for the build)."""
    css: list[str] = []
    loaded: list[list] = []
    points = sorted(chars)

    def covers(spans: list[tuple[int, int]]) -> bool:
        for lo, hi in spans:
            k = bisect.bisect_left(points, lo)
            if k < len(points) and points[k] <= hi:
                return True
        return False

    fonts_out = out / "fonts"
    if fonts_out.exists():
        shutil.rmtree(fonts_out)
    missing = []
    for pkg, family, weights in FONT_PLAN:
        src = font_package(pkg)
        if src is None:
            missing.append(f"@fontsource/{pkg}")
            continue
        for w in weights:
            sheet = src / f"{w}.css"
            if not sheet.is_file():
                continue
            used = 0
            for m in FACE_RE.finditer(sheet.read_text(encoding="utf-8")):
                body = m.group("body")
                if "font-style: normal" not in body:
                    continue
                url = re.search(r"url\(\s*['\"]?\./files/([^'\")]+\.woff2)", body)
                if not url:
                    continue
                rng = re.search(r"unicode-range:\s*([^;]+);", body)
                spans = _ranges(rng.group(1)) if rng else [(0, 0x10FFFF)]
                if not covers(spans):
                    continue
                name = url.group(1)
                dst = fonts_out / pkg / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src / "files" / name, dst)
                urange = f"unicode-range:{rng.group(1).strip()};" if rng else ""
                css.append(f"@font-face{{font-family:'{family}';font-style:normal;font-weight:{w};font-display:block;"
                           f"src:url('fonts/{pkg}/{name}') format('woff2');{urange}}}")
                used += 1
            if used:
                loaded.append([family, w])
    if missing and strict:
        fail(f"fonts not found ({', '.join(missing)}); run `npm ci` or theme/film/setup.sh")
    if missing:
        print(f"film: warning: fonts not found ({', '.join(missing)}); run `npm ci` or theme/film/setup.sh. "
              "Falling back to system fonts.", file=sys.stderr)
    return "".join(css), loaded


def _safe_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _script(text: str, where: str) -> str:
    if re.search(r"</script", text, re.I):
        fail(f"{where} contains '</script'; split the string (e.g. '<' + '/script')")
    return text


def phrase_check(film, *, strict: bool, quiet: bool = False) -> None:
    """Report the literal timing phrases of scenes.js that script.json does not have; fail with ``strict``."""
    path = film.dir / "scenes.js"
    if not path.is_file():
        return
    found = tfilm.phrase_issues(path.read_text(encoding="utf-8"), film.script)
    if not quiet:
        for line, msg in found:
            print(f"{'error' if strict else 'warning'}: {tfilm.paths.rel(path)}:{line}: {msg}", file=sys.stderr)
    if found and strict:
        fail(f"{film.id}: {len(found)} timing phrase(s) of scenes.js are not in script.json (FILM_STRICT=1)")


def solid_assets(film, out: Path) -> dict | None:
    """Copy the modelling core and three.js to out/solid/ for a film with solid shots; remove them otherwise."""
    dst = out / "solid"
    if dst.exists():
        shutil.rmtree(dst)
    if not film.solid:
        return None
    if not tfilm.SOLID_CORE.is_file() or not (tfilm.SOLID_VENDOR / "three.module.min.js").is_file():
        fail(f"{film.id}: solid shots need {tfilm.paths.rel(tfilm.SOLID_CORE)} and the three.js of "
             f"{tfilm.paths.rel(tfilm.SOLID_VENDOR)}/")
    dst.mkdir(parents=True)
    shutil.copyfile(tfilm.SOLID_CORE, dst / "solid-core.js")
    shutil.copytree(tfilm.SOLID_VENDOR, dst / "vendor", ignore=shutil.ignore_patterns("*.md"))
    return {"core": "solid/solid-core.js"}


def build(film_dir: Path, *, strict: bool = False) -> Path:
    film = load(film_dir)
    issues = tfilm.check_film(film, tfilm._lock())
    for i in issues:
        print(i.format(), file=sys.stderr)
    if any(i.severity == "error" for i in issues):
        fail(f"{film.id}: fix the errors above first")
    phrase_check(film, strict=strict, quiet=True)  # check_film printed them as warnings
    out = out_dir(film_dir)
    tl, provisional = timeline(film, allow_provisional=not strict)
    if provisional:
        (out / "timeline.provisional.json").write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
    data = tfilm.engine_data(film)
    data["timeline"] = tl
    data["data"] = {}
    data_dir = film_dir / "data"
    if data_dir.is_dir():
        for p in sorted(data_dir.glob("*.json")):
            data["data"][p.stem] = json.loads(p.read_text(encoding="utf-8"))
    data["strict"] = strict
    solid = solid_assets(film, out)
    if solid:
        data["solid"] = solid
    tokens = film_tokens()
    engine = _script((HERE / "engine.js").read_text(encoding="utf-8"), "theme/film/engine.js")
    shared = "".join(f"<script>\n{_script(p.read_text(encoding='utf-8'), tfilm.paths.rel(p))}\n</script>\n"
                     for p in film.scripts)
    scenes = _script((film_dir / "scenes.js").read_text(encoding="utf-8"), f"{film.id}/scenes.js")
    corpus = engine + shared + scenes + json.dumps(data, ensure_ascii=False) + "".join(chr(c) for c in range(0x20, 0x7F))
    chars = {ord(ch) for ch in corpus if ord(ch) >= 0x20}
    faces, loaded = font_faces(chars, out, strict=strict)
    data["fonts"] = loaded
    data["fontText"] = "".join(sorted(chr(c) for c in chars))
    title = f"{film.title('en')} · {film.title('zh')}"
    bg = tokens["film"].get("bg", "#000")
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title.replace('<', '&lt;')}</title>
<meta name="generator" content="trureturing books · theme/film/build.py"><link rel="icon" href="data:,">
<style>{faces}
html,body{{margin:0;background:{bg};overflow:hidden}}canvas{{display:block;width:min(100vw,177.78vh);height:auto;margin:0 auto}}</style></head>
<body><canvas id="c" width="1920" height="1080"></canvas>
<script>window.FILM_ERRORS=[];addEventListener('error',e=>FILM_ERRORS.push(String(e.message)+' ('+(e.filename||'').split('/').pop()+':'+(e.lineno||0)+')'));</script>
<script>window.FILM_TOKENS={_safe_json(tokens)};window.DATA={_safe_json(data)};</script>
<script>
{engine}
</script>
{shared}<script>
{scenes}
</script>
<script>
window.ready = boot().then(() => {{
  const q = new URLSearchParams(location.search);
  if (q.has('poster')) poster();
  else if (q.has('play')) {{ const t0 = performance.now() - 1000 * (+q.get('play') || 0); const tick = () => {{ renderAt(((performance.now() - t0) / 1000) % DATA.timeline.duration); requestAnimationFrame(tick); }}; tick(); }}
  else renderAt(+(q.get('t') || 0));
  return true;
}}, e => {{ FILM_ERRORS.push('boot: ' + e); throw e; }});
</script>
</body></html>
"""
    page = out / "index.html"
    page.write_text(html, encoding="utf-8")
    kind = "provisional" if provisional else "narrated"
    print(f"film: wrote {page} ({len(html) // 1024} KB, {kind} timeline {tl['duration']:.1f}s, "
          f"{len(loaded)} font faces{', solid shots' if solid else ''})")
    return page


def write_provisional(film_dir: Path) -> Path:
    """out/timeline.provisional.json from script.json alone (preview timing before TTS)."""
    film = load(film_dir)
    if film.script is None:
        fail(f"{film.id}: script.json is unreadable")
    tl = tfilm.provisional_timeline(film.script)
    path = out_dir(film_dir) / "timeline.provisional.json"
    path.write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"film: wrote {path} ({tfilm.format_duration(tl['duration'])} at {tfilm.WORDS_PER_SECOND} words/s)")
    for s in tl["scenes"]:
        print(f"  {s['id']:12s} {s['start']:7.2f} {s['end']:7.2f} {s['end'] - s['start']:6.2f}")
    phrase_check(film, strict=os.environ.get("FILM_STRICT") == "1")
    return path


def main(argv: list[str]) -> int:
    film_dir = film_dir_arg([a for a in argv if not a.startswith("--")])
    if "--timeline-only" in argv:
        write_provisional(film_dir)
        return 0
    build(film_dir, strict="--strict" in argv or os.environ.get("FILM_STRICT") == "1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
