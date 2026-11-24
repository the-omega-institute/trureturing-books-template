"""Book statistics from the publication parser; consumers never count Markdown with regexes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
import json
from pathlib import Path

from . import config, lean, model, paths, render

AXIOM_STATUSES = ("free", "depends", "unknown")


def lean_axiom_counts(envs: Iterable[model.Env], lock: lean.Lock | None) -> dict[str, int]:
    counts = Counter(render.env_axiom_status(env, lock) for env in envs)
    return {status: counts[status] for status in AXIOM_STATUSES}


def collect(book: config.Book, *, exclude: tuple[str, ...] | None = None, lock=None) -> dict:
    """Count the authoritative edition. Exclude index citations, retaining its authored environments.

    Environment occurrences, distinct declarations and cross-chapter reuse are different
    quantities. Declarations are scoped to this book; an unrelated book in the shared lock
    never inflates its totals. Source locations remain available for index generators.
    """
    lock = lean.Lock.load() if lock is None else lock
    if exclude is None:
        exclude = tuple(book.raw.get("statistics", {}).get("exclude", []))
    edition = book.editions[0]
    templates = book.raw.get("statistics", {}).get("templates", {})
    sources = {name: book.dir / template.format(lang=edition.lang) for name, template in templates.items()}
    ed = model.load_edition(edition, sources=sources)
    errors = [i.format() for i in ed.issues if i.severity == "error"]
    if errors:
        raise config.ConfigError("\n".join(errors))
    declarations: dict[str, dict] = {}
    counts = Counter()
    axiom_counts = lean_axiom_counts(ed.formal_envs(), lock)
    chapters = []

    def cite(gid, where):
        resolved = lock.get(gid) if lock else None
        if resolved is None:
            raise config.ConfigError(f"statistics: {gid} is missing from trureturing.lock.json")
        entry = declarations.setdefault(gid, {"kind": resolved.kind, "name": resolved.name,
                                              "source": lock.source_url(gid), "citations": []})
        if where not in entry["citations"]:
            entry["citations"].append(where)

    for doc in ed.chapters:
        file = doc.chapter.path
        env_gids, inline_gids = set(), set()
        lines = doc.text.splitlines()
        for env in doc.envs + doc.media:
            if env in doc.envs:
                counts[env.kind] += 1
                if env.status == model.WRITTEN_PROOF:
                    counts["written_proof"] += 1
                opening = " ".join(lines[env.line - 1:env.line + 1]).lower()
                if env.kind in model.INFORMAL and ("文献结果" in opening or "literature result" in opening):
                    counts["literature"] += 1
            if file in exclude:
                continue
            for gid in env.lean:
                env_gids.add(gid)
                cite(gid, {"file": file, "line": env.line, "id": env.id, "via": "environment"})
        if file in exclude:
            continue
        for line, gid in doc.lean_links:
            inline_gids.add(gid)
            cite(gid, {"file": file, "line": line, "id": "", "via": "inline"})
        chapters.append({"file": file, "top": doc.chapter.top, "part": doc.chapter.part,
                         "number": doc.chapter.number_label, "depth": doc.chapter.depth,
                         "environment": sorted(env_gids), "inline": sorted(inline_gids)})
    for file, line, gid in model.media_cited_gids(book):
        cite(gid, {"file": file.relative_to(book.dir).as_posix(), "line": line,
                   "id": "", "via": "media"})
    kinds = Counter(d["kind"] for d in declarations.values())
    groups = {"theorems": [], "definitions": [], "inline": []}
    for gid, d in sorted(declarations.items()):
        env = any(c["via"] == "environment" for c in d["citations"])
        group = ("theorems" if d["kind"] == "theorem" else "definitions") if env else "inline"
        groups[group].append(gid)
    counts["lean_verified"] = sum(axiom_counts.values())
    return {"schema": "tbook.statistics.v1", "book": book.slug, "lang": ed.lang,
            "lean_axioms": axiom_counts,
            "environments": {k: counts[k] for k in (*model.ENV_KINDS, "lean_verified", "written_proof", "literature")},
            "total": len(declarations), "kinds": dict(sorted(kinds.items())),
            "groups": groups, "declarations": dict(sorted(declarations.items())), "chapters": chapters}


def write_artifact(data: dict) -> Path:
    """Export a snapshot under the ignored build directory, without modifying book sources."""
    target = paths.BUILD / "statistics" / f"{data['book']}.json"
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file() or target.read_text(encoding="utf-8") != content:
        target.write_text(content, encoding="utf-8")
    return target


VIEWS = ("summary", "evidence", "environments", "kinds", "chapters", "pages", "declarations", "reuse")
FORMATS = ("json", "markdown", "csv", "html")
GROUPS = ("all", "theorems", "definitions", "inline")


def options(attrs) -> tuple[str, str, str, str]:
    keys = getattr(attrs, "kv", attrs)
    unknown = set(keys) - {"src", "display", "group", "format", "title"}
    if unknown:
        raise config.ConfigError("stats: unsupported attributes: " + ", ".join(sorted(unknown)))
    view = attrs.get("src") or "summary"
    display = attrs.get("display") or "embed"
    group = attrs.get("group") or "all"
    fmt = attrs.get("format") or ("html" if display == "link" else "markdown")
    if view not in VIEWS:
        raise config.ConfigError(f"stats: unknown view {view!r}; choose {', '.join(VIEWS)}")
    if display not in ("embed", "link"):
        raise config.ConfigError('stats: display must be "embed" or "link"')
    if group not in GROUPS or (group != "all" and view not in ("declarations", "reuse")):
        raise config.ConfigError('stats: group is all, theorems, definitions or inline; filtering requires declarations or reuse')
    if fmt not in FORMATS or (display == "embed" and fmt != "markdown"):
        raise config.ConfigError('stats: embedded tables use markdown; links support json, markdown, csv or html')
    return view, display, group, fmt


def check_ref(book, src: str) -> str | None:
    return None if src in VIEWS else f"stats: unknown view {src!r}; choose {', '.join(VIEWS)}"


def check_options(attrs) -> str | None:
    try:
        options(attrs)
    except config.ConfigError as exc:
        return str(exc)
    return None


def check(book) -> list:
    return []  # References are checked without generating or parsing their output.


def table(data: dict, view: str, lang: str, group: str = "all") -> tuple[list[str], list[list]]:
    """Plain cells shared by every format; generated tables never feed citation counts back in."""
    options({"src": view, "group": group})
    s = lambda key: config.s(lang, "stats." + key)
    counts = data["environments"]
    axiom_counts = data.get("lean_axioms")
    axiom_rows = ([[config.s(lang, "frozen." + status), axiom_counts[status]] for status in AXIOM_STATUSES]
                  if axiom_counts is not None else [])
    evidence_rows = [[s("verified"), counts["lean_verified"]],
                     *axiom_rows,
                     [s("written"), counts["written_proof"]],
                     [s("open"), counts["conjecture"] + counts["problem"]],
                     [s("definitions"), counts["definition"]]]
    if view == "summary":
        return [s("metric"), s("count")], [[s("distinct"), data["total"]], *evidence_rows]
    if view == "evidence":
        return [s("metric"), s("count")], evidence_rows
    if view == "environments":
        return [s("environment"), s("occurrences")], [[config.s(lang, "env." + k), counts[k]] for k in model.ENV_KINDS]
    if view == "kinds":
        return [s("kind"), s("distinct")], [[kind, n] for kind, n in data["kinds"].items()]
    if view in ("chapters", "pages"):
        groups = {}
        for ch in data["chapters"]:
            key = ch["top"] if view == "chapters" else ch["file"]
            row = groups.setdefault(key, {"file": ch["file"], "pages": 0, "environment": set(), "inline": set()})
            row["pages"] += 1
            row["environment"].update(ch["environment"])
            row["inline"].update(ch["inline"])
        return [s("chapter") if view == "chapters" else s("page"), s("source_pages"), s("distinct"), s("env_decls"), s("inline_decls")], [
            [r["file"], r["pages"], len(r["environment"] | r["inline"]), len(r["environment"]), len(r["inline"])]
            for r in groups.values()]
    gids = sorted(data["declarations"] if group == "all" else data["groups"][group])
    def uses(gid):
        citations = data["declarations"][gid]["citations"]
        return len({c["file"] for c in citations}), len(citations)
    if view == "reuse":
        gids.sort(key=lambda gid: (-uses(gid)[0], -uses(gid)[1], gid))
        return ["GID", s("source_files"), s("citations")], [[gid, *uses(gid)] for gid in gids]
    return ["GID", s("kind"), s("citations")], [
        [gid, data["declarations"][gid]["kind"], uses(gid)[1]] for gid in gids]


def artifact_name(view: str, lang: str, fmt: str, group: str = "all") -> str:
    import re
    if not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", lang):
        raise config.ConfigError(f"stats: invalid language {lang!r}")
    options({"src": view, "group": group, "display": "link", "format": fmt})
    suffix = "md" if fmt == "markdown" else fmt
    part = "" if group == "all" else "." + group
    return f"{view}{part}.{lang}.{suffix}"


def artifact_content(data: dict, view: str, lang: str, fmt: str, group: str = "all") -> str:
    import csv
    import html
    import io
    columns, rows = table(data, view, lang, group)
    if fmt == "json":
        return json.dumps({"schema": "tbook.statistics.table.v1", "book": data["book"],
                           "authoritative_lang": data["lang"], "lang": lang, "view": view, "group": group,
                           "columns": columns, "rows": rows}, ensure_ascii=False, indent=2) + "\n"
    if fmt == "csv":
        out = io.StringIO(newline="")
        writer = csv.writer(out, lineterminator="\n")
        writer.writerows([columns, *rows])
        return out.getvalue()
    if fmt == "html":
        esc = lambda value: html.escape(str(value), quote=True)
        title = config.s(lang, "stats." + view)
        head = "".join(f'<th scope="col">{esc(c)}</th>' for c in columns)
        def cell(value, column):
            source = data["declarations"].get(str(value), {}).get("source", "") if column == 0 and view in ("declarations", "reuse") else ""
            return f'<a href="{esc(source)}">{esc(value)}</a>' if source else esc(value)
        body = "".join("<tr>" + "".join(f"<td>{cell(c, i)}</td>" for i, c in enumerate(row)) + "</tr>" for row in rows)
        return (f'<!doctype html>\n<html lang="{esc(lang)}"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                f'<title>{esc(title)}</title><style>body{{font-family:system-ui,sans-serif;max-width:80rem;'
                'margin:2rem auto;padding:0 1rem}table{border-collapse:collapse}th,td{padding:.5rem;'
                'border:1px solid currentColor;text-align:start;overflow-wrap:anywhere}</style>'
                f'<h1>{esc(title)}</h1><p>{esc(config.s(lang, "stats.scope"))}</p>'
                f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></html>\n')
    if fmt != "markdown":
        raise config.ConfigError(f"stats: unknown format {fmt!r}")
    from .ledger import _cell
    line = lambda row: "| " + " | ".join(_cell(str(c)) for c in row) + " |"
    if view in ("declarations", "reuse"):
        from . import mdscan
        rows = [[f'[{mdscan.escape_markdown(row[0])}](<{data["declarations"][row[0]]["source"]}>)', *row[1:]]
                if data["declarations"][row[0]].get("source") else row for row in rows]
    return "\n".join([line(columns), line(["---"] * len(columns)), *(line(row) for row in rows)]) + "\n"


def export(data: dict, view: str, lang: str, fmt: str, group: str = "all") -> Path:
    target = paths.BUILD / "statistics" / data["book"] / artifact_name(view, lang, fmt, group)
    content = artifact_content(data, view, lang, fmt, group)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file() or target.read_text(encoding="utf-8") != content:
        target.write_text(content, encoding="utf-8")
    return target


def render_embed(env, ctx, inner: str, doc) -> str:
    import html
    import posixpath
    view, display, group, fmt = options(env.attrs)
    if ctx.statistics_data is None:
        ctx.statistics_data = collect(ctx.book, lock=ctx.lock)
    data = ctx.statistics_data
    # Stage only the requested view. Nothing is written back to a book's source directory.
    content = artifact_content(data, view, ctx.lang, fmt, group)
    name = artifact_name(view, ctx.lang, fmt, group)
    # mdBook rewrites .md links as chapter links; a Markdown download remains a plain-text asset.
    if fmt == "markdown" and display == "link":
        name += ".txt"
    ctx.book_texts["statistics/" + name] = content
    caption = inner.strip() or env.title
    if display == "link":
        rel = posixpath.relpath(ctx.book_prefix + "/statistics/" + name,
                               posixpath.dirname(doc.chapter.path) or ".")
        return f'[{caption or config.s(ctx.lang, "stats." + view)}]({rel})'
    note = config.s(ctx.lang, "stats.scope")
    body = content.rstrip() + "\n\n" + note
    if caption:
        body += "\n\n" + caption
    if ctx.target == "mdbook":
        ident = f' id="{html.escape(env.id, quote=True)}"' if env.id else ""
        return f'<div class="tr-stats"{ident}>\n\n{body}\n\n</div>'
    ident = f" #{env.id}" if env.id else ""
    return f'::: {{.tr-stats{ident}}}\n{body}\n:::'
