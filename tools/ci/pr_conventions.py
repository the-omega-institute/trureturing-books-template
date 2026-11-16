"""Validate pull request metadata without executing pull request code."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

TYPES = r"(?:feat|fix|docs|refactor|perf|test|build|ci|chore|revert)"
TOPIC = r"[a-z0-9]+(?:-[a-z0-9]+)*"
TITLE = re.compile(TYPES + r"(?:\([a-z0-9]+(?:[./-][a-z0-9]+)*\))?!?: \S(?:[^\r\n]*\S)?")
VERSION = r"v?\d+\.\d+\.\d+(?:-[0-9a-z]+(?:[.-][0-9a-z]+)*)?"
BRANCH = re.compile(
    rf"(?:{TYPES}/{TOPIC}|template-update/(?:{TOPIC}/)?{VERSION}|trureturing-bump/[0-9a-f]{{12}})"
)


def utc_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("时间必须包含 UTC 时区（Z 或 +00:00）")
    return parsed


def validate(pr: dict, since: str = "") -> list[str]:
    if since and utc_time(pr["created_at"]) < utc_time(since):
        return []
    errors = []
    title, branch = pr["title"], pr["head"]["ref"]
    if not TITLE.fullmatch(title) or len(title) > 100:
        errors.append("PR 标题须为 type(scope): 摘要，scope 可省略，最长 100 个字符；见 CONTRIBUTING.md。")
    if not BRANCH.fullmatch(branch):
        errors.append("源分支须为 type/lowercase-topic，或文档规定的模板升级、钉版分支；见 CONTRIBUTING.md。")
    return errors


def main() -> int:
    try:
        payload = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        errors = validate(payload["pull_request"], os.environ.get("PR_CONVENTIONS_SINCE", ""))
    except (KeyError, TypeError, ValueError, OSError):
        errors = ["无法读取 PR 元数据或 PR_CONVENTIONS_SINCE 不是有效 UTC 时间。"]
    for error in errors:
        print(f"::error::{error}")
    if not errors:
        print("PR 命名检查通过（启用前的 PR 保留历史命名）。")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
