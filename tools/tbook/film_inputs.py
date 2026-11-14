"""Source scopes of the existing film constructor, without loading build dependencies.

Directories end in '/'; exclusions use the same label fragments as buildcache.Inputs.
Keep file order: video_unit's key interleaves generated values and extra files.
These scopes describe the supported self-contained classic scripts, not arbitrary
network/filesystem reads performed by custom scripts.
"""

ENGINE_LANGUAGES = ("zh", "en")


def video_files(where, *, theme="theme/film", tokens="theme/generated/tokens.mjs", implementation="tools/tbook/film.py"):
    return (
        (where + "/", (f"/{where}/poster.jpg", f"/{where}/README.md", f"/{where}/out/")),
        (theme.rstrip("/") + "/", ("/theme/film/site/",)),
        (tokens, ()),
        (implementation, ()),
    )


def extra_files(scripts, solid, *, core="theme/viz/solid-core.js", vendor="theme/viz/vendor"):
    return tuple((p, ()) for p in scripts) + (
        ((core, ()), (vendor.rstrip("/") + "/", ())) if solid else ()
    )


def engine_sources(book):
    """Provenance of engine_data/_npm_packages, including optional absent overrides.

    Provenance is for change impact; video_unit continues hashing the generated
    values, so unrelated keys in these source files do not alter its output key.
    """
    return (f"books/{book}/book.toml", "trureturing.lock.json", "package-lock.json",
            *(f"{base}/{lang}.toml" for base in ("theme/i18n", "i18n") for lang in ENGINE_LANGUAGES))
