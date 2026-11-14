"""Book statistics from the publication parser; consumers never count Markdown with regexes."""

from __future__ import annotations

from collections import Counter

from . import config, lean, model, render


def collect(book: config.Book, *, exclude: tuple[str, ...] | None = None, lock=None) -> dict:
    """Count the authoritative edition. Exclude generated indexes to avoid self-citations.

    Environment occurrences, distinct declarations and cross-chapter reuse are different
    quantities. Declarations are scoped to this book; an unrelated book in the shared lock
    never inflates its totals. Source locations remain available for index generators.
    """
    lock = lean.Lock.load() if lock is None else lock
    if exclude is None:
        exclude = tuple(book.raw.get("statistics", {}).get("exclude", []))
    ed = model.load_edition(book.editions[0])
    errors = [i.format() for i in ed.issues if i.severity == "error"]
    if errors:
        raise config.ConfigError("\n".join(errors))
    declarations: dict[str, dict] = {}
    counts = Counter()
    chapters = []

    def cite(gid, where):
        resolved = lock.get(gid) if lock else None
        if resolved is None:
            raise config.ConfigError(f"statistics: {gid} is missing from trureturing.lock.json")
        entry = declarations.setdefault(gid, {"kind": resolved.kind, "name": resolved.name,
                                              "citations": []})
        if where not in entry["citations"]:
            entry["citations"].append(where)

    for doc in ed.chapters:
        file = doc.chapter.path
        if file in exclude:
            continue
        env_gids, inline_gids = set(), set()
        lines = doc.text.splitlines()
        for env in doc.envs + doc.media:
            if env in doc.envs:
                counts[env.kind] += 1
                if render.env_verified(env, lock):
                    counts["lean_verified"] += 1
                if env.status == model.WRITTEN_PROOF:
                    counts["written_proof"] += 1
                opening = " ".join(lines[env.line - 1:env.line + 1]).lower()
                if env.kind in model.INFORMAL and ("文献结果" in opening or "literature result" in opening):
                    counts["literature"] += 1
            for gid in env.lean:
                env_gids.add(gid)
                cite(gid, {"file": file, "line": env.line, "id": env.id, "via": "environment"})
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
    return {"schema": "tbook.statistics.v1", "book": book.slug, "lang": ed.lang,
            "environments": {k: counts[k] for k in (*model.ENV_KINDS, "lean_verified", "written_proof", "literature")},
            "total": len(declarations), "kinds": dict(sorted(kinds.items())),
            "groups": groups, "declarations": dict(sorted(declarations.items())), "chapters": chapters}
