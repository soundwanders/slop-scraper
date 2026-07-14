import os
import json
from supabase import create_client
from typing import Set, Optional, List, Dict

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
        supabase = create_client(url, key)

        if verify_db_structure(supabase):
            return supabase
        else:
            print("Database structure verification failed.")
            return None

    except Exception as e:
        print(f"Error connecting to Supabase: {e}")
        return None

def verify_db_structure(supabase):
    """Verify that the required tables exist in the database."""
    required = ["games", "launch_options", "game_launch_options"]
    try:
        supabase.table("games").select("app_id").limit(1).execute()
        supabase.table("launch_options").select("id").limit(1).execute()
        supabase.table("game_launch_options").select("game_app_id").limit(1).execute()
        print("✅ Database structure verification passed.")
        return True
    except Exception as e:
        print(f"⚠️ Database structure verification failed: {e}")
        print("Run schema.sql in the Supabase SQL Editor to create the required tables.")
        return False

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

# ========================================
# FUNCTIONS FOR GENERIC OPTIONS ISSUE
# ========================================

def get_existing_app_ids(supabase) -> Set[int]:
    """
    Get all app_ids that already exist in the database
    Returns a set of app_ids for fast lookup
    """
    try:
        response = supabase.table("games").select("app_id").execute()
        
        if response.data:
            # Extract unique app_ids
            app_ids = {row["app_id"] for row in response.data}
            return app_ids
        else:
            return set()
            
    except Exception as e:
        print(f"⚠️ Error fetching existing app_ids: {e}")
        return set()

def check_game_exists(supabase, app_id: int) -> bool:
    """
    Check if a specific game already exists in the database
    """
    try:
        response = supabase.table("games")\
            .select("app_id")\
            .eq("app_id", app_id)\
            .limit(1)\
            .execute()
        
        return len(response.data) > 0
        
    except Exception as e:
        print(f"⚠️ Error checking if game exists: {e}")
        return False

def check_game_needs_reprocessing(supabase, app_id: int) -> bool:
    """
    Check if a game needs reprocessing due to having only generic options
    """
    try:
        # Get current launch options for this game
        response = supabase.table("game_launch_options")\
            .select("launch_options(command, source)")\
            .eq("game_app_id", app_id)\
            .execute()
        
        if not response.data:
            # No options = definitely needs processing
            return True
        
        # Extract commands and sources
        commands = []
        sources = []
        for item in response.data:
            if item.get('launch_options'):
                commands.append(item['launch_options']['command'])
                sources.append(item['launch_options']['source'])
        
        # If very few options, check if they're all generic/problematic
        if len(commands) <= 3:
            # The old problematic commands that were added to every game
            problematic_commands = {'-fps_max', '-nojoy', '-nosplash'}
            
            # Generic/universal sources that indicate poor quality data
            generic_sources = {'Launch Option', 'Generic', 'Universal'}
            
            # Check if all commands are problematic or all sources are generic
            all_problematic = all(cmd in problematic_commands for cmd in commands)
            all_generic_sources = all(src in generic_sources for src in sources)
            
            # Needs reprocessing if it has the old problematic options or only generic sources
            if all_problematic or all_generic_sources:
                return True
        
        return False
        
    except Exception as e:
        print(f"⚠️ Error checking if game {app_id} needs reprocessing: {e}")
        return False

def get_games_needing_reprocessing(supabase, max_options: int = 3) -> List[Dict]:
    try:
        print("🔍 Analyzing games needing reprocessing (optimized)...")
        
        response = supabase.table("games")\
            .select("""
                app_id,
                title,
                game_launch_options(
                    launch_options(command, source)
                )
            """)\
            .limit(100)\
            .execute()  # Limit for performance
        
        candidates = []
        
        if response.data:
            for game in response.data:
                app_id = game['app_id']
                title = game['title']
                options_data = game.get('game_launch_options', [])
                
                option_count = len(options_data)
                
                if option_count <= max_options:
                    # Extract commands and sources
                    commands = []
                    sources = []
                    
                    for opt_rel in options_data:
                        if opt_rel.get('launch_options'):
                            commands.append(opt_rel['launch_options']['command'])
                            sources.append(opt_rel['launch_options']['source'])
                    
                    # Check for problematic patterns
                    problematic_commands = {'-fps_max', '-nojoy', '-nosplash'}
                    generic_sources = {'Launch Option', 'Generic'}
                    
                    has_problematic = any(cmd in problematic_commands for cmd in commands)
                    only_generic_sources = all(src in generic_sources for src in sources) if sources else True
                    
                    priority = 'HIGH' if has_problematic else 'MEDIUM' if only_generic_sources else 'LOW'
                    
                    candidates.append({
                        'app_id': app_id,
                        'title': title,
                        'option_count': option_count,
                        'commands': commands,
                        'sources': sources,
                        'has_problematic': has_problematic,
                        'only_generic': only_generic_sources,
                        'priority': priority
                    })
        
        print(f"✅ Found {len(candidates)} games that might need reprocessing")
        return candidates
        
    except Exception as e:
        print(f"⚠️ Error getting games needing reprocessing (using empty list): {e}")
        return []

def get_smart_existing_games(supabase, skip_existing: bool = True, force_reprocess_generic: bool = True) -> Set[int]:
    """
    Return the set of app_ids that should be skipped during scraping.

    Strategy: skip only games that already have at least one launch option
    (total_options_count > 0). Games that exist in `games` but have zero
    options should be processed so we can fill them in.
    """
    if not skip_existing:
        return set()

    try:
        response = (
            supabase.table("games")
            .select("app_id")
            .gt("total_options_count", 0)
            .execute()
        )

        if response.data:
            covered = {row['app_id'] for row in response.data}
            print(f"📊 Skipping {len(covered)} games that already have launch options")
            return covered

        return set()

    except Exception as e:
        print(f"⚠️ Error in smart existing games logic: {e}")
        return set()

def get_game_option_count(supabase, app_id: int) -> int:
    """
    Get the number of launch options for a specific game
    """
    try:
        response = supabase.table("game_launch_options")\
            .select("*", count="exact")\
            .eq("game_app_id", app_id)\
            .execute()
        
        return response.count or 0
        
    except Exception as e:
        print(f"⚠️ Error getting option count for game {app_id}: {e}")
        return 0

def get_games_with_few_options(supabase, max_options: int = 3) -> List[Dict]:
    """
    Get games that have few launch options (candidates for re-scraping)
    """
    try:
        # This is a more complex query - we need to count options per game
        response = supabase.rpc('get_games_with_option_count').execute()
        
        if response.data:
            return [game for game in response.data if game.get('option_count', 0) <= max_options]
        else:
            # Fallback method if RPC doesn't exist
            print("ℹ️ Using fallback method for games with few options")
            all_games = supabase.table("games").select("app_id, title").execute()
            candidates = []
            
            for game in all_games.data:
                option_count = get_game_option_count(supabase, game['app_id'])
                if option_count <= max_options:
                    candidates.append({
                        'app_id': game['app_id'],
                        'title': game['title'],
                        'option_count': option_count
                    })
            
            return candidates
            
    except Exception as e:
        print(f"⚠️ Error getting games with few options: {e}")
        return []

def get_database_stats(supabase) -> Dict:
    """
    Get comprehensive statistics about the database contents
    """
    try:
        # Total games
        games_response = supabase.table("games")\
            .select("app_id", count="exact")\
            .execute()
        
        total_games = games_response.count or 0
        
        # Total launch options relationships
        options_response = supabase.table("game_launch_options")\
            .select("*", count="exact")\
            .execute()
        
        total_option_relationships = options_response.count or 0
        
        # Unique launch options
        unique_options_response = supabase.table("launch_options")\
            .select("id", count="exact")\
            .execute()
        
        unique_options = unique_options_response.count or 0
        
        # Options by source (get source distribution)
        sources_response = supabase.table("launch_options")\
            .select("source")\
            .execute()
        
        source_counts = {}
        if sources_response.data:
            for row in sources_response.data:
                source = row.get("source", "Unknown")
                source_counts[source] = source_counts.get(source, 0) + 1
        
        # Analyze problematic options for generic options issue
        problematic_commands = ['-fps_max', '-nojoy', '-nosplash']
        problematic_stats = {}
        
        for cmd in problematic_commands:
            cmd_response = supabase.table("launch_options")\
                .select("id, source", count="exact")\
                .eq("command", cmd)\
                .execute()
            
            if cmd_response.data:
                # Count how many games use this option
                option_id = cmd_response.data[0]['id']
                usage_response = supabase.table("game_launch_options")\
                    .select("game_app_id", count="exact")\
                    .eq("launch_option_id", option_id)\
                    .execute()
                
                problematic_stats[cmd] = {
                    'exists': True,
                    'source': cmd_response.data[0]['source'],
                    'games_count': usage_response.count or 0
                }
            else:
                problematic_stats[cmd] = {'exists': False, 'games_count': 0}
        
        return {
            "total_games": total_games,
            "total_option_relationships": total_option_relationships,
            "unique_launch_options": unique_options,
            "avg_options_per_game": round(total_option_relationships / total_games, 2) if total_games > 0 else 0,
            "options_by_source": source_counts,
            "problematic_options": problematic_stats
        }
        
    except Exception as e:
        print(f"⚠️ Error getting database stats: {e}")
        return {}

# ========================================
# SUPABASE CLIENT WRAPPER
# ========================================

class SupabaseClient:
    """Wrapper class for easier database operations"""
    
    def __init__(self, force_reprocess_generic: bool = True):
        """Initialize the Supabase client"""
        self.supabase = setup_supabase_connection()
        if not self.supabase:
            raise ValueError("Failed to establish Supabase connection")
        
        self.force_reprocess_generic = force_reprocess_generic
    
    def get_existing_app_ids(self) -> Set[int]:
        """Get all existing app_ids (standard method)"""
        return get_existing_app_ids(self.supabase)
    
    def get_smart_existing_app_ids(self, skip_existing: bool = True) -> Set[int]:
        """Get existing app_ids with smart reprocessing logic"""
        return get_smart_existing_games(
            self.supabase, 
            skip_existing=skip_existing,
            force_reprocess_generic=self.force_reprocess_generic
        )
    
    def check_game_exists(self, app_id: int) -> bool:
        """Check if game exists"""
        return check_game_exists(self.supabase, app_id)
    
    def check_game_needs_reprocessing(self, app_id: int) -> bool:
        """Check if game needs reprocessing due to generic options"""
        return check_game_needs_reprocessing(self.supabase, app_id)
    
    def get_game_option_count(self, app_id: int) -> int:
        """Get option count for game"""
        return get_game_option_count(self.supabase, app_id)
    
    def get_database_stats(self) -> Dict:
        """Get database statistics including problematic options analysis"""
        return get_database_stats(self.supabase)
    
    def get_reprocessing_candidates(self, max_options: int = 3) -> List[Dict]:
        """Get games that need reprocessing due to generic options issue"""
        return get_games_needing_reprocessing(self.supabase, max_options)
    
    def analyze_generic_options_issue(self) -> Dict:
        """Analyze the extent of the generic options issue"""
        try:
            stats = self.get_database_stats()
            candidates = self.get_reprocessing_candidates()
            
            total_games = stats.get('total_games', 0)
            problematic_stats = stats.get('problematic_options', {})
            
            # Count games with problematic options
            games_with_problematic = sum(
                opt_info.get('games_count', 0) 
                for opt_info in problematic_stats.values() 
                if opt_info.get('exists', False)
            )
            
            # Count high-priority reprocessing candidates
            high_priority_candidates = len([
                c for c in candidates 
                if c.get('priority') == 'HIGH' or c.get('has_problematic', False)
            ])
            
            # Calculate severity
            if total_games > 0:
                problematic_rate = (games_with_problematic / total_games) * 100
                if problematic_rate > 50:
                    severity = "CRITICAL"
                elif problematic_rate > 25:
                    severity = "HIGH"
                elif problematic_rate > 10:
                    severity = "MEDIUM"
                else:
                    severity = "LOW"
            else:
                severity = "UNKNOWN"
            
            return {
                'total_games': total_games,
                'games_with_problematic_options': games_with_problematic,
                'high_priority_reprocess_candidates': high_priority_candidates,
                'problematic_options_details': problematic_stats,
                'severity': severity,
                'recommendations': self._generate_recommendations(severity, problematic_stats, high_priority_candidates)
            }
            
        except Exception as e:
            print(f"⚠️ Error analyzing generic options issue: {e}")
            return {}
    
    def _generate_recommendations(self, severity: str, problematic_stats: Dict, candidates_count: int) -> List[str]:
        """Generate recommendations based on analysis"""
        recommendations = []
        
        if severity == "CRITICAL":
            recommendations.append("🚨 IMMEDIATE ACTION REQUIRED: Replace game_specific.py and reprocess all games")
            recommendations.append("🚨 Run: slop-scraper --force-refresh --no-skip-existing --limit 100")
        elif severity == "HIGH":
            recommendations.append("⚠️ URGENT: Many games affected by generic options bug")
            recommendations.append("⚠️ Run selective reprocessing with scraper")
        elif severity == "MEDIUM":
            recommendations.append("ℹ️ Some games affected - selective reprocessing recommended")
        elif severity == "LOW":
            recommendations.append("✅ Low impact - monitor and fix as needed")
        
        # Specific problematic option recommendations
        for cmd, info in problematic_stats.items():
            if info.get('exists') and info.get('games_count', 0) > 10:
                recommendations.append(f"🎯 '{cmd}' found in {info['games_count']} games - high priority for cleanup")
        
        if candidates_count > 0:
            recommendations.append(f"🔄 {candidates_count} games identified for reprocessing")
        
        return recommendations

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

_LOW_QUALITY_SOURCES = {'Universal', 'Generic', 'Launch Option'}

def _is_meaningful_option(option: dict) -> bool:
    """Return True if an option is substantive enough to store."""
    return option.get('source', '') not in _LOW_QUALITY_SOURCES

def _passes_save_gate(option: dict) -> bool:
    """
    Final validation gate — every option from every source must pass before
    the database is touched. Rejects the junk classes found in the 2026-07
    production cleanup (WINEPREFIX paths, placeholder fragments, prose words
    scraped as flags, trailing punctuation).
    """
    try:
        from ..validation import is_valid_launch_option
    except ImportError:
        from validation import is_valid_launch_option

    is_valid, reason = is_valid_launch_option(option.get('command', ''))
    if not is_valid:
        print(f"🚫 Save gate rejected '{option.get('command', '')}': {reason}")
    return is_valid

def _get_or_create_launch_option(supabase, option: dict) -> Optional[int]:
    """
    Return the id for a launch option, inserting it only if it doesn't exist.

    We never overwrite an existing description — the first version wins.
    This prevents auto-generated fallback descriptions (e.g. "Launch option
    from PCGamingWiki") from silently replacing a previously curated one.
    """
    command = option['command']

    # 1. Try to find an existing record first
    try:
        existing = supabase.table("launch_options") \
            .select("id") \
            .eq("command", command) \
            .limit(1) \
            .execute()

        if existing.data:
            return existing.data[0]['id']
    except Exception:
        pass

    # 2. Not found — insert the new option.
    # Descriptions are cleaned at this final boundary: wiki markup is cut,
    # dangling fragments dropped. None is preferred over a polluted string.
    try:
        from ..validation import clean_option_description
    except ImportError:
        from validation import clean_option_description

    try:
        insert_res = supabase.table("launch_options").insert({
            "command": command,
            "description": clean_option_description(option.get('description', '')),
            "source": option.get('source', 'Unknown'),
            "verified": option.get('verified', False)
        }).execute()

        if insert_res.data:
            return insert_res.data[0]['id']
    except Exception:
        # Race condition: another process inserted between our select and insert.
        # Try the select one more time.
        try:
            retry = supabase.table("launch_options") \
                .select("id") \
                .eq("command", command) \
                .limit(1) \
                .execute()
            if retry.data:
                return retry.data[0]['id']
        except Exception:
            pass

    return None


def save_to_database(game, options, supabase):
    """
    Save game and launch options to Supabase.

    Design rules:
    - Quality gate: only save if at least one non-generic option is present.
    - Games: upsert on app_id (safe to refresh metadata from Steam API).
    - Launch options: select-then-insert — never overwrite an existing description.
    - Junction: upsert on (game_app_id, launch_option_id) — idempotent.
    """
    import time

    # Quality gate — skip games with no meaningful options.
    # The save gate is the last line of defense against scraped junk.
    meaningful = [o for o in options if _is_meaningful_option(o) and _passes_save_gate(o)]
    if not meaningful:
        print(f"ℹ️ Skipping {game['name']} — no meaningful options to save")
        return

    try:
        # Final guard on date format: every save path (new games, rescan
        # echoes of existing rows) funnels through here, so normalizing at
        # this choke point keeps raw Steam date strings out of the DB.
        try:
            from ..utils.dates import normalize_release_date
        except ImportError:
            from utils.dates import normalize_release_date

        # Upsert game metadata (safe: Steam API data is authoritative for name/developer/etc.)
        game_data = {
            "app_id": game['appid'],
            "title": game['name'],
            "developer": game.get('developer', ''),
            "publisher": game.get('publisher', ''),
            "release_date": normalize_release_date(game.get('release_date', '')),
            "engine": game.get('engine', 'Unknown')
        }

        res = supabase.table("games").upsert(
            game_data,
            on_conflict="app_id"
        ).execute()

        if hasattr(res, 'error') and res.error:
            print(f"⚠️ Error saving game {game['name']}: {res.error}")
            return

        print(f"✅ Saved game {game['name']} to database")

        success_count = 0
        error_count = 0

        for option in meaningful:
            try:
                option_id = _get_or_create_launch_option(supabase, option)

                if option_id is None:
                    print(f"⚠️ Could not get/create option '{option['command']}'")
                    error_count += 1
                    continue

                supabase.table("game_launch_options").upsert(
                    {"game_app_id": game['appid'], "launch_option_id": option_id},
                    on_conflict="game_app_id,launch_option_id"
                ).execute()

                success_count += 1

            except Exception as inner_e:
                print(f"⚠️ Error saving option '{option['command']}': {inner_e}")
                error_count += 1
                time.sleep(0.3)

        total = len(meaningful)
        rate = (success_count / total * 100) if total else 0
        print(f"✅ Saved {success_count}/{total} options ({rate:.1f}%) for {game['name']}")
        if error_count:
            print(f"⚠️ Failed to save {error_count} option(s)")

    except Exception as e:
        print(f"⚠️ Database error saving {game.get('name', 'unknown')}: {e}")
        print("Make sure your Supabase tables are set up correctly.")

# ========================================
# SQL HELPER FUNCTIONS
# ========================================

# Run this SQL in your Supabase SQL editor for better performance:
HELPFUL_SQL_FUNCTIONS = """
-- Function to get games with few options (for better performance)
CREATE OR REPLACE FUNCTION get_games_with_few_options(max_option_count INTEGER DEFAULT 3)
RETURNS TABLE(app_id INTEGER, title TEXT, option_count BIGINT, has_problematic BOOLEAN) AS $$
BEGIN
    RETURN QUERY
    WITH game_option_counts AS (
        SELECT 
            g.app_id,
            g.title,
            COUNT(glo.launch_option_id) as option_count
        FROM games g
        LEFT JOIN game_launch_options glo ON g.app_id = glo.game_app_id
        GROUP BY g.app_id, g.title
    ),
    game_problematic_check AS (
        SELECT 
            goc.*,
            CASE 
                WHEN goc.option_count = 0 THEN FALSE
                WHEN goc.option_count <= max_option_count THEN (
                    SELECT COUNT(*) > 0
                    FROM game_launch_options glo
                    JOIN launch_options lo ON glo.launch_option_id = lo.id
                    WHERE glo.game_app_id = goc.app_id
                    AND lo.command IN ('-fps_max', '-nojoy', '-nosplash')
                )
                ELSE FALSE
            END as has_problematic
        FROM game_option_counts goc
    )
    SELECT 
        gpc.app_id,
        gpc.title,
        gpc.option_count,
        gpc.has_problematic
    FROM game_problematic_check gpc
    WHERE gpc.option_count <= max_option_count;
END;
$$ LANGUAGE plpgsql;

-- Function to analyze database quality
CREATE OR REPLACE FUNCTION analyze_database_quality()
RETURNS JSON AS $$
DECLARE
    result JSON;
    total_games INTEGER;
    problematic_count INTEGER;
BEGIN
    -- Get total games
    SELECT COUNT(*) INTO total_games FROM games;
    
    -- Get games with problematic options
    SELECT COUNT(DISTINCT glo.game_app_id) INTO problematic_count
    FROM game_launch_options glo
    JOIN launch_options lo ON glo.launch_option_id = lo.id
    WHERE lo.command IN ('-fps_max', '-nojoy', '-nosplash');
    
    -- Build result
    result := json_build_object(
        'total_games', total_games,
        'games_with_problematic_options', problematic_count,
        'problematic_rate_percent', 
        CASE WHEN total_games > 0 THEN ROUND((problematic_count::DECIMAL / total_games) * 100, 2) ELSE 0 END
    );
    
    RETURN result;
END;
$$ LANGUAGE plpgsql;
"""

def setup_database_performance_functions():
    """Print SQL functions that should be added to Supabase for better performance"""
    print("🔧 OPTIONAL PERFORMANCE IMPROVEMENT")
    print("=" * 50)
    print("Add these SQL functions to your Supabase database for better performance:")
    print("(Go to your Supabase dashboard → SQL Editor → New Query)")
    print()
    print(HELPFUL_SQL_FUNCTIONS)
    print("=" * 50)