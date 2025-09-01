"""
Steam Game List Fetcher with Efficient Filtering
"""

import requests
import time
import re
from tqdm import tqdm

try:
    from ..utils.extract_engine import extract_engine
except ImportError:
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.extract_engine import extract_engine

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
    
    # Combine existing and cached IDs to skip
    skip_app_ids = existing_app_ids | cached_app_ids
    
    if test_mode and limit <= 10:
        print("🧪 Using test data for small limits")
        return get_test_games(limit, skip_app_ids, cache, debug, rate_limiter, session_monitor)

    # Fetch complete Steam app list
    print("📥 Fetching Steam app list...")
    all_apps = fetch_steam_app_list(rate_limiter, session_monitor, debug)
    
    if not all_apps:
        print("❌ Failed to fetch Steam app list")
        return []

    # Filter out games we already have
    print(f"🔍 Filtering {len(all_apps)} apps (removing {len(skip_app_ids)} existing/cached games)...")
    
    candidate_apps = []
    for app in all_apps:
        app_id = app['appid']
        if app_id not in skip_app_ids:
            candidate_apps.append(app)
    
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

def fetch_steam_app_list(rate_limiter, session_monitor, debug):
    """Fetch the complete Steam app list from the API"""
    url = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"
    
    try:
        if rate_limiter:
            rate_limiter.wait_if_needed("steam_api")
        
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        if session_monitor:
            session_monitor.record_request()
            
        all_apps = response.json()['applist']['apps']
        
        if debug:
            print(f"📊 Retrieved {len(all_apps)} total Steam apps")
        
        return all_apps
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Error fetching Steam app list: {e}")
        return []

def process_candidate_games(candidate_apps, limit, cache, debug, rate_limiter, session_monitor, force_refresh):
    """Process candidate games with quality filtering and metadata fetching"""
    
    # Quality filtering patterns
    blocklist_terms = [
        'dlc', 'soundtrack', 'beta', 'demo', 'test', 'adult', 'hentai', 
        'xxx', 'mature', 'expansion', 'tool', 'software'
    ]
    
    blocklist_pattern = re.compile(r'(?i)(' + '|'.join(re.escape(term) for term in blocklist_terms) + ')')
    non_latin_pattern = re.compile(r'[^\x00-\x7F]')
    only_numeric_special = re.compile(r'^[0-9\s\-_+=.,!@#$%^&*()\[\]{}|\\/<>?;:\'"`~]*$')
    
    # High-priority games to process first
    priority_keywords = [
        'counter-strike', 'dota', 'team fortress', 'half-life', 'portal',
        'final fantasy', 'dark souls', 'witcher', 'cyberpunk'
    ]
    
    # Sort candidates by priority
    sorted_candidates = sorted(candidate_apps, key=lambda x: (
        -any(keyword in x['name'].lower() for keyword in priority_keywords),
        x['name'].lower()
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
                non_latin_pattern.search(name) or 
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
    
    # Extract complete metadata
    enriched_game = {
        "appid": app_id,
        "name": store_data.get("name", name),
        "developer": extract_developer_safely(store_data),
        "publisher": extract_publisher_safely(store_data),
        "release_date": extract_release_date_safely(store_data),
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