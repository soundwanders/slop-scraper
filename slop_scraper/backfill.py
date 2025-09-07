#!/usr/bin/env python3
"""
Database Metadata Backfill Script
Updates games in database with missing metadata using local file for tracking
"""

import os
import sys
import time
import json
import requests
from datetime import datetime, timedelta
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

def load_tracking_data():
    """Load tracking data from local file"""
    tracking_file = "backfill_tracking.json"
    
    if os.path.exists(tracking_file):
        try:
            with open(tracking_file, 'r') as f:
                data = json.load(f)
                print(f"📄 Loaded tracking data for {len(data)} games")
                return data
        except Exception as e:
            print(f"⚠️ Error loading tracking file: {e}")
    
    print("📄 Starting with empty tracking data")
    return {}

def save_tracking_data(tracking_data):
    """Save tracking data to local file"""
    tracking_file = "backfill_tracking.json"
    
    try:
        with open(tracking_file, 'w') as f:
            json.dump(tracking_data, f, indent=2)
        print(f"💾 Saved tracking data for {len(tracking_data)} games")
    except Exception as e:
        print(f"⚠️ Error saving tracking file: {e}")

def should_skip_game(app_id, tracking_data, days_back=7):
    """Check if we should skip this game based on recent attempts"""
    
    app_id_str = str(app_id)
    if app_id_str not in tracking_data:
        return False
    
    attempt_info = tracking_data[app_id_str]
    last_attempt = attempt_info.get('last_attempt')
    last_result = attempt_info.get('last_result')
    
    if not last_attempt:
        return False
    
    try:
        # Parse the timestamp
        last_attempt_dt = datetime.fromisoformat(last_attempt.replace('Z', '+00:00'))
        cutoff_dt = datetime.now() - timedelta(days=days_back)
        
        # Skip if recent attempt with no useful result
        if (last_attempt_dt > cutoff_dt and 
            last_result in ['no_data', 'no_change', 'api_error']):
            return True
            
    except Exception:
        # If we can't parse the date, don't skip
        pass
    
    return False

def record_attempt(tracking_data, app_id, result, notes=""):
    """Record an attempt in tracking data"""
    app_id_str = str(app_id)
    
    if app_id_str not in tracking_data:
        tracking_data[app_id_str] = {'attempt_count': 0}
    
    tracking_data[app_id_str].update({
        'last_attempt': datetime.now().isoformat(),
        'last_result': result,
        'notes': notes[:200],
        'attempt_count': tracking_data[app_id_str].get('attempt_count', 0) + 1
    })

def analyze_database_gaps_with_file_tracking(supabase, tracking_data, skip_recent=True, debug=False):
    """Analyze database gaps using file-based tracking"""
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
        skipped_recent = 0
        
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
                # Check if we should skip this game
                if skip_recent and should_skip_game(app_id, tracking_data):
                    skipped_recent += 1
                    if debug:
                        print(f"⏭️ Skipping {title} - recently attempted with no useful data")
                else:
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
        if skipped_recent > 0:
            print(f"⏭️ Skipped {skipped_recent} games (recently attempted with no data)")
            print(f"📈 File-based optimization saved {skipped_recent} API calls!")
        
        return {
            'total_games': total_games,
            'field_analysis': field_analysis,
            'needs_backfill': needs_backfill,
            'skipped_recent': skipped_recent
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
                        status = "✅" if value and value != 'Unknown' and value.strip() else "❌"
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

def update_game_metadata_enhanced(supabase, app_id, metadata, current_data, debug=False):
    """
    Update game metadata in database with proper validation and tracking.
    Returns success status, message, and list of actually updated fields.
    """
    try:
        # Only update fields with valid data that are different from current data
        update_data = {}
        updated_fields = []
        
        for field, new_value in metadata.items():
            # Skip if new value is empty/invalid
            if not new_value or new_value == '' or new_value == 'null':
                if debug:
                    print(f"   ⚠️ Skipping {field} for {app_id} (empty/null value)")
                continue
                
            # Skip if engine is still Unknown
            if field == 'engine' and new_value == 'Unknown':
                if debug:
                    print(f"   ⚠️ Skipping engine update for {app_id} (still Unknown)")
                continue
            
            # Get current value from database
            current_value = current_data.get(field)
            
            # Normalize values for comparison
            current_normalized = str(current_value).strip() if current_value else ''
            new_normalized = str(new_value).strip()
            
            # Check if the value is actually different
            if current_normalized == new_normalized:
                if debug:
                    print(f"   ⚠️ Skipping {field} for {app_id} (same value: '{new_normalized}')")
                continue
            
            # Skip if current value is already good and new value isn't better
            if (current_normalized and 
                current_normalized not in ['Unknown', 'unknown', 'null', ''] and
                new_normalized in ['Unknown', 'unknown']):
                if debug:
                    print(f"   ⚠️ Skipping {field} for {app_id} (current value better: '{current_normalized}' vs '{new_normalized}')")
                continue
            
            # This field should be updated
            update_data[field] = new_value
            updated_fields.append(field)
            
            if debug:
                print(f"   ✅ Will update {field} for {app_id}: '{current_normalized}' → '{new_normalized}'")
        
        if not update_data:
            if debug:
                print(f"⚠️ No fields need updating for app_id {app_id}")
            return False, "No fields need updating", []
        
        # Perform the database update
        response = supabase.table("games").update(update_data).eq("app_id", app_id).execute()
        
        if response.data:
            if debug:
                print(f"✅ Successfully updated app_id {app_id} fields: {', '.join(updated_fields)}")
            return True, f"Updated: {', '.join(updated_fields)}", updated_fields
        else:
            if debug:
                print(f"⚠️ Update returned no data for app_id {app_id}")
            return False, "Update returned no data", []
        
    except Exception as e:
        if debug:
            print(f"⚠️ Error updating app_id {app_id}: {e}")
        return False, str(e), []

def run_file_based_backfill(limit=None, rate_limit=2.0, debug=False, dry_run=False, 
                           analyze_only=False, skip_recent=True, force_retry=False):
    """
    Run database backfill process with file-based tracking
    """
    
    print("🔄 Database Backfill Process - FILE-BASED TRACKING")
    print("=" * 60)
    
    if not load_environment_variables():
        print("⚠️ Could not load environment variables from file")
    
    print("🔗 Connecting to Supabase...")
    supabase = setup_supabase_connection()
    if not supabase:
        print("❌ Failed to connect to database")
        return False
    
    # Load file-based tracking
    tracking_data = load_tracking_data()
    
    # Analyze database gaps with file-based tracking
    analysis = analyze_database_gaps_with_file_tracking(
        supabase, 
        tracking_data,
        skip_recent=(skip_recent and not force_retry), 
        debug=debug
    )
    
    if not analysis:
        return False
    
    if analyze_only:
        print("📊 Analysis complete. Use --no-analyze-only to proceed with backfill.")
        if analysis.get('skipped_recent', 0) > 0:
            print("💡 Use --force-retry to include recently attempted games")
        return True
    
    needs_backfill = analysis['needs_backfill']
    
    if not needs_backfill:
        skipped = analysis.get('skipped_recent', 0)
        if skipped > 0:
            print(f"✅ No NEW games need metadata backfill!")
            print(f"ℹ️ {skipped} games were skipped (recently attempted)")
            print(f"💡 Use --force-retry to retry recently attempted games")
        else:
            print("✅ No games need metadata backfill!")
        return True
    
    print(f"🎯 Found {len(needs_backfill)} games needing backfill")
    
    # Sort by priority (games missing more fields first)
    needs_backfill.sort(key=lambda x: len(x['missing_fields']), reverse=True)
    
    if limit:
        original_count = len(needs_backfill)
        needs_backfill = needs_backfill[:limit]
        print(f"🔒 Processing first {len(needs_backfill)}/{original_count} games (limited by --limit)")
    
    # Show priority breakdown
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
    
    # Enhanced tracking with file-based recording
    stats = {
        'attempts': 0,
        'api_success': 0,
        'db_updates': 0,
        'no_changes_needed': 0,
        'errors': 0,
        'rate_limited': 0,
        'no_data': 0,
        'field_updates': {'developer': 0, 'publisher': 0, 'release_date': 0, 'engine': 0},
        'actual_games_updated': set()
    }
    
    with tqdm(needs_backfill, desc="Backfilling metadata", unit="game") as pbar:
        for game in pbar:
            app_id = game['app_id']
            title = game['title'][:30]
            missing_fields = game['missing_fields']
            current_data = game['current_data']
            
            pbar.set_description(f"Processing {title}...")
            stats['attempts'] += 1
            
            try:
                # Fetch metadata from Steam API
                metadata = fetch_complete_game_metadata_enhanced(app_id, debug=debug)
                
                if metadata:
                    stats['api_success'] += 1
                    
                    # Try to update database with enhanced tracking
                    success, message, updated_fields = update_game_metadata_enhanced(
                        supabase, app_id, metadata, current_data, debug=debug
                    )
                    
                    if success and updated_fields:
                        # Actual database update occurred
                        stats['db_updates'] += 1
                        stats['actual_games_updated'].add(app_id)
                        
                        # Track which specific fields were updated
                        for field in updated_fields:
                            if field in stats['field_updates']:
                                stats['field_updates'][field] += 1
                        
                        pbar.write(f"✅ {title} - Updated {len(updated_fields)} fields: {', '.join(updated_fields)}")
                        
                        # Record successful update
                        record_attempt(tracking_data, app_id, "updated", f"Updated: {', '.join(updated_fields)}")
                    
                    elif success and not updated_fields:
                        # Update "succeeded" but no fields actually changed
                        stats['no_changes_needed'] += 1
                        pbar.write(f"ℹ️ {title} - No changes needed (data already current)")
                        
                        # Record that no changes were needed
                        record_attempt(tracking_data, app_id, "no_change", "Data already current")
                    
                    else:
                        # Update failed
                        stats['errors'] += 1
                        pbar.write(f"❌ {title} - {message}")
                        
                        # Record the error
                        record_attempt(tracking_data, app_id, "db_error", message[:200])
                
                else:
                    stats['no_data'] += 1
                    pbar.write(f"⚠️ {title} - No Steam data available")
                    
                    # Record that no data was available
                    record_attempt(tracking_data, app_id, "no_data", "Steam API returned no data")
                
            except Exception as e:
                if "Rate limited" in str(e) or "429" in str(e):
                    stats['rate_limited'] += 1
                    pbar.write(f"🔄 {title} - Rate limited, waiting...")
                    time.sleep(rate_limit * 3)
                    
                    # Don't record rate limit as permanent failure
                else:
                    stats['errors'] += 1
                    pbar.write(f"❌ {title} - Error: {e}")
                    
                    # Record API error
                    record_attempt(tracking_data, app_id, "api_error", str(e)[:200])
            
            time.sleep(rate_limit)
    
    # Save tracking data
    save_tracking_data(tracking_data)
    
    # Results summary
    print(f"\n📊 Backfill Complete!")
    print(f"   🎯 Games processed: {stats['attempts']}")
    print(f"   📡 API calls successful: {stats['api_success']}")
    print(f"   💾 Actual database updates: {stats['db_updates']}")
    print(f"   ℹ️ No changes needed: {stats['no_changes_needed']}")
    print(f"   ❌ Errors: {stats['errors']}")
    print(f"   🔄 Rate limited: {stats['rate_limited']}")
    print(f"   ⚠️ No data available: {stats['no_data']}")
    
    if stats['attempts'] > 0:
        api_success_rate = (stats['api_success'] / stats['attempts']) * 100
        actual_update_rate = (stats['db_updates'] / stats['attempts']) * 100
        print(f"   📈 API success rate: {api_success_rate:.1f}%")
        print(f"   📈 Actual update rate: {actual_update_rate:.1f}%")
    
    print(f"\n📊 Field Update Summary (Actual Database Changes):")
    total_field_updates = sum(stats['field_updates'].values())
    for field, count in stats['field_updates'].items():
        print(f"   {field}: {count} games updated")
    
    print(f"\n🎯 Summary:")
    print(f"   • {len(stats['actual_games_updated'])} unique games had metadata updated")
    print(f"   • {total_field_updates} total field updates across all games")
    print(f"   • Tracking data saved to backfill_tracking.json")
    
    if stats['no_data'] > 0:
        print(f"   • {stats['no_data']} games recorded as having no Steam data")
        print(f"   • These will be skipped for 7 days to optimize future runs")
    
    # Enhanced recommendations
    print(f"\n💡 Recommendations:")
    if stats['db_updates'] < stats['api_success'] * 0.3:
        print(f"   ℹ️ Low update rate - most fetched data matches existing database values")
        print(f"   → This indicates the database is well-populated!")
    
    if stats['rate_limited'] > 0:
        print(f"   🔄 Consider increasing --rate to avoid rate limiting")
    
    if stats['field_updates']['engine'] < stats['db_updates'] * 0.3:
        print(f"   🎮 Engine detection might need improvement")
        
    if stats['no_data'] > stats['attempts'] * 0.2:
        print(f"   📡 High rate of missing Steam data - these games will be skipped for 7 days")
    
    print(f"   ⚡ Next run will be faster due to file-based tracking optimization")
    
    return True

# Helper functions for metadata extraction (same as before)
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

def extract_engine_safely(game_info, app_id):
    try:
        return extract_engine(game_info, app_id)
    except Exception as e:
        print(f"⚠️ Engine extraction error for {app_id}: {e}")
        return 'Unknown'

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='File-based backfill for missing metadata in database')
    parser.add_argument('--limit', type=int, help='Maximum number of games to process')
    parser.add_argument('--rate', type=float, default=2.0, help='Rate limit in seconds between requests')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be updated without actually updating')
    parser.add_argument('--analyze-only', action='store_true', help='Only analyze database gaps, don\'t perform backfill')
    parser.add_argument('--no-skip-recent', dest='skip_recent', action='store_false', default=True,
                       help='Don\'t skip recently attempted games (slower but more thorough)')
    parser.add_argument('--force-retry', action='store_true', 
                       help='Retry recently attempted games (ignores the 7-day skip period)')
    
    args = parser.parse_args()
    
    try:
        success = run_file_based_backfill(
            limit=args.limit,
            rate_limit=args.rate,
            debug=args.debug,
            dry_run=args.dry_run,
            analyze_only=args.analyze_only,
            skip_recent=args.skip_recent,
            force_retry=args.force_retry
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