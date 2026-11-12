"""Academic Beamer decks. Literal TeX citations; metadata always comes from the book and lock.

The deliberately bounded source contract does not expand TeX macros. It reads balanced
arguments, comments and verbatim, and rejects source imports and computed identifiers
rather than silently missing their citations. See theme/beamer/README.md.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from . import config, evidence, figure, lean, model, paths, viz

ENGINE_VERSION = "0.16.9"
BUNDLE = "https://relay.fullyjustified.net/default_bundle_v33.tar"
EPOCH = "946684800"  # 2000-01-01 UTC; never the current clock
ID = re.compile(r"[A-Za-z][A-Za-z0-9:_-]*\Z")
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def is_academic(directory: Path) -> bool:
    # A descriptor opts into this path, including malformed descriptors (check reports them).
    return (directory / "deck.toml").is_file()


def settings(book, deck: str) -> dict:
    directory = book.slides_dir / deck
    if not NAME.fullmatch(deck):
        raise ValueError("academic deck name must be kebab-case")
    try:
        data = tomllib.loads((directory / "deck.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{directory / 'deck.toml'}: {exc}") from exc
    allowed = {"kind", "editions", "aspect", "structure_colour", "theme_dir", "theme_name",
               "institution_graphic", "institution", "coauthors", "date", "navigation_symbols",
               "short_author", "short_title", "title"}
    if set(data) - allowed:
        raise ValueError(f"deck.toml: unknown keys: {', '.join(sorted(set(data) - allowed))}")
    if data.get("kind") != "academic":
        raise ValueError('deck.toml: kind must be "academic" (Slidev decks need no descriptor)')
    editions = data.get("editions", book.languages)
    if not isinstance(editions, list) or not editions or any(not isinstance(x, str) or x not in book.languages for x in editions):
        raise ValueError("deck.toml: editions must be a nonempty subset of the book's editions")
    if len(set(editions)) != len(editions):
        raise ValueError("deck.toml: editions must not repeat")
    data["editions"] = editions
    data.setdefault("aspect", "4:3")
    if data["aspect"] not in ("4:3", "16:9"):
        raise ValueError('deck.toml: aspect must be "4:3" or "16:9"')
    data.setdefault("structure_colour", "#0e2c8e")
    if not isinstance(data["structure_colour"], str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", data["structure_colour"]):
        raise ValueError("deck.toml: structure_colour must be #RRGGBB")
    for key in ("theme_dir", "theme_name", "institution_graphic", "institution", "coauthors", "date", "short_author", "short_title"):
        if key in data and (not isinstance(data[key], str) or not data[key].strip()):
            raise ValueError(f"deck.toml: {key} must be a nonempty string")
    if not isinstance(data.get("navigation_symbols", False), bool):
        raise ValueError("deck.toml: navigation_symbols must be a boolean")
    if not isinstance(data.get("title", {}), dict) or any(not isinstance(v, str) for v in data.get("title", {}).values()):
        raise ValueError("deck.toml: title must be a table of edition titles")
    if data.get("theme_name") and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", data["theme_name"]):
        raise ValueError("deck.toml: theme_name must be a literal Beamer theme name")
    if data.get("theme_dir"):
        theme = (directory / data["theme_dir"]).resolve()
        name = data.get("theme_name", "LinZhang")
        if not (theme / f"beamertheme{name}.sty").is_file():
            raise ValueError(f"theme_dir: no beamertheme{name}.sty in {theme}")
    if data.get("institution_graphic") and not (directory / data["institution_graphic"]).is_file():
        raise ValueError("institution_graphic: file does not exist")
    return data


def edition_file(data: dict, lang: str) -> str:
    return "slides.tex" if lang == data["editions"][0] else f"slides.{lang}.tex"


@dataclass
class Command:
    name: str
    args: list[str]
    options: list[str]
    line: int
    depth: int


def commands(text: str) -> list[Command]:
    """Lex literal TeX, preserving source lines. Never match inside comments or verbatim.

    Escaped percent/braces, nested groups, [] containing groups, \u005cverb* delimiters,
    frame overlays and frame optional arguments are consumed as TeX tokens.
    """
    # TeX removes the comment's newline, too; preserve offsets for diagnostics.
    chars = list(text)
    i = 0
    while i < len(chars):
        literal = re.match(r"\\(?:verb\*?|lstinline)\s*([^A-Za-z\s])", text[i:]) if chars[i] == "\\" else None
        environment = re.match(r"\\begin\s*\{(verbatim\*?|Verbatim|lstlisting|minted|comment)\}", text[i:]) if chars[i] == "\\" else None
        if literal:
            end = text.find(literal[1], i + len(literal[0]))
            if end < 0:
                raise ValueError("unterminated verbatim command")
            i = end + 1
        elif environment:
            end = re.search(r"\\end\s*\{" + re.escape(environment[1]) + r"\}", text[i + len(environment[0]):])
            if not end:
                raise ValueError(f"unclosed {environment[1]} environment")
            i += len(environment[0]) + end.end()
        elif chars[i] == "\\":
            i += 2
        elif chars[i] == "%":
            end = text.find("\n", i)
            end = len(text) if end < 0 else end + 1
            chars[i:end] = " " * (end - i)
            i = end
        else:
            i += 1
    clean = "".join(chars)

    def space(pos):
        while pos < len(clean) and clean[pos].isspace():
            pos += 1
        return pos

    def group(pos, opening):
        closing = {"{": "}", "[": "]", "<": ">"}[opening]
        start, level, braces = pos + 1, 1, 0
        pos += 1
        while pos < len(clean):
            c = clean[pos]
            if c == "\\":
                pos += 2
                continue
            if opening != "{" and c == "{":
                braces += 1
            elif opening != "{" and c == "}":
                braces -= 1
            elif braces == 0:
                if c == opening:
                    level += 1
                elif c == closing:
                    level -= 1
                    if level == 0:
                        return clean[start:pos], pos + 1
            pos += 1
        raise ValueError(f"line {text.count(chr(10), 0, start) + 1}: unclosed {opening} argument")

    out, i, depth = [], 0, 0
    while i < len(clean):
        if clean[i] != "\\":
            if clean[i] == "{":
                depth += 1
            elif clean[i] == "}":
                depth -= 1
            i += 1
            continue
        start = i
        match = re.match(r"\\([A-Za-z@]+|.)", clean[i:], re.S)
        if not match:
            break
        name = match[1]
        i += len(match[0])
        if name in ("verb", "lstinline"):
            if clean[i:i + 1] == "*":
                i += 1
            if i >= len(clean):
                raise ValueError("unterminated verbatim command")
            end = clean.find(clean[i], i + 1)
            if end < 0:
                raise ValueError("unterminated verbatim command")
            i = end + 1
            continue
        args, opts = [], []
        j = space(i)
        if clean[j:j + 1] == "*":
            j = space(j + 1)
        while j < len(clean) and clean[j] in "[{<":
            opening = clean[j]
            value, j = group(j, opening)
            (args if opening == "{" else opts).append(value.strip())
            j = space(j)
            # Read only the arguments belonging to known calls. For other commands,
            # traverse their groups so nested citations cannot disappear.
            if name in ("begin", "end") and len(args) == (2 if args and args[0] == "bookresult" else 1):
                break
            if name in ("BookFigure", "BookViz") and len(args) == (1 if name == "BookFigure" else 2):
                break
            if name not in ("begin", "end", "BookFigure", "BookViz", "input", "include", "href", "url", "usepackage"):
                break
        line = text.count("\n", 0, start) + 1
        out.append(Command(name, args, opts, line, depth))
        if name == "begin" and args and args[0] in ("verbatim", "verbatim*", "Verbatim", "lstlisting", "minted", "comment"):
            end = re.search(r"\\end\s*\{" + re.escape(args[0]) + r"\}", text[j:])
            if not end:
                raise ValueError(f"line {line}: unclosed {args[0]} environment")
            i = j + end.end()
        elif name in ("begin", "end", "BookFigure", "BookViz", "input", "include", "href", "url", "usepackage"):
            i = j
    return out


@dataclass
class Source:
    path: Path
    calls: list[Command]
    results: list[str] = field(default_factory=list)

    @property
    def count(self):
        frames = sum(c.name == "begin" and c.args == ["frame"] or c.name == "frame" for c in self.calls)
        ledger = sum(c.name == "FormalVerification" for c in self.calls)
        return frames + ledger * max(1, (len(set(self.results)) + 11) // 12)


def read_source(book, deck, lang, data=None) -> Source:
    data = data or settings(book, deck)
    path = book.slides_dir / deck / edition_file(data, lang)
    calls = commands(path.read_text(encoding="utf-8"))
    ids = [c.args[1] for c in calls if c.name == "begin" and len(c.args) == 2 and c.args[0] == "bookresult"]
    return Source(path, calls, ids)


def validate_source(book, lang, source, lock) -> list[model.Issue]:
    issues = []
    def err(c, msg):
        issues.append(model.Issue("error", source.path, c.line, msg))
    edition = model.load_edition(book.edition(lang))
    for c in source.calls:
        if c.name in ("input", "include") and c.args != ["tbook-deck"]:
            err(c, "academic deck imports are not checked: keep frames and citations in this edition file; only \\input{tbook-deck} is supported")
        if c.name in ("catcode", "csname", "includeonly", "inputminted"):
            err(c, f"\\{c.name} is outside the literal academic source contract")
        if c.name in ("href", "url") and c.args and c.args[0].startswith(("/", "file:")):
            err(c, "use relative or https:// links; the site is served under /<repo>/")
        if c.name == "begin" and c.args and c.args[0] == "bookresult":
            if len(c.args) != 2 or not ID.fullmatch(c.args[-1]):
                err(c, "bookresult needs one literal book result id: \\begin{bookresult}{thm-…}")
                continue
            if c.options:
                err(c, "bookresult takes no options: kind, GID, number and verified status are derived from the book and lock")
            env = edition.envs.get(c.args[1])
            if env is None:
                err(c, f"unknown result id #{c.args[1]} in the {lang} book edition")
                continue
            if env.kind not in model.FORMAL + model.DEFINITION + model.OPEN:
                err(c, f"#{env.id} is a {env.kind}; bookresult cites formal results, definitions or open problems")
            if env.kind in model.OPEN and env.lean:
                err(c, f"open problem #{env.id} must not have a GID")
            if env.status == "written-proof":
                from . import check
                policy = []
                check.check_env_policy(edition, policy)
                doc = next(d for d in edition.chapters if d.chapter is env.chapter)
                issues.extend(i for i in policy if i.path == doc.path and i.line == env.line)
            if env.kind in model.FORMAL and not env.lean and env.status != "written-proof":
                err(c, f"#{env.id}: unverified result has no GID")
            for gid in env.lean:
                res = lock.get(gid) if lock else None
                if not res:
                    err(c, f"#{env.id}: {gid} is UNVERIFIED: not in trureturing.lock.json; run ./tbook pin --refresh")
                elif env.kind in model.FORMAL and res.kind not in lean.FORMAL_KINDS:
                    err(c, f"#{env.id}: {gid} is a Lean {res.kind}, not a verified theorem")
        if c.name == "BookViz":
            if c.options:
                err(c, "BookViz takes no optional arguments; its snapshot fits the frame automatically")
            if len(c.args) != 2 or not all(NAME.fullmatch(x) for x in c.args):
                err(c, "BookViz needs literal visualization and snapshot ids")
                continue
            vid, preset = c.args
            problem = viz.check_ref(book, vid) or viz.check_preset(book, vid, preset)
            if problem:
                err(c, problem)
            elif not snapshot_path(book, vid, preset, lang).is_file():
                err(c, f"unknown paper snapshot {vid}/{preset} ({lang}); run ./tbook slides snapshots {book.slug}")
        if c.name == "BookFigure":
            if len(c.args) != 1 or not NAME.fullmatch(c.args[0]):
                err(c, "BookFigure needs one literal figure name")
                continue
            problem = figure.check_ref(book, c.args[0])
            if problem:
                err(c, problem)
            else:
                current = figure.out_path(book, c.args[0], lang)
                try:
                    if current.read_text(encoding="utf-8") != figure.render(book, c.args[0], lang):
                        err(c, f"figure {c.args[0]} is stale: run ./tbook fig build --book {book.slug}")
                except figure.FigureError as exc:
                    err(c, str(exc))
    if sum(c.name == "FormalVerification" for c in source.calls) != 1:
        issues.append(model.Issue("error", source.path, 0, "academic deck needs exactly one \\FormalVerification ledger"))
    if not any(c.name == "input" and c.args == ["tbook-deck"] for c in source.calls):
        issues.append(model.Issue("error", source.path, 0, "academic deck needs \\input{tbook-deck} in its preamble"))
    return issues


def check_deck(book, deck, lock):
    issues, sources = [], []
    try:
        data = settings(book, deck)
        wanted = {edition_file(data, lang) for lang in data["editions"]}
        directory = book.slides_dir / deck
        for p in directory.glob("slides*.tex"):
            if p.name not in wanted:
                issues.append(model.Issue("error", p, 0, "not a declared academic edition file; check deck.toml editions"))
        if list(directory.glob("slides*.md")):
            raise ValueError("academic deck must not also contain Slidev edition files")
        for lang in data["editions"]:
            try:
                source = read_source(book, deck, lang, data)
                issues += validate_source(book, lang, source, lock)
                sources.append(source)
            except (OSError, ValueError) as exc:
                issues.append(model.Issue("error", directory / edition_file(data, lang), 0, str(exc)))
        for source in sources[1:]:
            if source.count != sources[0].count:
                issues.append(model.Issue("error", source.path, 0, f"{source.count} frames, but {sources[0].path.name} has {sources[0].count}; editions of this deck correspond frame for frame"))
            if source.results != sources[0].results:
                issues.append(model.Issue("error", source.path, 0, "result citation sequence differs between this deck's editions"))
    except ValueError as exc:
        issues.append(model.Issue("error", book.slides_dir / deck / "deck.toml", 0, str(exc)))
    return issues


def cited_gids(book, deck):
    data = settings(book, deck)
    out = []
    for lang in data["editions"]:
        try:
            source = read_source(book, deck, lang, data)
        except (OSError, ValueError):
            continue  # check_deck reports malformed source
        edition = model.load_edition(book.edition(lang))
        for c in source.calls:
            if c.name == "begin" and len(c.args) == 2 and c.args[0] == "bookresult":
                env = edition.envs.get(c.args[1])
                out += [(source.path, c.line, gid) for gid in env.lean] if env else []
    return out


def tex(text):
    return "".join({"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "#": r"\#", "$": r"\$", "%": r"\%",
                    "&": r"\&", "_": r"\_", "^": r"\textasciicircum{}", "~": r"\textasciitilde{}"}.get(c, c) for c in text)


def title_tex(title):
    # Book titles support inline math and Markdown punctuation escapes (same book model).
    from . import mdscan
    return "".join(part if i % 2 else tex(mdscan.unescape_markdown(part))
                   for i, part in enumerate(re.split(r"(\$[^$]+\$)", title)))


def url_tex(url):
    # URLs occur inside generated macro definitions, where raw #/% are TeX syntax.
    return url.replace("%", r"\%").replace("#", r"\#")


def doi_link(doi):
    # DOI punctuation is data, never TeX; allow long identifiers to wrap in the ledger.
    display = r"\allowbreak{}".join(tex(c) for c in doi)
    return r"\href{" + url_tex(evidence.doi_url(doi)) + r"}{\texttt{" + display + "}}"


def snapshot_path(book, vid, preset, lang):
    return book.viz_dir / vid / f"fig-{preset}.{lang}.paper.png"


def generate_package(book, lang, source, lock, dest):
    """Generate presentation-neutral result blocks and a ledger; never a copied statement."""
    edition = model.load_edition(book.edition(lang))
    tokens = json.loads(paths.TOKENS.read_text(encoding="utf-8"))
    colours = {"Lean": tokens["paper"][tokens["semantic"]["lean"]],
               "Written": tokens["paper"][tokens["semantic"]["argued"]],
               "Open": tokens["paper"][tokens["semantic"]["open"]], "Neutral": tokens["paper"]["dim"]}
    lines = [r"\ProvidesPackage{tbook-lean}[Generated from the book and trureturing lock]",
             r"\RequirePackage{amssymb}", r"\RequirePackage{xurl}", r"\RequirePackage{array}",
             r"\newcommand{\TBookBadge}[2]{\begingroup\setlength{\fboxsep}{1pt}\colorbox{white}{\textcolor{#1}{#2}}\endgroup}"]
    lines += [rf"\definecolor{{TBook{k}}}{{HTML}}{{{v.lstrip('#')}}}" for k, v in colours.items()]
    lines += [r"\newcommand{\PinnedCommit}{\href{" + url_tex(lock.tree_url) + r"}{\texttt{" + lock.commit[:12] + "}}}"]
    ids = list(dict.fromkeys(source.results))
    badges = {}
    for ident in ids:
        env = edition.envs.get(ident)
        if not env:
            heading, badge = tex(ident), r"\TBookBadge{TBookOpen}{UNVERIFIED}"
        else:
            heading = tex(env.ref_text(lang))
            if env.title:
                heading += " (" + title_tex(edition.title_markdown(env)) + ")"
            resolutions = [lock.get(gid) for gid in env.lean]
            if env.status == "written-proof":
                badge = r"\TBookBadge{TBookWritten}{" + tex(config.s(lang, "badge.written_proof")) + "}"
            elif env.kind in model.OPEN:
                badge = r"\TBookBadge{TBookOpen}{OPEN}"
            elif env.kind == "definition" and all(resolutions) and env.lean:
                badge = r"\TBookBadge{TBookNeutral}{LEAN DEF}"
            elif env.kind == "definition" and not env.lean:
                badge = ""
            elif env.kind in model.FORMAL and resolutions and all(r and r.kind in lean.FORMAL_KINDS for r in resolutions):
                badge = rf"\href{{{url_tex(lock.source_url(env.lean[0]))}}}{{\TBookBadge{{TBookLean}}{{Lean $\checkmark$}}}}"
            else:
                badge = r"\TBookBadge{TBookOpen}{UNVERIFIED}"
        badges[ident] = badge
        block = "alertblock" if env and env.kind in model.OPEN else "block"
        provenance = ""
        if env and env.status == "written-proof" and evidence.doi_url(env.attrs.get("doi")):
            provenance = (r"\par{\tiny DOI: " + doi_link(env.attrs.get("doi"))
                          + "; " + tex(env.attrs.get("source") or ""))
            if evidence.request_number(env.attrs.get("request")):
                provenance += r"; \href{" + url_tex(env.attrs.get("request")) + r"}{trureturing-requests\#" + str(evidence.request_number(env.attrs.get("request"))) + "}"
            provenance += "}"
        lines += [rf"\expandafter\def\csname tbook@{ident}\endcsname{{{heading}\quad{{\scriptsize {badge}}}{provenance}}}",
                  rf"\expandafter\def\csname tbook@env@{ident}\endcsname{{{block}}}"]
    lines += [r"\newenvironment{bookresult}[1]{\edef\TBookResultEnvironment{\csname tbook@env@#1\endcsname}\begin{\TBookResultEnvironment}{\csname tbook@#1\endcsname}}{\end{\TBookResultEnvironment}}"]
    lines += [r"\newsavebox{\TBookLedgerTable}"]
    ledger = []
    for start in range(0, max(1, len(ids)), 12):
        ledger += [r"\begin{frame}[t]{Formal verification}",
                   r"\setlength{\tabcolsep}{3pt}\renewcommand{\arraystretch}{1}",
                   r"\fontsize{6.4}{7.4}\selectfont",
                   r"\begin{lrbox}{\TBookLedgerTable}",
                   r"\begin{tabular}{@{}>{\raggedright\arraybackslash}p{.26\linewidth}>{\raggedright\arraybackslash}p{.54\linewidth}>{\raggedright\arraybackslash}p{.16\linewidth}@{}}",
                   r"\textbf{Result} & \textbf{Source (Lean / DOI / request)} & \textbf{Status} \\\hline"]
        for ident in ids[start:start + 12]:
            env = edition.envs.get(ident)
            gids = []
            if env and env.status == "written-proof":
                doi = env.attrs.get("doi") or ""
                gids = ["DOI: " + doi_link(doi) + "; " + tex(env.attrs.get("source") or "")]
                if evidence.request_number(env.attrs.get("request")):
                    gids.append(r"\href{" + url_tex(env.attrs.get("request")) + r"}{trureturing-requests\#" + str(evidence.request_number(env.attrs.get("request"))) + "}")
            elif env and env.lean:
                for gid in env.lean:
                    label = rf"\nolinkurl{{{gid}}}"
                    gids.append(rf"\href{{{url_tex(lock.source_url(gid))}}}{{{label}}}" if lock.get(gid) else label)
            elif env and env.kind in model.OPEN:
                gids = ["No GID (open problem)"]
            elif env and env.kind in model.DEFINITION:
                gids = ["No Lean citation"]
            else:
                gids = ["No GID"]
            label = tex(env.ref_text(lang) if env else ident)
            status = badges[ident] or r"\TBookBadge{TBookNeutral}{No Lean citation}"
            ledger += [label + r"\rule{0pt}{8pt} & {\fontsize{5}{5.7}\selectfont " + r"\par ".join(gids)
                       + r"} & {\fontsize{5.5}{6.5}\selectfont " + status + r"} \\[1pt]"]
        ledger += [r"\end{tabular}\end{lrbox}",
                   # Fit the table alone, leaving normal frame stretch for the footer line.
                   r"\ifdim\dimexpr\ht\TBookLedgerTable+\dp\TBookLedgerTable\relax>.78\textheight",
                   r"\resizebox*{!}{.78\textheight}{\usebox{\TBookLedgerTable}}",
                   r"\else\usebox{\TBookLedgerTable}\fi\par",
                   r"\vskip0pt plus 1filll{\tiny Pinned source: \PinnedCommit\par}", r"\end{frame}"]
    lines += [r"\newcommand{\FormalVerification}{" + "\n".join(ledger) + "}"]
    (dest / "tbook-lean.sty").write_text("\n".join(lines) + "\n", encoding="utf-8")


def engine():
    executable = os.environ.get("TECTONIC") or shutil.which("tectonic")
    if not executable:
        raise RuntimeError(f"academic slides need Tectonic {ENGINE_VERSION}; see theme/beamer/README.md")
    try:
        version = subprocess.check_output([executable, "--version"], text=True, stderr=subprocess.STDOUT).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"cannot run Tectonic {ENGINE_VERSION}: {exc}") from exc
    if version != f"Tectonic {ENGINE_VERSION}":
        raise RuntimeError(f"academic slides require Tectonic {ENGINE_VERSION}, found {version}")
    return executable


def stage_assets(site, book, lang, source, dest):
    from . import pandoc
    lines = []
    for c in source.calls:
        if c.name == "BookFigure" and len(c.args) == 1:
            name = c.args[0]
            svg = figure.materialize(figure.out_path(book, name, lang).read_text(encoding="utf-8"), "paper", ground=True)
            asset = f"figure-{name}"
            (dest / f"{asset}.svg").write_text(svg, encoding="utf-8")
            w, h = figure.natural_size(svg)
            typ = f'#set page(width: {w}pt, height: {h}pt, margin: 0pt)\n#image("{asset}.svg", width: 100%)'
            (dest / f"{asset}.typ").write_text(typ, encoding="utf-8")
            pandoc.compile_typst(dest / f"{asset}.typ", dest / f"{asset}.pdf", root=dest,
                                 timestamp=int(os.environ.get("SOURCE_DATE_EPOCH", EPOCH)))
            lines.append(rf"\expandafter\def\csname tbook@figure@{name}\endcsname{{{asset}.pdf}}")
        if c.name == "BookViz" and len(c.args) == 2:
            vid, preset = c.args
            asset = f"viz-{vid}-{preset}.png"
            shutil.copy2(snapshot_path(book, vid, preset, lang), dest / asset)
            url = viz.published_url(site, book, vid) + f"?lang={quote(lang)}&preset={quote(preset)}"
            lines.append(rf"\expandafter\def\csname tbook@viz@{vid}@{preset}\endcsname{{\href{{{url_tex(url)}}}{{\includegraphics[width=\linewidth]{{{asset}}}}}}}")
    lines += [r"\newcommand{\BookFigure}[2][]{\includegraphics[width=\linewidth,height=.64\textheight,keepaspectratio,#1]{\csname tbook@figure@#2\endcsname}}",
              r"\newcommand{\BookViz}[2]{\csname tbook@viz@#1@#2\endcsname}"]
    return lines


def build_deck(site, book, deck, out):
    from . import slides
    data = settings(book, deck)
    lock = lean.Lock.load()
    errors = check_deck(book, deck, lock)
    if errors:
        raise RuntimeError("\n".join(x.format() for x in errors))
    executable = engine()
    directory = book.slides_dir / deck
    theme = (directory / data["theme_dir"]).resolve() if data.get("theme_dir") else paths.THEME / "beamer"
    entry = {"kind": "academic", "langs": {}}
    for lang in data["editions"]:
        source = read_source(book, deck, lang, data)
        stage = paths.BUILD / "stage" / book.slug / "beamer" / deck / lang
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        generate_package(book, lang, source, lock, stage)
        preamble = [rf"\usetheme{{{data.get('theme_name', 'LinZhang') if data.get('theme_dir') else 'TBookAcademic'}}}",
                    r"\usefonttheme[onlymath]{serif}", r"\usepackage{appendixnumberbeamer}", r"\usepackage{tbook-lean}",
                    r"\ifdefined\TBookNotes\setbeameroption{show notes}\else\setbeameroption{hide notes}\fi"]
        if lang.startswith("zh"):
            preamble.insert(0, r"\usepackage[fontset=fandol]{ctex}")
        preamble += [rf"\definecolor{{TBookStructure}}{{HTML}}{{{data['structure_colour'][1:]}}}",
                     r"\setbeamercolor{structure}{fg=TBookStructure}"]
        for key, command in (("short_author", "author"), ("short_title", "title")):
            if data.get(key):
                # Preserve the author's raw long field, including coauthor/affiliation macros.
                # Reusing \insertauthor would reinsert Beamer's display-only definitions into PDF metadata.
                preamble += [rf"\let\TBookOriginal{command}\{command}",
                             rf"\renewcommand{{\{command}}}[2][]{{\TBookOriginal{command}[{tex(data[key])}]{{#2}}}}"]
        # Descriptor metadata wins over source defaults, for every edition.
        for key, command in (("institution", "institute"), ("date", "date")):
            if data.get(key):
                preamble += [rf"\AtBeginDocument{{\{command}{{{tex(data[key])}}}}}"]
        preamble += [rf"\providecommand{{\TBookCoauthors}}{{}}",
                     rf"\renewcommand{{\TBookCoauthors}}{{{tex(data.get('coauthors', ''))}}}",
                     r"\setbeamertemplate{navigation symbols}[default]" if data.get("navigation_symbols", False)
                     else r"\setbeamertemplate{navigation symbols}{}"]
        if data.get("institution_graphic"):
            graphic = (directory / data["institution_graphic"]).resolve()
            preamble += [rf"\titlegraphic{{\includegraphics[height=1.6cm]{{{graphic.as_posix()}}}}}"]
        preamble += stage_assets(site, book, lang, source, stage)
        (stage / "tbook-deck.tex").write_text("\n".join(preamble) + "\n", encoding="utf-8")
        for notes in (False, True):
            job = "notes" if notes else "audience"
            # Stable wrapper names; no timestamps or random paths in the PDF metadata/ID.
            wrapper = (r"\def\TBookNotes{1}" if notes else "")
            wrapper += rf"\PassOptionsToClass{{compress,aspectratio={'43' if data['aspect'] == '4:3' else '169'}}}{{beamer}}" + "\n"
            wrapper += source.path.read_text(encoding="utf-8")
            (stage / f"{job}.tex").write_text(wrapper, encoding="utf-8")
            cmd = [executable, "-X", "compile", f"{job}.tex", "--bundle", BUNDLE,
                   "--keep-logs", "-Z", "deterministic-mode", "-Z", f"search-path={theme}",
                   "-Z", f"search-path={directory.resolve()}"]
            env = dict(os.environ, SOURCE_DATE_EPOCH=os.environ.get("SOURCE_DATE_EPOCH", EPOCH),
                       TECTONIC_CACHE_DIR=os.environ.get("TECTONIC_CACHE_DIR", str(paths.CACHE / "tectonic")))
            result = subprocess.run(cmd, cwd=stage, env=env, capture_output=True, text=True)
            (stage / f"{job}-build.log").write_text(result.stdout + result.stderr, encoding="utf-8")
            if result.returncode:
                raise RuntimeError(f"Tectonic failed: {stage / (job + '-build.log')}\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
            filename = f"{deck}-{lang}{'-notes' if notes else ''}.pdf"
            shutil.copy2(stage / f"{job}.pdf", out / filename)
            print(f"  academic: {filename}", flush=True)
        target = out / deck / lang
        target.mkdir(parents=True, exist_ok=True)
        title = data.get("title", {}).get(lang, deck)
        up = "" if lang == book.languages[0] else "../"
        audience = up + slides.pdf_name(book, deck, lang)
        notes = audience[:-4] + "-notes.pdf"
        (target / "index.html").write_text(f'<!doctype html><html lang="{html.escape(lang)}"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{html.escape(title)}</title><h1>{html.escape(title)}</h1><p><a href="{audience}">{html.escape(slides.t(lang, "pdf"))}</a> · <a href="{notes}">{html.escape(slides.t(lang, "notes_pdf"))}</a></p></html>\n', encoding="utf-8")
        entry["langs"][lang] = {"dir": f"{deck}/{lang}", "site_path": slides.site_path(book, deck, lang),
                               "pdf": f"{deck}-{lang}.pdf", "notes_pdf": f"{deck}-{lang}-notes.pdf", "slides": source.count}
    return entry


def scaffold(rest):
    parser = argparse.ArgumentParser(prog="tbook slides new")
    parser.add_argument("book")
    parser.add_argument("deck")
    parser.add_argument("titles", nargs="+")
    parser.add_argument("--academic", action="store_true")
    parser.add_argument("--editions", help="comma-separated subset, first edition owns slides.tex")
    parser.add_argument("--aspect", choices=["4:3", "16:9"], default="4:3")
    args = parser.parse_args(rest)
    book = config.named_book(args.book)
    editions = args.editions.split(",") if args.editions else list(book.languages)
    if not editions or len(set(editions)) != len(editions) or any(x not in book.languages for x in editions):
        raise config.ConfigError("--editions must be a nonempty subset of book editions, without repeats")
    if len(args.titles) != len(editions):
        raise config.ConfigError("give one title per requested edition, in --editions order")
    if not NAME.fullmatch(args.deck):
        raise config.ConfigError("deck name must be kebab-case")
    directory = book.slides_dir / args.deck
    if directory.exists():
        raise config.ConfigError(f"{directory} already exists")
    directory.mkdir(parents=True)
    data = {"editions": editions}
    descriptor = f'kind = "academic"\neditions = {json.dumps(editions)}\naspect = "{args.aspect}"\nstructure_colour = "#0e2c8e"\nshort_author = "Speaker"\nshort_title = "Seminar"\n\n[title]\n'
    template = (paths.TEMPLATES / "beamer" / "slides.tex").read_text(encoding="utf-8")
    for lang, title in zip(editions, args.titles):
        descriptor += f"{lang} = {json.dumps(title, ensure_ascii=False)}\n"
        (directory / edition_file(data, lang)).write_text(template.replace("@@TITLE@@", tex(title)), encoding="utf-8")
    (directory / "deck.toml").write_text(descriptor, encoding="utf-8")
    print(f"created {paths.rel(directory)} (academic; {', '.join(editions)})")
    return 0


def snapshots(books):
    jobs = []
    for book in books:
        for directory in sorted(book.slides_dir.glob("*")):
            if not is_academic(directory):
                continue
            data = settings(book, directory.name)
            for lang in data["editions"]:
                for c in read_source(book, directory.name, lang, data).calls:
                    if c.name == "BookViz" and len(c.args) == 2:
                        vid, preset = c.args
                        problem = viz.check_ref(book, vid) or viz.check_preset(book, vid, preset)
                        if problem:
                            raise config.ConfigError(problem)
                        jobs.append({"book": book.slug, "id": vid, "preset": preset, "lang": lang,
                                     "out": str(snapshot_path(book, vid, preset, lang))})
    subprocess.run([shutil.which("node") or "node", str(paths.TOOLS / "node" / "beamer-snapshots.mjs"), json.dumps(jobs)], check=True, cwd=paths.ROOT)
    return 0
