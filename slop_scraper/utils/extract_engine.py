"""
Engine detection system for slop-scraper using multiple data sources and pattern matching
"""

import re
import requests
import time
from typing import Dict, Optional, List
from bs4 import BeautifulSoup

try:
    from utils.known_engines import lookup_title_engine
except ImportError:
    from .known_engines import lookup_title_engine

class EngineDetector:
    """Engine detection using multiple sources and improved patterns"""
    
    def __init__(self):
        # Comprehensive engine detection patterns
        # Only two kinds of string belong here:
        #
        #   1. names of the engine itself ('cryengine', 'id tech'), and
        #   2. studios that have shipped their ENTIRE catalogue on one engine.
        #
        # FRANCHISE names used to be here too ('counter-strike', 'fallout',
        # 'battlefield', 'doom', 'unity') and were matched against the game
        # title at the highest weight. Measured against the live catalogue that
        # was wrong about 30% of the time — a franchise switches engine between
        # entries, and unrelated games reuse the words. "Assassin's Creed
        # Unity" became a Unity game; "Counter-Strike: Condition Zero" (GoldSrc)
        # became Source; "Doom Rails" became id Tech. Specific games are named
        # in utils/known_engines.py instead, where each one is verified.
        #
        # Two studio entries also had to go:
        #   'bioware'          — Unreal only from Mass Effect on. Dragon Age,
        #                        KOTOR, Jade Empire and MDK2 are in-house engines.
        #   'gearbox software' — would have overwritten Half-Life: Opposing
        #                        Force and Blue Shift (GoldSrc) with Unreal.
        self.engine_patterns = {
            'Unity Engine': [
                'unity technologies', 'made with unity', 'unity3d',
                'unity player', 'unityengine',
                'innersloth', 'team cherry', 'night school studio',
            ],

            'Unreal Engine': [
                'unreal engine', 'unrealengine', 'unrealtournament',
                'epic games', 'epic megagames', 'rocksteady studios',
            ],

            'Source Engine': [
                'source engine', 'source 2',
            ],

            'Creation Engine': [
                'creation engine',
            ],

            'Gamebryo': [
                'gamebryo',
            ],

            'Frostbite Engine': [
                'frostbite',
            ],

            'id Tech': [
                'id software', 'id tech',
            ],

            'CryEngine': [
                'crytek', 'cryengine', 'cry engine',
            ],

            'GameMaker Studio': [
                'gamemaker', 'yoyo games',
            ],

            'Godot Engine': [
                'godot engine',
            ],

            'RPG Maker': [
                'rpg maker', 'rpgmaker', 'enterbrain',
            ],

            'Construct': [
                'construct 2', 'construct 3', 'scirra',
            ],

            'Java (Minecraft)': [
                'mojang',
            ],

            'Flash/AIR': [
                'adobe flash', 'adobe air', 'macromedia flash'
            ]
        }
        
        # App ID ranges that are commonly associated with certain engines
        # Based on Steam's app ID allocation patterns
        self.appid_engine_hints = {
            # Unity games often fall in certain ranges (this is heuristic)
            'Unity Engine': [(200000, 300000), (400000, 500000)],
            # Source engine games (Valve's range)
            'Source Engine': [(1, 1000), (240, 250), (440, 450), (500, 600)]
        }
        
        # Cache for external lookups to avoid repeated requests
        self.external_cache = {}
    
    def detect_engine_comprehensive(self, game_info: Dict, app_id: int = None) -> str:
        """
        Comprehensive engine detection using multiple methods
        
        Args:
            game_info: Steam API game information
            app_id: Steam app ID
            
        Returns:
            Detected engine name or 'Unknown'
        """
        
        # Method 0: the curated title table. Hand-verified per game, so it
        # outranks every inference below — including the deliberate 'Unknown'
        # entries, which exist to stop a weaker method from guessing an engine
        # for a game we know does NOT share its franchise's engine (Fallout 1,
        # Need for Speed: Shift, Minecraft: Story Mode).
        curated = lookup_title_engine(game_info.get('name', ''))
        if curated is not None:
            return curated

        # Method 1: Check if engine is directly provided by Steam API
        direct_engine = self._extract_direct_engine(game_info)
        if direct_engine and direct_engine != 'Unknown':
            return direct_engine

        # Method 2:  pattern matching on existing Steam data
        pattern_engine = self._detect_engine_by_patterns(game_info)
        if pattern_engine and pattern_engine != 'Unknown':
            return pattern_engine
        
        # Method 3 used to guess from the Steam app ID: anything numbered
        # 200000-300000 was labelled "Unity Engine (heuristic)", anything under
        # 1000 "Source Engine (heuristic)". An app ID records when a game was
        # registered with Steam, not what it was built with, so this invented
        # an engine for hundreds of unrelated games. Removed — 'Unknown' is the
        # honest answer. _detect_engine_by_appid is kept below but unused, in
        # case the ranges are ever wanted as a low-confidence signal that is
        # clearly separated from real evidence.

        # Method 4: External sources (SteamDB, PCGamingWiki)
        if app_id:
            external_engine = self._detect_engine_external(app_id, game_info.get('name', ''))
            if external_engine and external_engine != 'Unknown':
                return external_engine
        
        # Method 5: Advanced heuristics (file analysis, etc.)
        heuristic_engine = self._detect_engine_heuristic(game_info)
        if heuristic_engine and heuristic_engine != 'Unknown':
            return heuristic_engine
        
        return 'Unknown'
    
    # Patterns that actually name an engine. Only these may be matched against
    # free-form store prose; a franchise or studio name appearing in a
    # description ("inspired by DOOM", "roll the dice") says nothing about what
    # the game is built on.
    # Deliberately excludes engine names that are also ordinary English:
    # bare 'unity' ("a sense of unity"), bare 'unreal' ("an unreal
    # experience"), and 'game maker' ("every game maker dreams of this") all
    # appear in normal marketing copy. Their unambiguous forms are kept, so a
    # description saying "made with Unity" or "GameMaker" still resolves.
    _ENGINE_NAME_PATTERNS = {
        'unity3d', 'unityengine', 'made with unity', 'unity player',
        'unreal engine', 'unrealengine',
        'source engine', 'source 2',
        'creation engine', 'gamebryo',
        'frostbite',
        'id tech',
        'cryengine', 'cry engine',
        'gamemaker',
        'godot engine',
        'rpg maker', 'rpgmaker',
        'construct 2', 'construct 3',
        'adobe flash', 'adobe air', 'macromedia flash',
    }

    def _extract_direct_engine(self, game_info: Dict) -> str:
        """
        Extract the engine when a Steam field states it outright.

        This runs before every other method, so a loose match here overrides
        all the more careful ones. It used to substring-match every pattern —
        including franchise and studio names — against the full store
        description, which is how a blurb mentioning dice produced "Frostbite"
        and one mentioning doom produced "id Tech".

        Now: explicit engine fields may match any pattern, but free-form prose
        may only match a string that actually names an engine, and always on
        word boundaries.
        """
        explicit_fields = ('engine', 'game_engine', 'technology')
        prose_fields = ('detailed_description', 'about_the_game')

        def _matches(pattern, content):
            return re.search(r'(?<![\w])' + re.escape(pattern) + r'(?![\w])', content) is not None

        for field in explicit_fields:
            if field in game_info:
                content = str(game_info[field]).lower()
                for engine, patterns in self.engine_patterns.items():
                    if any(_matches(p, content) for p in patterns):
                        return engine

        for field in prose_fields:
            if field in game_info:
                content = str(game_info[field]).lower()
                for engine, patterns in self.engine_patterns.items():
                    named = [p for p in patterns if p in self._ENGINE_NAME_PATTERNS]
                    if any(_matches(p, content) for p in named):
                        return engine

        return 'Unknown'
    
    def _detect_engine_by_patterns(self, game_info: Dict) -> str:
        """ pattern matching using all available Steam data"""
        
        # Collect all text data
        text_fields = []
        
        # Game title
        if 'name' in game_info:
            text_fields.append(game_info['name'].lower())
        
        # Developer(s)
        developers = game_info.get('developers', [])
        if isinstance(developers, list):
            text_fields.extend([dev.lower() for dev in developers])
        elif isinstance(developers, str):
            text_fields.append(developers.lower())
        
        # Publisher(s)  
        publishers = game_info.get('publishers', [])
        if isinstance(publishers, list):
            text_fields.extend([pub.lower() for pub in publishers])
        elif isinstance(publishers, str):
            text_fields.append(publishers.lower())
        
        # Categories
        categories = game_info.get('categories', [])
        if isinstance(categories, list):
            text_fields.extend([cat.get('description', '').lower() for cat in categories if isinstance(cat, dict)])
        
        # Genres
        genres = game_info.get('genres', [])
        if isinstance(genres, list):
            text_fields.extend([genre.get('description', '').lower() for genre in genres if isinstance(genre, dict)])
        
        # Combine all text
        all_text = ' '.join(text_fields)
        
        # Score each engine based on pattern matches.
        #
        # Matching is WORD-BOUNDED. Plain substring matching mislabelled a
        # large share of the catalogue, because short patterns appear inside
        # ordinary words: 'rage' inside "storage"/"average", 'dice' inside any
        # description that mentions dice, 'doom' inside "doomed". That is how
        # "It Takes Two" became GameMaker Studio and "Chuzzle Deluxe" became
        # Frostbite.
        #
        # Store-page prose is also the weakest evidence available, so a match
        # found only in the description no longer scores at all — a game whose
        # blurb says "roll the dice" tells us nothing about its engine. Only
        # the title and the developer/publisher fields count, and the engine
        # name itself still counts wherever it appears.
        engine_scores = {}
        title_text = text_fields[0] if text_fields else ''
        attribution_text = ' '.join(text_fields[1:6])

        for engine, patterns in self.engine_patterns.items():
            score = 0
            for pattern in patterns:
                bounded = re.compile(r'(?<![\w])' + re.escape(pattern) + r'(?![\w])')
                if bounded.search(title_text):
                    score += 3
                elif bounded.search(attribution_text):
                    score += 2
                elif engine.lower().split()[0] in pattern and bounded.search(all_text):
                    # The engine's own name (e.g. "cryengine", "id tech") is
                    # meaningful anywhere; a franchise or studio name is not.
                    score += 1

            if score > 0:
                engine_scores[engine] = score
        
        # Return highest scoring engine
        if engine_scores:
            return max(engine_scores, key=engine_scores.get)
        
        return 'Unknown'
    
    def _detect_engine_by_appid(self, app_id: int) -> str:
        """Detect engine based on app ID ranges (heuristic)"""
        
        for engine, ranges in self.appid_engine_hints.items():
            for start, end in ranges:
                if start <= app_id <= end:
                    return f"{engine} (heuristic)"
        
        return 'Unknown'
    
    def _detect_engine_external(self, app_id: int, game_title: str) -> str:
        """Detect engine using external sources"""
        
        # Check cache first
        cache_key = f"{app_id}_{game_title}"
        if cache_key in self.external_cache:
            return self.external_cache[cache_key]
        
        engine = 'Unknown'
        
        # Try SteamDB
        steamdb_engine = self._check_steamdb(app_id)
        if steamdb_engine != 'Unknown':
            engine = steamdb_engine
        
        # Try PCGamingWiki if SteamDB didn't work
        if engine == 'Unknown':
            pcgw_engine = self._check_pcgamingwiki(game_title)
            if pcgw_engine != 'Unknown':
                engine = pcgw_engine
        
        # Cache the result
        self.external_cache[cache_key] = engine
        
        return engine
    
    def _check_steamdb(self, app_id: int) -> str:
        """Check SteamDB for engine information"""
        try:
            url = f"https://steamdb.info/app/{app_id}/"
            
            # Rate limiting
            time.sleep(1)
            
            response = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Look for engine information in various places
                page_text = soup.get_text().lower()
                
                for engine, patterns in self.engine_patterns.items():
                    if any(pattern in page_text for pattern in patterns):
                        return f"{engine} (SteamDB)"
            
        except Exception as e:
            print(f"SteamDB lookup failed for {app_id}: {e}")
        
        return 'Unknown'
    
    def _check_pcgamingwiki(self, game_title: str) -> str:
        """Check PCGamingWiki for engine information"""
        try:
            # Format title for PCGamingWiki
            formatted_title = game_title.replace(' ', '_').replace(':', '')
            
            # PCGamingWiki API
            api_url = "https://www.pcgamingwiki.com/w/api.php"
            params = {
                "action": "query",
                "format": "json", 
                "titles": formatted_title,
                "prop": "extracts",
                "exintro": True,
                "explaintext": True
            }
            
            # Rate limiting
            time.sleep(1)
            
            response = requests.get(api_url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if 'query' in data and 'pages' in data['query']:
                    for page_id, page_data in data['query']['pages'].items():
                        if 'extract' in page_data:
                            extract_text = page_data['extract'].lower()
                            
                            for engine, patterns in self.engine_patterns.items():
                                if any(pattern in extract_text for pattern in patterns):
                                    return f"{engine} (PCGamingWiki)"
            
        except Exception as e:
            print(f"PCGamingWiki lookup failed for {game_title}: {e}")
        
        return 'Unknown'
    
    def _detect_engine_heuristic(self, game_info: Dict) -> str:
        """
        Retained as a no-op so the call site and its ordering stay intact.

        This used to label any indie game released after 2010 priced under $30
        as 'Unity Engine (heuristic)'. Release year, price and genre are not
        evidence of an engine — that inference produced the fabricated
        "(heuristic)" labels that had to be cleared from the catalogue, and it
        produced them for games that were never Unity at all.

        Because backfill only refreshes an engine whose value is exactly
        'Unknown', a fabricated label here was effectively permanent: nothing
        downstream would ever revisit it. Guessing is therefore strictly worse
        than declining, and this declines.
        """
        return 'Unknown'

# Integration function
def extract_engine(game_info: Dict, app_id: int = None) -> str:
    detector = EngineDetector()
    return detector.detect_engine_comprehensive(game_info, app_id)

# Batch processing function for updating existing database
def update_unknown_engines_batch(supabase_client, limit: int = 100):
    """
    Batch update games with 'Unknown' engines in the database
    """
    try:
        # Get games with Unknown engines
        response = supabase_client.table("games")\
            .select("app_id, title, developer, publisher")\
            .eq("engine", "Unknown")\
            .limit(limit)\
            .execute()
        
        if not response.data:
            print("No games with Unknown engines found")
            return
        
        detector = EngineDetector()
        updated_count = 0
        
        print(f"Processing {len(response.data)} games with Unknown engines...")
        
        for game in response.data:
            app_id = game['app_id']
            title = game['title']
            
            print(f"Processing: {title} (App ID: {app_id})")
            
            # Create game_info dict from database data
            game_info = {
                'name': title,
                'developers': [game['developer']] if game['developer'] else [],
                'publishers': [game['publisher']] if game['publisher'] else []
            }
            
            # Try to get fresh Steam API data
            fresh_engine = get_fresh_steam_data_engine(app_id)
            if fresh_engine != 'Unknown':
                detected_engine = fresh_engine
            else:
                # Use  detection on existing data
                detected_engine = detector.detect_engine_comprehensive(game_info, app_id)
            
            if detected_engine != 'Unknown':
                # Update database
                update_response = supabase_client.table("games")\
                    .update({"engine": detected_engine})\
                    .eq("app_id", app_id)\
                    .execute()
                
                if update_response.data:
                    print(f"  ✅ Updated to: {detected_engine}")
                    updated_count += 1
                else:
                    print(f"  ❌ Failed to update database")
            else:
                print(f"  ⚠️ Still unknown")
            
            # Rate limiting
            time.sleep(0.5)
        
        print(f"\n📊 Updated {updated_count}/{len(response.data)} games")
        
    except Exception as e:
        print(f"Error in batch update: {e}")

def get_fresh_steam_data_engine(app_id: int) -> str:
    """Get fresh engine data from Steam API"""
    try:
        url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if str(app_id) in data and data[str(app_id)].get('success'):
                game_info = data[str(app_id)]['data']
                detector = EngineDetector()
                return detector.detect_engine_comprehensive(game_info, app_id)
    
    except Exception as e:
        print(f"Failed to get fresh Steam data for {app_id}: {e}")
    
    return 'Unknown'