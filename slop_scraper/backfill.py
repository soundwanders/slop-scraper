#!/usr/bin/env python3
"""
Database Metadata Backfill Script
Updates games in database with missing developer, publisher, release_date, and engine fields
"""

import os
import sys
import time
import json
import requests
from tqdm import tqdm
from dotenv import load_dotenv

# Add current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from utils.extract_engine import extract_engine
    from utils.security_config import SecureRequestHandler
    from database.supabase import setup_supabase_connection
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're running this script from the slop_scraper directory")
    sys.exit(1)

def load_environment_variables():
    """Load environment variables from various locations"""
    env_files = [
        '.env',
        '../.env',
        '../../.env',
        os.path.join(os.path.expanduser('~'), '.env'),
    ]
    
    for env_file in env_files:
        if os.path.exists(env_file):
            print(f"📁 Loading environment from: {env_file}")
            load_dotenv(env_file)
            return True
    
    print("⚠️ No .env file found, checking environment variables...")
    return False

def analyze_database_gaps(supabase, debug=False):
    """Analyze what metadata is missing from games in the database."""
    try:
        print("🔍 Analyzing database metadata gaps...")
        
        response = supabase.table("games").select("app_id, title, developer, publisher, release_date, engine").execute()
        
        if not response.data:
            print("❌ No games found in database")
            return {}
        
        total_games = len(response.data)
        
        field_analysis = {
            'developer': {'missing': 0, 'empty': 0, 'present': 0},
            'publisher': {'missing': 0, 'empty': 0, 'present': 0},
            'release_date': {'missing': 0, 'empty': 0, 'present': 0},
            'engine': {'missing': 0, 'empty': 0, 'unknown': 0, 'present': 0}
        }
        
        needs_backfill = []
        
        for game in response.data:
            app_id = game['app_id']
            title = game['title']
            missing_fields = []
            
            # Check each metadata field
            for field in ['developer', 'publisher', 'release_date', 'engine']:
                value = game.get(field)
                
                if value is None:
                    field_analysis[field]['missing'] += 1
                    missing_fields.append(field)
                elif value == '' or value == 'null':
                    field_analysis[field]['empty'] += 1
                    missing_fields.append(field)
                elif field == 'engine' and value in ['Unknown', 'unknown']:
                    field_analysis[field]['unknown'] += 1
                    missing_fields.append(field)
                else:
                    field_analysis[field]['present'] += 1
            
            if missing_fields:
                needs_backfill.append({
                    'app_id': app_id,
                    'title': title,
                    'missing_fields': missing_fields,
                    'current_data': game
                })
        
        # Print analysis results
        print(f"\n📊 Database Metadata Analysis ({total_games} total games):")
        for field, stats in field_analysis.items():
            missing = stats['missing'] + stats['empty']
            if field == 'engine':
                missing += stats['unknown']
            
            present = stats['present']
            missing_pct = (missing / total_games) * 100
            present_pct = (present / total_games) * 100
            
            status = "🔴" if missing_pct > 50 else "🟡" if missing_pct > 25 else "🟢"
            print(f"   {status} {field}: {present} present ({present_pct:.1f}%), {missing} missing ({missing_pct:.1f}%)")
        
        print(f"\n🎯 Games needing backfill: {len(needs_backfill)}")
        
        return {
            'total_games': total_games,
            'field_analysis': field_analysis,
            'needs_backfill': needs_backfill
        }
        
    except Exception as e:
        print(f"❌ Error analyzing database: {e}")
        import traceback
        traceback.print_exc()
        return {}

def fetch_complete_game_metadata_enhanced(app_id, debug=False):
    """Fetch complete metadata for a game from Steam Store API."""
    try:
        store_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=us&l=en"
        
        if debug:
            print(f"🌐 Fetching: {store_url}")
        
        response = SecureRequestHandler.make_secure_request(store_url, timeout=20, debug=debug)
        
        if response.status_code == 200:
            data = response.json()
            
            if str(app_id) in data and data[str(app_id)].get('success'):
                game_info = data[str(app_id)]['data']
                
                if game_info.get('type') != 'game':
                    if debug:
                        print(f"⚠️ App {app_id} is not a game (type: {game_info.get('type')})")
                    return None
                
                metadata = {
                    'developer': extract_developer_safely(game_info),
                    'publisher': extract_publisher_safely(game_info),
                    'release_date': extract_release_date_safely(game_info),
                    'engine': extract_engine_safely(game_info, app_id)
                }
                
                if debug:
                    title = game_info.get('name', f'App {app_id}')
                    print(f"✅ Fetched metadata for {title}")
                    for field, value in metadata.items():
                        status = "✅" if value and value != 'Unknown' else "❌"
                        print(f"   {status} {field}: {value or 'MISSING'}")
                
                return metadata
            else:
                if debug:
                    error_msg = data.get(str(app_id), {})
                    print(f"⚠️ Steam API returned no data for {app_id}: {error_msg}")
                
        elif response.status_code == 429:
            if debug:
                print(f"🔄 Rate limited for app_id {app_id}")
            raise Exception("Rate limited")
        else:
            if debug:
                print(f"⚠️ Failed to fetch metadata for app_id {app_id}: HTTP {response.status_code}")
            
    except Exception as e:
        if debug:
            print(f"⚠️ Error fetching metadata for app_id {app_id}: {e}")
        raise e
    
    return None

def update_game_metadata_enhanced(supabase, app_id, metadata, debug=False):
    """Update game metadata in database with validation."""
    try:
        # Only update fields with valid data
        update_data = {}
        for field, value in metadata.items():
            if value and value != '' and value != 'null':
                if field == 'engine' and value == 'Unknown':
                    if debug:
                        print(f"   ⚠️ Skipping engine update for {app_id} (still Unknown)")
                    continue
                update_data[field] = value
        
        if not update_data:
            if debug:
                print(f"⚠️ No valid data to update for app_id {app_id}")
            return False, "No valid data"
        
        response = supabase.table("games").update(update_data).eq("app_id", app_id).execute()
        
        if response.data:
            updated_fields = list(update_data.keys())
            if debug:
                print(f"✅ Updated app_id {app_id} fields: {', '.join(updated_fields)}")
            return True, f"Updated: {', '.join(updated_fields)}"
        else:
            if debug:
                print(f"⚠️ Update returned no data for app_id {app_id}")
            return False, "Update returned no data"
        
    except Exception as e:
        if debug:
            print(f"⚠️ Error updating app_id {app_id}: {e}")
        return False, str(e)

def run_enhanced_backfill(limit=None, rate_limit=2.0, debug=False, dry_run=False, analyze_only=False):
    """
    Run database backfill process to update missing metadata.
    
    Args:
        limit: Maximum number of games to process
        rate_limit: Delay between Steam API requests
        debug: Enable verbose output
        dry_run: Show what would be updated without updating
        analyze_only: Only analyze gaps, don't perform backfill
    """
    
    print("🔄 Database Backfill Process")
    print("=" * 60)
    
    if not load_environment_variables():
        print("⚠️ Could not load environment variables from file")
    
    print("🔗 Connecting to Supabase...")
    supabase = setup_supabase_connection()
    if not supabase:
        print("❌ Failed to connect to database")
        return False
    
    analysis = analyze_database_gaps(supabase, debug=debug)
    if not analysis:
        return False
    
    if analyze_only:
        print("📊 Analysis complete. Use --no-analyze-only to proceed with backfill.")
        return True
    
    needs_backfill = analysis['needs_backfill']
    
    if not needs_backfill:
        print("✅ No games need metadata backfill!")
        return True
    
    print(f"🎯 Found {len(needs_backfill)} games needing backfill")
    
    # Sort by priority (games missing more fields first)
    needs_backfill.sort(key=lambda x: len(x['missing_fields']), reverse=True)
    
    if limit:
        original_count = len(needs_backfill)
        needs_backfill = needs_backfill[:limit]
        print(f"🔒 Processing first {len(needs_backfill)}/{original_count} games (limited by --limit)")
    
    # Show priority distribution
    priority_breakdown = {}
    for game in needs_backfill:
        field_count = len(game['missing_fields'])
        priority_breakdown[field_count] = priority_breakdown.get(field_count, 0) + 1
    
    print(f"\n📋 Priority breakdown:")
    for field_count in sorted(priority_breakdown.keys(), reverse=True):
        count = priority_breakdown[field_count]
        priority = "🔴 HIGH" if field_count >= 3 else "🟡 MEDIUM" if field_count == 2 else "🟢 LOW"
        print(f"   {priority}: {count} games missing {field_count} fields")
    
    if dry_run:
        print(f"\n🔍 DRY RUN MODE - No actual updates will be made")
        print(f"Sample games that would be updated:")
        for game in needs_backfill[:5]:
            print(f"   📋 {game['title']} (App ID: {game['app_id']})")
            print(f"      Missing: {', '.join(game['missing_fields'])}")
        if len(needs_backfill) > 5:
            print(f"   ... and {len(needs_backfill) - 5} more")
        return True
    
    if not debug:
        print(f"\n❓ This will make API calls to Steam and update {len(needs_backfill)} games.")
        confirm = input(f"Proceed? (y/N): ").lower()
        if confirm != 'y':
            print("❌ Backfill cancelled")
            return False
    
    print(f"\n🚀 Starting backfill process...")
    
    stats = {
        'success': 0,
        'errors': 0,
        'rate_limited': 0,
        'no_data': 0,
        'field_updates': {'developer': 0, 'publisher': 0, 'release_date': 0, 'engine': 0}
    }
    
    with tqdm(needs_backfill, desc="Backfilling metadata", unit="game") as pbar:
        for game in pbar:
            app_id = game['app_id']
            title = game['title'][:30]
            missing_fields = game['missing_fields']
            
            pbar.set_description(f"Processing {title}...")
            
            try:
                metadata = fetch_complete_game_metadata_enhanced(app_id, debug=debug)
                
                if metadata:
                    success, message = update_game_metadata_enhanced(supabase, app_id, metadata, debug=debug)
                    
                    if success:
                        stats['success'] += 1
                        
                        # Track field update statistics
                        for field in missing_fields:
                            if metadata.get(field) and metadata[field] != 'Unknown':
                                stats['field_updates'][field] += 1
                        
                        pbar.write(f"✅ {title} - {message}")
                    else:
                        stats['errors'] += 1
                        pbar.write(f"❌ {title} - {message}")
                else:
                    stats['no_data'] += 1
                    pbar.write(f"⚠️ {title} - No Steam data available")
                
            except Exception as e:
                if "Rate limited" in str(e) or "429" in str(e):
                    stats['rate_limited'] += 1
                    pbar.write(f"🔄 {title} - Rate limited, waiting...")
                    time.sleep(rate_limit * 3)
                else:
                    stats['errors'] += 1
                    pbar.write(f"❌ {title} - Error: {e}")
            
            time.sleep(rate_limit)
    
    # Results summary
    print(f"\n📊 Backfill Complete!")
    print(f"   ✅ Successfully updated: {stats['success']}")
    print(f"   ❌ Errors: {stats['errors']}")
    print(f"   🔄 Rate limited: {stats['rate_limited']}")
    print(f"   ⚠️ No data available: {stats['no_data']}")
    
    if needs_backfill:
        success_rate = (stats['success'] / len(needs_backfill)) * 100
        print(f"   📈 Overall success rate: {success_rate:.1f}%")
    
    print(f"\n📊 Field Update Summary:")
    for field, count in stats['field_updates'].items():
        print(f"   {field}: {count} games updated")
    
    # Recommendations
    print(f"\n💡 Recommendations:")
    if stats['success'] < len(needs_backfill) * 0.8:
        print(f"   ⚠️ Low success rate - check Steam API connectivity and rate limits")
    if stats['rate_limited'] > 0:
        print(f"   🔄 Consider increasing --rate to avoid rate limiting")
    if stats['field_updates']['engine'] < stats['success'] * 0.5:
        print(f"   🎮 Engine detection might need improvement")
    
    return True

# Helper functions for metadata extraction
def extract_developer_safely(game_info):
    """Extract developer information from Steam API response."""
    try:
        developers = game_info.get('developers', [])
        if isinstance(developers, list) and developers:
            return developers[0][:200]
        elif isinstance(developers, str):
            return developers[:200]
        return ''
    except Exception:
        return ''

def extract_publisher_safely(game_info):
    """Extract publisher information from Steam API response."""
    try:
        publishers = game_info.get('publishers', [])
        if isinstance(publishers, list) and publishers:
            return publishers[0][:200]
        elif isinstance(publishers, str):
            return publishers[:200]
        return ''
    except Exception:
        return ''

def extract_release_date_safely(game_info):
    """Extract release date from Steam API response."""
    try:
        release_info = game_info.get('release_date', {})
        if isinstance(release_info, dict):
            date = release_info.get('date', '')
            return date[:50] if date else ''
        return ''
    except Exception:
        return ''

def extract_engine_safely(game_info, app_id):
    """Extract game engine using detection system."""
    try:
        return extract_engine(game_info, app_id)
    except Exception as e:
        print(f"⚠️ Engine extraction error for {app_id}: {e}")
        return 'Unknown'

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Enhanced backfill for missing metadata in database')
    parser.add_argument('--limit', type=int, help='Maximum number of games to process')
    parser.add_argument('--rate', type=float, default=2.0, help='Rate limit in seconds between requests')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be updated without actually updating')
    parser.add_argument('--analyze-only', action='store_true', help='Only analyze database gaps, don\'t perform backfill')
    
    args = parser.parse_args()
    
    try:
        success = run_enhanced_backfill(
            limit=args.limit,
            rate_limit=args.rate,
            debug=args.debug,
            dry_run=args.dry_run,
            analyze_only=args.analyze_only
        )
        
        if success:
            print("\n🎉 Backfill script completed successfully!")
        else:
            print("\n❌ Backfill script failed")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⚠️ Backfill interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)