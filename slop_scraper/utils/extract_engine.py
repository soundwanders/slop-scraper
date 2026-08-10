"""
Engine detection system for slop-scraper using multiple data sources and pattern matching
"""

import re
import requests
import time
from typing import Dict, Optional, List

try:
    from utils.known_engines import lookup_title_engine
    from utils.pcgw_engines import lookup_engine
except ImportError:
    from .known_engines import lookup_title_engine
    from .pcgw_engines import lookup_engine

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
        
        # Method 0: PCGamingWiki's infobox via its Cargo API — sourced,
        # version-specific, keyed by Steam App ID, and independently
        # maintained. This is the highest authority available.
        #
        # It outranks the curated table below, which is the reverse of the
        # original ordering. The curated table is a hand-written compilation,
        # and where the two disagreed the wiki was right and the table wrong
        # every time it was checked:
        #
        #   Dota Underlords  table said Unity;   it is Source 2
        #   Quake / Quake II table said id Tech; Steam ships Kex Engine
        #
        # The table's failure mode is systematic rather than random — it is
        # least reliable on exactly the obscure titles a fallback exists to
        # cover — so it is demoted to filling gaps the wiki does not reach.
        if app_id:
            external_engine = self._detect_engine_external(app_id, game_info.get('name', ''))
            if external_engine and external_engine != 'Unknown':
                return external_engine

        # Method 1: the curated title table, for games PCGamingWiki has no row
        # for (about 7 in the current catalogue).
        curated = lookup_title_engine(game_info.get('name', ''))
        if curated is not None and curated != 'Unknown':
            return curated

        # Method 2: Check if engine is directly provided by Steam API.
        # Steam's appdetails carries no engine field in practice, so this is
        # effectively dead weight kept for other callers that pass richer data.
        direct_engine = self._extract_direct_engine(game_info)
        if direct_engine and direct_engine != 'Unknown':
            return direct_engine

        # A curated entry of 'Unknown' is a deliberate decline: we know this
        # game does NOT share its franchise's engine (Fallout 1, Need for
        # Speed: Shift, Minecraft: Story Mode). It exists to stop the GUESSING
        # below, so it is honoured only after the sourced lookups above have
        # had their chance.
        if curated == 'Unknown':
            return 'Unknown'

        # Method 3: pattern matching on existing Steam data
        pattern_engine = self._detect_engine_by_patterns(game_info)
        if pattern_engine and pattern_engine != 'Unknown':
            return pattern_engine

        # A further method used to guess from the Steam app ID: anything
        # numbered 200000-300000 was labelled "Unity Engine (heuristic)",
        # anything under 1000 "Source Engine (heuristic)". An app ID records
        # when a game was registered with Steam, not what it was built with,
        # so this invented an engine for hundreds of unrelated games. Removed —
        # 'Unknown' is the honest answer. _detect_engine_by_appid is kept below
        # but unused, in case the ranges are ever wanted as a low-confidence
        # signal that is clearly separated from real evidence.

        # Method 4: retained for call-site compatibility; now a no-op that
        # always declines. See _detect_engine_heuristic for why.
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
        """
        Engine from PCGamingWiki's structured infobox data, by Steam App ID.

        This replaces two lookups that could not work:

          * SteamDB — scraped steamdb.info HTML, which is Cloudflare-protected
            and disallows scraping. It never returned a result, and it matched
            engine patterns against the whole page, so a result would have
            been unreliable anyway. Removed rather than repaired.
          * PCGamingWiki via prop=extracts&exintro — that returns the
            article's intro PROSE, while engines live in the infobox. Right
            site, wrong endpoint.

        Between them they cost about 2.4 seconds per game and answered nothing.
        The Cargo API answers properly and in bulk: one fetch covers ~26,800
        app IDs, cached for a week, so this call is an in-memory dict lookup.

        `game_title` is unused now — matching is by app ID, which is exact,
        rather than by title string, which is not. It stays in the signature
        for the existing call site.
        """
        if not app_id:
            return 'Unknown'

        cache_key = f"pcgw_{app_id}"
        if cache_key in self.external_cache:
            return self.external_cache[cache_key]

        family, _detail = lookup_engine(app_id)
        engine = family or 'Unknown'

        self.external_cache[cache_key] = engine
        return engine
    
    # _check_steamdb and _check_pcgamingwiki were removed here.
    #
    # SteamDB scraped steamdb.info HTML, which is Cloudflare-protected and
    # disallows scraping; it never returned a result. PCGamingWiki queried
    # prop=extracts&exintro, the article intro prose, while engine data lives
    # in the infobox — so it could not return one either. Both then
    # substring-matched engine patterns against a whole page, which would have
    # been unreliable even had they worked.
    #
    # utils/pcgw_engines.py queries the same wiki through its Cargo API, which
    # exposes the infobox as structured data keyed by Steam App ID. See
    # _detect_engine_external above.

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