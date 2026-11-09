"""Availability of the repository's example books for integration tests."""

from tbook import config, paths


def example_shown(slug: str = "example-monograph") -> bool:
    """Hidden books may have neither declarations nor their original commit in the live lock."""
    try:
        return (paths.BOOKS / slug).is_dir() and not config.load_site().hidden_by(slug)
    except config.ConfigError:
        return False
    finally:
        config.load_site.cache_clear()
