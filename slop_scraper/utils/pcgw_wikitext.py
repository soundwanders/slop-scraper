"""
Facts read directly out of a PCGamingWiki page's wikitext.

The scraper already downloads this wikitext for every game it looks up, to
parse launch options out of it. Two other facts are sitting in the same
document and were being sourced from elsewhere, or not at all:

WHICH GAME THE PAGE IS ABOUT
    Every infobox states `steam appid = 440`, plus `steam appid side` for
    editions and bundles that share a page. That is an exact identity check.

    It matters because page lookup lost its exact path. PCGamingWiki's Cargo
    API — which resolved a page by Steam App ID — now answers "You don't have
    permission to run arbitrary Cargo queries", so the scraper falls back to
    full-text title search and takes the first hit unverified. Measured
    against live pages, that resolves "Fallout 4" to *Fallout 4 VR* and
    "Portal 2" to *Portal 2 Sixense Perceptual Pack*. Matching a game by the
    shape of its title is the unbounded-string mistake this codebase has
    removed twice; this is how it gets removed a third time, using the App ID
    the page itself declares.

WHICH ENGINE IT RECORDS
    `{{Infobox game/row/engine|Source}}`. Previously read only through the
    same closed Cargo endpoint, via a bulk table cached for a week — so a
    game's engine could not be learned at scrape time at all.

Both are pure parsing. Nothing here fetches anything.
"""

import re
from typing import List, Set

# "steam appid  = 440" — the row may or may not carry a leading pipe.
_APPID = re.compile(r'^\s*\|?\s*steam[ _]appid\s*=\s*([0-9,\s]*)$', re.I | re.M)
# "steam appid side = 202485,211720,220760" — other App IDs the page covers.
_APPID_SIDE = re.compile(r'^\s*\|?\s*steam[ _]appid[ _]side\s*=\s*([0-9,\s]*)$', re.I | re.M)
# "{{Infobox game/row/engine|Source}}" — the value ends at '|' or '}'.
_ENGINE = re.compile(r'\{\{\s*Infobox game/row/engine\s*\|\s*([^}|\n]+)')

_NOT_AN_ENGINE = {'unknown', 'n/a', 'na', 'none', ''}


def _ids(raw: str) -> Set[int]:
    return {int(c) for c in re.split(r'[,\s]+', raw or '') if c.strip().isdigit()}


def parse_page_appids(wikitext: str) -> Set[int]:
    """Every Steam App ID the page claims to cover — main row plus side rows."""
    ids: Set[int] = set()
    for pattern in (_APPID, _APPID_SIDE):
        for match in pattern.finditer(wikitext or ''):
            ids |= _ids(match.group(1))
    return ids


def parse_page_engines(wikitext: str) -> List[str]:
    """
    Distinct engine strings the page records, in order of appearance.

    A page may repeat the row (Team Fortress 2 lists Source twice) — that is
    one engine. A page may also list genuinely different engines (Terraria
    records XNA *and* FNA), and the caller is expected to decline rather than
    pick one.
    """
    seen, out = set(), []
    for match in _ENGINE.finditer(wikitext or ''):
        value = match.group(1).strip()
        # "[[Engine:Source|Source]]" -> "Source"
        value = re.sub(r'^\[\[(?:Engine:)?([^\]|]+)(?:\|[^\]]*)?\]\]$', r'\1', value).strip()
        if value.lower().startswith('engine:'):
            value = value[len('engine:'):].strip()
        if value.lower() in _NOT_AN_ENGINE:
            continue
        if value.lower() not in seen:
            seen.add(value.lower())
            out.append(value)
    return out


def page_covers_app(wikitext: str, app_id) -> bool:
    """
    True only when the page states this exact App ID.

    Deliberately has no title fallback. A page that names no App ID — a
    redirect stub, a disambiguation page — returns False, because "this page
    does not say which game it is" is not evidence that it is the right one.
    """
    try:
        return int(app_id) in parse_page_appids(wikitext)
    except (TypeError, ValueError):
        return False
