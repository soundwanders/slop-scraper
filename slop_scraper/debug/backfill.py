#!/usr/bin/env python3
"""
Standalone Database Backfill Script
Fixes existing games in database that are missing developer, publisher, release_date, and engine fields
"""

import os
import sys
import time
import json
import requests
from tqdm import tqdm
from dotenv import load_dotenv

from ..utils import extract_engine

# Add current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Load environment variables from multiple possible locations
def load_environment_variables():
    """Load environment variables from various locations"""
    # Try current directory first
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
            break
    else:
        print("⚠️ No .env file found, checking environment variables...")

def get_supabase_credentials():
    """Get Supabase credentials from environment or credentials file"""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    
    print(f"🔍 Environment check:")
    print(f"   SUPABASE_URL: {'✅ Found' if url else '❌ Missing'}")
    print(f"   SUPABASE_SERVICE_ROLE_KEY: {'✅ Found' if key else '❌ Missing'}")
    
    # Check if environment variables are set
    if not url or not key:
        print("⚠️ Supabase credentials not found in environment variables.")
        print("Checking for credentials file...")
        
        # Try loading from a credentials file as fallback
        creds_file = os.path.join(os.path.expanduser('~'), '.supabase_creds')
        if os.path.exists(creds_file):
            try:
                with open(creds_file, 'r') as f:
                    creds = json.load(f)
                    url = creds.get('url')
                    key = creds.get('key')
                    print("✅ Loaded Supabase credentials from file.")
            except Exception as e:
                print(f"❌ Error loading credentials file: {e}")
    
    return url, key

def setup_supabase_connection():
    """Set up connection to Supabase with detailed error reporting"""
    try:
        from supabase import create_client
    except ImportError:
        print("❌ Error: supabase package not installed. Run: pip install supabase")
        return None
        
    url, key = get_supabase_credentials()
    
    if not url or not key:
        print("❌ No valid Supabase credentials found.")
        print("\n💡 To fix this, either:")
        print("   1. Set environment variables:")
        print("      export SUPABASE_URL='your_url_here'")
        print("      export SUPABASE_SERVICE_ROLE_KEY='your_key_here'")
        print("   2. Create ~/.supabase_creds file with:")
        print("      {\"url\": \"your_url\", \"key\": \"your_key\"}")
        print("   3. Create .env file in project root with:")
        print("      SUPABASE_URL=your_url_here")
        print("      SUPABASE_SERVICE_ROLE_KEY=your_key_here")
        return None
        
    try:
        print(f"🔗 Connecting to Supabase...")
        print(f"   URL: {url[:30]}...")  # Show first 30 chars for verification
        
        # Connect to Supabase
        supabase = create_client(url, key)
        
        # Test the connection with a simple query
        print("🧪 Testing database connection...")
        result = supabase.table("games").select("app_id").limit(1).execute()
        
        print("✅ Database connection successful!")
        return supabase
        
    except Exception as e:
        print(f"❌ Error connecting to Supabase: {e}")
        print("\n💡 Check that:")
        print("   - Your Supabase URL is correct")
        print("   - Your service role key is correct")
        print("   - Your database tables exist")
        print("   - Your internet connection is working")
        return None

def get_games_needing_backfill(supabase, debug=False):
    """Get games that need metadata backfill"""
    try:
        print("🔍 Scanning database for games missing metadata...")
        
        # Find games with missing or empty metadata fields
        response = supabase.table("games").select("app_id, title, developer, publisher, release_date, engine").execute()
        
        if debug:
            print(f"📊 Found {len(response.data)} total games in database")
        
        games_needing_backfill = []
        
        for game in response.data:
            needs_update = False
            missing_fields = []
            
            # Check which fields are missing or empty
            if not game.get('developer') or game.get('developer') == '':
                needs_update = True
                missing_fields.append('developer')
                
            if not game.get('publisher') or game.get('publisher') == '':
                needs_update = True
                missing_fields.append('publisher')
                
            if not game.get('release_date') or game.get('release_date') == '':
                needs_update = True
                missing_fields.append('release_date')
                
            if not game.get('engine') or game.get('engine') in ['Unknown', '']:
                needs_update = True
                missing_fields.append('engine')
            
            if needs_update:
                games_needing_backfill.append({
                    'app_id': game['app_id'],
                    'title': game['title'],
                    'missing_fields': missing_fields,
                    'current_data': game
                })
        
        return games_needing_backfill
        
    except Exception as e:
        print(f"❌ Error getting games needing backfill: {e}")
        import traceback
        traceback.print_exc()
        return []

def fetch_complete_game_metadata(app_id, debug=False):
    """Fetch complete metadata for a game from Steam API"""
    try:
        store_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=us&l=en"
        
        if debug:
            print(f"🌐 Fetching: {store_url}")
        
        response = requests.get(store_url, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            
            if str(app_id) in data and data[str(app_id)].get('success'):
                game_info = data[str(app_id)]['data']
                
                # Extract all metadata using helper functions
                metadata = {
                    'developer': extract_developer_safely(game_info),
                    'publisher': extract_publisher_safely(game_info),
                    'release_date': extract_release_date_safely(game_info),
                    'engine': extract_engine_safely(game_info)
                }
                
                if debug:
                    print(f"✅ Fetched metadata for {game_info.get('name', app_id)}")
                    for field, value in metadata.items():
                        print(f"   {field}: {value}")
                
                return metadata
            
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

def update_game_metadata(supabase, app_id, metadata, debug=False):
    """Update game metadata in database"""
    try:
        # Only update non-empty fields
        update_data = {}
        for field, value in metadata.items():
            if value and value != '':
                update_data[field] = value
        
        if update_data:
            response = supabase.table("games").update(update_data).eq("app_id", app_id).execute()
            
            if debug:
                print(f"✅ Updated app_id {app_id} with: {update_data}")
            
            return True
        else:
            if debug:
                print(f"⚠️ No valid data to update for app_id {app_id}")
        
    except Exception as e:
        if debug:
            print(f"⚠️ Error updating app_id {app_id}: {e}")
        return False
    
    return False

def run_database_backfill(limit=None, rate_limit=2.0, debug=False, dry_run=False):
    """
    Run the database backfill process
    
    Args:
        limit: Maximum number of games to process (None for all)
        rate_limit: Delay between Steam API requests
        debug: Enable debug output
        dry_run: If True, only show what would be updated without actually updating
    """
    
    print("🔄 Starting Database Backfill Process")
    print("=" * 60)
    
    # Load environment variables
    load_environment_variables()
    
    # Connect to database
    print("🔗 Connecting to Supabase...")
    supabase = setup_supabase_connection()
    if not supabase:
        print("❌ Failed to connect to database")
        return False
    
    # Get games needing backfill
    print("🔍 Finding games that need metadata backfill...")
    games_needing_backfill = get_games_needing_backfill(supabase, debug=debug)
    
    if not games_needing_backfill:
        print("✅ No games need metadata backfill!")
        return True
    
    print(f"📊 Found {len(games_needing_backfill)} games needing backfill")
    
    # Limit if specified
    if limit:
        games_needing_backfill = games_needing_backfill[:limit]
        print(f"🔒 Processing first {len(games_needing_backfill)} games (limited by --limit)")
    
    # Show summary of what will be updated
    field_counts = {}
    for game in games_needing_backfill:
        for field in game['missing_fields']:
            field_counts[field] = field_counts.get(field, 0) + 1
    
    print(f"\n📋 Missing fields summary:")
    for field, count in field_counts.items():
        print(f"   {field}: {count} games")
    
    if dry_run:
        print(f"\n🔍 DRY RUN MODE - No actual updates will be made")
        print(f"Games that would be updated:")
        for game in games_needing_backfill[:10]:  # Show first 10
            print(f"   {game['title']} (App ID: {game['app_id']}) - Missing: {', '.join(game['missing_fields'])}")
        if len(games_needing_backfill) > 10:
            print(f"   ... and {len(games_needing_backfill) - 10} more")
        return True
    
    # Confirm before proceeding
    if not debug:
        confirm = input(f"\n❓ Update {len(games_needing_backfill)} games? (y/N): ").lower()
        if confirm != 'y':
            print("❌ Backfill cancelled")
            return False
    
    # Process games
    print(f"\n🚀 Starting backfill process...")
    success_count = 0
    error_count = 0
    rate_limit_count = 0
    
    with tqdm(games_needing_backfill, desc="Backfilling metadata", unit="game") as pbar:
        for game in pbar:
            app_id = game['app_id']
            title = game['title']
            
            pbar.set_description(f"Processing {title[:20]}...")
            
            try:
                # Fetch metadata from Steam API
                metadata = fetch_complete_game_metadata(app_id, debug=debug)
                
                if metadata:
                    # Update database
                    if update_game_metadata(supabase, app_id, metadata, debug=debug):
                        success_count += 1
                        pbar.write(f"✅ Updated {title}")
                    else:
                        error_count += 1
                        pbar.write(f"❌ Failed to update {title}")
                else:
                    error_count += 1
                    pbar.write(f"❌ No metadata found for {title}")
                
            except Exception as e:
                if "Rate limited" in str(e) or "429" in str(e):
                    rate_limit_count += 1
                    pbar.write(f"🔄 Rate limited for {title}, waiting...")
                    time.sleep(rate_limit * 2)  # Double delay on rate limit
                    # Could implement retry logic here
                else:
                    error_count += 1
                    pbar.write(f"❌ Error processing {title}: {e}")
            
            # Rate limiting between requests
            time.sleep(rate_limit)
    
    # Summary
    print(f"\n📊 Backfill Complete!")
    print(f"   ✅ Successfully updated: {success_count}")
    print(f"   ❌ Errors: {error_count}")
    print(f"   🔄 Rate limited: {rate_limit_count}")
    print(f"   📈 Success rate: {(success_count / len(games_needing_backfill) * 100):.1f}%")
    
    return True

# Helper functions for metadata extraction
def extract_developer_safely(game_info):
    """Safely extract developer information from Steam API response"""
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
    """Safely extract publisher information from Steam API response"""
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
    """Safely extract release date from Steam API response"""
    try:
        release_info = game_info.get('release_date', {})
        if isinstance(release_info, dict):
            return release_info.get('date', '')
        return ''
    except Exception:
        return ''


def extract_engine_safely(game_info):
    """Engine detection wrapper"""
    app_id = game_info.get('appid') or game_info.get('steam_appid')
    return extract_engine(game_info, app_id)

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Backfill missing metadata in database')
    parser.add_argument('--limit', type=int, help='Maximum number of games to process')
    parser.add_argument('--rate', type=float, default=2.0, help='Rate limit in seconds between requests')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be updated without actually updating')
    
    args = parser.parse_args()
    
    try:
        success = run_database_backfill(
            limit=args.limit,
            rate_limit=args.rate,
            debug=args.debug,
            dry_run=args.dry_run
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