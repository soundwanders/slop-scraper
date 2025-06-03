import os
import json
from supabase import create_client

def get_supabase_credentials():
    """Get Supabase credentials from environment or credentials file"""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    
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
                print(f"Error loading credentials file: {e}")
    return url, key

def setup_supabase_connection():
    """Set up connection to Supabase"""
    url, key = get_supabase_credentials()
    
    if not url or not key:
        print("No valid Supabase credentials found.")
        return None
        
    try:
        # Connect to Supabase
        supabase = create_client(url, key)
        
        # Verify database structure
        if verify_db_structure(supabase):
            # Seed sources if needed
            seed_sources(supabase)
            return supabase
        else:
            print("Database structure verification failed.")
            return None
            
    except Exception as e:
        print(f"Error connecting to Supabase: {e}")
        return None

def verify_db_structure(supabase):
    """Verify that the required tables exist in the database"""
    try:
        # Check if the games table exists by querying it
        games_result = supabase.table("games").select("app_id").limit(1).execute()
        
        # Check if the launch_options table exists
        options_result = supabase.table("launch_options").select("id").limit(1).execute()
        
        # Check if the sources table exists
        sources_result = supabase.table("sources").select("id").limit(1).execute()
        
        print("✅ Database structure verification passed.")
        return True
    except Exception as e:
        print(f"⚠️ Database structure verification failed: {e}")
        print("Please make sure you've created the required tables using the SQL schema.")
        print("For instructions, see the README.md file or the documentation.")
        return False

def seed_sources(supabase):
    """Seed the sources table with common sources if empty"""
    try:
        # Check if sources table is empty
        result = supabase.table("sources").select("count", count="exact").execute()
        count = result.count if hasattr(result, 'count') else 0
        
        if count == 0:
            # Add common sources
            sources = [
                {
                    "name": "PCGamingWiki",
                    "description": "Launch options from PCGamingWiki pages",
                    "reliability_score": 0.9
                },
                {
                    "name": "Steam Community",
                    "description": "Launch options from Steam community guides",
                    "reliability_score": 0.7
                },
                {
                    "name": "Common Source Engine",
                    "description": "Common launch options for Source engine games",
                    "reliability_score": 0.8
                },
                {
                    "name": "Common Unity Engine",
                    "description": "Common launch options for Unity engine games",
                    "reliability_score": 0.8
                },
                {
                    "name": "Common Unreal Engine",
                    "description": "Common launch options for Unreal engine games",
                    "reliability_score": 0.8
                },
                {
                    "name": "Common Launch Option",
                    "description": "Generic launch options that work across many games",
                    "reliability_score": 0.6
                }
            ]
            
            for source in sources:
                supabase.table("sources").insert(source).execute()
            
            print(f"✅ Added {len(sources)} sources to the database.")
        else:
            print("✅ Sources table already populated.")
    except Exception as e:
        print(f"⚠️ Error seeding sources: {e}")

def test_database_connection(test_mode=False, supabase=None):
    """Test database connection and return status"""
    if test_mode:
        print("Running in test mode, database connection not required")
        return True
        
    if not supabase:
        print("Database connection not initialized")
        reconnect = input("Would you like to try reconnecting? (y/n): ").lower() == 'y'
        if reconnect:
            supabase = setup_supabase_connection()
            return supabase is not None
        return False
        
    try:
        # Simple query to test connection
        result = supabase.table("games").select("count", count="exact").limit(1).execute()
        print("✅ Database connection test successful")
        return True
    except Exception as e:
        print(f"⚠️ Database connection test failed: {e}")
        return False

def fetch_steam_launch_options_from_db(app_id, supabase):
    try:
        # Query the junction table, embed related launch_options
        result = supabase.table("game_launch_options") \
            .select("launch_options(*)") \
            .eq("game_app_id", app_id) \
            .execute()

        options = []
        if hasattr(result, 'data'):
            for item in result.data:
                lo = item.get('launch_options')
                if lo:
                    options.append({
                        'command': lo['command'],
                        'description': lo['description'],
                        'source': lo['source'],
                        'verified': lo.get('verified', False)
                    })

        print(f"✅ Found {len(options)} launch options for app_id {app_id}")
        return options

    except Exception as e:
        print(f"⚠️ Database query error: {e}")
        return []

def save_to_database(game, options, supabase):
    """Save game and launch options to Supabase"""
    try:
        # Prepare game data
        game_data = {
            "app_id": game['appid'],
            "title": game['name'],
            "developer": game.get('developer', ''),
            "publisher": game.get('publisher', ''), 
            "release_date": game.get('release_date', ''),
            "engine": game.get('engine', 'Unknown')
        }
        
        # Insert game info
        res = supabase.table("games").upsert(game_data).execute()
        
        # Check response
        if hasattr(res, 'error') and res.error:
            print(f"Error saving game {game['name']}: {res.error}")
            return

        print(f"✅ Saved game {game['name']} to database")

        # Process each launch option - first ensuring they exist in launch_options table
        success_count = 0
        error_count = 0
        
        for option in options:
            # Try up to 3 times for each option
            for attempt in range(3):
                try:
                    # 1. First upsert the launch option itself (if it doesn't exist)
                    option_data = {
                        "command": option['command'],
                        "description": option['description'],
                        "source": option['source'],
                        "verified": option.get('verified', False)
                        # upvotes/downvotes are defaulted to 0 in schema
                    }
                    
                    # Use on_conflict to handle the case where this option already exists
                    option_res = supabase.table("launch_options")\
                        .upsert(option_data, on_conflict="command")\
                        .execute()
                        
                    # Extract the launch option id (either new or existing)
                    if option_res.data and len(option_res.data) > 0:
                        option_id = option_res.data[0]['id']
                        
                        # 2. Now create the association between game and launch option
                        junction_data = {
                            "game_app_id": game['appid'],
                            "launch_option_id": option_id
                        }
                        
                        # Insert into junction table (will fail if already exists)
                        supabase.table("game_launch_options")\
                            .upsert(junction_data, on_conflict="game_app_id,launch_option_id")\
                            .execute()
                            
                        success_count += 1
                        # Break out of retry loop
                        break
                    else:
                        raise Exception("Failed to get launch option ID")
                        
                except Exception as inner_e:
                    # Only print error on last attempt
                    if attempt == 2:
                        print(f"Error saving option {option['command']} after 3 attempts: {inner_e}")
                        error_count += 1
                    # Small delay before retry
                    import time
                    time.sleep(0.5)
        
        # Calculate percentage success rate
        if options:
            success_rate = (success_count / len(options)) * 100
            print(f"✅ Saved {success_count}/{len(options)} options ({success_rate:.1f}%) to database")
            if error_count > 0:
                print(f"⚠️ Failed to save {error_count} options")
        else:
            print("ℹ️ No options to save for this game")
            
    except Exception as e:
        print(f"⚠️ Database error: {e}")
        print("Make sure your Supabase tables are set up correctly with the right columns")