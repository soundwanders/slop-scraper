#!/usr/bin/env python3
import os
import sys
import argparse
from dotenv import load_dotenv

# Add the project root to Python path to enable absolute imports
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    # Try relative imports first (when run as module)
    from .core.scraper import SlopScraper
    from .utils.security_config import SecurityConfig, validate_usage_pattern
    from .database.supabase import SupabaseClient, get_database_stats  # Import for stats
except ImportError:
    # Fall back to absolute imports (when run directly)
    from core.scraper import SlopScraper
    from utils.security_config import SecurityConfig, validate_usage_pattern
    from database.supabase import SupabaseClient, get_database_stats
 
def get_script_dir():
    """Get directory where this script (slop_scraper) is located"""
    script_path = os.path.dirname(os.path.abspath(__file__))
    return script_path

def setup_argument_parser():
    """Set up and return the argument parser for CLI arguments"""
    parser = argparse.ArgumentParser(description='Steam Launch Options Scraper')
    parser.add_argument('--test', action='store_true', help='Run in test mode')
    parser.add_argument('--limit', type=int, default=50,
                       help=f'Maximum number of games to process (default: 50, max: {SecurityConfig.MAX_GAMES_LIMIT})')
    parser.add_argument('--rate', type=float, default=2.0, 
                       help=f'Rate limit in seconds between requests (min: {SecurityConfig.MIN_RATE_LIMIT})')
    parser.add_argument('--output', type=str, default='./test-output', 
                       help='Output directory for test results (restricted paths)')
    parser.add_argument('--absolute-path', action='store_true', 
                       help='Use absolute path for output directory (use with caution)')
    parser.add_argument('--force-refresh', action='store_true', 
                       help='Force refresh of game data cache')
    parser.add_argument('--test-db', action='store_true', 
                       help='Test database connection and exit')
    
    # Database filtering options
    parser.add_argument('--skip-existing', action='store_true', default=True,
                       help='Skip games already in database (default: enabled)')
    parser.add_argument('--no-skip-existing', dest='skip_existing', action='store_false',
                       help='Process all games, including those already in database')
    parser.add_argument('--db-stats', action='store_true',
                       help='Show database statistics and exit')
    parser.add_argument('--check-duplicates', action='store_true',
                       help='Report catalogue games that PCGamingWiki lists as one game '
                            'under several Steam App IDs (read-only; never writes)')
    parser.add_argument('--rescan', action='store_true',
                       help='Re-scan games already in the database (thinnest option counts first); '
                            'new options are added, existing data is never overwritten')
    parser.add_argument('--rescan-engines', action='store_true',
                       help='Narrow --rescan to games whose engine has documented launch options '
                            '(Source, Unity, Unreal, id Tech, Creation, Frostbite). Use after an '
                            'engine-metadata change, when a full rescan would spend most of its '
                            'runtime on games no engine block applies to')
    parser.add_argument('--rescan-reset', action='store_true',
                       help='Clear rescan progress tracking and start the rescan campaign over')
    parser.add_argument('--pcgw-recheck', action='store_true',
                       help='Re-scan only games whose PCGamingWiki result was inconclusive due to '
                            'a site outage (tracked in pcgw_recheck_needed.json); use once PCGamingWiki '
                            'is back up to recover data missed during the outage')
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug output including database stats')
    
    # Add scraper-specific debug options
    parser.add_argument('--debug-scrapers', action='store_true',
                       help='Enable detailed debug output for all scrapers')
    parser.add_argument('--test-single-game', type=str, 
                       help='Test scrapers on a single game by name (debug mode)')
    
    return parser


def show_duplicate_games():
    """
    Report catalogue rows that are the same game under different App IDs.

    READ-ONLY. It never merges or deletes, and that restraint is the design,
    not an unfinished half. Merging two games means choosing which App ID
    survives, moving the loser's option links onto it, and deleting a row the
    website may already link to — irreversible from a report.

    The grouping comes from PCGamingWiki, which lists every App ID a page
    covers. Steam cannot answer this: asked about apps 80 and 100 it returns
    type='game' for both, no `fullgame` parent, and the same name. Matching on
    title instead would merge on a coincidence of naming — app 52003 is titled
    "Portal" and PCGamingWiki does not place it with app 400, so a title rule
    would destroy a row nothing has identified.
    """
    try:
        from database.supabase import setup_supabase_connection
        from utils.pcgw_appid_groups import fetch_appid_groups
    except ImportError:
        from .database.supabase import setup_supabase_connection
        from .utils.pcgw_appid_groups import fetch_appid_groups

    from collections import defaultdict

    supabase = setup_supabase_connection()
    if not supabase:
        print("❌ Failed to connect to database")
        return False

    games, start = [], 0
    while True:
        batch = (supabase.table('games')
                 .select('app_id, title, total_options_count')
                 .range(start, start + 999).execute().data) or []
        games.extend(batch)
        if len(batch) < 1000:
            break
        start += 1000

    links, start = [], 0
    while True:
        batch = (supabase.table('game_launch_options')
                 .select('game_app_id, launch_option_id')
                 .range(start, start + 999).execute().data) or []
        links.extend(batch)
        if len(batch) < 1000:
            break
        start += 1000

    options_for = defaultdict(set)
    for link in links:
        options_for[link['game_app_id']].add(link['launch_option_id'])

    try:
        groups = fetch_appid_groups()
    except Exception as e:
        print(f"❌ Could not fetch PCGamingWiki App ID groups: {e}")
        return False

    in_catalogue = {g['app_id']: g for g in games}

    clusters = {}
    for app_id in in_catalogue:
        entry = groups.get(app_id)
        if not entry:
            continue
        page, ids = entry
        present = tuple(sorted(i for i in ids if i in in_catalogue))
        if len(present) > 1:
            clusters[present] = page

    # A PCGamingWiki page covers a game AND its add-ons, so a shared page means
    # "documented together", which is broader than "the same product". Doom
    # Eternal shares a page with The Ancient Gods; Penumbra: Black Plague with
    # Penumbra: Requiem, which is a different game outright.
    #
    # Matching titles inside a cluster is what separates the two. It is not
    # proof — it is the difference between a row worth examining and a row that
    # is plainly an expansion — so both lists are printed and neither is acted
    # on automatically.
    def normalise(title):
        text = ''.join(c for c in str(title) if c not in '™®©').lower()
        return ' '.join(text.split())

    same_title, add_ons = {}, {}
    for present, page in clusters.items():
        titles = {normalise(in_catalogue[i]['title']) for i in present}
        (same_title if len(titles) == 1 else add_ons)[present] = page

    print(f"\n{'=' * 66}")
    print("📊 CATALOGUE ROWS SHARING A PCGAMINGWIKI PAGE")
    print(f"{'=' * 66}")
    print(f"   {len(in_catalogue)} games in catalogue")
    print(f"   {len(clusters)} clusters — {len(same_title)} identical-title, "
          f"{len(add_ons)} with differing titles\n")

    if not clusters:
        print("✅ Nothing PCGamingWiki groups together.")
        return True

    def render(bucket, heading, note):
        if not bucket:
            return
        print(f"   {heading}")
        print(f"   {note}\n")
        for present, page in sorted(bucket.items(), key=lambda kv: -len(kv[0])):
            shared = set.intersection(*(options_for[i] for i in present))
            union = set().union(*(options_for[i] for i in present))
            print(f"      {page}")
            for app_id in present:
                unique = len(options_for[app_id] - shared)
                print(f"         {app_id:>8}  {str(in_catalogue[app_id]['title'])[:36]:38} "
                      f"{len(options_for[app_id]):>3} opts"
                      f"{f'  ({unique} not shared)' if unique else ''}")
            print(f"         → {len(union)} distinct, {len(shared)} common to all\n")

    render(same_title,
           "── LIKELY DUPLICATES — same title, same wiki page " + "─" * 14,
           "Worth examining. Still not proof: a multiplayer component often\n"
           "   carries the base game's exact name.")
    render(add_ons,
           "── LIKELY ADD-ONS — titles differ " + "─" * 30,
           "Probably DLC, expansions or standalone sequels documented on one\n"
           "   page. Merging these would destroy distinct games.")

    print("   Read-only, and merging is deliberately not automated: it means")
    print("   choosing a surviving App ID and deleting a row the site may link")
    print("   to. Options that differ inside a cluster are the signal worth")
    print("   reading — they can mean genuinely different builds.")
    return True


def show_database_statistics():
    """Show comprehensive database statistics and exit"""
    try:
        db_client = SupabaseClient()
        stats = db_client.get_database_stats()
        
        print("📊 Database Statistics:")
        print(f"   Total games: {stats.get('total_games', 0)}")
        print(f"   Total option relationships: {stats.get('total_option_relationships', 0)}")
        print(f"   Unique launch options: {stats.get('unique_launch_options', 0)}")
        print(f"   Average options per game: {stats.get('avg_options_per_game', 0)}")
        print("   Options by source:")
        for source, count in stats.get('options_by_source', {}).items():
            print(f"     {source}: {count}")
        
        # Options attached in bulk by engine, with nothing documenting them.
        # Not necessarily wrong — but this is the shape -malloc=system and
        # -sm4 had, so each one is worth a look rather than a cleanup.
        problematic_stats = stats.get('problematic_options', {})
        if problematic_stats:
            print("\n🔎 Attached by engine rule, not yet documented:")
            for cmd, info in sorted(problematic_stats.items(),
                                    key=lambda kv: -kv[1].get('games_count', 0)):
                games_count = info.get('games_count', 0)
                source = info.get('source', 'Unknown')
                cited = 'cited' if info.get('source_url') else 'NO source_url'
                print(f"   {cmd}: {games_count} games (source: {source}, {cited})")
            print("   Each is either worth a curated entry or worth withdrawing —")
            print("   check whether the flag is real AND applies to every game listed.")
        
        # Additional helpful statistics
        from database.supabase import get_games_with_few_options
        sparse_games = get_games_with_few_options(db_client.supabase, max_options=2)
        print(f"\n🔍 Analysis:")
        print(f"   Games with ≤2 options: {len(sparse_games)} (candidates for re-scraping)")
        
        if len(sparse_games) > 0 and len(sparse_games) <= 10:
            print("   Games with few options:")
            for game in sparse_games[:10]:
                print(f"     {game.get('title', 'Unknown')} (App ID: {game.get('app_id', 'N/A')}) - {game.get('option_count', 0)} options")
        elif len(sparse_games) > 10:
            print(f"   First 5 games with few options:")
            for game in sparse_games[:5]:
                print(f"     {game.get('title', 'Unknown')} (App ID: {game.get('app_id', 'N/A')}) - {game.get('option_count', 0)} options")
            print(f"     ... and {len(sparse_games) - 5} more")
                
        return True
    except Exception as e:
        print(f"⚠️ Error getting database statistics: {e}")
        print("Make sure you have valid Supabase credentials and database access.")
        return False

def test_single_game_scrapers(game_input, debug=True):
    """Test all scrapers on a single game for debugging purposes"""
    
    # Parse input - could be app_id or game name
    app_id = None
    game_name = None
    
    # Try to parse as app_id first
    try:
        app_id = int(game_input)
        
        # Look up game name from Steam API
        try:
            import requests
            response = requests.get(f"https://store.steampowered.com/api/appdetails?appids={app_id}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                if str(app_id) in data and data[str(app_id)].get('success'):
                    game_name = data[str(app_id)]['data'].get('name', f'App ID {app_id}')
                else:
                    game_name = f'App ID {app_id} (not found)'
            else:
                game_name = f'App ID {app_id} (API error)'
        except Exception as e:
            game_name = f'App ID {app_id} (lookup failed: {e})'
            
    except ValueError:
        # Input is a game name, not app_id
        game_name = game_input
        # Use a reasonable default app_id for testing when only name is provided
        app_id = 730  # Counter-Strike 2 as default
        print(f"ℹ️ Using game name '{game_name}' with default test app_id {app_id}")
    
    print(f"\n🧪 Testing all scrapers on '{game_name}' (App ID: {app_id})...")
    
    try:
        # Import scrapers
        from scrapers.pcgamingwiki import fetch_pcgamingwiki_launch_options
        from scrapers.steamcommunity import fetch_steam_community_launch_options
        from scrapers.protondb import fetch_protondb_launch_options
        from scrapers.game_specific import fetch_game_specific_options
        
        print(f"\n1. Testing PCGamingWiki scraper...")
        print(f"   → Searching for: '{game_name}'")
        pcg_options = fetch_pcgamingwiki_launch_options(
            game_name,  # PCGamingWiki uses game name
            app_id=app_id,  # Steam AppID enables exact Cargo lookup
            rate_limit=1.0,
            debug=debug,
            test_mode=True
        )
        print(f"   Result: {len(pcg_options)} options found")
        for i, opt in enumerate(pcg_options[:3]):
            print(f"     {i+1}. {opt['command']}: {opt['description'][:50]}...")
        
        print(f"\n2. Testing Steam Community scraper...")
        print(f"   → Using app_id: {app_id}")
        sc_options = fetch_steam_community_launch_options(
            app_id,  # Steam Community uses app_id
            game_title=game_name,
            rate_limit=1.0,
            debug=debug,
            test_mode=True
        )
        print(f"   Result: {len(sc_options)} options found")
        for i, opt in enumerate(sc_options[:3]):
            print(f"     {i+1}. {opt['command']}: {opt['description'][:50]}...")
        
        print(f"\n3. Testing ProtonDB scraper...")
        print(f"   → Using app_id: {app_id}")
        pdb_options = fetch_protondb_launch_options(
            app_id,  # ProtonDB uses app_id
            game_title=game_name,
            rate_limit=1.0,
            debug=debug,
            test_mode=True
        )
        print(f"   Result: {len(pdb_options)} options found")
        for i, opt in enumerate(pdb_options[:3]):
            print(f"     {i+1}. {opt['command']}: {opt['description'][:50]}...")
        
        print(f"\n4. Testing Game-Specific scraper...")
        print(f"   → Using app_id: {app_id}, game_name: '{game_name}'")
        cache = {}  # Empty cache for testing
        gs_options = fetch_game_specific_options(
            app_id,
            game_name,
            cache,
            test_mode=True
        )
        print(f"   Result: {len(gs_options)} options found")
        for i, opt in enumerate(gs_options[:3]):
            print(f"     {i+1}. {opt['command']}: {opt['description'][:50]}...")
        
        # Summary
        total_options = len(pcg_options) + len(sc_options) + len(pdb_options) + len(gs_options)
        print(f"\n📊 Summary for '{game_name}' (App ID: {app_id}):")
        print(f"   PCGamingWiki: {len(pcg_options)} options")
        print(f"   Steam Community: {len(sc_options)} options") 
        print(f"   ProtonDB: {len(pdb_options)} options")
        print(f"   Game-Specific: {len(gs_options)} options")
        print(f"   Total: {total_options} options")
        
        if total_options == 0:
            print("\n⚠️ NO OPTIONS FOUND! This indicates the scrapers need debugging.")
            print("   Possible issues:")
            print("   - Sites are blocking requests")
            print("   - HTML structure has changed") 
            print("   - Network connectivity issues")
            print("   - App ID mapping issues")
            print("   - Security validation is too strict")
        else:
            print(f"\n✅ Found {total_options} total options - scrapers appear to be working!")
            
        # Specific debugging info
        print(f"\n🔧 Debug Info:")
        print(f"   App ID used: {app_id}")
        print(f"   Game name used: '{game_name}'")
        print(f"   PCGamingWiki searched for: '{game_name}'")
        print(f"   Steam Community checked: /app/{app_id}/guides/")
        print(f"   ProtonDB checked app_id: {app_id}")
            
    except Exception as e:
        print(f"❌ Error testing scrapers: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Main entry point for the application"""
    # Check for abuse patterns first
    if not validate_usage_pattern():
        print("Exiting due to usage pattern validation failure.")
        sys.exit(1)
    
    # Load environment variables
    load_dotenv()
    
    # If env not found, try parent directories
    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        # Try multiple parent directory levels
        current_dir = os.path.dirname(os.path.abspath(__file__))
        for i in range(5):  # Try up to 5 levels up
            parent_dir = os.path.join(current_dir, *(['..'] * (i + 1)))
            env_path = os.path.join(parent_dir, ".env")
            if os.path.exists(env_path):
                load_dotenv(env_path)
                break
    
    # Parse command line arguments
    parser = setup_argument_parser()
    args = parser.parse_args()
    
    # Handle single game testing
    if args.test_single_game:
        test_single_game_scrapers(args.test_single_game, debug=True)
        sys.exit(0)
    
    # Handle database statistics request
    if args.db_stats:
        success = show_database_statistics()
        sys.exit(0 if success else 1)

    if args.check_duplicates:
        success = show_duplicate_games()
        sys.exit(0 if success else 1)
    
    # Apply security validation to all parameters
    print("🔒 Applying security validation...")
    args.rate = SecurityConfig.validate_rate_limit(args.rate)
    args.limit = SecurityConfig.validate_games_limit(args.limit)
    args.output = SecurityConfig.validate_output_path(args.output, args.absolute_path)
    
    slops_debug = args.debug or args.debug_scrapers
    
    # Display security-validated parameters
    print(f"🔒 Validated parameters:")
    print(f"   Rate limit: {args.rate}s")
    print(f"   Games limit: {args.limit}")
    print(f"   Output directory: {args.output}")
    print(f"   Skip existing games: {'✅' if args.skip_existing else '❌'}")
    print(f"   Force refresh: {'✅' if args.force_refresh else '❌'}")
    print(f"   Debug mode: {'✅' if slops_debug else '❌'}")
    
    # Better guidance on flag combinations
    if args.force_refresh and args.skip_existing:
        print("ℹ️  Configuration: Force refresh cache but skip games already in database")
        print("   This will refresh Steam API data but won't re-process existing games")
    elif args.force_refresh and not args.skip_existing:
        print("⚠️  Configuration: Force refresh cache AND re-process all games")
        print("   This may result in duplicate processing and longer run times")
    elif not args.force_refresh and args.skip_existing:
        print("ℹ️  Configuration: Use cached data and skip existing games (efficient)")
    else:
        print("⚠️  Configuration: Use cached data but process all games")
    
    # Rescan mode setup
    if args.rescan_reset:
        from core.scraper import RESCAN_PROGRESS_FILE
        if os.path.exists(RESCAN_PROGRESS_FILE):
            os.remove(RESCAN_PROGRESS_FILE)
            print(f"🔁 Cleared rescan progress ({RESCAN_PROGRESS_FILE})")
        else:
            print("🔁 No rescan progress file to clear")
        if not args.rescan:
            sys.exit(0)

    if args.rescan_engines and not args.rescan:
        print("❌ --rescan-engines narrows --rescan; pass --rescan as well")
        sys.exit(1)

    if args.rescan:
        if args.test:
            print("❌ --rescan requires production mode (it re-processes database games); drop --test")
            sys.exit(1)
        if args.rescan_engines:
            print("🔁 Rescan mode: engine-targeted — only games whose engine has "
                  "documented launch options, thinnest option counts first")
        else:
            print("🔁 Rescan mode: re-processing existing database games, thinnest option counts first")

    if args.pcgw_recheck:
        if args.test:
            print("❌ --pcgw-recheck requires production mode (it re-processes database games); drop --test")
            sys.exit(1)
        if args.rescan:
            print("❌ --pcgw-recheck and --rescan are mutually exclusive game sources; pick one")
            sys.exit(1)
        print("🔎 PCGamingWiki recheck mode: re-processing only games flagged during a prior outage")

    # Provide guidance on skip_existing behavior
    if not args.test and not args.skip_existing and not args.rescan and not args.pcgw_recheck:
        print("⚠️  Warning: You're processing ALL games, including those already in the database.")
        print("   This may result in duplicate processing and longer run times.")
        print("   Consider using --skip-existing to avoid re-processing existing games.")
        confirm = input("   Continue anyway? (y/N): ").lower()
        if confirm != 'y':
            print("Exiting.")
            sys.exit(0)
    
    # Initialize scraper with validated parameters
    scraper = SlopScraper(
        rate_limit=args.rate,
        max_games=args.limit,
        test_mode=args.test,
        output_dir=args.output,
        force_refresh=args.force_refresh,
        debug=slops_debug,  # Pass debug flag
        skip_existing=args.skip_existing,  # Pass skip_existing flag
        rescan=args.rescan,  # Re-scan existing database games
        rescan_engines=args.rescan_engines,  # ...narrowed to engines with documented options
        pcgw_recheck=args.pcgw_recheck  # Re-scan only PCGamingWiki-outage-flagged games
    )
    
    # Only test the database connection if requested
    if args.test_db:
        success = scraper.test_database_connection()
        sys.exit(0 if success else 1)
    
    try:
        # Run the scraper
        scraper.run()
    except KeyboardInterrupt:
        # This shouldn't be reached if signal handling works
        print("\nScript interrupted. Exiting.")
        sys.exit(1)
    except Exception as e:
        print(f"\n🚨 Security or execution error: {e}")
        if slops_debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()