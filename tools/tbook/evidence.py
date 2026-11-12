"""Source identifiers for written proofs (not certificates of kernel verification)."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote

REQUEST_REPO = "the-omega-institute/trureturing-requests"
REQUEST_TITLE_PREFIX = "[Formalization] "
REQUEST_PREFIX = f"https://github.com/{REQUEST_REPO}/issues/"


def request_number(value: str | None) -> int | None:
    """Only canonical issue URLs in the shared formalization queue are accepted."""
    m = re.fullmatch(re.escape(REQUEST_PREFIX) + r"([1-9][0-9]*)", value) if isinstance(value, str) else None
    return int(m[1]) if m else None


def request_title(name: str, doi: str, source: str) -> str:
    return f"{REQUEST_TITLE_PREFIX}{name} | DOI:{doi} | {source}"


def source_location(value: str | None) -> bool:
    return bool(isinstance(value, str) and value and value.strip() == value and not any(
        c in "|\r\n" or unicodedata.category(c).startswith("C") for c in value))


def parse_request_title(title: str) -> tuple[str, str] | None:
    parts = title.split(" | ")
    if (len(title) <= 256 and len(parts) == 3 and parts[0].startswith(REQUEST_TITLE_PREFIX)
            and bool(parts[0][len(REQUEST_TITLE_PREFIX):].strip()) and parts[1].startswith("DOI:")
            and doi_url(parts[1][4:]) and source_location(parts[2])):
        return parts[1][4:], parts[2]
    return None


def doi_url(value: str | None) -> str:
    """A safe resolver URL for one bare DOI, or empty for a malformed identifier.

    DOI suffixes include punctuation (including legacy SICI identifiers). Encode the
    suffix for URLs instead of treating its punctuation as Markdown or URL syntax.
    Existence and support for the exact statement remain author/reviewer checks.
    """
    if not isinstance(value, str) or not value or not re.fullmatch(r'10\.[0-9]{4,9}/\S+', value):
        return ""
    if any(unicodedata.category(c).startswith("C") for c in value):
        return ""
    return "https://doi.org/" + quote(value, safe="/")
