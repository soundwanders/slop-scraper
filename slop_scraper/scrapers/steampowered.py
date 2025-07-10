import re
import time
import os
from tqdm import tqdm

try:
    # Try relative imports first (when run as module)
    from ..utils.cache import save_cache
    from ..utils.security_config import SecureRequestHandler
except ImportError:
    # Fall back to absolute imports (when run directly)
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.cache import save_cache
    from utils.security_config import SecureRequestHandler

def extract_first_from_list(data_list):
    """Safely extract the first item from a list, handling various data types"""
    if not data_list:
        return ""
    
    if isinstance(data_list, list) and len(data_list) > 0:
        first_item = data_list[0]
        if isinstance(first_item, str):
            return first_item
        elif isinstance(first_item, dict):
            return first_item.get("name", "") or first_item.get("description", "")
        else:
            return str(first_item)
    elif isinstance(data_list, str):
        return data_list
    
    return ""

def detect_game_engine(store_data, game_name):
    """Detect game engine based on available Steam API data"""
    
    # Check categories for engine hints
    categories = store_data.get("categories", [])
    category_names = [cat.get("description", "").lower() for cat in categories if isinstance(cat, dict)]
    
    # Check genres for engine hints
    genres = store_data.get("genres", [])
    genre_names = [genre.get("description", "").lower() for genre in genres if isinstance(genre, dict)]
    
    # Check developers and publishers for engine clues
    developers = store_data.get("developers", [])
    publishers = store_data.get("publishers", [])
    
    game_name_lower = game_name.lower()
    all_text = " ".join([game_name_lower] + category_names + genre_names + developers + publishers).lower()
    
    # Engine detection based on comzmon patterns
    if any(keyword in all_text for keyword in ["source", "valve", "counter-strike", "half-life", "portal", "team fortress", "left 4 dead", "dota"]):
        return "Source Engine"
    
    if any(keyword in all_text for keyword in ["unreal", "epic games", "unreal engine"]):
        return "Unreal Engine"
    
    if any(keyword in all_text for keyword in ["unity", "unity technologies"]):
        return "Unity"
    
    if any(keyword in all_text for keyword in ["id tech", "id software", "doom", "quake", "wolfenstein"]):
        return "id Tech"
    
    if any(keyword in all_text for keyword in ["cryengine", "crytek", "far cry", "crysis"]):
        return "CryEngine"
    
    if any(keyword in all_text for keyword in ["frostbite", "battlefield", "fifa", "need for speed"]):
        return "Frostbite"
    
    if any(keyword in all_text for keyword in ["creation engine", "gamebryo", "bethesda", "elder scrolls", "fallout"]):
        return "Creation Engine"
    
    if any(keyword in all_text for keyword in ["anvil", "assassin's creed", "ubisoft"]):
        return "Anvil"
    
    if any(keyword in all_text for keyword in ["rage engine", "rockstar", "grand theft auto", "red dead"]):
        return "RAGE"
    
    # Check for indie engines
    if any(keyword in all_text for keyword in ["godot"]):
        return "Godot"
    
    if any(keyword in all_text for keyword in ["construct", "clickteam", "game maker", "gamemaker"]):
        return "Game Maker Studio"
    
    # Check for web technologies
    if any(keyword in all_text for keyword in ["html5", "javascript", "web browser"]):
        return "HTML5/Web"
    
    # Check for mobile engines
    if any(keyword in all_text for keyword in ["cocos2d", "corona", "solar2d"]):
        return "Mobile Engine"
    
    # Default fallback
    return "Unknown"

def get_steam_game_list(cache, debug, limit, force_refresh, test_mode, cache_file='appdetails_cache.json', 
                       rate_limiter=None, session_monitor=None, db_client=None, **kwargs):
    """Fetch Steam game list with security controls"""
    print(f"🔒 Fetching game list securely (force_refresh={force_refresh})...")
    print(f"Debug: Attempting to fetch up to {limit} games")

    if test_mode and limit <= 10:
        print("🔒 Using test mode data for security")
        return [
            {"appid": 570, "name": "Dota 2", "developer": "Valve Corporation", "publisher": "Valve Corporation", "engine": "Source Engine"},
            {"appid": 730, "name": "Counter-Strike 2", "developer": "Valve Corporation", "publisher": "Valve Corporation", "engine": "Source Engine"},
            {"appid": 264710, "name": "Subnautica", "developer": "Unknown Worlds Entertainment", "publisher": "Unknown Worlds Entertainment", "engine": "Unity"},
            {"appid": 377840, "name": "Final Fantasy IX", "developer": "Square Enix", "publisher": "Square Enix", "engine": "Unknown"},
            {"appid": 1868140, "name": "Dave the Diver", "developer": "MINTROCKET", "publisher": "NEXON", "engine": "Unity"},
        ][:limit]

    url = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"
    try:
        # Use rate limiter for Steam API request type
        if rate_limiter:
            rate_limiter.wait_if_needed("steam_api")
        
        # Use secure request handler
        print("🔒 Making secure request to Steam API...")
        response = SecureRequestHandler.make_secure_request(url, timeout=30, max_size_mb=50)
        response.raise_for_status()
        
        # Record the request for monitoring
        if session_monitor:
            session_monitor.record_request()
            
        all_apps = response.json()['applist']['apps']
        print(f"✅ Securely fetched {len(all_apps)} total apps")

        # Blocklist of terms to exclude
        blocklist_terms = [
            'dlc', 'soundtrack', 'beta', 'demo', 'test', 'adult', 'hentai', 'xxx', 'mature', 
            'expansion', 'tool', 'software', 'trailer', 'video'
        ]

        # Regex patterns for filtering unwanted games
        blocklist_pattern = re.compile(r'(?i)(' + '|'.join(re.escape(term) for term in blocklist_terms) + ')')
        non_latin_pattern = re.compile(r'[^\x00-\x7F]')
        only_numeric_special = re.compile(r'^[0-9\s\-_+=.,!@#$%^&*()\[\]{}|\\/<>?;:\'"`~]*$')

        # Known game engines to keep (for better filtering)
        known_engines = ['unreal', 'unity', 'godot', 'source', 'cryengine', 'frostbite', 'id tech']

        filtered_games = []

        # Use tqdm for processing apps with security checks
        with tqdm(total=min(limit * 3, len(all_apps)), desc="🔒 Filtering games securely") as pbar:
            for app_index, app in enumerate(all_apps):
                if len(filtered_games) >= limit:
                    break
                
                # Periodic security checks
                if app_index % 100 == 0 and session_monitor:
                    session_monitor.check_runtime_limit()

                app_id = str(app['appid'])
                name = app['name']
                pbar.update(1)

                # Skip invalid or unwanted entries based on blocklist
                if not name or blocklist_pattern.search(name) or non_latin_pattern.search(name) or only_numeric_special.match(name):
                    continue

                # Additional length validation for security
                if len(name) > 100 or len(app_id) > 10:
                    pbar.write(f"⚠️ Skipping app with suspicious name/ID length: {name[:50]}")
                    continue

                store_data = None
                if not force_refresh and app_id in cache:
                    store_data = cache[app_id]
                else:
                    # Apply Steam API rate limiting before making request
                    if rate_limiter:
                        rate_limiter.wait_if_needed("steam_api") 
                    
                    # Fetch detailed data from store if not cached or forced refresh
                    store_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=us&l=en"
                    try:
                        # Use secure request handler for store API
                        store_res = SecureRequestHandler.make_secure_request(store_url, timeout=10, max_size_mb=2)
                        store_res.raise_for_status()
                        
                        # Record the request
                        if session_monitor:
                            session_monitor.record_request()
                        
                        raw = store_res.json()
                        store_data = raw.get(app_id, {}).get("data", {})

                        if store_data:
                            cache[app_id] = store_data
                        else:
                            pbar.write(f"⚠️ No valid data for app_id {app_id}. Skipping.")
                            continue
                            
                    except Exception as e:
                        if session_monitor:
                            session_monitor.record_error()
                        pbar.write(f"⚠️ Error fetching data for app_id {app_id}: {e}. Skipping.")
                        continue

                # Validate store_data before proceeding
                if not store_data or not isinstance(store_data, dict):
                    pbar.write(f"⚠️ Invalid or missing data for app_id {app_id}. Skipping.")
                    continue

                # Additional validation checks
                if store_data.get("type") != "game":
                    continue  # Silent skip for non-games
                if store_data.get("release_date", {}).get("coming_soon", False):
                    continue  # Silent skip for unreleased games
                if store_data.get("is_free", False) and "demo" in store_data.get("name", "").lower():
                    continue  # Silent skip for demos

                # Additional security validation on store data
                game_name = store_data.get("name", name)
                if len(game_name) > 200:  # Sanity check
                    pbar.write(f"⚠️ Game name too long, skipping: {game_name[:50]}...")
                    continue

                # Extract developer using our helper function
                developer = extract_first_from_list(store_data.get("developers", []))
                if not developer:
                    developer = "Unknown"
                if len(developer) > 100:  # Limit developer name length
                    developer = developer[:100]

                # Extract publisher using our helper function
                publisher = extract_first_from_list(store_data.get("publishers", []))
                if not publisher:
                    publisher = "Unknown"
                if len(publisher) > 100:  # Limit publisher name length
                    publisher = publisher[:100]
                
                # Detect engine using our helper function
                engine = detect_game_engine(store_data, game_name)
                if len(engine) > 50:  # Limit engine name length
                    engine = engine[:50]

                # Add the game to the filtered list if it passes all checks
                filtered_games.append({
                    "appid": int(app_id),
                    "name": game_name[:200],  # Limit name length
                    "developer": developer,
                    "publisher": publisher, 
                    "release_date": str(store_data.get("release_date", {}).get("date", ""))[:50],
                    "engine": engine 
                })

                # Optional debug output to verify data extraction
                if debug:
                    print(f"✅ Game: {game_name}")
                    print(f"  Developer: {developer}")
                    print(f"  Publisher: {publisher}")
                    print(f"  Engine: {engine}")
                    print(f"  Raw developers: {store_data.get('developers', [])}")
                    print(f"  Raw publishers: {store_data.get('publishers', [])}")

                pbar.write(f"✔️ Added: {game_name}")

        # Securely save cache
        try:
            save_cache(cache, cache_file)
        except Exception as e:
            print(f"⚠️ Error saving cache: {e}")
            
        print(f"🔒 Final game count: {len(filtered_games)} (security validated)")
        return filtered_games

    except Exception as e:
        if session_monitor:
            session_monitor.record_error()
        print(f"🔒 Error fetching game list: {e}")
        return []