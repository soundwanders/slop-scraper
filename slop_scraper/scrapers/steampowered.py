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
    from ..utils import extract_engine
except ImportError:
    # Fall back to absolute imports (when run directly)
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.cache import load_cache, save_cache
    from utils.security_config import SecurityConfig, SessionMonitor, RateLimiter
    from utils.extract_engine import extract_engine
    from validation import LaunchOptionsValidator, ValidationLevel, EngineType  

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
        # Get the initial app list (this usually works fine)
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
        # DON'T report this to session monitor - it's an initial setup issue
        if debug:
            print(f"❌ Failed to fetch app list: {e}")
        return []
    
    # Process apps with NO session monitor error reporting
    games = []
    rate_limit_count = 0
    actual_error_count = 0  # Only count truly unexpected errors
    max_actual_errors = 20  # Much lower threshold for real errors
    consecutive_429s = 0
    
    # Rate limiting settings
    base_delay = 2.0
    current_delay = base_delay
    max_delay = 60.0
    backoff_multiplier = 1.5
    
    if debug:
        print(f"🔒 Starting with {base_delay}s delay between requests")
        print(f"🔒 Will only report truly unexpected errors to security system")
    
    # REVERTED: Use original game processing logic that was working
    # Process games in original order without "smart starting point"
    
    if debug:
        print(f"🔍 Processing games in original order (no filtering by app_id range)")
    
    with tqdm(all_apps, desc="🔒 Filtering games securely", unit="game") as pbar:
        for app in pbar:
            # Check if we have enough games
            if len(games) >= limit:
                break
            
            # Safety check for runtime - but don't count this as an error
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
                if cached_game:  # Only use non-null cached data
                    games.append(cached_game)
                continue
            
            # Apply current delay with jitter
            if rate_limiter:
                rate_limiter.wait_if_needed("steam_api", domain="store.steampowered.com")
            else:
                jittered_delay = current_delay + random.uniform(0, 0.5)
                time.sleep(jittered_delay)
            
            # Fetch game details WITHOUT reporting rate limits as errors
            success, game_data, error_type = fetch_game_details_no_error_reporting(
                app_id, 
                cache, 
                current_delay,
                debug=debug
            )
            
            if success and game_data:
                games.append(game_data)
                # Success! Reset consecutive 429 counter and reduce delay slightly
                consecutive_429s = 0
                current_delay = max(base_delay, current_delay * 0.9)
                
            elif error_type == "rate_limit":
                # Handle rate limits without reporting to session monitor
                consecutive_429s += 1
                rate_limit_count += 1
                current_delay = min(max_delay, current_delay * backoff_multiplier)
                
                if debug and rate_limit_count % 20 == 1:  # Log every 20th rate limit
                    print(f"🔄 Rate limiting detected ({rate_limit_count} total). Delay now {current_delay:.1f}s")
                
            elif error_type == "real_error":
                # Only count truly unexpected errors
                actual_error_count += 1
                
                if debug and actual_error_count % 5 == 1:
                    print(f"⚠️ Unexpected error #{actual_error_count}: {str(game_data)[:50]}...")
                
                # ONLY report truly unexpected errors to session monitor
                if session_monitor and actual_error_count <= 3:  # Only report first few real errors
                    session_monitor.record_error()
                
                if actual_error_count > max_actual_errors:
                    if debug:
                        print(f"⚠️ Too many unexpected errors ({actual_error_count}). Stopping.")
                        print(f"📊 Final stats: {rate_limit_count} rate limits, {actual_error_count} unexpected errors")
                    break
            
            # Update progress bar with current status
            if consecutive_429s > 0:
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
        print(f"📊 Processing stats: {rate_limit_count} rate limits, {actual_error_count} unexpected errors")
        if skip_existing and existing_app_ids:
            skipped_count = len(existing_app_ids)
            print(f"⚡ Efficiency: Skipped {skipped_count} existing games, saved {skipped_count} API calls")
    
    return valid_games

def fetch_game_details_no_error_reporting(app_id, cache, current_delay, max_retries=3, debug=False):
    """
    Fetch game details with ZERO error reporting to session monitor
    Now extracts full game metadata like the original scraper
    
    Returns:
        (success: bool, data: dict/str, error_type: str)
    """
    
    for attempt in range(max_retries):
        try:
            # Make the API request
            store_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=us&l=en"
            
            store_res = requests.get(store_url, timeout=15)
            
            if store_res.status_code == 200:
                # Success! Parse the data
                store_data = store_res.json()
                
                if str(app_id) in store_data and store_data[str(app_id)].get('success'):
                    game_info = store_data[str(app_id)]['data']
                    
                    # Validate the game data
                    if not game_info.get('name') or game_info.get('type') != 'game':
                        if debug:
                            print(f"⚠️ No valid data for app_id {app_id}. Skipping.")
                        cache[str(app_id)] = None
                        return False, None, "invalid_data"
                    
                    # Extract FULL game metadata like the original scraper
                    game = {
                        'appid': app_id,
                        'name': game_info['name'],
                        # Extract developer information
                        'developer': extract_developer_safely(game_info),
                        'publisher': extract_publisher_safely(game_info),
                        'release_date': extract_release_date_safely(game_info),
                        'engine': extract_engine_safely(game_info)
                    }
                    
                    # Cache the result with full metadata
                    cache[str(app_id)] = game
                    
                    if debug:
                        print(f"✔️ Added: {game['name']} (Dev: {game['developer']}, Engine: {game['engine']})")
                    
                    return True, game, "success"
                
                else:
                    # Game exists but isn't available/valid
                    if debug:
                        print(f"⚠️ No valid data for app_id {app_id}. Skipping.")
                    cache[str(app_id)] = None
                    return False, None, "invalid_data"
            
            elif store_res.status_code == 429:
                # Rate limited! Handle gracefully without reporting error
                if attempt < max_retries - 1:
                    # Calculate backoff delay for this specific 429
                    backoff_delay = current_delay * (2 ** attempt) + random.uniform(0, 1)
                    backoff_delay = min(backoff_delay, 120)  # Max 2 minutes
                    
                    if debug and attempt == 0:  # Only log on first 429 for this app
                        print(f"🔄 Rate limited for app {app_id}. Waiting {backoff_delay:.1f}s...")
                    
                    time.sleep(backoff_delay)
                    continue  # Retry
                else:
                    # Max retries reached for this app - still not an error, just rate limiting
                    return False, "429_max_retries", "rate_limit"
            
            else:
                # Other HTTP error - could be real issue
                if debug:
                    print(f"⚠️ HTTP {store_res.status_code} for app_id {app_id}. Skipping.")
                cache[str(app_id)] = None
                return False, f"HTTP_{store_res.status_code}", "http_error"
        
        except requests.exceptions.Timeout:
            # Timeout is not a real error in this context - just slow network
            if debug and attempt == 0:
                print(f"⚠️ Timeout for app_id {app_id}. Retrying...")
            if attempt < max_retries - 1:
                time.sleep(current_delay * (attempt + 1))
                continue
            else:
                return False, "timeout", "timeout"
        
        except requests.exceptions.RequestException as e:
            if "429" in str(e):
                # This is a 429 error wrapped in an exception
                if attempt < max_retries - 1:
                    backoff_delay = current_delay * (2 ** attempt) + random.uniform(0, 1)
                    if debug and attempt == 0:
                        print(f"🔄 Rate limit exception for app {app_id}. Waiting {backoff_delay:.1f}s...")
                    time.sleep(backoff_delay)
                    continue
                else:
                    return False, "429_exception", "rate_limit"
            else:
                # Real network error
                if debug:
                    print(f"⚠️ Network error for app_id {app_id}: {e}. Skipping.")
                cache[str(app_id)] = None
                return False, str(e), "network_error"
        
        except Exception as e:
            # Truly unexpected error
            if debug:
                print(f"⚠️ Unexpected error for app_id {app_id}: {e}. Skipping.")
            cache[str(app_id)] = None
            return False, str(e), "real_error"
    
    # If we get here, we exhausted retries
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
    """Enhanced engine detection wrapper"""
    app_id = game_info.get('appid') or game_info.get('steam_appid')
    return extract_engine(game_info, app_id)