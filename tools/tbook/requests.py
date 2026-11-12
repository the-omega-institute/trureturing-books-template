"""The shared formalization queue: provenance, registration checks and usage counts.

Only reads GitHub. Creating an issue or registering a book's use is an explicit author
action; check/build never publish messages or create duplicate issues.
"""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import config, evidence, model


def marker(repo: str, book: str, ident: str) -> str:
    return f"<!-- tbook:{repo}:{book}:{ident} -->"


def entries(editions):
    """A result is one use, regardless of the number of translated editions."""
    seen = set()
    for edition in editions:
        for env in edition.formal_envs():
            key = (edition.edition.book.slug, env.id)
            if env.status == "written-proof" and key not in seen:
                seen.add(key)
                yield edition, env


def collect(editions) -> list[dict]:
    editions = list(editions)
    english_names = {(ed.edition.book.slug, env.id): env.title for ed in editions if ed.lang == "en"
                     for env in ed.formal_envs() if env.title}
    groups = {}
    for edition, env in entries(editions):
        url = env.attrs.get("request") or ""
        key = url or f"{edition.edition.book.slug}#{env.id}"
        group = groups.setdefault(key, {
            "request": url, "sources": [],
            "suggested_title": evidence.request_title(english_names.get((edition.edition.book.slug, env.id)) or env.id, env.attrs.get("doi") or "", env.attrs.get("source") or ""),
            "uses": [],
        })
        group["uses"].append({"book": edition.edition.book.slug, "id": env.id,
                              "chapter": env.chapter.path, "lang": edition.lang,
                              "title": env.title or "", "proof": env.attrs.get("proof") or "",
                              "doi": env.attrs.get("doi") or "", "source": env.attrs.get("source") or ""})
        source = {"doi": env.attrs.get("doi") or "", "source": env.attrs.get("source") or ""}
        if source not in group["sources"]:
            group["sources"].append(source)
    for group in groups.values():
        group["result_count"] = len(group["uses"])
        group["book_count"] = len({u["book"] for u in group["uses"]})
    return sorted(groups.values(), key=lambda g: (-g["book_count"], -g["result_count"], g["request"]))


def _api(path: str):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "tbook"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    with urlopen(Request("https://api.github.com/repos/" + evidence.REQUEST_REPO + path, headers=headers), timeout=20) as r:
        return json.load(r)


def registration(doi: str, source: str) -> str:
    return f"DOI:{doi} | {source}"


def registered(issue: dict, number: int, markers: dict[str, str]) -> bool:
    def remaining(pending, body):
        return {m: source for m, source in pending.items() if m not in body or source not in body}
    missing = remaining(markers, issue.get("body") or "")
    if not missing:
        return True
    if not issue.get("comments"):
        return False
    page = 1
    while missing:
        comments = _api(f"/issues/{number}/comments?per_page=100&page={page}")
        for comment in comments:
            missing = remaining(missing, comment.get("body") or "")
        if not missing:
            return True
        if len(comments) < 100:
            return False
        page += 1
    return True


def check(editions, site: config.Site, *, offline=False) -> list[model.Issue]:
    issues = []
    groups = {}
    for edition, env in entries(editions):
        number = evidence.request_number(env.attrs.get("request"))
        if number and evidence.doi_url(env.attrs.get("doi")) and evidence.source_location(env.attrs.get("source")):
            groups.setdefault(number, []).append((edition, env))
    for number, uses in groups.items():
        edition, env = uses[0]
        doc = next(d for d in edition.chapters if d.chapter is env.chapter)
        def report(severity, message):
            issues.append(model.Issue(severity, doc.path, env.line, f"request #{number}: {message}"))
        if offline:
            report("warning", "issue existence, title and book registration not checked offline")
            continue
        try:
            issue = _api(f"/issues/{number}")
            if "pull_request" in issue:
                report("error", "the URL names a pull request, not a formalization issue")
                continue
            if not evidence.parse_request_title(issue.get("title", "")):
                report("error", "title must be [Formalization] <Result name> | DOI:<bare DOI> | <Source location>")
            markers = {marker(site.repo, ed.edition.book.slug, e.id): registration(e.attrs.get("doi"), e.attrs.get("source")) for ed, e in uses}
            if not site.repo or not registered(issue, number, markers):
                report("error", "register every book/result in the issue body or a comment with " + ", ".join(sorted(markers)))
        except HTTPError as exc:
            report("error" if exc.code in (404, 410) or os.environ.get("GITHUB_ACTIONS") == "true" else "warning",
                   f"cannot verify issue (HTTP {exc.code})")
        except (OSError, URLError, ValueError, TypeError) as exc:
            report("error" if os.environ.get("GITHUB_ACTIONS") == "true" else "warning",
                   f"cannot verify issue ({type(exc).__name__})")
    return issues
