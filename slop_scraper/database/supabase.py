import os
import re
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

def fetch_all_rows(supabase, table: str, columns: str, filters=None) -> List[Dict]:
    """
    Every matching row, paginated.

    PostgREST answers a select() with at most 1,000 rows and says nothing about
    the ones it left behind — no error, no flag, just a short list that looks
    complete. Any query expected to return more than a thousand rows has to
    page through explicitly, so every such read in this file goes through here
    rather than open-coding the loop and getting it right most of the time.

    `filters` is applied to each page's query builder, e.g.
        fetch_all_rows(sb, "games", "app_id", lambda q: q.gt("total_options_count", 0))
    """
    rows, start = [], 0
    while True:
        query = supabase.table(table).select(columns)
        if filters:
            query = filters(query)
        batch = query.range(start, start + 999).execute().data or []
        rows.extend(batch)
        if len(batch) < 1000:
            break
        start += 1000
    return rows


def get_existing_app_ids(supabase) -> Set[int]:
    """
    Get all app_ids that already exist in the database
    Returns a set of app_ids for fast lookup
    """
    try:
        return {row["app_id"] for row in fetch_all_rows(supabase, "games", "app_id")}
            
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
        # Paginated, and not optional: this select used to run unbounded and so
        # returned exactly 1,000 app_ids no matter how large the catalogue got.
        # Everything past the cap looked new, and the scraper spent its request
        # budget re-fetching games it already had — against other people's
        # wikis. A skip list that silently stops skipping is worse than none.
        rows = fetch_all_rows(supabase, "games", "app_id",
                              lambda q: q.gt("total_options_count", 0))

        if rows:
            covered = {row['app_id'] for row in rows}
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
    Games with few launch options — candidates for re-scraping.

    Reads games.total_options_count directly. That column is maintained by a
    database trigger and was verified exact against a full recount of
    game_launch_options: 2,452 games, zero disagreements.

    This previously called an RPC, get_games_with_option_count, that has never
    existed in this database. PostgREST answers a missing function with a
    PGRST202 error rather than an empty result, so the call RAISED and the
    `else:` fallback below it was unreachable — every invocation landed in the
    except and returned []. `--db-stats` has therefore been reporting
    "Games with <=2 options: 0" for its whole life, which reads as good news
    and is actually the diagnostic failing.

    The unreachable fallback is gone too, and would have been worth removing
    even if it had run: it issued one count query PER GAME — 2,452 round trips
    — and read `games` unpaginated, so it could only ever have seen the first
    1,000 rows.

    Hidden duplicate rows are excluded. They are the same game as their
    canonical row, so re-scraping one gains nothing; the canonical row is the
    candidate. Falls back to including them if migration 008 has not been
    applied.
    """
    columns = "app_id, title, total_options_count, duplicate_of"
    try:
        rows = _fetch_games_for_option_counts(supabase, columns)
    except Exception:
        # migration 008 not applied — duplicate_of does not exist yet
        try:
            rows = _fetch_games_for_option_counts(
                supabase, "app_id, title, total_options_count")
        except Exception as e:
            print(f"⚠️ Error getting games with few options: {e}")
            return []

    return [
        {'app_id': row['app_id'],
         'title': row.get('title'),
         'option_count': row.get('total_options_count') or 0}
        for row in rows
        if (row.get('total_options_count') or 0) <= max_options
        and not row.get('duplicate_of')
    ]


def _fetch_games_for_option_counts(supabase, columns: str) -> List[Dict]:
    """Every games row, paginated — a bare select() stops at 1,000."""
    return fetch_all_rows(supabase, "games", columns)

# Source labels emitted by game_specific.py's static per-engine blocks. A row
# carrying one of these was attached because of the game's ENGINE, not because
# any page documented it for that game.
_ENGINE_BLOCK_SOURCES = {
    'Source Engine', 'Unity Engine', 'Unreal Engine', 'id Tech',
    'Creation Engine', 'Frostbite Engine', 'Minecraft Java', 'Universal',
}


def _blanket_attached_options(supabase, min_games: int = 10) -> Dict:
    """
    Options attached to many games in bulk with nothing documenting them.

    This replaces a check that named three commands literally — '-fps_max',
    '-nojoy', '-nosplash' — from the era when those were emitted to every game
    regardless of engine. Two of them have since become curated flags sitting
    correctly on the games that take them, so the old check reported perfectly
    good data as "HIGH PRIORITY for cleanup". A diagnostic that cries wolf
    trains you to ignore it, which is worse than not having one.

    What actually goes wrong is the SHAPE, not the name: a flag emitted from a
    static per-engine block, attached to a large number of games, with no entry
    in the curated dictionary explaining it. `-malloc=system` (237 games, not
    even valid Unreal syntax) and `-sm4` (238 games, removed from Unreal in
    4.23) were both exactly this, and both would have shown up here.

    A curated entry clears the flag because the dictionary is where a claim
    gets checked against primary documentation — that is the difference between
    a flag attached by rule and a flag attached by evidence.
    """
    try:
        from ..validation import lookup_flag
    except ImportError:
        from validation import lookup_flag

    # Paginated on purpose: an unbounded select() silently caps at 1000 rows,
    # and there are far more junction rows than that.
    options = fetch_all_rows(supabase, "launch_options", "id, command, source, source_url")
    counts = {}
    for link in fetch_all_rows(supabase, "game_launch_options", "launch_option_id"):
        counts[link['launch_option_id']] = counts.get(link['launch_option_id'], 0) + 1

    flagged = {}
    for opt in options:
        games = counts.get(opt['id'], 0)
        if (games >= min_games
                and opt.get('source') in _ENGINE_BLOCK_SOURCES
                and not lookup_flag(opt['command'])):
            flagged[opt['command']] = {
                'exists': True,
                'source': opt.get('source'),
                'source_url': opt.get('source_url'),
                'games_count': games,
            }
    return flagged


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
        
        # Options by source. Paginated because the source breakdown is meant to
        # sum to unique_options above, which is a count="exact" and therefore
        # not subject to the 1,000-row cap this select would otherwise hit.
        source_counts = {}
        for row in fetch_all_rows(supabase, "launch_options", "source"):
            source = row.get("source", "Unknown")
            source_counts[source] = source_counts.get(source, 0) + 1
        
        problematic_stats = _blanket_attached_options(supabase)

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

# Commands where letter case carries meaning, so two spellings are two
# different flags rather than one flag written twice. JVM options are the
# whole of it: -Xmx4G sets a heap size, -xmx4g is not a flag at all.
# Deliberately does NOT match -D3D12, which is a DirectX renderer switch that
# merely looks like a Java -Dproperty=value.
_CASE_SENSITIVE_COMMAND = re.compile(r'^-(Xm[sx]|XX:|D[a-z]+\.)', re.ASCII)

_SCRAPED_VERIFICATION_METHODS = {
    'PCGamingWiki': 'pcgamingwiki-scrape',
    'ProtonDB': 'protondb-scrape',
    'Steam Community': 'steam-community-scrape',
    'Steam Community Guides': 'steam-community-scrape',
}


def _vetted_description(option: dict) -> Optional[str]:
    """
    The description to store for an option, or None to store nothing.

    Runs the shared quality gate (validation/description_quality.py) so that
    instruction steps, pasted flag lists, circular restatements and the
    scrapers' own placeholders never reach the database. Storing None here is
    deliberate: the site renders the source link when a description is
    missing, which is more honest than text that looks like an answer.

    This gate lives on the write path on purpose. When the same rules existed
    only in a cleanup script, the next re-scrape put every removed
    description straight back.
    """
    try:
        from ..validation import (clean_option_description, acceptable_description,
                                  curated_description)
    except ImportError:
        from validation import (clean_option_description, acceptable_description,
                                curated_description)

    command = option.get('command', '')

    # The curated dictionary is authoritative: a description verified against
    # primary documentation beats anything a scraper pulled out of a forum post,
    # so it overrides rather than merely filling a gap.
    curated = curated_description(command)
    if curated:
        return curated

    cleaned = clean_option_description(option.get('description', ''))
    return acceptable_description(command, cleaned)


def _verification_method_for_source(source: str) -> str:
    """
    How last_verified_at was established. Live-scraped sources get their own
    tag; everything else (game_specific.py's engine-block lists, 'Universal',
    documentation-derived sources) is re-emitted from a static list each run
    rather than freshly fetched, so 'curated' rather than implying a live
    re-check happened.

    The legacy 'manual_curation' source, which mapped to 'manual' here, was
    retired by migrations/004 — no scraper ever emitted it.
    """
    if source in _SCRAPED_VERIFICATION_METHODS:
        return _SCRAPED_VERIFICATION_METHODS[source]
    return 'curated'


def _touch_launch_option_verification(supabase, option_id: int, option: dict, existing: dict) -> None:
    """
    Stamp last_verified_at/verification_method on a re-encountered option,
    and backfill source_url / description if we now have one and the row
    doesn't. Never overwrites an existing non-empty value — the rule is
    "first GOOD value wins", not "first value ever seen wins".

    The description backfill matters because bad descriptions get nulled out
    rather than replaced (a wrong description is worse than none — see
    cleanup_bad_descriptions.py). Without this, a nulled row could never be
    repaired, since the insert path only runs for commands that don't exist
    yet. With it, the next scrape/rescan that finds clean text heals the row.

    Silently no-ops if migrations/002 hasn't been run yet (columns don't
    exist) — freshness tracking should never break scraping.
    """
    import datetime

    source = option.get('source', 'Unknown')
    update_fields = {
        "last_verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "verification_method": _verification_method_for_source(source),
    }

    if option.get('source_url') and not existing.get('source_url'):
        update_fields["source_url"] = option['source_url']

    if not (existing.get('description') or '').strip():
        fresh_description = _vetted_description(option)
        if fresh_description:
            update_fields["description"] = fresh_description

    try:
        supabase.table("launch_options").update(update_fields).eq("id", option_id).execute()
    except Exception:
        pass


def _get_or_create_launch_option(supabase, option: dict) -> Optional[int]:
    """
    Return the id for a launch option, inserting it only if it doesn't exist.

    We never overwrite an existing description — the first version wins.
    This prevents auto-generated fallback descriptions (e.g. "Launch option
    from PCGamingWiki") from silently replacing a previously curated one.

    The existence check is CASE-INSENSITIVE. `command` is UNIQUE, but Postgres
    compares it case-sensitively, so an exact-match lookup let '-nosplash',
    '-NoSplash' and '-noSplash' coexist as three rows for one flag — Unreal and
    Source both parse switches case-insensitively. The damage is not the extra
    row, it is that everything attached to the flag gets split across the
    variants: '-USEALLAVAILABLECORES' held 234 games with the correct Unreal
    description while '-useallavailablecores' held 1 with a wrong L4D one.

    JVM-style options are exempted, because case genuinely carries meaning
    there: -Xmx4G is a heap size and -xmx4g is not a flag at all. -D3D12 is
    deliberately not treated as one — it is DirectX, not a Java property.
    """
    command = option['command']

    # A scrape reporting a new casing binds to the row that already exists
    # rather than creating a rival; the stored spelling is left alone, since it
    # is the one the merge script chose on evidence.
    #
    # 'ilike' treats _ and % as wildcards, and _ is common in cvars
    # (+jobs_numThreads, +cl_forcepreload). Rather than exempt those — which
    # would leave exactly the collisions the merge script just cleaned up free
    # to come back — the query is allowed to over-match and the results are
    # filtered to a true case-insensitive equality in Python.
    case_insensitive = not _CASE_SENSITIVE_COMMAND.match(command.strip())
    target = command.strip().lower()

    def _find(select_columns):
        query = supabase.table("launch_options").select(select_columns)
        if not case_insensitive:
            return query.eq("command", command).limit(1).execute()
        result = query.ilike("command", command).limit(20).execute()
        result.data = [row for row in (result.data or [])
                       if str(row.get('command', '')).strip().lower() == target]
        return result

    # 1. Try to find an existing record first
    try:
        existing = _find("id, command, source_url, description")

        if existing.data:
            option_id = existing.data[0]['id']
            _touch_launch_option_verification(supabase, option_id, option, existing.data[0])
            return option_id
    except Exception:
        # source_url column may not exist yet (migration 002 not run) — retry
        # the lookup without it so re-encountering an option never breaks.
        try:
            existing = _find("id, command")
            if existing.data:
                return existing.data[0]['id']
        except Exception:
            pass

    # 2. Not found — insert the new option.
    # Descriptions are cleaned at this final boundary: wiki markup is cut,
    # dangling fragments dropped. None is preferred over a polluted string.
    # Risk/category/engine metadata is computed here too — a pure function of
    # the command and source, so every option gets tagged going forward with
    # no extra scraping (see migrations/001_add_launch_option_metadata.sql
    # and validation/metadata_tagging.py).
    try:
        from ..validation import (clean_option_description, classify_option_metadata,
                                  honest_source, promoted_source,
                                  authority_url, authority_source)
    except ImportError:
        from validation import (clean_option_description, classify_option_metadata,
                                honest_source, promoted_source,
                                authority_url, authority_source)

    import datetime

    # The citation and the label are decided together, never separately.
    #
    # Where the curated dictionary documents this flag, both come from it: that
    # entry was checked against a page someone read, which outranks whichever
    # page a scraper happened to reach first. Where it does not, the scraper's
    # own values are used — with a vendor label DEMOTED if the URL points
    # somewhere else, so no row can present a Steam guide under Valve's name.
    #
    # Splitting these is what produced the defect this guards against: an
    # earlier pass promoted source_url alone and left 30 rows citing a vendor
    # while still labelled "ProtonDB". Promotion only ever comes from curation,
    # never from inspecting a URL's host — see validation/source_attribution.py.
    curated_url = authority_url(command)
    if curated_url:
        source = promoted_source(option.get('source', 'Unknown'), authority_source(command))
        source_url = curated_url
    else:
        source_url = option.get('source_url')
        source = honest_source(option.get('source', 'Unknown'), source_url)
    metadata = classify_option_metadata(command, source=source)

    base_fields = {
        "command": command,
        "description": _vetted_description(option),
        "source": source,
        "verified": option.get('verified', False)
    }
    metadata_fields = {
        "risk_level": metadata['risk_level'],
        "categories": metadata['categories'],
        "engine_compatibility": metadata['engine_compatibility']
    }
    verification_fields = {
        "source_url": source_url,
        "last_verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "verification_method": _verification_method_for_source(source),
    }

    # Usage docs come only from the curated dictionary — these fields exist to
    # tell a user how to actually apply a flag, so a scraped guess would defeat
    # the purpose. Absent for anything not yet documented.
    try:
        from ..validation import lookup_flag, curated_usage_example
    except ImportError:
        from validation import lookup_flag, curated_usage_example
    curated_entry = lookup_flag(command) or {}
    if curated_entry:
        verification_fields.update({
            "effect": curated_entry.get('effect'),
            "usage_example": curated_usage_example(command),
        })

    # Tiered fallback: newest columns first, dropping back a tier whenever a
    # migration hasn't been run yet, rather than ever failing the insert.
    for fields in (
        {**base_fields, **metadata_fields, **verification_fields},
        {**base_fields, **metadata_fields},
        base_fields,
    ):
        try:
            insert_res = supabase.table("launch_options").insert(fields).execute()
            if insert_res.data:
                return insert_res.data[0]['id']
            break
        except Exception as e:
            error_text = str(e).lower()
            missing_column = any(
                col in error_text for col in
                ('risk_level', 'categories', 'engine_compatibility',
                 'source_url', 'last_verified_at', 'verification_method')
            )
            if not missing_column:
                # Race condition: another process inserted between our select
                # and insert. Try the select one more time.
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
                break
            # else: fall through to the next, narrower tier

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
        }

        # The engine is written only when it can account for itself.
        #
        # This column previously wrote game['engine'] unconditionally and
        # never wrote engine_source at all, so ordinary scraper runs added
        # games carrying an engine with no provenance — 18 of them, all after
        # the backfill that was supposed to have made the column 100% sourced.
        # The rule lived only in the backfill script; the live path did not
        # know about it.
        #
        # Four cases, and the distinctions matter:
        engine = game.get('engine') or 'Unknown'
        engine_source = game.get('engine_source')

        if engine_source:
            # Fresh detection that named its method. Store all three.
            game_data["engine"] = engine
            game_data["engine_detail"] = game.get('engine_detail')
            game_data["engine_source"] = engine_source
        elif engine == 'Unknown':
            # A decline needs no provenance — "we do not know" is always
            # honest, and recording it stops a later pass from re-guessing.
            game_data["engine"] = 'Unknown'
        elif 'engine_source' not in game:
            # A rescan echo: this dict was built from the stored row and
            # carries no provenance key at all. Write the engine straight back
            # and say nothing about engine_source, so the upsert leaves the
            # existing value intact instead of nulling 1,468 of them.
            game_data["engine"] = engine
        else:
            # Detection ran, produced a real-looking engine, and could not say
            # what established it — the keyword fallback in
            # extract_engine_safely. Omit the column entirely: a label nothing
            # backs is not written, and an existing good label is not
            # clobbered by this save either.
            pass

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
#
# NOTE: the first function below is NO LONGER NEEDED and is kept only so the
# history of this bug stays readable. get_games_with_few_options() in this
# module used to call an RPC named get_games_with_option_count — a DIFFERENT
# name from the function defined here, which is why neither has ever existed
# in the database. The Python side now reads games.total_options_count, a
# trigger-maintained column verified exact against a full recount, so no
# database function is required at all.
#
# Do not apply it expecting --db-stats to improve; it will not be called.
HELPFUL_SQL_FUNCTIONS = """
-- Function to get games with few options (for better performance)
-- SUPERSEDED: the Python path reads games.total_options_count instead.
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