import requests
import time
import random
import os
import json
from tqdm import tqdm

try:
    # Try relative imports first (when run as module)
    from ..utils.cache import load_cache, save_cache
    from ..utils.security_config import SecurityConfig, SessionMonitor, RateLimiter
except ImportError:
    # Fall back to absolute imports (when run directly)
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.cache import load_cache, save_cache
    from utils.security_config import SecurityConfig, SessionMonitor, RateLimiter

def get_steam_game_list(limit=100, force_refresh=False, cache=None, test_mode=False, 
                       debug=False, cache_file='appdetails_cache.json', 
                       rate_limiter=None, session_monitor=None, 
                       db_client=None, skip_existing=True, db_client_wrapper=None):
    """
    Fetch a list of Steam games securely with error handling and rate limiting.
    Args:
        limit (int): Maximum number of games to fetch.
        force_refresh (bool): Whether to force refresh the cache.
        cache (dict): Optional cache to use instead of loading from file.
        test_mode (bool): If True, runs in test mode with limited output.
        debug (bool): If True, enables debug output.
        cache_file (str): Path to the cache file.
        rate_limiter (RateLimiter): Optional rate limiter instance.
        session_monitor (SessionMonitor): Optional session monitor for runtime limits.
        db_client (object): Optional database client for skip-existing logic.
        skip_existing (bool): Whether to skip existing games in the database.
        db_client_wrapper (object): Optional wrapper for database client to handle existing app IDs.
    """
    
    if debug:
        print(f"🔒 Fetching game list securely (force_refresh={force_refresh})...")
        print(f"Debug: Attempting to fetch up to {limit} games")
    
    # Validate limit
    limit = SecurityConfig.validate_games_limit(limit)
    
    # Initialize or use provided cache
    if cache is None:
        cache = load_cache(cache_file)
    
    # Skip-existing logic using database
    existing_app_ids = set()
    if skip_existing and db_client_wrapper:
        try:
            if debug:
                print("🔍 Using smart database logic for skip-existing...")
            existing_app_ids = db_client_wrapper.get_existing_app_ids()
            if debug:
                print(f"📊 Standard skip logic: will skip {len(existing_app_ids)} existing games")
        except Exception as e:
            if debug:
                print(f"⚠️ Database skip-existing check failed: {e}")
                print("🔍 Falling back to cache-only skip logic")
    
    # Get the main Steam app list
    if debug:
        print("🔒 Making secure request to Steam API...")
    
    try:
        # Get the initial app list
        response = requests.get(
            'https://api.steampowered.com/ISteamApps/GetAppList/v2/',
            timeout=30
        )
        response.raise_for_status()
        app_data = response.json()
        
        if 'applist' not in app_data or 'apps' not in app_data['applist']:
            raise Exception("Invalid app list response format")
        
        all_apps = app_data['applist']['apps']
        if debug:
            print(f"✅ Securely fetched {len(all_apps)} total apps")
        
    except Exception as e:
        if debug:
            print(f"❌ Failed to fetch app list: {e}")
        return []
    
    # Process apps with proper rate limiting
    games = []
    rate_limit_count = 0
    consecutive_429s = 0
    max_consecutive_429s = 10  # Stop after 10 consecutive 429s
    
    base_delay = 3.0  # Start with 3 seconds instead of 2
    current_delay = base_delay
    max_delay = 60.0 
    success_count = 0
    error_count = 0
    
    if debug:
        print(f"🔒 Starting with {base_delay}s delay between requests")
    
    with tqdm(all_apps, desc="🔒 Filtering games securely", unit="game") as pbar:
        for app in pbar:
            # Check if we have enough games
            if len(games) >= limit:
                break
            
            # Safety check for runtime
            if session_monitor:
                try:
                    session_monitor.check_runtime_limit()
                except Exception as e:
                    if debug:
                        print(f"⚠️ Runtime limit reached: {e}")
                    break
            
            # Security validation
            app_id = app.get('appid')
            if not app_id or not isinstance(app_id, int) or app_id <= 0:
                continue
            
            # Skip existing games
            if skip_existing and app_id in existing_app_ids:
                continue
            
            # Check cache first
            if str(app_id) in cache and not force_refresh:
                cached_game = cache[str(app_id)]
                if cached_game:
                    games.append(cached_game)
                continue
            
            # Apply rate limiting BEFORE making request
            if rate_limiter:
                # Use the more conservative Steam API rate limiting
                rate_limiter.wait_if_needed("steam_api", domain="store.steampowered.com")
            else:
                # Manual rate limiting with jitter
                jittered_delay = current_delay + random.uniform(0, 1.0)
                time.sleep(jittered_delay)
            
            # Fetch game details
            success, game_data, error_type = fetch_game_details(
                app_id, 
                cache, 
                current_delay,
                debug=debug
            )
            
            if success and game_data:
                games.append(game_data)
                success_count += 1
                consecutive_429s = 0  # Reset consecutive 429 counter
                
                # Gradually reduce delay (but not too aggressively)
                current_delay = max(base_delay, current_delay * 0.95)
                
            elif error_type == "rate_limit":
                consecutive_429s += 1
                rate_limit_count += 1
                
                # More aggressive backoff for 429s
                current_delay = min(max_delay, current_delay * 1.5)

                if debug and rate_limit_count % 20 == 1:  # Log every 20th rate limit
                    print(f"🔄 Rate limiting detected ({rate_limit_count} total). Delay now {current_delay:.1f}s")

                if debug and consecutive_429s % 5 == 1:
                    print(f"🔄 Rate limited {consecutive_429s} times. Delay now {current_delay:.1f}s")
                
                # If we get too many consecutive 429s, take a longer break
                if consecutive_429s >= max_consecutive_429s:
                    if debug:
                        print(f"⚠️ Too many consecutive rate limits ({consecutive_429s}). Taking extended break...")
                    time.sleep(60)  # 1 minute break
                    consecutive_429s = 0
                    current_delay = base_delay  # Reset delay
                
            elif error_type == "real_error":
                error_count += 1
                
                if session_monitor and error_count <= 3:
                    session_monitor.record_error()
                
                if error_count > 20:
                    if debug:
                        print(f"⚠️ Too many real errors ({error_count}). Stopping.")
                    break
            
            # Update progress bar
            if consecutive_429s > 5:
                pbar.set_description(f"🔄 Rate limited (delay: {current_delay:.1f}s)")
            else:
                pbar.set_description(f"🔒 Filtering games securely")
    
    # Save cache
    try:
        save_cache(cache, cache_file)
        if debug:
            print(f"✅ Cache saved to {cache_file}")
    except Exception as e:
        if debug:
            print(f"⚠️ Failed to save cache: {e}")
    
    # Filter for valid games
    valid_games = [g for g in games if g and 'appid' in g and 'name' in g]
    
    if debug:
        print(f"🔒 Final game count: {len(valid_games)} (security validated)")
        print(f"📊 Processing stats: {rate_limit_count} rate limits, {error_count} unexpected errors")
        print(f"📊 Success rate: {success_count} successes, {error_count} errors")
        if skip_existing and existing_app_ids:
            skipped_count = len(existing_app_ids)
            print(f"⚡ Efficiency: Skipped {skipped_count} existing games")
    
    return valid_games

def fetch_game_details(app_id, cache, current_delay, max_retries=2, debug=False):
    """
    Fetch game details - extracts full game metadata
    
    Returns:
        (success: bool, data: dict/str, error_type: str)
    """
    
    for attempt in range(max_retries):
        try:
            # Make the API request
            store_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=us&l=en"
            
            # TIMEOUT IS CHANGEABLE -- DEFAULT VALUE CURRENTLY SET TO 10
            store_res = requests.get(store_url, timeout=10)
            
            if store_res.status_code == 200:
                try:
                    store_data = store_res.json()
                except ValueError as json_error:
                    if debug:
                        print(f"⚠️ JSON decode error for app_id {app_id}: {json_error}")
                    cache[str(app_id)] = None
                    return False, None, "invalid_data"
                
                if str(app_id) in store_data and store_data[str(app_id)].get('success'):
                    game_info = store_data[str(app_id)]['data']
                    
                    # Validate the game data
                    if not game_info.get('name') or game_info.get('type') != 'game':
                        cache[str(app_id)] = None
                        return False, None, "invalid_data"
                    
                    # Create game object
                    game = {
                        'appid': app_id,
                        'name': game_info['name']
                    }
                    
                    # Cache the result
                    cache[str(app_id)] = game
                    return True, game, "success"
                
                else:
                    # Game exists but isn't available/valid
                    cache[str(app_id)] = None
                    return False, None, "invalid_data"
            
            elif store_res.status_code == 429:
                # Handle 429s more conservatively
                if attempt < max_retries - 1:
                    backoff_delay = current_delay * (3 ** attempt) + random.uniform(2, 5)
                    backoff_delay = min(backoff_delay, 120)  # Max 2 minutes
                    
                    if debug and attempt == 0:
                        print(f"🔄 429 for app {app_id}. Waiting {backoff_delay:.1f}s...")
                    
                    time.sleep(backoff_delay)
                    continue
                else:
                    return False, "429_max_retries", "rate_limit"
            
            else:
                # Other HTTP error
                cache[str(app_id)] = None
                return False, f"HTTP_{store_res.status_code}", "http_error"
        
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                time.sleep(current_delay * (attempt + 1))
                continue
            else:
                return False, "timeout", "timeout"
        
        except requests.exceptions.RequestException as e:
            if "429" in str(e):
                if attempt < max_retries - 1:
                    backoff_delay = current_delay * (3 ** attempt) + random.uniform(2, 5)
                    time.sleep(backoff_delay)
                    continue
                else:
                    return False, "429_exception", "rate_limit"
            else:
                cache[str(app_id)] = None
                return False, str(e), "network_error"
        
        except Exception as e:
            cache[str(app_id)] = None
            return False, str(e), "real_error"
    
    return False, "max_retries_exhausted", "real_error"

def extract_developer_safely(game_info):
    """Safely extract developer information from Steam API response"""
    try:
        developers = game_info.get('developers', [])
        if isinstance(developers, list) and developers:
            return developers[0]  # Get first developer
        elif isinstance(developers, str):
            return developers
        return ''
    except Exception:
        return ''


def extract_publisher_safely(game_info):
    """Safely extract publisher information from Steam API response"""
    try:
        publishers = game_info.get('publishers', [])
        if isinstance(publishers, list) and publishers:
            return publishers[0]  # Get first publisher
        elif isinstance(publishers, str):
            return publishers
        return ''
    except Exception:
        return ''


def extract_release_date_safely(game_info):
    """Safely extract release date from Steam API response"""
    try:
        release_info = game_info.get('release_date', {})
        if isinstance(release_info, dict):
            return release_info.get('date', '')
        return ''
    except Exception:
        return ''


def extract_engine_safely(game_info):
    """Safely extract or detect game engine from Steam API response"""
    try:
        # Method 1: Check if engine is directly provided (rare)
        engine = game_info.get('engine', '')
        if engine:
            return engine
        
        # Method 2: Detect engine from game title and metadata
        title = game_info.get('name', '').lower()
        developers = game_info.get('developers', [])
        categories = game_info.get('categories', [])
        
        # Convert lists to searchable text
        dev_text = ''
        if isinstance(developers, list):
            dev_text = ' '.join(developers).lower()
        elif isinstance(developers, str):
            dev_text = developers.lower()
        
        category_text = ''
        if isinstance(categories, list):
            category_text = ' '.join([cat.get('description', '') for cat in categories if isinstance(cat, dict)]).lower()
        
        all_text = f"{title} {dev_text} {category_text}"
        
        # Engine detection patterns (same as game_specific.py)
        if any(indicator in all_text for indicator in ['valve corporation', 'valve software', 'source engine', 'source 2']):
            return 'Source Engine'
        elif any(indicator in all_text for indicator in ['unity', 'unity technologies', 'made with unity']):
            return 'Unity Engine'
        elif any(indicator in all_text for indicator in ['unreal engine', 'epic games']):
            return 'Unreal Engine'
        elif any(indicator in all_text for indicator in ['id software', 'id tech']):
            return 'id Tech'
        elif any(indicator in all_text for indicator in ['electronic arts', 'ea games', 'frostbite']):
            return 'Frostbite Engine'
        elif 'minecraft' in title and 'java' in all_text:
            return 'Java (Minecraft)'
        elif any(game in title for game in ['skyrim', 'fallout', 'elder scrolls', 'starfield']):
            return 'Creation Engine'
        else:
            return 'Unknown'
            
    except Exception:
        return 'Unknown'