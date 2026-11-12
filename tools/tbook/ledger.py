"""The generated "verification ledger" chapter appended to every edition.

It lists Lean-backed formal environments with their declaration(s), linked at the
pinned commit, then written proofs with book proof links and explicitly open items. The output is plain Markdown
(pipe tables), rendered by every target.

The ledger never claims more than the lock backs: a declaration the lock does not resolve
is shown as plain text (no link), and an item whose declarations do not all resolve to Lean
theorems is marked UNVERIFIED in the state column (``./tbook check`` rejects such a book).
"""

from __future__ import annotations

import re
from typing import Callable

from . import config, lean, render
from .model import FORMAL, OPEN, EditionModel, Env

LEDGER_FILE = "verification-ledger.md"
LEDGER_ID = "tr-verification-ledger"


_MATH_RE = re.compile(r"(\$\$?)(.+?)\1", re.S)


def _cell(text: str) -> str:
    """Make ``text`` safe inside a pipe-table cell.

    Outside math a ``|`` is escaped; inside ``$…$`` it becomes ``\\vert`` so that Pandoc
    (which keeps ``\\|`` in math as the norm symbol) and mdBook render the same thing.
    """
    text = text.replace("\n", " ")
    out, pos = [], 0
    for m in _MATH_RE.finditer(text):
        out.append(text[pos:m.start()].replace("|", "\\|"))
        out.append(m.group(1) + m.group(2).replace("\\|", "\\Vert ").replace("|", "\\vert ") + m.group(1))
        pos = m.end()
    out.append(text[pos:].replace("|", "\\|"))
    return "".join(out)


def ledger_markdown(model: EditionModel, lock: lean.Lock | None,
                    href: Callable[[Env], str] | None = None) -> str:
    """``href(env)`` links an item to its environment (default ``#id``, right for Pandoc)."""
    href = href or (lambda env: "#" + env.id)
    link = lambda target, text: f"[{text}]({href(target)})" if target.id else text  # noqa: E731  [@id] in titles
    lang = model.lang
    s = lambda key: config.s(lang, key)  # noqa: E731
    out = [f"# {s('ledger.title')} {{#{LEDGER_ID} .unnumbered}}", "", s("ledger.intro"), ""]
    if lock:
        out += [f"{s('ui.pinned_at')} [`{lock.commit[:12]}`]({lock.tree_url}) · `{lock.repo}`", ""]
    formal = [e for e in model.all_envs() if e.kind in FORMAL and e.status != "written-proof"]
    unverified = s("badge.unverified") or s("slides.badge_unverified") or "UNVERIFIED"
    if formal:
        out += [f"| {s('ledger.col_item')} | {s('ledger.col_title')} | {s('ledger.col_decl')} | {s('ledger.col_state')} |",
                "| --- | --- | --- | --- |"]
        for env in formal:
            decls = []
            states = []
            verified = bool(env.lean)
            for gid in env.lean:
                res = lock.get(gid) if lock else None
                name = res.name if res else gid
                url = lock.source_url(gid) if lock and res else ""
                decls.append(f"[`{_cell(name)}`]({url})" if url else f"`{_cell(name)}`")
                if lock and res and res.kind in lean.FORMAL_KINDS:
                    sid = res.statement_id.split(":", 1)[-1][:10] if res.statement_id else "state"
                    states.append(f"[`{sid}`]({lock.state_url(gid)})")
                else:
                    verified = False
            if not verified:
                states = [f"**{_cell(unverified)}**"]
            item = f"[{env.ref_text(lang)}]({href(env)})" if env.id else env.ref_text(lang)
            title = _cell(model.title_markdown(env, link))
            out.append(f"| {item} | {title or '—'} | {' · '.join(decls)} | {' '.join(states) or '—'} |")
        out.append("")
    else:
        out += [s("ledger.none"), ""]
    written = [e for e in model.all_envs() if e.status == "written-proof"]
    out += [f"## {s('ledger.written_title')} {{.unnumbered}}", "", s("ledger.written_intro"), ""]
    for env in written:
        proof = model.envs.get(env.attrs.get("proof"))
        proof_link = f" · [{s('env.proof')}]({href(proof)})" if proof and proof.kind == "proof" else ""
        title = f" — {model.title_markdown(env, link)}" if env.title else ""
        out.append(f"- [{env.ref_text(lang)}]({href(env)}){title}{proof_link} · {render.source_markdown(env)}")
    if not written:
        out.append(s("ledger.none"))
    out.append("")
    open_items = [e for e in model.all_envs() if e.kind in OPEN]
    out += [f"## {s('ledger.open_title')} {{.unnumbered}}", "", s("ledger.open_intro"), ""]
    if open_items:
        for env in open_items:
            title = f" — {model.title_markdown(env, link)}" if env.title else ""
            out.append(f"- [{env.ref_text(lang)}]({href(env)}){title}")
    else:
        out.append(s("ledger.none"))
    out.append("")
    return "\n".join(out)
