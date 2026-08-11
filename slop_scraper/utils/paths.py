"""
Where the scraper keeps its local working state.

Runtime state — resume cursors, progress logs, the Steam metadata cache — used
to sit loose in the repository root next to the source. Every one of those
files is gitignored individually, which meant the ignore list had to grow a
new entry each time a feature added a file, and a missed entry would commit
operational state into a public repository.

They now live under `_local/state/`, alongside `_local/rollbacks/` and
`_local/cache/`. A single `_local/` ignore rule covers all of it.

Paths are anchored to the repository root rather than the current working
directory, so the same file is used no matter where the scraper is launched
from. `appdetails_cache.json` previously defaulted to a bare relative name,
which meant running from a different directory silently started a second,
empty cache — a bug this move also fixes.

Existing files are migrated on first access, so an in-flight rescan or reheal
keeps its progress rather than starting over.
"""

import os
import shutil

# utils/paths.py -> utils -> slop_scraper -> repo root
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

LOCAL_DIR = os.path.join(PROJECT_ROOT, '_local')
STATE_DIR = os.path.join(LOCAL_DIR, 'state')
CACHE_DIR = os.path.join(LOCAL_DIR, 'cache')
ROLLBACK_DIR = os.path.join(LOCAL_DIR, 'rollbacks')


def _ensure(directory):
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError:
        pass
    return directory


def state_path(filename, legacy_name=None):
    """
    Absolute path to a state file under _local/state/.

    If the file does not exist there yet but a legacy copy is sitting in the
    repository root, the legacy copy is MOVED into place first. Resume state is
    the whole point of these files — silently starting from an empty one would
    re-scrape thousands of games, so migration happens rather than a fresh
    start.
    """
    _ensure(STATE_DIR)
    target = os.path.join(STATE_DIR, filename)

    if not os.path.exists(target):
        legacy = os.path.join(PROJECT_ROOT, legacy_name or filename)
        if os.path.exists(legacy):
            try:
                shutil.move(legacy, target)
                print(f"📦 Moved {os.path.basename(legacy)} → _local/state/")
            except OSError:
                # Migration is a convenience, not a requirement. If it fails,
                # keep using the legacy location rather than losing the state.
                return legacy

    return target


def cache_path(filename):
    """Absolute path to a cache file under _local/cache/, migrating legacy copies."""
    _ensure(CACHE_DIR)
    target = os.path.join(CACHE_DIR, filename)

    if not os.path.exists(target):
        legacy = os.path.join(PROJECT_ROOT, filename)
        if os.path.exists(legacy):
            try:
                shutil.move(legacy, target)
                print(f"📦 Moved {filename} → _local/cache/")
            except OSError:
                return legacy

    return target


def rollback_path(filename):
    """Absolute path for a rollback file under _local/rollbacks/."""
    _ensure(ROLLBACK_DIR)
    return os.path.join(ROLLBACK_DIR, filename)
