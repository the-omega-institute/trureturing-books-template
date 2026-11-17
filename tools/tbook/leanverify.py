"""Deep verification: a Lake project that re-checks every Lean declaration the books cite.

``./tbook check`` reads trureturing's frozen ledger (``Golden/Frozen/state``) at each declaration's
evidence commit. This module produces the independent, slow check behind it: a small Lake workspace
that resolves the followed branch once and uses that immutable snapshot for its toolchain and
dependency (legacy locks use their global pinned commit). It imports every cited module and asks
the Lean environment itself, for each declaration in ``trureturing-lock/``, that

1. the declaration exists (``Environment.find?``);
2. it comes from the module the lock names (``getModuleIdxFor?`` → ``header.moduleNames``);
3. its ``ConstantInfo`` kind matches the lock kind (theorem ↔ ``.thmInfo``, def ↔ ``.defnInfo``, …;
   the same names trureturing's ``tools/lean-inspector/Inspector.lean`` writes into the state files);
4. its axiom closure (``Lean.collectAxioms``) is contained in {``propext``, ``Classical.choice``,
   ``Quot.sound``} — in particular it does not use ``sorryAx``.

Every verified item logs a ``✓`` line; at the end one ``throwError`` lists all failures, so
``lake build BookVerify`` fails exactly when something is wrong.

Generated files (``build/lean-verify/`` by default)::

    lean-toolchain     trureturing's own lean-toolchain at the verification snapshot
    lakefile.toml      package "bookverify": requires trureturing at that same snapshot
    BookVerify.lean    imports + the checks above
    README.md          what is checked, how to run it, the list of declarations
    verify.sh          lake exe cache get || true; lake build BookVerify

Declaration names are rebuilt component by component (``Lean.Name.mkStr`` / ``mkNum``) from
the lock's display names, honouring ``«…»`` escapes, so no dotted string is ever re-parsed by
Lean. The output is deterministic (no timestamps), which keeps CI caches stable.
CI: ``.github/workflows/lean-verify.yml`` (weekly, manual, and callable before a release).
"""

from __future__ import annotations

import re
from dataclasses import replace
import stat
from pathlib import Path

from . import config, lean, paths

PROJECT_NAME = "bookverify"
LIB_NAME = "BookVerify"
TOOLCHAIN_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+:[A-Za-z0-9_.+-]+$")
NUMERIC_RE = re.compile(r"^[0-9]+$")
# Lock "kind" values and the ConstantInfo constructor each one must be (Inspector.lean kindOf).
KINDS = {
    "axiom": "axiomInfo",
    "def": "defnInfo",
    "theorem": "thmInfo",
    "opaque": "opaqueInfo",
    "quotient": "quotInfo",
    "constructor": "ctorInfo",
    "recursor": "recInfo",
    "inductive": "inductInfo",
}


class LeanVerifyError(config.ConfigError):
    """The verification project cannot be generated (subclass of ConfigError: the CLI prints it cleanly)."""


# --------------------------------------------------------------------------- names


def split_name(text: str) -> list[str | int]:
    """Components of a Lean name as written by :func:`tbook.lean.name_to_str`.

    ``D5.S1.«a.b».x.0`` → ``["D5", "S1", "a.b", "x", 0]``: ``«…»`` encloses one string
    component verbatim (dots included); an unescaped all-digit component is numeric.
    """
    if not text:
        raise LeanVerifyError("empty Lean name")
    comps: list[str | int] = []
    i, n = 0, len(text)
    while True:
        if text.startswith("«", i):
            j = text.find("»", i + 1)
            if j < 0:
                raise LeanVerifyError(f"unterminated «…» in Lean name {text!r}")
            comps.append(text[i + 1:j])
            i = j + 1
        else:
            j = text.find(".", i)
            part = text[i:] if j < 0 else text[i:j]
            if not part or "«" in part or "»" in part:
                raise LeanVerifyError(f"malformed Lean name {text!r}")
            comps.append(int(part) if NUMERIC_RE.match(part) else part)
            i = n if j < 0 else j
        if i == n:
            return comps
        if text[i] != "." or i + 1 == n:
            raise LeanVerifyError(f"malformed Lean name {text!r}")
        i += 1


def lean_string(value: str) -> str:
    """A Lean 4 string literal for ``value``."""
    out = ['"']
    for ch in value:
        code = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\x{code:02x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def name_expr(comps: list[str | int]) -> str:
    """Lean term building the name from its components with ``Lean.Name.mkStr`` / ``mkNum``."""
    expr = "Lean.Name.anonymous"
    for c in comps:
        if isinstance(c, int):
            expr = f"Lean.Name.mkNum ({expr}) {c}"
        else:
            expr = f"Lean.Name.mkStr ({expr}) {lean_string(c)}"
    return expr


def module_name(module_path: str) -> str:
    """``D5/S1/Deficit/DeficitInteger`` → ``D5.S1.Deficit.DeficitInteger`` (as written after ``import``)."""
    parts = module_path.split("/")
    for p in parts:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_']*$", p):
            raise LeanVerifyError(f"module path component {p!r} of {module_path!r} is not a plain Lean identifier")
    return ".".join(parts)


# --------------------------------------------------------------------------- inputs


def _entries(lock: lean.Lock) -> list[dict]:
    """Lock declarations, sorted by GID, with the data BookVerify.lean needs."""
    out = []
    for gid in sorted(lock.declarations):
        d = lock.declarations[gid]
        name, module, kind = d.get("name", ""), d.get("module", ""), d.get("kind", "")
        if not (name and module and kind):
            raise LeanVerifyError(f"trureturing.lock.json: {gid} lacks name/module/kind; run ./tbook pin --refresh")
        if kind not in KINDS:
            raise LeanVerifyError(f"trureturing.lock.json: {gid} has unknown kind {kind!r} (known: {', '.join(KINDS)})")
        out.append({"gid": gid, "name": name, "comps": split_name(name), "module": module,
                    "module_name": module_name(module), "kind": kind, "statement_id": d.get("statement_id", "")})
    return out


def read_toolchain(lock: lean.Lock, ledger: lean.Ledger | None = None) -> str:
    """trureturing's ``lean-toolchain`` at the supplied revision, e.g. ``leanprover/lean4:v4.35.0``."""
    ledger = ledger or lean.Ledger(lock.repo)
    try:
        data = ledger.read(lock.commit, "lean-toolchain")
    except lean.LeanError as exc:
        raise LeanVerifyError(f"cannot read lean-toolchain of {lock.repo} at {lock.commit[:12]}: {exc}") from exc
    if data is None:
        raise LeanVerifyError(f"cannot read lean-toolchain of {lock.repo} at {lock.commit[:12]}: no trureturing "
                              "checkout ($TRURETURING_DIR or ../trureturing), no cache and no network")
    if not data:
        raise LeanVerifyError(f"{lock.repo} has no lean-toolchain at {lock.commit[:12]}")
    text = data.decode("utf-8", "replace").strip()
    if not TOOLCHAIN_RE.match(text):
        raise LeanVerifyError(f"unexpected lean-toolchain at {lock.commit[:12]}: {text[:80]!r}")
    return text


def _citing_books(gids: set[str]) -> dict[str, list[str]]:
    """GID → slugs of the books whose primary edition cites it (best effort, for the README)."""
    from .model import load_edition

    out: dict[str, list[str]] = {}
    try:
        books = config.load_books()
    except config.ConfigError:
        return out
    for book in books:
        try:
            model = load_edition(book.primary)
        except Exception:  # noqa: BLE001 - informational only
            continue
        for _path, _line, gid, _env in model.cited_gids():
            if gid in gids and book.slug not in out.setdefault(gid, []):
                out[gid].append(book.slug)
    return out


# --------------------------------------------------------------------------- generated text


def lakefile_toml(lock: lean.Lock) -> str:
    return (
        "# Generated by ./tbook lean-project from trureturing.lock.json; do not edit.\n"
        f'name = "{PROJECT_NAME}"\n'
        'version = "0.1.0"\n'
        f'defaultTargets = ["{LIB_NAME}"]\n'
        "\n"
        "[[require]]\n"
        'name = "trureturing"\n'
        f'git = "https://github.com/{lock.repo}"\n'
        f'rev = "{lock.commit}"\n'
        "\n"
        "[[lean_lib]]\n"
        f'name = "{LIB_NAME}"\n'
    )


LEAN_PRELUDE = '''
open Lean Elab Command

namespace BookVerify

/-- The kind names of trureturing's frozen state files (as in its tools/lean-inspector/Inspector.lean). -/
def declKind : ConstantInfo → String
  | .axiomInfo _ => "axiom"
  | .defnInfo _ => "def"
  | .thmInfo _ => "theorem"
  | .opaqueInfo _ => "opaque"
  | .quotInfo _ => "quotient"
  | .ctorInfo _ => "constructor"
  | .recInfo _ => "recursor"
  | .inductInfo _ => "inductive"

/-- The only axioms a cited declaration may depend on. -/
def standardAxioms : Array Lean.Name := #[``propext, ``Classical.choice, ``Quot.sound]

/-- One declaration from trureturing.lock.json: GID, Lean name, the module it must come from, its kind. -/
structure Cited where
  gid : String
  name : Lean.Name
  module : Lean.Name
  kind : String
'''

LEAN_CHECKS = '''
/-- Checks one cited declaration; logs a ✓ line and returns `#[]` when it passes, else the problems. -/
def checkCited (c : Cited) : CommandElabM (Array String) := do
  let env ← getEnv
  let some ci := env.find? c.name
    | return #[s!"{c.gid}: {c.name} is not in the environment"]
  let mut problems : Array String := #[]
  match env.getModuleIdxFor? c.name with
  | some idx =>
    let actual := env.header.moduleNames[idx.toNat]?
    if actual != some c.module then
      let found := (actual.map toString).getD "?"
      problems := problems.push s!"{c.gid}: {c.name} is declared in {found}, expected {c.module}"
  | none =>
    problems := problems.push s!"{c.gid}: {c.name} is not declared in an imported module"
  let kind := declKind ci
  if kind != c.kind then
    problems := problems.push s!"{c.gid}: {c.name} is a {kind}, but trureturing.lock.json says {c.kind}"
  let axioms ← Lean.collectAxioms c.name
  let extra := axioms.filter fun a => !standardAxioms.contains a
  if !extra.isEmpty then
    let note := if extra.contains ``sorryAx then " (sorryAx: the proof is incomplete)" else ""
    problems := problems.push s!"{c.gid}: {c.name} depends on non-standard axioms {extra}{note}"
  if problems.isEmpty then
    logInfo m!"✓ {c.gid} · {kind} {c.name} · module {c.module} · axioms {axioms}"
  return problems

end BookVerify

run_cmd do
  let mut failures : Array String := #[]
  for c in BookVerify.cited do
    failures := failures ++ (← BookVerify.checkCited c)
  if failures.isEmpty then
    logInfo m!"BookVerify: all {BookVerify.cited.size} cited declaration(s) verified"
  else
    let report := String.intercalate "\\n" failures.toList
    throwError "BookVerify: {failures.size} problem(s) among {BookVerify.cited.size} cited declaration(s):\\n{report}"
'''


def book_verify_lean(lock: lean.Lock, entries: list[dict]) -> str:
    modules = sorted({e["module_name"] for e in entries})
    out = [
        "-- Generated by ./tbook lean-project from trureturing.lock.json; do not edit.",
        f"-- Re-checks the {len(entries)} declaration(s) the books cite, at {lock.repo}@{lock.commit}.",
        "import Lean",
    ]
    out += [f"import {m}" for m in modules]
    out.append(LEAN_PRELUDE.rstrip("\n"))
    out.append("")
    if entries:
        out.append("/-- The cited declarations (names built component-wise; see the comment above each). -/")
        out.append("def cited : Array Cited := #[")
        for i, e in enumerate(entries):
            sep = "," if i + 1 < len(entries) else ""
            out.append(f"  -- {e['gid']}  ↦  {e['name']}")
            out.append(f"  {{ gid := {lean_string(e['gid'])},")
            out.append(f"    name := {name_expr(e['comps'])},")
            out.append(f"    module := {name_expr(e['module_name'].split('.'))},")
            out.append(f"    kind := {lean_string(e['kind'])} }}{sep}")
        out.append("]")
    else:
        out.append("/-- trureturing.lock.json lists no declarations yet. -/")
        out.append("def cited : Array Cited := #[]")
    out.append(LEAN_CHECKS.rstrip("\n"))
    return "\n".join(out) + "\n"


def verify_sh() -> str:
    return (
        "#!/usr/bin/env bash\n"
        "# Generated by ./tbook lean-project: re-check every Lean declaration the books cite.\n"
        "# Needs elan (https://github.com/leanprover/elan); the toolchain comes from lean-toolchain.\n"
        "set -euo pipefail\n"
        'cd "$(dirname "${BASH_SOURCE[0]}")"\n'
        "if ! command -v lake >/dev/null 2>&1; then\n"
        '  echo "verify.sh: lake not found; install elan: curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh" >&2\n'
        "  exit 127\n"
        "fi\n"
        "# Mathlib's prebuilt .olean cache (optional: without it everything is built from source).\n"
        "lake exe cache get || true\n"
        f"lake build {LIB_NAME}\n"
    )


def readme(lock: lean.Lock, toolchain: str, entries: list[dict], citing: dict[str, list[str]]) -> str:
    rows = []
    for e in entries:
        books = ", ".join(citing.get(e["gid"], [])) or "—"
        rows.append(f"| `{e['gid']}` | `{e['name']}` | {e['kind']} | `{e['module_name']}` | {books} |")
    table = "\n".join(rows) if rows else "| — | — | — | — | — |"
    return f"""# BookVerify — deep verification of the cited Lean declarations

Generated by `./tbook lean-project` from `trureturing.lock.json`; do not edit (regenerate instead).

- trureturing: [`{lock.repo}`](https://github.com/{lock.repo}) at
  verification snapshot [`{lock.commit}`](https://github.com/{lock.repo}/tree/{lock.commit})
- Lean toolchain: `{toolchain}` (trureturing's own `lean-toolchain` at that commit)
- Declarations: {len(entries)}

`./tbook check` reads trureturing's frozen ledger (`Golden/Frozen/state`) at each declaration's
evidence commit. For v3 locks, this project's snapshot is resolved once from the followed branch;
legacy locks use their global pinned commit. The declaration evidence commits remain unchanged.
This project asks Lean
itself. `BookVerify.lean` imports every cited module and, for each declaration below, checks that

1. it exists in the environment;
2. it is declared in the module the lock names;
3. its kind (theorem, def, …) is the one the lock records;
4. its axiom closure (`Lean.collectAxioms`) lies within `propext`, `Classical.choice` and
   `Quot.sound` (no `sorryAx`).

Each passing declaration logs a `✓` line; any failure makes `lake build BookVerify` fail with a
list of every problem.

## Run

```bash
./verify.sh              # = lake exe cache get || true; lake build BookVerify
```

This builds the cited trureturing modules (and what they import) from source, with Mathlib's
prebuilt cache when available: expect a long first run. CI runs it weekly and before releases
(`.github/workflows/lean-verify.yml`).

## Declarations

| GID | Lean name | Kind | Module | Cited by |
| --- | --- | --- | --- | --- |
{table}
"""


# --------------------------------------------------------------------------- entry point


def generate(out_dir: str | Path, *, lock: lean.Lock | None = None, ledger: lean.Ledger | None = None,
             toolchain: str | None = None) -> Path:
    """Write the Lake project into ``out_dir`` and return it.

    ``lock`` defaults to ``trureturing.lock.json``; ``toolchain`` defaults to trureturing's
    ``lean-toolchain`` at the verification snapshot, read through ``ledger`` (a :class:`tbook.lean.Ledger`).
    For v3, resolve the followed branch once; legacy locks keep their global pinned commit.
    """
    if lock is None:
        try:
            lock = lean.Lock.load()
        except lean.LeanError as exc:
            raise LeanVerifyError(str(exc)) from exc
        if lock is None:
            raise LeanVerifyError(f"{paths.rel(paths.LOCK_FILE)} not found; run ./tbook pin first")
    if lock.schema == lean.SHARDED_LOCK_SCHEMA:
        # One snapshot of the configured branch supplies the deep-check environment. The
        # evidence shards retain their own immutable source commits.
        commit = lean.ls_remote(lock.repo, f"refs/heads/{lock.branch}")
        lock = replace(lock, commit=commit)
    entries = _entries(lock)
    toolchain = toolchain or read_toolchain(lock, ledger)
    if not TOOLCHAIN_RE.match(toolchain):
        raise LeanVerifyError(f"unexpected Lean toolchain {toolchain!r}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    citing = _citing_books({e["gid"] for e in entries})
    files = {
        "lean-toolchain": toolchain + "\n",
        "lakefile.toml": lakefile_toml(lock),
        f"{LIB_NAME}.lean": book_verify_lean(lock, entries),
        "README.md": readme(lock, toolchain, entries, citing),
        "verify.sh": verify_sh(),
    }
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8", newline="\n")
    script = out / "verify.sh"
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return out
