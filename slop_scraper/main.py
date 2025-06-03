#!/usr/bin/env python3
import os
import sys
import argparse
from dotenv import load_dotenv

try:
    # Try relative imports first (when run as module)
    from .core.scraper import SlopScraper
    from .utils.security_config import SecurityConfig, validate_usage_pattern
except ImportError:
    # Fall back to absolute imports (when run directly)
    from core.scraper import SlopScraper
    from utils.security_config import SecurityConfig, validate_usage_pattern
 
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
    return parser

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
    
    # Initialize scraper with validated parameters
    scraper = SlopScraper(
        rate_limit=args.rate,
        max_games=args.limit,
        test_mode=args.test,
        output_dir=args.output,
        force_refresh=args.force_refresh,
        debug=False
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