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
    from database.supabase import SupabaseClient, get_database_stats  # Import for stats
 
def get_script_dir():
    """Get directory where this script (slop_scraper) is located"""
    script_path = os.path.dirname(os.path.abspath(__file__))
    return script_path

def setup_argument_parser():
    """Set up and return the argument parser for CLI arguments"""
    parser = argparse.ArgumentParser(description='Steam Launch Options Scraper')
    parser.add_argument('--test', action='store_true', help='Run in test mode')
    parser.add_argument('--limit', type=int, default=5, 
                       help=f'Maximum number of games to process (max: {SecurityConfig.MAX_GAMES_LIMIT})')
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
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug output including database stats')
    
    # Add scraper-specific debug options
    parser.add_argument('--debug-scrapers', action='store_true',
                       help='Enable detailed debug output for all scrapers')
    parser.add_argument('--test-single-game', type=str, 
                       help='Test scrapers on a single game by name (debug mode)')
    
    return parser

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
        
        # Show problematic options analysis
        problematic_stats = stats.get('problematic_options', {})
        if problematic_stats:
            print("\n🚨 Problematic Options Analysis:")
            for cmd, info in problematic_stats.items():
                if info.get('exists', False):
                    games_count = info.get('games_count', 0)
                    source = info.get('source', 'Unknown')
                    print(f"   {cmd}: {games_count} games (source: {source})")
                    if games_count > 10:
                        print(f"     ⚠️ HIGH PRIORITY for cleanup!")
        
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

def test_single_game_scrapers(game_name, debug=True):
    """Test all scrapers on a single game for debugging purposes"""
    print(f"\n🧪 Testing all scrapers on '{game_name}'...")
    
    try:
        # Import scrapers
        from scrapers.pcgamingwiki import fetch_pcgamingwiki_launch_options
        from scrapers.steamcommunity import fetch_steam_community_launch_options
        from scrapers.protondb import fetch_protondb_launch_options
        from scrapers.game_specific import fetch_game_specific_options
        
        # Mock app_id for testing (use Counter-Strike as default)
        test_app_id = 10  # Counter-Strike
        
        print(f"\n1. Testing PCGamingWiki scraper...")
        pcg_options = fetch_pcgamingwiki_launch_options(
            game_name, 
            rate_limit=1.0, 
            debug=debug,
            test_mode=True
        )
        print(f"   Result: {len(pcg_options)} options found")
        for i, opt in enumerate(pcg_options[:3]):
            print(f"     {i+1}. {opt['command']}: {opt['description'][:50]}...")
        
        print(f"\n2. Testing Steam Community scraper...")
        sc_options = fetch_steam_community_launch_options(
            test_app_id,
            game_title=game_name,
            rate_limit=1.0,
            debug=debug,
            test_mode=True
        )
        print(f"   Result: {len(sc_options)} options found")
        for i, opt in enumerate(sc_options[:3]):
            print(f"     {i+1}. {opt['command']}: {opt['description'][:50]}...")
        
        print(f"\n3. Testing ProtonDB scraper...")
        pdb_options = fetch_protondb_launch_options(
            test_app_id,
            game_title=game_name,
            rate_limit=1.0,
            debug=debug,
            test_mode=True
        )
        print(f"   Result: {len(pdb_options)} options found")
        for i, opt in enumerate(pdb_options[:3]):
            print(f"     {i+1}. {opt['command']}: {opt['description'][:50]}...")
        
        print(f"\n4. Testing Game-Specific scraper...")
        cache = {}  # Empty cache for testing
        gs_options = fetch_game_specific_options(
            test_app_id,
            game_name,
            cache,
            test_mode=True
        )
        print(f"   Result: {len(gs_options)} options found")
        for i, opt in enumerate(gs_options[:3]):
            print(f"     {i+1}. {opt['command']}: {opt['description'][:50]}...")
        
        # Summary
        total_options = len(pcg_options) + len(sc_options) + len(pdb_options) + len(gs_options)
        print(f"\n📊 Summary for '{game_name}':")
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
            print("   - Security validation is too strict")
        else:
            print(f"\n✅ Found {total_options} total options - scrapers appear to be working!")
            
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
    
    # Provide guidance on skip_existing behavior
    if not args.test and not args.skip_existing:
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
        skip_existing=args.skip_existing  # Pass skip_existing flag
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