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
    
    # Handle database statistics request
    if args.db_stats:
        success = show_database_statistics()
        sys.exit(0 if success else 1)
    
    # Apply security validation to all parameters
    print("🔒 Applying security validation...")
    args.rate = SecurityConfig.validate_rate_limit(args.rate)
    args.limit = SecurityConfig.validate_games_limit(args.limit)
    args.output = SecurityConfig.validate_output_path(args.output, args.absolute_path)
    
    # Display security-validated parameters
    print(f"🔒 Validated parameters:")
    print(f"   Rate limit: {args.rate}s")
    print(f"   Games limit: {args.limit}")
    print(f"   Output directory: {args.output}")
    print(f"   Skip existing games: {'✅' if args.skip_existing else '❌'}")  # Show skip setting
    print(f"   Force refresh: {'✅' if args.force_refresh else '❌'}")
    print(f"   Debug mode: {'✅' if args.debug else '❌'}")  # Show debug setting
    
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
        debug=args.debug,  # Pass debug flag
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
        sys.exit(1)

if __name__ == "__main__":
    main()