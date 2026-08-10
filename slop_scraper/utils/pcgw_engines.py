"""
Engine metadata from PCGamingWiki's Cargo API, keyed by Steam App ID.

Why this exists
---------------
Steam's `appdetails` endpoint carries no engine field at all — 41 keys, none
engine-related. A full backfill over 2,367 games produced 2 engine detections,
which is the ceiling of what Steam can tell us, not a bug in the caller.

Two "external" lookups were supposed to cover that gap and could not:

  * `_check_steamdb` scraped steamdb.info HTML, which is Cloudflare-protected
    and disallows scraping. It never returned a result.
  * `_check_pcgamingwiki` asked the MediaWiki API for `prop=extracts&exintro`,
    the article's INTRO PROSE. PCGamingWiki keeps engine data in the infobox,
    which that endpoint never returns. Right site, wrong question.

Both cost ~2.4s per game, so roughly half of a 65-minute backfill was spent on
requests structurally incapable of answering.

PCGamingWiki does expose the infobox — through Cargo, its structured-data
query API. `Infobox_game.Engines` is keyed by `Infobox_game.Steam_AppID`, so
the whole table can be pulled in bulk and queried offline:

    16,156 wiki rows -> 26,860 Steam App IDs, in about 20 seconds.

That is one bulk fetch for the entire catalogue rather than a request per
game, which is both far faster and far kinder to the wiki.

Naming
------
PCGamingWiki returns precise names ('Unreal Engine 4', 'id Tech 3'). Callers
get both halves:

    family  -> 'Unreal Engine'      stable, small vocabulary, good for filters
    detail  -> 'Unreal Engine 4'    verbatim, good for display

Version numbers are folded into the family, but genuinely distinct engines are
never folded together. Source, Source 2 and GoldSrc stay separate: they are
different engines that accept different launch options, which is the entire
subject of this database.
"""

import os
import re
import json
import time
import requests

_API = "https://www.pcgamingwiki.com/w/api.php"
_TABLE = "Infobox_game"
_UA = "slop-scraper/1.0 (Steam launch-option metadata; PCGamingWiki Cargo)"

# List-typed Cargo fields need the __full suffix in a WHERE clause; the bare
# name is a "virtual field" and the API rejects operators on it.
_WHERE = "Infobox_game.Engines__full <> '' AND Infobox_game.Steam_AppID__full <> ''"
_FIELDS = ("Infobox_game.Steam_AppID__full=AppID,"
           "Infobox_game.Engines__full=Engines")

_PAGE_SIZE = 500
_CACHE_TTL = 7 * 24 * 3600  # a week; engines effectively never change


def _cache_path():
    # this file is <repo>/slop_scraper/utils/pcgw_engines.py, so the repo root
    # is three levels up — utils -> slop_scraper -> repo.
    here = os.path.abspath(__file__)
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(repo_root, '_local', 'cache', 'pcgw_engines.json')


# --- name normalisation --------------------------------------------------

# Exact renames onto the vocabulary this catalogue already uses, so PCGW's
# 'Unity' does not sit alongside our pre-existing 'Unity Engine' as if they
# were two different things.
_EXACT = {
    'unity': 'Unity Engine',
    'source': 'Source Engine',
    'source 2': 'Source 2',
    'goldsrc': 'GoldSrc',
    'gamemaker': 'GameMaker Studio',
    'gamemaker studio': 'GameMaker Studio',
    'godot': 'Godot Engine',
    'quake engine': 'id Tech',
    'wolfenstein 3d engine': 'id Tech',
}

# Version-suffixed families. Order matters: the first match wins, so anything
# that must NOT be folded (Source 2) is handled in _EXACT above and by the
# negative lookahead here.
_FAMILIES = (
    (r'^unreal engine\b', 'Unreal Engine'),
    (r'^id tech\b', 'id Tech'),
    (r'^cryengine\b', 'CryEngine'),
    (r'^frostbite\b', 'Frostbite Engine'),
    (r'^gamebryo\b', 'Gamebryo'),
    (r'^creation engine\b', 'Creation Engine'),
    (r'^glacier\b', 'Glacier'),
    (r'^lithtech\b', 'LithTech'),
    (r'^torque\b', 'Torque'),
    (r'^avalanche engine\b', 'Avalanche Engine'),
    (r'^gem\b', 'GEM'),
    (r'^playground sdk\b', 'PlayGround SDK'),
    (r'^cocos2d\b', 'Cocos2d'),
    (r'^hedgehog engine\b', 'Hedgehog Engine'),
    (r'^kirikiri\b', 'KiriKiri'),
    (r'^giants engine\b', 'GIANTS Engine'),
    (r'^dunia\b', 'Dunia'),
    (r'^geo-mod\b', 'Geo-Mod'),
    (r'^sage\b', 'SAGE'),
    (r'^divinity\b', 'Divinity Engine'),
    (r'^isimotor\b', 'isiMotor'),
    (r'^construct\b', 'Construct'),
    (r'^phoenix engine\b', 'Phoenix Engine'),
    (r'^vicious engine\b', 'Vicious Engine'),
    (r'^voxel space\b', 'Voxel Space'),
    (r'^storm3d\b', 'Storm3D'),
)


def normalize_engine(name: str):
    """
    PCGW engine string -> (family, detail).

    detail is the wiki's own wording, cleaned of the 'Engine:' namespace
    prefix. family collapses version numbers so the value is usable as a
    filter facet.
    """
    if not name:
        return None, None
    detail = str(name).strip()
    if detail.startswith('Engine:'):
        detail = detail[len('Engine:'):].strip()
    if not detail:
        return None, None

    key = detail.lower()
    if key in _EXACT:
        return _EXACT[key], detail

    for pattern, family in _FAMILIES:
        if re.match(pattern, key):
            return family, detail

    # Long tail: hundreds of one-off proprietary engines (Clausewitz, MT
    # Framework, PopCap Games Framework...). They are already the family.
    return detail, detail


# --- fetching ------------------------------------------------------------

def _fetch_page(offset, session, retries=4):
    params = {
        "action": "cargoquery",
        "format": "json",
        "tables": _TABLE,
        "fields": _FIELDS,
        "where": _WHERE,
        "limit": str(_PAGE_SIZE),
        "offset": str(offset),
    }
    last = None
    for attempt in range(retries + 1):
        try:
            response = session.get(_API, params=params, timeout=40,
                                   headers={'User-Agent': _UA})
            if response.status_code == 200:
                payload = response.json()
                if 'error' in payload:
                    raise RuntimeError(payload['error'].get('info', 'cargo error'))
                return payload.get('cargoquery', [])

            if response.status_code == 429:
                # The wiki is asking us to slow down, and it means it. Honour
                # Retry-After when given, otherwise back off far harder than
                # for an ordinary error — a tight retry here is what earns a
                # longer ban.
                try:
                    wait = int(response.headers.get('Retry-After', ''))
                except ValueError:
                    wait = 0
                wait = max(wait, 20 * (attempt + 1))
                last = "HTTP 429 (rate limited)"
                if attempt < retries:
                    time.sleep(wait)
                continue

            last = f"HTTP {response.status_code}"
        except Exception as e:
            last = str(e)
        if attempt < retries:
            time.sleep(3 * (attempt + 1))

    raise RuntimeError(
        f"PCGamingWiki Cargo failed at offset {offset}: {last}. "
        f"No partial map is written — a half-downloaded table would cache for "
        f"a week and read as 'engine unknown' for every missing game."
    )


def fetch_engine_map(force=False, verbose=True):
    """
    {app_id: (family, detail)} for every Steam game PCGamingWiki documents.

    Cached on disk for a week. Engines do not change after release, so the
    only reason to refetch is to pick up newly documented games.
    """
    path = _cache_path()
    if not force and os.path.exists(path):
        try:
            age = time.time() - os.path.getmtime(path)
            if age < _CACHE_TTL:
                with open(path) as f:
                    cached = json.load(f)
                if verbose:
                    print(f"   📦 PCGamingWiki engine map from cache "
                          f"({len(cached)} app IDs, {age/3600:.0f}h old)")
                return {int(k): tuple(v) for k, v in cached.items()}
        except Exception:
            pass  # unreadable cache is not fatal, just refetch

    if verbose:
        print("   🌐 Downloading PCGamingWiki engine table...")

    rows, offset = [], 0
    session = requests.Session()
    while True:
        batch = _fetch_page(offset, session)
        rows.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
        time.sleep(0.4)  # be a good citizen

    # app_id -> (specificity, (family, detail)). Lower specificity wins.
    staged = {}

    for row in rows:
        entry = row.get('title', {})
        app_ids = str(entry.get('AppID') or '')
        engines = str(entry.get('Engines') or '')

        candidates = []
        for part in engines.split(','):
            family, detail = normalize_engine(part)
            if family and (family, detail) not in candidates:
                candidates.append((family, detail))
        if not candidates:
            continue

        families = {family for family, _ in candidates}
        if len(families) == 1:
            # One family, possibly several versions ('Source' + 'Source 2' are
            # different families and will not land here; 'Unreal Engine 3' +
            # 'Unreal Engine 4' would). Take the last, which is the version the
            # game ended up on.
            chosen = candidates[-1]
        else:
            # Genuinely several DIFFERENT engines on one page. There is no
            # reliable ordering convention to lean on: Dota 2 lists
            # 'Source, Source 2' chronologically (last is current), while
            # Borderlands 2 lists 'Unreal Engine 3, XNA' where the first is
            # the game engine and the second is an ancillary component.
            # Guessing either way mislabels the other, so we decline and let
            # the curated table or the existing value stand.
            continue

        # A wiki page can list dozens of app IDs — Borderlands 2 covers 48,
        # mostly DLC and bundles. A page listing ONE app ID is describing that
        # exact product, so it is the more trustworthy source when two pages
        # claim the same ID. That is what separates 'Counter-Strike 2' (one
        # ID) from 'Counter-Strike: Global Offensive' (two), which both claim
        # app 730 and would otherwise resolve by dict-iteration order.
        ids = [i.strip() for i in app_ids.split(',') if i.strip().isdigit()]
        specificity = len(ids)

        for raw_id in ids:
            app_id = int(raw_id)
            existing = staged.get(app_id)
            if existing is None or specificity < existing[0]:
                staged[app_id] = (specificity, chosen)
            elif specificity == existing[0] and existing[1] != chosen:
                # Two equally specific pages disagree — no basis to choose.
                staged[app_id] = (specificity, None)

    engine_map = {app_id: value for app_id, (_, value) in staged.items()
                  if value is not None}

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump({str(k): list(v) for k, v in engine_map.items()}, f)
    except Exception as e:
        if verbose:
            print(f"   ⚠️ could not write engine cache ({e}) — continuing")

    if verbose:
        print(f"   ✅ {len(engine_map)} app IDs from {len(rows)} wiki rows")
    return engine_map


_MEMO = None


def lookup_engine(app_id):
    """
    (family, detail) for one Steam App ID, or (None, None).

    Loads the whole map on first use. Callers doing a whole catalogue should
    prefer fetch_engine_map() directly and index it themselves.
    """
    global _MEMO
    if _MEMO is None:
        try:
            _MEMO = fetch_engine_map(verbose=False)
        except Exception:
            _MEMO = {}
    try:
        return _MEMO.get(int(app_id), (None, None))
    except (TypeError, ValueError):
        return None, None
