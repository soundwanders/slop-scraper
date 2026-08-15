"""
Which Steam App IDs are the same game, according to PCGamingWiki.

Steam publishes one product under several App IDs — a multiplayer component, a
re-release, a bundled edition — and its own API gives no way to tell. Asked
about app 80 and app 100, `appdetails` returns type='game' for both, no
`fullgame` parent on either, and the identical name "Counter-Strike: Condition
Zero". By Steam's own account they are two separate games.

Matching on title instead is not an option. It is the same unbounded-string
mistake that had to be removed from engine detection, and here it would MERGE
CATALOGUE ROWS — a destructive operation driven by a coincidence of naming.
Under a title rule, app 52003 ("Portal") merges into app 400 ("Portal") on no
evidence beyond the word.

PCGamingWiki does record it. One wiki page carries every App ID that page
covers, so the grouping is an editorial statement that these IDs are one game:

    Counter-Strike: Condition Zero   80,100
    Call of Duty: Black Ops II       202970,202990
    Portal 2                         620,659,660,323180,104600
    Portal                           400,323170          <- 52003 absent

That last line is the point. A sourced check declines to merge 52003 because
nothing establishes what it is; a title check would have merged it silently.

This reads the same Cargo table as pcgw_engines.py but keeps a different
projection — every row with a Steam App ID, whether or not an engine is
recorded — so the two caches are separate rather than one being derived from
the other.
"""

import os
import json
import time
import requests

_API = "https://www.pcgamingwiki.com/w/api.php"
_TABLE = "Infobox_game"
_UA = "slop-scraper/1.0 (Steam launch-option metadata; PCGamingWiki Cargo)"

# Only pages listing MORE THAN ONE App ID can establish a duplicate, and the
# comma is what marks them. Filtering server-side rather than downloading
# everything and discarding: the unfiltered query returns ~48,600 rows, this
# one ~5,450. The 43,000 dropped are single-ID pages the grouping code threw
# away anyway, so this costs nothing and turns a multi-minute fetch into a
# few seconds.
_WHERE = "Infobox_game.Steam_AppID__full LIKE '%,%'"
_FIELDS = ("Infobox_game._pageName=Page,"
           "Infobox_game.Steam_AppID__full=AppID")

_PAGE_SIZE = 500
_CACHE_TTL = 7 * 24 * 3600  # a week; a page's App ID list rarely changes


def _cache_path():
    here = os.path.abspath(__file__)
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(repo_root, '_local', 'cache', 'pcgw_appid_groups.json')


def _fetch_page(offset, session, retries=4):
    params = {
        "action": "cargoquery", "format": "json", "tables": _TABLE,
        "fields": _FIELDS, "where": _WHERE,
        "limit": str(_PAGE_SIZE), "offset": str(offset),
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
        f"PCGamingWiki Cargo failed at offset {offset}: {last}. No partial map "
        f"is written — a half-downloaded table would cache for a week and read "
        f"as 'these App IDs are unrelated', which is the answer that silently "
        f"lets duplicates through."
    )


def fetch_appid_groups(force=False, verbose=True):
    """
    {app_id: [page_name, [app_ids...]]} for every Steam game PCGamingWiki lists.

    Every App ID on a page maps to the same group, so two catalogue rows are
    the same game exactly when they land on the same page.
    """
    path = _cache_path()
    if not force and os.path.exists(path):
        try:
            age = time.time() - os.path.getmtime(path)
            if age < _CACHE_TTL:
                with open(path) as f:
                    cached = json.load(f)
                if verbose:
                    print(f"   📦 PCGamingWiki App ID groups from cache "
                          f"({len(cached)} app IDs, {age/3600:.0f}h old)")
                return {int(k): (v[0], v[1]) for k, v in cached.items()}
        except Exception:
            pass

    if verbose:
        print("   🌐 Downloading PCGamingWiki App ID table...")

    rows, offset = [], 0
    session = requests.Session()
    while True:
        batch = _fetch_page(offset, session)
        rows.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
        time.sleep(0.4)

    groups = {}
    for row in rows:
        entry = row.get('title', {})
        page = str(entry.get('Page') or '').strip()
        raw = str(entry.get('AppID') or '')
        ids = sorted({int(i.strip()) for i in raw.split(',') if i.strip().isdigit()})
        if len(ids) < 2 or not page:
            # A page listing one App ID cannot establish a duplicate, so it is
            # not stored. Keeping it would bloat the cache with the ~90% of
            # pages that say nothing about this question.
            continue
        for app_id in ids:
            existing = groups.get(app_id)
            if existing is None or len(ids) < len(existing[1]):
                # Prefer the tightest grouping when two pages claim an ID —
                # the narrower page is describing that product more precisely.
                groups[app_id] = (page, ids)

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump({str(k): [v[0], v[1]] for k, v in groups.items()}, f)
    except Exception as e:
        if verbose:
            print(f"   ⚠️ could not write group cache ({e}) — continuing")

    if verbose:
        print(f"   ✅ {len(groups)} app IDs in multi-ID groups, "
              f"from {len(rows)} wiki rows")
    return groups
