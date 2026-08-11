"""
Steam Game List Fetcher with Efficient Filtering
"""

import os
import requests
import time
import re
import unicodedata
from tqdm import tqdm

try:
    from ..utils.extract_engine import extract_engine
    from ..utils.dates import normalize_release_date
except ImportError:
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.extract_engine import extract_engine
    from utils.dates import normalize_release_date

def get_steam_game_list(limit=100, force_refresh=False, cache=None, test_mode=False, 
                       debug=False, cache_file=None, rate_limiter=None, 
                       session_monitor=None, db_client=None, skip_existing=True, 
                       db_client_wrapper=None):
    """
    Fetch Steam game list with optional filtering of existing games
    """
    
    print(f"🎮 Fetching Steam game list (limit={limit}, force_refresh={force_refresh})")
    
    # Get existing games from database to avoid duplicates
    existing_app_ids = set()
    if skip_existing:
        print("🔍 Skip existing games: ✅")
        
        if db_client_wrapper:
            existing_app_ids = db_client_wrapper.get_smart_existing_app_ids(skip_existing=True)
        elif db_client:
            try:
                from ..database.supabase import get_smart_existing_games
                existing_app_ids = get_smart_existing_games(db_client, skip_existing=True)
            except ImportError:
                from database.supabase import get_smart_existing_games
                existing_app_ids = get_smart_existing_games(db_client, skip_existing=True)
                
        print(f"📊 Found {len(existing_app_ids)} existing games in database")
    else:
        print("🔍 Processing all games (skip existing: ❌)")

    # Get cached games for efficiency
    cached_app_ids = set()
    if cache:
        cached_app_ids = {int(app_id) for app_id in cache.keys() if cache.get(app_id)}
        print(f"💾 Found {len(cached_app_ids)} games in cache")
    
    # Combine existing and cached IDs to skip. The cache only proves we fetched
    # a game's metadata, not that its options were scraped — so cached games are
    # only skipped when skip_existing is on; --no-skip-existing processes them.
    skip_app_ids = existing_app_ids | (cached_app_ids if skip_existing else set())
    
    if test_mode and limit <= 10:
        print("🧪 Using test data for small limits")
        return get_test_games(limit, skip_app_ids, cache, debug, rate_limiter, session_monitor)

    # Fetch complete Steam app list
    print("📥 Fetching Steam app list...")
    all_apps = fetch_steam_app_list(rate_limiter, session_monitor, debug)
    
    if not all_apps:
        # Steam API is unavailable — fall back to games already in our database
        # that have zero options. This is actually the ideal population to target.
        if db_client or db_client_wrapper:
            client = db_client_wrapper.supabase if db_client_wrapper else db_client
            print("⚠️ Steam API unavailable — falling back to DB games with 0 options")
            db_games = _get_unprocessed_games_from_db(client, limit, existing_app_ids, debug)
            if db_games:
                print(f"✅ Found {len(db_games)} unprocessed games in database")
                return db_games
        print("❌ Failed to fetch Steam app list")
        return []

    # Filter out games we already have
    print(f"🔍 Filtering {len(all_apps)} apps (removing {len(skip_app_ids)} existing/cached games)...")

    candidate_apps = [app for app in all_apps if app['appid'] not in skip_app_ids]

    print(f"✅ Found {len(candidate_apps)} NEW games to potentially process")

    if not candidate_apps:
        print("⚠️ No new games found to process")
        return []

    # Apply quality filtering and fetch metadata for new games only
    filtered_games = process_candidate_games(
        candidate_apps,
        limit,
        cache,
        debug,
        rate_limiter,
        session_monitor,
        force_refresh
    )

    return filtered_games


def _get_unprocessed_games_from_db(db_client, limit, skip_app_ids, debug=False):
    """
    Query our own database for games with total_options_count = 0.
    Used as a fallback when the Steam app list API is unavailable.
    Games already in our DB have all the metadata we need (title, developer, etc.).
    """
    try:
        response = (
            db_client.table("games")
            .select("app_id, title, developer, publisher, release_date, engine")
            .eq("total_options_count", 0)
            .limit(limit * 5)
            .execute()
        )

        games = []
        for row in (response.data or []):
            if row['app_id'] not in skip_app_ids:
                games.append({
                    'appid': row['app_id'],
                    'name': row['title'],
                    'developer': row.get('developer') or '',
                    'publisher': row.get('publisher') or '',
                    'release_date': row.get('release_date') or '',
                    'engine': row.get('engine') or 'Unknown',
                })
            if len(games) >= limit:
                break

        if debug:
            print(f"🔍 DB fallback: found {len(games)} games with 0 options to process")

        return games

    except Exception as e:
        print(f"⚠️ DB fallback query failed: {e}")
        return []

def fetch_steam_app_list(rate_limiter, session_monitor, debug):
    """
    Fetch a Steam app list for new-game discovery.

    Valve deprecated the keyless ISteamApps/GetAppList endpoints (404 since
    mid-2026), so the chain is:
      1. Legacy endpoints (cheap to try in case they come back)
      2. IStoreService/GetAppList — official replacement, needs STEAM_API_KEY
      3. SteamSpy — keyless, ordered by owner count, so the most-played games
         (the ones people actually search launch options for) come first
    """
    candidate_urls = [
        "https://api.steampowered.com/ISteamApps/GetAppList/v2/",
        "https://api.steampowered.com/ISteamApps/GetAppList/v0002/",
        "https://store.steampowered.com/api/ISteamApps/GetAppList/v2/",
    ]

    if rate_limiter:
        rate_limiter.wait_if_needed("steam_api")

    for url in candidate_urls:
        try:
            if debug:
                print(f"📥 Trying Steam app list URL: {url}")

            response = requests.get(url, timeout=30)

            if session_monitor:
                session_monitor.record_request()

            if response.status_code != 200:
                if debug:
                    print(f"⚠️ {url} returned {response.status_code}, trying next...")
                continue

            data = response.json()
            all_apps = data.get('applist', {}).get('apps', [])

            if all_apps:
                if debug:
                    print(f"📊 Retrieved {len(all_apps)} total Steam apps from {url}")
                return all_apps

        except requests.exceptions.RequestException as e:
            print(f"⚠️ Error fetching Steam app list from {url}: {e}")
            continue

    apps = _fetch_applist_istoreservice(rate_limiter, session_monitor, debug)
    if apps:
        return apps

    apps = _fetch_applist_steamspy(rate_limiter, session_monitor, debug)
    if apps:
        return apps

    print("❌ All Steam app list endpoints failed")
    return []


def _fetch_applist_istoreservice(rate_limiter, session_monitor, debug):
    """Official GetAppList replacement — requires a (free) Steam Web API key."""
    api_key = os.getenv('STEAM_API_KEY')
    if not api_key:
        if debug:
            print("ℹ️ STEAM_API_KEY not set — skipping IStoreService (get a free key at steamcommunity.com/dev/apikey)")
        return []

    apps = []
    last_appid = 0
    try:
        # Paginate; cap pages defensively
        for _ in range(10):
            if rate_limiter:
                rate_limiter.wait_if_needed("steam_api")

            response = requests.get(
                "https://api.steampowered.com/IStoreService/GetAppList/v1/",
                params={
                    "key": api_key,
                    "include_games": "true",
                    "include_dlc": "false",
                    "include_software": "false",
                    "max_results": 50000,
                    "last_appid": last_appid,
                },
                timeout=30
            )
            if session_monitor:
                session_monitor.record_request()

            if response.status_code != 200:
                if debug:
                    print(f"⚠️ IStoreService returned {response.status_code}")
                break

            payload = response.json().get('response', {})
            batch = payload.get('apps', [])
            apps.extend({'appid': a['appid'], 'name': a.get('name', '')} for a in batch)

            if not payload.get('have_more_results'):
                break
            last_appid = payload.get('last_appid', 0)

        if apps:
            print(f"📊 Retrieved {len(apps)} apps from IStoreService")
        return apps

    except Exception as e:
        print(f"⚠️ IStoreService app list failed: {e}")
        return apps


# SteamSpy's "all" request is paginated: each page is a STATIC, fixed slice
# of ~1000 games (page 0 is always the same top-1000-by-owners, page 1 the
# next 1000, etc. — confirmed zero overlap between consecutive pages).
# Pages 0-86 return data (~87,000 games total); page 87+ is empty.
# Fetching only page 0 every run meant discovery permanently dried up once
# those 1000 games were absorbed into the database. A persisted cursor
# advances through the catalog on each run instead, wrapping around after
# the last page so the scraper never runs out of games to consider.
STEAMSPY_MAX_PAGE = 86
STEAMSPY_PAGES_PER_RUN = 3  # ~3000 apps/run is plenty of new-candidate headroom

try:
    from utils.paths import state_path as _state_path
except ImportError:
    from ..utils.paths import state_path as _state_path

STEAMSPY_CURSOR_FILE = _state_path('steamspy_page_cursor.json')


def _load_steamspy_cursor():
    import json
    try:
        if os.path.exists(STEAMSPY_CURSOR_FILE):
            with open(STEAMSPY_CURSOR_FILE) as f:
                return json.load(f).get('next_page', 0)
    except Exception:
        pass
    return 0


def _save_steamspy_cursor(next_page):
    import json
    try:
        with open(STEAMSPY_CURSOR_FILE, 'w') as f:
            json.dump({'next_page': next_page}, f)
    except Exception as e:
        print(f"⚠️ Could not save SteamSpy page cursor: {e}")


def _fetch_applist_steamspy(rate_limiter, session_monitor, debug):
    """
    Keyless fallback via SteamSpy, paging through the catalog across runs.

    Each run fetches STEAMSPY_PAGES_PER_RUN pages starting from wherever the
    last run left off (steamspy_page_cursor.json), then advances the cursor
    so the next run picks up fresh pages instead of re-requesting the same
    already-exhausted slice.
    """
    start_page = _load_steamspy_cursor()
    apps = []
    page = start_page

    for i in range(STEAMSPY_PAGES_PER_RUN):
        try:
            if rate_limiter:
                rate_limiter.wait_if_needed("scraping", domain="steamspy.com")
            elif i > 0:
                time.sleep(1)  # be polite between our own sequential page requests

            response = requests.get(
                "https://steamspy.com/api.php",
                params={"request": "all", "page": page},
                timeout=30
            )
            if session_monitor:
                session_monitor.record_request()

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and data:
                    page_apps = [
                        {'appid': int(app_id), 'name': info.get('name', '')}
                        for app_id, info in data.items()
                        if isinstance(info, dict) and info.get('name')
                    ]
                    apps.extend(page_apps)
                    if debug:
                        print(f"📥 SteamSpy page {page}: {len(page_apps)} apps")
            elif debug:
                print(f"⚠️ SteamSpy page {page} returned {response.status_code}")

        except Exception as e:
            if debug:
                print(f"⚠️ SteamSpy page {page} failed: {e}")

        page = (page + 1) % (STEAMSPY_MAX_PAGE + 1)

    _save_steamspy_cursor(page)

    if apps:
        print(f"📊 Retrieved {len(apps)} apps from SteamSpy "
              f"(pages {start_page}-{(start_page + STEAMSPY_PAGES_PER_RUN - 1) % (STEAMSPY_MAX_PAGE + 1)}, "
              f"next run starts at page {page})")
    return apps

# Scripts that indicate a genuinely non-Latin title (Vanilla Slops is an
# English-language site). Deliberately narrow: symbols/punctuation/accented
# Latin are NOT included, so legitimate Western titles using (R)/(TM) or
# accented characters (Nancy Drew(R), Cesar, etc.) are never rejected. An
# earlier version of this check used `[^\x00-\x7F]` (any non-ASCII byte),
# which would have wrongly flagged ~15% of the real catalog on trademark
# symbols alone — see slop-scraper issue: '救済の日' slipped through instead,
# because that check only ran on the pre-fetch discovery name, not the
# final officially-fetched Steam name that actually gets saved.
_NON_LATIN_SCRIPT_MARKERS = (
    'CJK', 'HIRAGANA', 'KATAKANA', 'HANGUL', 'CYRILLIC', 'ARABIC',
    'HEBREW', 'THAI', 'DEVANAGARI', 'GREEK'
)


def _has_non_latin_script(title):
    """True if the title contains characters from a non-Latin script."""
    if not title:
        return False
    for ch in title:
        if ord(ch) < 128:
            continue
        try:
            char_name = unicodedata.name(ch)
        except ValueError:
            continue
        if any(marker in char_name for marker in _NON_LATIN_SCRIPT_MARKERS):
            return True
    return False


def process_candidate_games(candidate_apps, limit, cache, debug, rate_limiter, session_monitor, force_refresh):
    """Process candidate games with quality filtering and metadata fetching"""

    # Quality filtering patterns
    blocklist_terms = [
        'dlc', 'soundtrack', 'beta', 'demo', 'test', 'adult', 'hentai',
        'xxx', 'mature', 'expansion', 'tool', 'software'
    ]

    blocklist_pattern = re.compile(r'(?i)(' + '|'.join(re.escape(term) for term in blocklist_terms) + ')')
    only_numeric_special = re.compile(r'^[0-9\s\-_+=.,!@#$%^&*()\[\]{}|\\/<>?;:\'"`~]*$')
    
    # High-priority games to process first
    priority_keywords = [
        'counter-strike', 'dota', 'team fortress', 'half-life', 'portal',
        'final fantasy', 'dark souls', 'witcher', 'cyberpunk'
    ]
    
    # Stable sort: priority keywords first, otherwise preserve source order.
    # The app list is ordered most-owned-first (SteamSpy/IStoreService), and
    # alphabetizing it would bury popular games behind shovelware again.
    sorted_candidates = sorted(candidate_apps, key=lambda x: (
        -any(keyword in x['name'].lower() for keyword in priority_keywords),
    ))
    
    filtered_games = []
    
    with tqdm(total=min(limit * 3, len(sorted_candidates)), desc="Processing candidate games") as pbar:
        for app in sorted_candidates:
            if len(filtered_games) >= limit:
                break
                
            app_id = app['appid']
            name = app['name']
            
            pbar.update(1)
            
            # Basic quality filtering
            if not name or len(name) < 3 or len(name) > 100:
                continue
                
            if (blocklist_pattern.search(name) or
                    _has_non_latin_script(name) or
                    only_numeric_special.match(name)):
                continue
            
            # Fetch detailed metadata
            enriched_game = fetch_game_metadata(
                app_id, 
                name, 
                cache, 
                debug, 
                rate_limiter, 
                session_monitor, 
                force_refresh
            )
            
            if enriched_game:
                filtered_games.append(enriched_game)
                if debug:
                    pbar.write(f"✅ Added: {name}")
    
    print(f"✅ Successfully processed {len(filtered_games)} games with complete metadata")
    return filtered_games

def fetch_game_metadata(app_id, name, cache, debug, rate_limiter, session_monitor, force_refresh):
    """Fetch detailed metadata for a single game from Steam Store API"""
    
    # Check cache first unless forcing refresh
    if not force_refresh and str(app_id) in cache and cache[str(app_id)]:
        store_data = cache[str(app_id)]
        if debug:
            print(f"💾 Using cached data for {name}")
    else:
        # Fetch from Steam Store API
        store_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=us&l=en"
        
        if rate_limiter:
            rate_limiter.wait_if_needed("steam_api")
        
        try:
            response = requests.get(store_url, timeout=10)
            if session_monitor:
                session_monitor.record_request()
                
            if response.status_code == 200:
                data = response.json()
                if str(app_id) in data and data[str(app_id)].get('success'):
                    store_data = data[str(app_id)]['data']
                    cache[str(app_id)] = store_data
                else:
                    if debug:
                        print(f"⚠️ No store data for {name} ({app_id})")
                    return None
            else:
                if debug:
                    print(f"⚠️ Store API error {response.status_code} for {name}")
                return None
                
            time.sleep(0.3)  # Rate limiting
            
        except Exception as e:
            if debug:
                print(f"⚠️ Error fetching store data for {name}: {e}")
            return None
    
    if not store_data:
        return None
    
    # Validation checks
    if store_data.get("type") != "game":
        return None
    if store_data.get("release_date", {}).get("coming_soon", False):
        return None

    official_name = store_data.get("name", name)

    # Authoritative non-Latin-script check: the pre-fetch filter in
    # process_candidate_games only sees the discovery source's name, which
    # can differ from Steam's own official name (e.g. a blank/placeholder
    # name from a bulk listing vs. the real title once we ask Steam
    # directly). This check runs on the name that actually gets saved, so
    # it can't be bypassed by a source/official name mismatch.
    if _has_non_latin_script(official_name):
        if debug:
            print(f"⚠️ Rejecting non-Latin-script title: {official_name!r} ({app_id})")
        return None

    # Extract complete metadata
    enriched_game = {
        "appid": app_id,
        "name": official_name,
        "developer": extract_developer_safely(store_data),
        "publisher": extract_publisher_safely(store_data),
        "release_date": normalize_release_date(extract_release_date_safely(store_data)),
        "engine": extract_engine_safely(store_data, app_id)
    }

    return enriched_game

def get_test_games(limit, skip_app_ids, cache, debug, rate_limiter, session_monitor):
    """Get test games with metadata for development/testing"""
    test_games = [
        {"appid": 570, "name": "Dota 2"},
        {"appid": 730, "name": "Counter-Strike 2"},
        {"appid": 264710, "name": "Subnautica"},
        {"appid": 377840, "name": "Final Fantasy IX"},
        {"appid": 1868140, "name": "Dave the Diver"},
    ]
    
    # Filter out existing games
    test_games = [game for game in test_games if game['appid'] not in skip_app_ids][:limit]
    
    # Enrich with metadata
    enriched_games = []
    for game in test_games:
        enriched_game = fetch_game_metadata(
            game['appid'], 
            game['name'], 
            cache, 
            debug, 
            rate_limiter, 
            session_monitor, 
            False
        )
        if enriched_game:
            enriched_games.append(enriched_game)
    
    return enriched_games

# Helper functions for metadata extraction
def extract_developer_safely(game_info):
    """Safely extract developer information"""
    try:
        developers = game_info.get('developers', [])
        if isinstance(developers, list) and developers:
            return developers[0]
        elif isinstance(developers, str):
            return developers
        return ''
    except Exception:
        return ''

def extract_publisher_safely(game_info):
    """Safely extract publisher information"""
    try:
        publishers = game_info.get('publishers', [])
        if isinstance(publishers, list) and publishers:
            return publishers[0]
        elif isinstance(publishers, str):
            return publishers
        return ''
    except Exception:
        return ''

def extract_release_date_safely(game_info):
    """Safely extract release date"""
    try:
        release_info = game_info.get('release_date', {})
        if isinstance(release_info, dict):
            return release_info.get('date', '')
        return ''
    except Exception:
        return ''

def extract_engine_safely(game_info, app_id=None):
    """Extract game engine using enhanced detection"""
    try:
        return extract_engine(game_info, app_id)
    except Exception:
        # Fallback to basic detection
        return basic_engine_detection(game_info)

def basic_engine_detection(game_info):
    """Basic engine detection fallback"""
    name = game_info.get('name', '').lower()
    developers = game_info.get('developers', [])
    
    if isinstance(developers, list):
        dev_text = ' '.join(developers).lower()
    else:
        dev_text = str(developers).lower()
    
    # Basic engine patterns
    if 'valve' in dev_text or any(game in name for game in ['counter-strike', 'dota', 'team fortress']):
        return 'Source Engine'
    elif 'unity' in dev_text:
        return 'Unity Engine'
    elif 'epic games' in dev_text:
        return 'Unreal Engine'
    else:
        return 'Unknown'