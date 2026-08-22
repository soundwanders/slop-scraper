"""
Whether a newly observed engine should replace the one already stored.

`games.engine` is not a display field. game_specific.py maps it to a block of
engine-specific launch options and attaches them, so a wrong engine does not
mislabel a game — it gives that game another engine's flags. Two rounds of
cleanup have already been spent undoing exactly that (`-malloc=system` on 237
games, `-sm4` on 238). A wrong engine is worse than `Unknown`, because
`Unknown` attaches nothing.

Everything here is therefore written to prefer doing nothing.

WHERE ENGINES COME FROM, BEST FIRST

    curated             hand-verified lists in game_specific.py
    pcgamingwiki-page   the game's own wiki page, read at scrape time
    pcgamingwiki        the bulk Cargo table, cached; currently frozen because
                        the endpoint refuses queries
    steam-field         the rare case Steam states it (2 games)

The page outranks the bulk table because both read the same infobox, but the
page is per-game and current while the table is a snapshot that can no longer
be refreshed.

THE RULES

    1. `curated` is never overwritten by anything.
    2. An engine is written when nothing is stored. That is the whole gain.
    3. A stored engine that AGREES is left alone — except that a stored engine
       with no recorded source gains one, since `engine` set with
       `engine_source` NULL is the one combination this project does not trust.
    4. A stored engine that DISAGREES is left alone and reported. Measured
       over 60 games there were zero disagreements — page and table read the
       same infobox — so a conflict means something unmodelled is happening,
       and guessing which side is right is how the earlier bad attachments
       happened.
    5. A page naming several engines is declined. Terraria records XNA and
       FNA; nothing here establishes which applies to the Steam build.
"""

from typing import List, Optional, Tuple

ENGINE_SOURCE_RANK = {
    'curated': 3,
    'pcgamingwiki-page': 2,
    'pcgamingwiki': 1,
    'steam-field': 1,
}

PAGE_SOURCE = 'pcgamingwiki-page'

_NO_ENGINE = ('', 'unknown', 'none', 'null')


def _rank(source: Optional[str]) -> int:
    return ENGINE_SOURCE_RANK.get((source or '').strip().lower(), 0)


def resolve_engine(stored_engine: Optional[str],
                   stored_source: Optional[str],
                   page_engines: List[str]) -> Tuple[Optional[tuple], str]:
    """
    -> (update, reason)

    `update` is (engine, detail, source) to write, or None to leave the row
    alone. `reason` always explains the decision, for logs and for audits.
    """
    try:
        from .pcgw_engines import normalize_engine
    except ImportError:
        from pcgw_engines import normalize_engine

    if not page_engines:
        return None, 'page records no engine'

    if len(page_engines) > 1:
        return None, f'page lists several engines ({", ".join(page_engines)}) — declining'

    family, detail = normalize_engine(page_engines[0])
    if not family:
        return None, f'page value {page_engines[0]!r} does not normalise'

    stored = (stored_engine or '').strip()
    has_stored = stored.lower() not in _NO_ENGINE

    if not has_stored:
        return (family, detail, PAGE_SOURCE), f'stored engine was empty — writing {family!r}'

    if _rank(stored_source) >= ENGINE_SOURCE_RANK['curated']:
        return None, 'stored engine is curated — never overwritten'

    if stored == family:
        if not (stored_source or '').strip():
            return (family, detail, PAGE_SOURCE), 'agrees, and gives the stored label a source'
        return None, 'agrees with stored engine — nothing to change'

    return None, (f'CONFLICT: stored {stored!r} ({stored_source or "no source"}) '
                  f'vs page {family!r} — declining, needs a human')
