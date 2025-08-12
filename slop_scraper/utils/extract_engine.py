"""
Engine detection system for slop-scraper using multiple data sources and pattern matching
"""

import re
import requests
import time
from typing import Dict, Optional, List
from bs4 import BeautifulSoup

class EngineDetector:
    """Engine detection using multiple sources and improved patterns"""
    
    def __init__(self):
        # Comprehensive engine detection patterns
        self.engine_patterns = {
            'Unity Engine': [
                # Direct indicators
                'unity', 'unity technologies', 'made with unity', 'unity3d',
                # Known Unity developers
                'innersloth', 'team cherry', 'night school studio', 'ori and the',
                # Unity-specific terms that appear in Steam data
                'unity player', 'unityengine'
            ],
            
            'Unreal Engine': [
                # Direct indicators  
                'unreal engine', 'unreal', 'epic games', 'epic megagames',
                # Known Unreal developers
                'gearbox software', 'bioware', 'rocksteady studios',
                # Unreal-specific terms
                'unrealtournament', 'unrealengine'
            ],
            
            'Source Engine': [
                # Direct indicators
                'source engine', 'source 2', 'valve corporation', 'valve software',
                # Source games/franchises
                'half-life', 'counter-strike', 'portal', 'team fortress', 'left 4 dead',
                'dota', 'garry', 'black mesa'
            ],
            
            'Creation Engine': [
                # Bethesda games
                'bethesda', 'elder scrolls', 'skyrim', 'fallout', 'starfield',
                'creation engine', 'gamebryo'
            ],
            
            'Frostbite Engine': [
                # EA/DICE games
                'electronic arts', 'ea games', 'dice', 'frostbite',
                'battlefield', 'fifa', 'need for speed', 'mass effect andromeda'
            ],
            
            'id Tech': [
                # id Software
                'id software', 'id tech', 'doom', 'quake', 'wolfenstein', 'rage'
            ],
            
            'CryEngine': [
                'crytek', 'cryengine', 'cry engine', 'crysis', 'hunt showdown'
            ],
            
            'GameMaker Studio': [
                'gamemaker', 'game maker', 'yoyo games', 'undertale', 'hyper light drifter'
            ],
            
            'Godot Engine': [
                'godot', 'godot engine'
            ],
            
            'RPG Maker': [
                'rpg maker', 'rpgmaker', 'enterbrain', 'kadokawa'
            ],
            
            'Construct': [
                'construct 2', 'construct 3', 'scirra'
            ],
            
            'Java (Minecraft)': [
                'minecraft', 'mojang'
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
        
        # Method 1: Check if engine is directly provided by Steam API
        direct_engine = self._extract_direct_engine(game_info)
        if direct_engine and direct_engine != 'Unknown':
            return direct_engine
        
        # Method 2:  pattern matching on existing Steam data
        pattern_engine = self._detect_engine_by_patterns(game_info)
        if pattern_engine and pattern_engine != 'Unknown':
            return pattern_engine
        
        # Method 3: Check app ID ranges (heuristic)
        if app_id:
            appid_engine = self._detect_engine_by_appid(app_id)
            if appid_engine and appid_engine != 'Unknown':
                return appid_engine
        
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
    
    def _extract_direct_engine(self, game_info: Dict) -> str:
        """Extract engine if directly provided by Steam API"""
        # Check various fields where engine might be mentioned
        fields_to_check = [
            'engine', 'game_engine', 'technology',
            'detailed_description', 'about_the_game'
        ]
        
        for field in fields_to_check:
            if field in game_info:
                content = str(game_info[field]).lower()
                
                # Look for direct engine mentions
                for engine, patterns in self.engine_patterns.items():
                    if any(pattern in content for pattern in patterns):
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
        
        # Score each engine based on pattern matches
        engine_scores = {}
        for engine, patterns in self.engine_patterns.items():
            score = 0
            for pattern in patterns:
                if pattern in all_text:
                    # Weight different types of matches
                    if pattern in text_fields[0]:  # Title match
                        score += 3
                    elif any(pattern in dev for dev in text_fields[1:6]):  # Developer/publisher match  
                        score += 2
                    else:  # General match
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
        """Advanced heuristic detection based on game characteristics"""
        
        # File size heuristics (Unity games often have certain size patterns)
        # Release date heuristics (certain engines popular in certain eras)
        # Price point heuristics (indie games more likely to use certain engines)
        
        try:
            release_date = game_info.get('release_date', {})
            if isinstance(release_date, dict):
                date_str = release_date.get('date', '')
                
                # Extract year
                year_match = re.search(r'(\d{4})', date_str)
                if year_match:
                    year = int(year_match.group(1))
                    
                    # Unity became very popular after 2010
                    if year >= 2010:
                        # Check for indie indicators
                        price = game_info.get('price_overview', {}).get('initial', 0)
                        if price and price < 3000:  # Under $30
                            categories = game_info.get('categories', [])
                            if any('indie' in str(cat).lower() for cat in categories):
                                return 'Unity Engine (heuristic)'
        
        except Exception:
            pass
        
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