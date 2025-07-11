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
        save_to_database,
        SupabaseClient,  # Import the wrapper class
        get_database_stats  # Import stats function
    )
    from ..scrapers.steampowered import get_steam_game_list
    from ..scrapers.pcgamingwiki import fetch_pcgamingwiki_launch_options
    from ..scrapers.steamcommunity import fetch_steam_community_launch_options
    from ..scrapers.game_specific import fetch_game_specific_options
    from ..scrapers.protondb import fetch_protondb_launch_options
    from ..scrapers.reddit_wiki import fetch_reddit_wiki_launch_options
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
        save_to_database,
        SupabaseClient,  # Import the wrapper class
        get_database_stats  # Import stats function
    )
    from scrapers.steampowered import get_steam_game_list
    from scrapers.pcgamingwiki import fetch_pcgamingwiki_launch_options
    from scrapers.steamcommunity import fetch_steam_community_launch_options
    from scrapers.game_specific import fetch_game_specific_options
    from scrapers.protondb import fetch_protondb_launch_options
    from scrapers.reddit_wiki import fetch_reddit_wiki_launch_options
    from utils.results_utils import save_test_results, save_game_results

class SlopScraper:
    def __init__(self, test_mode=False, cache_file='appdetails_cache.json', 
                 rate_limit=None, force_refresh=False, max_games=100, 
                 output_dir="./test-output", debug=False, skip_existing=True):  # skip_existing parameter
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
        self.skip_existing = skip_existing  # Store skip_existing setting
        self.db_client = None  # Database client wrapper

        # Security monitoring and rate limiting
        self.session_monitor = SessionMonitor()
        self.rate_limiter = RateLimiter(self.rate_limit)
        
        print(f"🔒 Security initialized:")
        print(f"   Session monitoring: ✅")
        print(f"   Rate limiting: {self.rate_limit}s between requests")
        print(f"   Resource limits: max {self.max_games} games")
        print(f"   Skip existing games: {'✅' if self.skip_existing else '❌'}")  # Show skip setting

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
            # Try to initialize database client wrapper for better functionality
            try:
                if self.skip_existing:
                    self.db_client = SupabaseClient()
                    self.supabase = self.db_client.supabase
                    print("✅ Connected to Supabase with a fancy client successfully")
                    
                    # Show database statistics on startup
                    if self.debug:
                        stats = self.db_client.get_database_stats()
                        print(f"🔒 Database stats: {stats['total_games']} games, {stats['total_option_relationships']} options")
                else:
                    self.supabase = setup_supabase_connection()
                    print("✅ Connected to Supabase successfully")
            except Exception as e:
                print(f"⚠️ Database connection failed: {e}")
                print("🔒 Falling back to test mode for security.")
                self.test_mode = True
                self.skip_existing = False  # Can't skip without database
        
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
        
        # Call as standalone function, not class method
        try:
            save_cache(self.cache, self.cache_file)
            print("✅ Cache saved successfully")
        except Exception as e:
            print(f"⚠️ Error saving cache: {e}")
        
        # Save test results if in test mode
        if self.test_mode:
            try:
                save_test_results(self.test_results, self.output_dir)
                print("✅ Test results saved successfully")
            except Exception as e:
                print(f"⚠️ Error saving test results: {e}")
            
        print("Cleanup complete. Exiting.")
        sys.exit(0)

    def test_database_connection(self):
        """Test database connection and return status"""
        return test_database_connection(
            test_mode=self.test_mode,
            supabase=self.supabase
        )

    def show_database_stats(self):  # Method to show database statistics
        """Show comprehensive database statistics"""
        if self.test_mode:
            print("ℹ️ Database stats not available in test mode")
            return
        
        if not self.db_client:
            print("⚠️ Database client not available")
            return
        
        try:
            stats = self.db_client.get_database_stats()
            print("\n📊 Database Statistics:")
            print(f"   Total games: {stats.get('total_games', 0)}")
            print(f"   Total option relationships: {stats.get('total_option_relationships', 0)}")
            print(f"   Unique launch options: {stats.get('unique_launch_options', 0)}")
            print(f"   Average options per game: {stats.get('avg_options_per_game', 0)}")
            print("   Options by source:")
            for source, count in stats.get('options_by_source', {}).items():
                print(f"     {source}: {count}")
            print()
        except Exception as e:
            print(f"⚠️ Error getting database stats: {e}")

    def run(self):
        """Main method to run the scraper with security monitoring and duplicate prevention"""
        print(f"Running in {'TEST' if self.test_mode else 'PRODUCTION'} mode")
        print(f"🔒 Security: Rate limit={self.rate_limit}s, Max games={self.max_games}")
        
        try:
            # Initial runtime check
            if hasattr(self, 'session_monitor'):
                self.session_monitor.check_runtime_limit()
            
            # Get list of games (limited by max_games) with security monitoring
            games = get_steam_game_list(
                limit=self.max_games,
                force_refresh=self.force_refresh,
                cache=self.cache,
                test_mode=self.test_mode,
                debug=self.debug,
                cache_file=self.cache_file,
                rate_limiter=getattr(self, 'rate_limiter', None),
                session_monitor=getattr(self, 'session_monitor', None),
                db_client=self.supabase  # Pass database client for skip-existing check
            )
            
            if not games:
                print("⚠️ No new games found to process")
                return
            
            print(f"📋 Found {len(games)} NEW games to process")
            
            # Process each game
            with tqdm(games, desc="Processing new games", unit="game") as game_pbar:
                for game in game_pbar:
                    app_id = game['appid']
                    title = game['name']
                    
                    game_pbar.set_description(f"Games processed")
                    
                    # Collect options from different sources
                    all_options = []
                    
                    game_pbar.write(f"\n📋 Processing {title} (App ID: {app_id})")
                    
                    # Add game-specific options from our knowledge base
                    try:
                        game_pbar.write(f"  🔍 Checking game-specific options...")
                        if self.session_monitor:
                            self.session_monitor.start_scraper_timing("Game-specific")
                        
                        game_specific_options = fetch_game_specific_options(
                            app_id=app_id, 
                            title=title, 
                            cache=self.cache,
                            test_results=getattr(self, 'test_results', None),
                            test_mode=self.test_mode
                        )
                        
                        if self.session_monitor:
                            elapsed = self.session_monitor.end_scraper_timing("Game-specific")
                            game_pbar.write(f"  ✅ Game-specific: {len(game_specific_options)} options found ({elapsed:.1f}s)")
                        else:
                            game_pbar.write(f"  ✅ Game-specific: {len(game_specific_options)} options found")
                        
                        if game_specific_options:
                            all_options.extend(game_specific_options)
                    except Exception as e:
                        game_pbar.write(f"  ❌ Game-specific: Error - {e}")

                    # Fetch from PCGamingWiki
                    try:
                        game_pbar.write(f"  🔍 Searching PCGamingWiki...")
                        if self.session_monitor:
                            self.session_monitor.start_scraper_timing("PCGamingWiki")
                        
                        pcgaming_options = fetch_pcgamingwiki_launch_options(
                            title, 
                            rate_limit=self.rate_limit,
                            debug=self.debug,
                            test_results=getattr(self, 'test_results', None),
                            test_mode=self.test_mode,
                            rate_limiter=self.rate_limiter,
                            session_monitor=self.session_monitor
                        )
                        
                        if self.session_monitor:
                            elapsed = self.session_monitor.end_scraper_timing("PCGamingWiki")
                            game_pbar.write(f"  ✅ PCGamingWiki: {len(pcgaming_options)} options found ({elapsed:.1f}s)")
                        else:
                            game_pbar.write(f"  ✅ PCGamingWiki: {len(pcgaming_options)} options found")
                        
                        all_options.extend(pcgaming_options)
                    except Exception as e:
                        game_pbar.write(f"  ❌ PCGamingWiki: Error - {e}")
                    
                    # Fetch from Steam Community
                    try:
                        game_pbar.write(f"  🔍 Searching Steam Community guides...")
                        if self.session_monitor:
                            self.session_monitor.start_scraper_timing("Steam Community")
                        
                        steam_community_options = fetch_steam_community_launch_options(
                            app_id, 
                            game_title=title,
                            rate_limit=self.rate_limit,
                            debug=self.debug,
                            test_results=getattr(self, 'test_results', None),
                            test_mode=self.test_mode,
                            rate_limiter=self.rate_limiter,
                            session_monitor=self.session_monitor
                        )
                        
                        if self.session_monitor:
                            elapsed = self.session_monitor.end_scraper_timing("Steam Community")
                            game_pbar.write(f"  ✅ Steam Community: {len(steam_community_options)} options found ({elapsed:.1f}s)")
                        else:
                            game_pbar.write(f"  ✅ Steam Community: {len(steam_community_options)} options found")
                        
                        all_options.extend(steam_community_options)
                    except Exception as e:
                        game_pbar.write(f"  ❌ Steam Community: Error - {e}")
                    
                    # Fetch from ProtonDB
                    try:
                        game_pbar.write(f"  🔍 Checking ProtonDB...")
                        if self.session_monitor:
                            self.session_monitor.start_scraper_timing("ProtonDB")
                        
                        protondb_options = fetch_protondb_launch_options(
                            app_id,
                            game_title=title,
                            rate_limit=self.rate_limit,
                            debug=self.debug,
                            test_results=getattr(self, 'test_results', None),
                            test_mode=self.test_mode,
                            rate_limiter=self.rate_limiter,
                            session_monitor=self.session_monitor
                        )
                        
                        if self.session_monitor:
                            elapsed = self.session_monitor.end_scraper_timing("ProtonDB")
                            game_pbar.write(f"  ✅ ProtonDB: {len(protondb_options)} options found ({elapsed:.1f}s)")
                        else:
                            game_pbar.write(f"  ✅ ProtonDB: {len(protondb_options)} options found")
                        
                        all_options.extend(protondb_options)
                    except Exception as e:
                        game_pbar.write(f"  ❌ ProtonDB: Error - {e}")
                    
                    # Fetch from Reddit Gaming Wikis
                    try:
                        game_pbar.write(f"  🔍 Searching Reddit wikis...")
                        if self.session_monitor:
                            self.session_monitor.start_scraper_timing("Reddit Wikis")
                        
                        reddit_options = fetch_reddit_wiki_launch_options(
                            title,
                            app_id=app_id,
                            rate_limit=self.rate_limit,
                            debug=self.debug,
                            test_results=getattr(self, 'test_results', None),
                            test_mode=self.test_mode,
                            rate_limiter=self.rate_limiter,
                            session_monitor=self.session_monitor
                        )
                        
                        if self.session_monitor:
                            elapsed = self.session_monitor.end_scraper_timing("Reddit Wikis")
                            game_pbar.write(f"  ✅ Reddit wikis: {len(reddit_options)} options found ({elapsed:.1f}s)")
                        else:
                            game_pbar.write(f"  ✅ Reddit wikis: {len(reddit_options)} options found")
                        
                        all_options.extend(reddit_options)
                    except Exception as e:
                        game_pbar.write(f"  ❌ Reddit wikis: Error - {e}")

                    # Deduplicate options by command
                    unique_options = []
                    seen_commands = set()
                    for option in all_options:
                        cmd = option['command'].strip().lower()
                        if cmd not in seen_commands:
                            seen_commands.add(cmd)
                            unique_options.append(option)
                    
                    # Update test statistics or save to database
                    if self.test_mode:
                        if hasattr(self, 'test_results'):
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
                        
                        # Save individual game results
                        try:
                            save_game_results(app_id, title, unique_options, self.output_dir)
                        except Exception as e:
                            game_pbar.write(f"  Error saving game results: {e}")
                    else:
                        # Save to database in production mode
                        if self.supabase:
                            try:
                                save_to_database(game, unique_options, self.supabase)
                            except Exception as e:
                                game_pbar.write(f"⚠️ Error saving to database: {e}")
                        else:
                            game_pbar.write(f"⚠️ Database connection not available")
                    
                    game_pbar.write(f"\n✅ Completed {title}: {len(unique_options)} unique options found\n")
                    
                    # Periodically save cache during execution
                    if app_id % 3 == 0:
                        try:
                            save_cache(self.cache, self.cache_file)
                        except Exception as e:
                            game_pbar.write(f"⚠️ Error saving cache: {e}")

            # Save test results summary
            if self.test_mode:
                try:
                    save_test_results(self.test_results, self.output_dir)
                except Exception as e:
                    print(f"⚠️ Error saving test results: {e}")
                    
        except Exception as e:
            print(f"\n🚨 Error during execution: {e}")
            import traceback
            traceback.print_exc()
            
            # Save what we have so far
            try:
                # Call as standalone function, not class method  
                save_cache(self.cache, self.cache_file)
            except Exception as cache_error:
                print(f"⚠️ Error saving cache during cleanup: {cache_error}")
                
            if self.test_mode:
                try:
                    save_test_results(self.test_results, self.output_dir)
                except Exception as results_error:
                    print(f"⚠️ Error saving test results during cleanup: {results_error}")
            raise