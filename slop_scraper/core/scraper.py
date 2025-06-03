import os
import sys
import signal
import shutil
import time
from tqdm import tqdm

try:
    # Try relative imports first (when run as module)
    from ..utils.cache import load_cache, save_cache
    from ..utils.security_config import SecurityConfig, SessionMonitor, RateLimiter
    from ..database.supabase import (
        setup_supabase_connection, 
        test_database_connection,
        fetch_steam_launch_options_from_db,
        save_to_database
    )
    from ..scrapers.steampowered import get_steam_game_list
    from ..scrapers.pcgamingwiki import fetch_pcgamingwiki_launch_options
    from ..scrapers.steamcommunity import fetch_steam_community_launch_options
    from ..scrapers.game_specific import fetch_game_specific_options
    from ..utils.results_utils import save_test_results, save_game_results
except ImportError:
    # Fall back to absolute imports (when run directly)
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    from utils.cache import load_cache, save_cache
    from utils.security_config import SecurityConfig, SessionMonitor, RateLimiter
    from database.supabase import (
        setup_supabase_connection, 
        test_database_connection,
        fetch_steam_launch_options_from_db,
        save_to_database
    )
    from scrapers.steampowered import get_steam_game_list
    from scrapers.pcgamingwiki import fetch_pcgamingwiki_launch_options
    from scrapers.steamcommunity import fetch_steam_community_launch_options
    from scrapers.game_specific import fetch_game_specific_options
    from utils.results_utils import save_test_results, save_game_results

class SlopScraper:
    def __init__(self, test_mode=False, cache_file='appdetails_cache.json', 
                 rate_limit=None, force_refresh=False, max_games=100, 
                 output_dir="./test-output", debug=False):
        """Initialize with configuration options and security validation"""
        
        # Security validation first
        self.test_mode = test_mode
        self.force_refresh = force_refresh
        self.rate_limit = SecurityConfig.validate_rate_limit(rate_limit or 2.0)
        self.cache_file = cache_file
        self.max_games = SecurityConfig.validate_games_limit(max_games)
        self.output_dir = SecurityConfig.validate_output_path(output_dir)
        self.failed_cache = set()
        self.debug = debug
        self.supabase = None

        # Security monitoring and rate limiting
        self.session_monitor = SessionMonitor()
        self.rate_limiter = RateLimiter(self.rate_limit)
        
        print(f"🔒 Security initialized:")
        print(f"   Session monitoring: ✅")
        print(f"   Rate limiting: {self.rate_limit}s between requests")
        print(f"   Resource limits: max {self.max_games} games")

        # Validate cache size and handle if too large
        if not SecurityConfig.validate_cache_size(self.cache_file):
            backup_cache = f"{self.cache_file}.backup"
            print(f"🔒 Creating backup and clearing large cache file: {backup_cache}")
            try:
                if os.path.exists(self.cache_file):
                    shutil.copy2(self.cache_file, backup_cache)
                    os.remove(self.cache_file)
                    print("✅ Cache file reset for security")
            except Exception as e:
                print(f"⚠️ Could not reset cache file: {e}")

        # Create output directory if it doesn't exist
        if not os.path.exists(self.output_dir):
            try:
                os.makedirs(self.output_dir)
                print(f"Created output directory: {self.output_dir}")
            except Exception as e:
                print(f"Error creating output directory: {e}")
                # Fall back to current directory if we can't create the specified one
                self.output_dir = "./"
                print(f"Falling back to current directory: {self.output_dir}")
        
        # Load cache
        self.cache = load_cache(self.cache_file)
        
        # Initialize Supabase connection if not in test mode
        if not self.test_mode:
            self.supabase = setup_supabase_connection()
            if self.supabase:
                print("✅ Connected to Supabase successfully")
            else:
                print("🔒 Falling back to test mode for security.")
                self.test_mode = True
        
        # Initialize test results dict if test mode is on
        if self.test_mode:
            self.test_results = {
                "games_processed": 0,
                "games_with_options": 0,
                "total_options_found": 0,
                "options_by_source": {},
                "games": []
            }
        
        # Set up signal handlers for graceful exit
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, sig, frame):
        """Handle shutdown signals gracefully"""
        print("\n\n🔒 Gracefully shutting down...")
        print("Saving cache and collected data...")
        
        # Save cache 
        save_cache(self.cache, self.cache_file)
        
        # Save test results if in test mode
        if self.test_mode:
            save_test_results(self.test_results, self.output_dir)
            
        print("Cleanup complete. Exiting.")
        sys.exit(0)

    def test_database_connection(self):
        """Test database connection and return status"""
        return test_database_connection(
            test_mode=self.test_mode,
            supabase=self.supabase
        )

    def run(self):
        """Main method to run the scraper with security monitoring"""
        print(f"Running in {'TEST' if self.test_mode else 'PRODUCTION'} mode")
        print(f"🔒 Security: Rate limit={self.rate_limit}s, Max games={self.max_games}")
        
        try:
            # Initial runtime check
            self.session_monitor.check_runtime_limit()
            
            # Get list of games (limited by max_games) with security monitoring
            games = get_steam_game_list(
                limit=self.max_games,
                force_refresh=self.force_refresh,
                cache=self.cache,
                test_mode=self.test_mode,
                debug=self.debug,
                cache_file=self.cache_file,
                rate_limiter=self.rate_limiter,
                session_monitor=self.session_monitor
            )
            
            # Process each game with better progress indication and security checks
            with tqdm(games, desc="Processing games", unit="game") as game_pbar:
                for game_index, game in enumerate(game_pbar):
                    # Periodic security checks
                    if game_index % 10 == 0:
                        self.session_monitor.check_runtime_limit()
                    
                    app_id = game['appid']
                    title = game['name']
                    
                    # Update progress bar description
                    game_pbar.set_description(f"Processing {title}")
                    
                    # Check if we already have data in database
                    existing_options = [] if self.test_mode else fetch_steam_launch_options_from_db(
                        app_id=app_id,
                        supabase=self.supabase
                    )
                    
                    # If we already have data and not forcing refresh, skip
                    if existing_options and not self.force_refresh:
                        game_pbar.write(f"Skipping {title} - already have {len(existing_options)} options in database")
                        continue
                    
                    # Collect options from different sources
                    all_options = []
                    
                    # Add game-specific options from our knowledge base
                    try:
                        game_specific_options = fetch_game_specific_options(
                            title=title, 
                            app_id=app_id,
                            cache=self.cache,
                            test_results=self.test_results if self.test_mode else None
                        )
                        
                        if game_specific_options:
                            all_options.extend(game_specific_options)
                            game_pbar.write(f"  Added {len(game_specific_options)} game-specific options")
                    except Exception as e:
                        self.session_monitor.record_error()
                        game_pbar.write(f"  Error fetching game-specific options: {e}")

                    # Create a small progress bar for sources with security controls
                    sources = [
                        ("PCGamingWiki", lambda: fetch_pcgamingwiki_launch_options(
                            game_title=title,
                            rate_limit=self.rate_limit,
                            debug=self.debug,
                            test_results=self.test_results if self.test_mode else None,
                            test_mode=self.test_mode,
                            rate_limiter=self.rate_limiter,
                            session_monitor=self.session_monitor
                        )),
                        ("Steam Community", lambda: fetch_steam_community_launch_options(
                            game_title=title, 
                            app_id=app_id,
                            rate_limit=self.rate_limit,
                            debug=self.debug,
                            test_results=self.test_results if self.test_mode else None,
                            test_mode=self.test_mode,
                            rate_limiter=self.rate_limiter,
                            session_monitor=self.session_monitor
                        ))
                    ]
                    
                    with tqdm(sources, desc="Checking sources", leave=False) as source_pbar:
                        for source_name, source_func in source_pbar:
                            source_pbar.set_description(f"Checking {source_name}")
                            try:
                                options = source_func()
                                all_options.extend(options)
                                game_pbar.write(f"  Found {len(options)} options on {source_name}")
                                self.session_monitor.record_request()
                            except Exception as e:
                                self.session_monitor.record_error()
                                game_pbar.write(f"  Error fetching from {source_name}: {e}")
                    
                    # Deduplicate options by command
                    unique_options = []
                    seen_commands = set()
                    for option in all_options:
                        cmd = option['command'].strip().lower()
                        if cmd not in seen_commands:
                            seen_commands.add(cmd)
                            unique_options.append(option)
                    
                    # Update test statistics
                    if self.test_mode:
                        self.test_results['games_processed'] += 1
                        if unique_options:
                            self.test_results['games_with_options'] += 1
                        self.test_results['total_options_found'] += len(unique_options)
                        
                        # Add game data to test results
                        self.test_results['games'].append({
                            'app_id': app_id,
                            'title': title,
                            'options_count': len(unique_options),
                            'options': unique_options
                        })
                        
                        # Save individual game results to separate file
                        save_game_results(
                            app_id=app_id,
                            title=title,
                            options=unique_options,
                            output_dir=self.output_dir
                        )
                    else:
                        # Save to database in production mode
                        try:
                            save_to_database(
                                game=game,
                                options=unique_options,
                                supabase=self.supabase
                            )
                        except Exception as e:
                            self.session_monitor.record_error()
                            game_pbar.write(f"  Database error for {title}: {e}")
                    
                    game_pbar.write(f"Found {len(unique_options)} unique launch options for {title}")
                    
                    # Periodically save cache during execution
                    if game['appid'] % 3 == 0:  # Save every 3 games
                        save_cache(self.cache, self.cache_file)

            # Final save operations
            if self.test_mode:
                save_test_results(self.test_results, self.output_dir)
            
            # Final cache save
            save_cache(self.cache, self.cache_file)
            
            print(f"🔒 Session completed successfully:")
            print(f"   Total requests: {self.session_monitor.request_count}")
            print(f"   Total errors: {self.session_monitor.error_count}")
            print(f"   Runtime: {(time.time() - self.session_monitor.start_time)/60:.1f} minutes")
                
        except Exception as e:
            self.session_monitor.record_error()
            print(f"\n🚨 Error during execution: {e}")
            # Save what we have so far
            save_cache(self.cache, self.cache_file)
            if self.test_mode:
                save_test_results(self.test_results, self.output_dir)
            raise