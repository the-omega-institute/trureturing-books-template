"""One Typst compilation per process; called by tbook.pandoc.compile_typst."""

from __future__ import annotations

import json
import sys


def main() -> int:
    import typst

    request = json.load(sys.stdin)
    try:
        _, warnings = typst.compile_with_warnings(request["main"], **request["kwargs"])
    except (typst.TypstError, RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    json.dump([getattr(w, "message", str(w)) for w in warnings or []], sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
