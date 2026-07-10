#!/usr/bin/env python3

import os
import sys
import time
import json
import requests
from datetime import datetime, timedelta
from tqdm import tqdm
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import re

# Add current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from utils.extract_engine import extract_engine
    from utils.security_config import SecureRequestHandler
    from utils.dates import normalize_release_date
    from database.supabase import setup_supabase_connection
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're running this script from the slop_scraper directory")
    sys.exit(1)

class EngineDetector:
    """Engine detection with multiple detection methods"""
    
    def __init__(self):
        # Pattern database
        self.engine_patterns = {
            'Unity': [
                'unity', 'made with unity', 'unity3d', 'unity technologies',
                'unity engine', 'developed with unity', 'powered by unity'
            ],
            'Unreal Engine': [
                'unreal engine', 'unreal', 'epic games', 'unrealengine',
                'powered by unreal', 'built with unreal', 'ue4', 'ue5'
            ],
            'Source Engine': [
                'source engine', 'valve corporation', 'valve software',
                'source 2', 'steam', 'half-life', 'portal'
            ],
            'Creation Engine': [
                'creation engine', 'bethesda', 'gamebryo', 'elder scrolls',
                'fallout', 'starfield'
            ],
            'Frostbite': [
                'frostbite', 'electronic arts', 'ea games', 'dice',
                'battlefield', 'mass effect', 'fifa'
            ],
            'id Tech': [
                'id software', 'id tech', 'doom', 'quake', 'wolfenstein'
            ],
            'CryEngine': [
                'crytek', 'cryengine', 'cry engine', 'crysis'
            ],
            'GameMaker Studio': [
                'gamemaker', 'game maker', 'yoyo games'
            ],
            'Godot': [
                'godot', 'godot engine'
            ],
            'RPG Maker': [
                'rpg maker', 'enterbrain', 'kadokawa'
            ],
            'Construct': [
                'construct 2', 'construct 3', 'scirra'
            ]
        }
        
        # Developer to engine mappings
        self.developer_engines = {
            'Valve Corporation': 'Source Engine',
            'id Software': 'id Tech',
            'Epic Games': 'Unreal Engine',
            'Bethesda Game Studios': 'Creation Engine',
            'Bethesda Softworks': 'Creation Engine',
            'DICE': 'Frostbite',
            'Electronic Arts': 'Frostbite',
            'Crytek': 'CryEngine',
            'Unity Technologies': 'Unity',
            'YoYo Games': 'GameMaker Studio'
        }
        
        # Game series patterns
        self.game_series_engines = {
            'Counter-Strike': 'Source Engine',
            'Half-Life': 'Source Engine',
            'Portal': 'Source Engine', 
            'Team Fortress': 'Source Engine',
            'Left 4 Dead': 'Source Engine',
            'Dota': 'Source Engine',
            'Cities: Skylines': 'Unity',
            'Hearthstone': 'Unity',
            'Cuphead': 'Unity',
            'Ori and the': 'Unity',
            'Hollow Knight': 'Unity',
            'Among Us': 'Unity',
            'Fall Guys': 'Unity',
            'Rocket League': 'Unreal Engine',
            'Fortnite': 'Unreal Engine',
            'Gears of War': 'Unreal Engine',
            'Mass Effect': 'Unreal Engine',
            'Borderlands': 'Unreal Engine'
        }

    def detect_engine(self, game_info, app_id):
        """Engine detection with multiple strategies"""
        
        # Strategy 1: Use existing extract_engine
        try:
            engine = extract_engine(game_info, app_id)
            if engine and engine != 'Unknown':
                return engine, 0.8, ['Steam_API']
        except Exception:
            pass
        
        # Strategy 2: Text pattern matching in descriptions
        text_sources = [
            game_info.get('detailed_description', ''),
            game_info.get('about_the_game', ''),
            game_info.get('short_description', ''),
            ' '.join(game_info.get('developers', [])) if isinstance(game_info.get('developers'), list) else str(game_info.get('developers', '')),
            ' '.join(game_info.get('publishers', [])) if isinstance(game_info.get('publishers'), list) else str(game_info.get('publishers', ''))
        ]
        
        combined_text = ' '.join(text_sources).lower()
        
        # Check for engine mentions in text
        for engine, patterns in self.engine_patterns.items():
            for pattern in patterns:
                if pattern in combined_text:
                    confidence = 0.9 if 'engine' in pattern else 0.7
                    return engine, confidence, ['Text_Patterns']
        
        # Strategy 3: Developer matching
        developers = game_info.get('developers', [])
        if isinstance(developers, list):
            for dev in developers:
                if dev in self.developer_engines:
                    return self.developer_engines[dev], 0.95, ['Developer_Match']
        elif isinstance(developers, str) and developers in self.developer_engines:
            return self.developer_engines[developers], 0.95, ['Developer_Match']
        
        # Strategy 4: Game series matching
        game_name = game_info.get('name', '').lower()
        for series, engine in self.game_series_engines.items():
            if series.lower() in game_name:
                return engine, 0.85, ['Series_Match']
        
        # Strategy 5: Heuristic detection
        categories = game_info.get('categories', [])
        if isinstance(categories, list):
            category_text = ' '.join([cat.get('description', '') for cat in categories if isinstance(cat, dict)]).lower()
            
            # Indie games are often Unity
            if 'indie' in category_text:
                price = game_info.get('price_overview', {}).get('initial', 0)
                if price and price < 2000:  # Under $20
                    return 'Unity', 0.4, ['Heuristic_Indie']
            
            # VR games often use Unity/Unreal
            if any(vr_term in category_text for vr_term in ['vr', 'virtual reality']):
                return 'Unity', 0.3, ['Heuristic_VR']
        
        return 'Unknown', 0.0, []

class ThreadSafeStats:
    """Thread-safe statistics collector"""
    
    def __init__(self):
        self.lock = Lock()
        self.stats = {
            'attempts': 0,
            'api_success': 0,
            'db_updates': 0,
            'no_changes_needed': 0,
            'errors': 0,
            'rate_limited': 0,
            'no_data': 0,
            'field_updates': {'developer': 0, 'publisher': 0, 'release_date': 0, 'engine': 0},
            'actual_games_updated': set(),
            'engine_detections': {},
            'confidence_scores': []
        }
    
    def increment(self, field, value=1):
        with self.lock:
            self.stats[field] += value
    
    def add_to_set(self, field, value):
        with self.lock:
            self.stats[field].add(value)
    
    def record_field_update(self, field):
        with self.lock:
            if field in self.stats['field_updates']:
                self.stats['field_updates'][field] += 1
    
    def record_engine_detection(self, engine, confidence):
        with self.lock:
            if engine != 'Unknown':
                self.stats['engine_detections'][engine] = self.stats['engine_detections'].get(engine, 0) + 1
                self.stats['confidence_scores'].append(confidence)
    
    def get_stats(self):
        with self.lock:
            return self.stats.copy()

def load_environment_variables():
    """Load environment variables from various locations"""
    env_files = ['.env', '../.env', '../../.env', os.path.join(os.path.expanduser('~'), '.env')]
    
    for env_file in env_files:
        if os.path.exists(env_file):
            print(f"📁 Loading environment from: {env_file}")
            load_dotenv(env_file)
            return True
    
    print("⚠️ No .env file found, checking environment variables...")
    return False

def fetch_single_game_metadata(game_data, engine_detector, stats, rate_limit=0.8):
    """Fetch metadata for a single game (thread-safe)"""
    
    app_id = game_data['app_id']
    title = game_data['title']
    current_data = game_data
    
    try:
        # Rate limiting
        time.sleep(rate_limit)
        
        stats.increment('attempts')
        
        # Fetch from Steam API
        store_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=us&l=en"
        response = SecureRequestHandler.make_secure_request(store_url, timeout=20)
        
        if response.status_code == 429:
            stats.increment('rate_limited')
            time.sleep(5)  # Wait longer for rate limit
            return None
        
        if response.status_code != 200:
            stats.increment('errors')
            return None
        
        data = response.json()
        
        if str(app_id) not in data or not data[str(app_id)].get('success'):
            stats.increment('no_data')
            return None
        
        game_info = data[str(app_id)]['data']
        
        if game_info.get('type') != 'game':
            stats.increment('no_data')
            return None
        
        stats.increment('api_success')
        
        # Extract metadata
        engine, confidence, sources = engine_detector.detect_engine(game_info, app_id)
        stats.record_engine_detection(engine, confidence)
        
        metadata = {
            'developer': extract_developer_safely(game_info),
            'publisher': extract_publisher_safely(game_info),
            'release_date': normalize_release_date(extract_release_date_safely(game_info)),
            'engine': engine,
            'engine_confidence': confidence,
            'engine_sources': sources
        }
        
        # Determine what needs updating
        update_data = {}
        updated_fields = []
        
        for field in ['developer', 'publisher', 'release_date', 'engine']:
            new_value = metadata[field]
            current_value = current_data.get(field)
            
            if should_update_field(field, current_value, new_value, confidence if field == 'engine' else 1.0):
                update_data[field] = new_value
                updated_fields.append(field)
                stats.record_field_update(field)
        
        if update_data:
            stats.increment('db_updates')
            stats.add_to_set('actual_games_updated', app_id)
            return {
                'app_id': app_id,
                'title': title,
                'update_data': update_data,
                'updated_fields': updated_fields,
                'metadata': metadata
            }
        else:
            stats.increment('no_changes_needed')
            return None
            
    except Exception as e:
        stats.increment('errors')
        print(f"Error processing {title} ({app_id}): {e}")
        return None

def should_update_field(field, current_value, new_value, confidence=1.0):
    """Determine if a field should be updated with confidence consideration"""
    
    if not new_value or new_value in ['', 'null']:
        return False
    
    # For engine field, use confidence threshold
    if field == 'engine':
        if new_value == 'Unknown':
            return False
        
        # Only update if we have reasonable confidence
        if confidence < 0.4:
            return False
        
        # Don't downgrade from specific engine to low-confidence generic
        if (current_value and current_value not in ['Unknown', 'unknown', 'null', ''] and
            confidence < 0.7):
            return False
    
    # Normalize for comparison
    current_normalized = str(current_value).strip() if current_value else ''
    new_normalized = str(new_value).strip()
    
    # Update if different and new value is better
    if current_normalized != new_normalized:
        if not current_normalized or current_normalized in ['Unknown', 'unknown', 'null']:
            return True
        # Don't downgrade quality
        if new_normalized in ['Unknown', 'unknown']:
            return False
        return True
    
    return False

def run__backfill(limit=None, rate_limit=0.8, max_workers=5, debug=False, dry_run=False, analyze_only=False):
    print("Database Backfill Process")
    print("=" * 60)
    print(f"Configuration:")
    print(f"  Rate limit: {rate_limit}s between requests")
    print(f"  Max workers: {max_workers}")
    
    if not load_environment_variables():
        print("⚠️ Could not load environment variables from file")
    
    print("🔗 Connecting to Supabase...")
    supabase = setup_supabase_connection()
    if not supabase:
        print("❌ Failed to connect to database")
        return False
    
    # Analyze database gaps
    print("🔍 Analyzing database metadata gaps...")
    response = supabase.table("games").select("app_id, title, developer, publisher, release_date, engine").execute()
    
    if not response.data:
        print("❌ No games found in database")
        return {}
    
    total_games = len(response.data)
    
    # Find games needing updates
    needs_backfill = []
    field_analysis = {
        'developer': {'missing': 0, 'present': 0},
        'publisher': {'missing': 0, 'present': 0},
        'release_date': {'missing': 0, 'present': 0},
        'engine': {'missing': 0, 'unknown': 0, 'present': 0}
    }
    
    for game in response.data:
        missing_fields = []
        
        for field in ['developer', 'publisher', 'release_date', 'engine']:
            value = game.get(field)
            
            if value is None or value == '' or value == 'null':
                field_analysis[field]['missing'] += 1
                missing_fields.append(field)
            elif field == 'engine' and value in ['Unknown', 'unknown']:
                field_analysis[field]['unknown'] += 1
                missing_fields.append(field)
            else:
                field_analysis[field]['present'] += 1
        
        if missing_fields:
            needs_backfill.append(game)
    
    # Print analysis
    print(f"\n📊 Database Metadata Analysis ({total_games} total games):")
    for field, stats in field_analysis.items():
        missing = stats['missing']
        unknown = stats.get('unknown', 0)
        total_missing = missing + unknown
        present = stats['present']
        
        missing_pct = (total_missing / total_games) * 100
        present_pct = (present / total_games) * 100
        
        status = "🔴" if missing_pct > 50 else "🟡" if missing_pct > 25 else "🟢"
        print(f"   {status} {field}: {present} present ({present_pct:.1f}%), {total_missing} missing ({missing_pct:.1f}%)")
    
    print(f"\n🎯 Games needing backfill: {len(needs_backfill)}")
    
    if analyze_only:
        print("📊 Analysis complete.")
        return True
    
    if not needs_backfill:
        print("✅ No games need metadata backfill!")
        return True
    
    if limit:
        needs_backfill = needs_backfill[:limit]
        print(f"🔒 Processing first {len(needs_backfill)} games (limited by --limit)")
    
    if dry_run:
        print(f"\n🔍 DRY RUN MODE - No actual updates will be made")
        print(f"Sample games that would be updated:")
        for game in needs_backfill[:5]:
            missing = [field for field in ['developer', 'publisher', 'release_date', 'engine'] 
                      if not game.get(field) or game.get(field) in ['Unknown', 'unknown', '', 'null']]
            print(f"   📋 {game['title']} (App ID: {game['app_id']}) - Missing: {', '.join(missing)}")
        return True
    
    if not debug:
        print(f"\n❓ This will make API calls to Steam and update {len(needs_backfill)} games.")
        confirm = input(f"Proceed? (y/N): ").lower()
        if confirm != 'y':
            print("❌ Backfill cancelled")
            return False
    
    print(f"\n🚀 Starting backfill process...")
    
    # Initialize components
    engine_detector = EngineDetector()
    stats = ThreadSafeStats()
    
    # Process games with threading
    successful_updates = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_game = {
            executor.submit(fetch_single_game_metadata, game, engine_detector, stats, rate_limit): game 
            for game in needs_backfill
        }
        
        # Process results with progress bar
        with tqdm(total=len(needs_backfill), desc="Processing games", unit="game") as pbar:
            for future in as_completed(future_to_game):
                result = future.result()
                if result:
                    successful_updates.append(result)
                    pbar.set_postfix({
                        'Updates': len(successful_updates),
                        'Engines': len([u for u in successful_updates if u['metadata']['engine'] != 'Unknown'])
                    })
                pbar.update(1)
    
    # Update database
    if successful_updates:
        print(f"\n💾 Updating database with {len(successful_updates)} games...")
        
        for update in tqdm(successful_updates, desc="Database updates"):
            try:
                supabase.table("games").update(update['update_data']).eq("app_id", update['app_id']).execute()
            except Exception as e:
                print(f"Error updating {update['title']}: {e}")
    
    # Print results
    final_stats = stats.get_stats()
    
    print(f"\n 📊 Backfill Complete!")
    print(f"   🎯 Games processed: {final_stats['attempts']}")
    print(f"   📡 API calls successful: {final_stats['api_success']}")
    print(f"   💾 Actual database updates: {final_stats['db_updates']}")
    print(f"   ℹ️ No changes needed: {final_stats['no_changes_needed']}")
    print(f"   ❌ Errors: {final_stats['errors']}")
    print(f"   🔄 Rate limited: {final_stats['rate_limited']}")
    print(f"   ⚠️ No data available: {final_stats['no_data']}")
    
    if final_stats['attempts'] > 0:
        api_success_rate = (final_stats['api_success'] / final_stats['attempts']) * 100
        actual_update_rate = (final_stats['db_updates'] / final_stats['attempts']) * 100
        print(f"   📈 API success rate: {api_success_rate:.1f}%")
        print(f"   📈 Actual update rate: {actual_update_rate:.1f}%")
    
    print(f"\n📊 Field Update Summary:")
    for field, count in final_stats['field_updates'].items():
        print(f"   {field}: {count} games updated")
    
    # Engine detection analysis
    if final_stats['engine_detections']:
        print(f"\n Engine Detection Results:")
        total_engines = sum(final_stats['engine_detections'].values())
        print(f"   Engines detected: {total_engines}/{final_stats['api_success']} ({total_engines/max(1,final_stats['api_success'])*100:.1f}%)")
        
        if final_stats['confidence_scores']:
            avg_confidence = sum(final_stats['confidence_scores']) / len(final_stats['confidence_scores'])
            print(f"   Average confidence: {avg_confidence:.2f}")
        
        print(f"   Engine breakdown:")
        for engine, count in sorted(final_stats['engine_detections'].items(), key=lambda x: x[1], reverse=True):
            print(f"     {engine}: {count}")
    
    return True

# Helper functions
def extract_developer_safely(game_info):
    try:
        developers = game_info.get('developers', [])
        if isinstance(developers, list) and developers:
            return developers[0][:200].strip()
        elif isinstance(developers, str):
            return developers[:200].strip()
        return ''
    except Exception:
        return ''

def extract_publisher_safely(game_info):
    try:
        publishers = game_info.get('publishers', [])
        if isinstance(publishers, list) and publishers:
            return publishers[0][:200].strip()
        elif isinstance(publishers, str):
            return publishers[:200].strip()
        return ''
    except Exception:
        return ''

def extract_release_date_safely(game_info):
    try:
        release_info = game_info.get('release_date', {})
        if isinstance(release_info, dict):
            date = release_info.get('date', '')
            return date[:50].strip() if date else ''
        return ''
    except Exception:
        return ''

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Backfill games with missing metadata from Steam API')
    parser.add_argument('--limit', type=int, help='Maximum number of games to process')
    parser.add_argument('--rate', type=float, default=0.8, help='Rate limit in seconds between requests')
    parser.add_argument('--workers', type=int, default=5, help='Number of worker threads')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be updated without updating')
    parser.add_argument('--analyze-only', action='store_true', help='Only analyze database gaps')
    
    args = parser.parse_args()
    
    try:
        success = run__backfill(
            limit=args.limit,
            rate_limit=args.rate,
            max_workers=args.workers,
            debug=args.debug,
            dry_run=args.dry_run,
            analyze_only=args.analyze_only
        )
        
        if success:
            print("\n🎉 Backfill completed successfully!")
        else:
            print("\n❌ Backfill failed")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⚠️ Backfill interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)