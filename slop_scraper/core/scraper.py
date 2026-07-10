import os
import sys
import signal
import shutil
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
    from ..utils.results_utils import save_test_results, save_game_results
    from ..validation import LaunchOptionsValidator, ValidationLevel, EngineType
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
        SupabaseClient, 
        get_database_stats 
    )
    from scrapers.steampowered import get_steam_game_list
    from scrapers.pcgamingwiki import fetch_pcgamingwiki_launch_options
    from scrapers.steamcommunity import fetch_steam_community_launch_options
    from scrapers.game_specific import fetch_game_specific_options
    from scrapers.protondb import fetch_protondb_launch_options
    from utils.results_utils import save_test_results, save_game_results
    from validation import LaunchOptionsValidator, ValidationLevel, EngineType

# Anchored to the project root (parent of the package) so the same progress
# file is used no matter which directory the scraper is launched from.
RESCAN_PROGRESS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'rescan_progress.json'
)

class SlopScraper:
    def __init__(self, test_mode=False, cache_file='appdetails_cache.json',
                 rate_limit=None, force_refresh=False, max_games=100,
                 output_dir="./test-output", debug=False, skip_existing=True,
                 rescan=False):
        
        # Add validation statistics tracking
        self.validation_stats = {
            'total_options_processed': 0,
            'options_accepted': 0,
            'options_rejected': 0,
            'rejection_reasons': {}
        }
        
        # Initialize validator for statistics
        self.validator = LaunchOptionsValidator(ValidationLevel.PERMISSIVE)
        
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
        self.rescan = rescan  # Re-scan games already in the database

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
            # Try to initialize database client wrapper
            try:
                if self.skip_existing:
                    self.db_client = SupabaseClient()
                    self.supabase = self.db_client.supabase
                    print("✅ Connected to Supabase successfully")
                    
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

    # ---------- Rescan support ----------

    def _load_rescan_progress(self):
        """Return the set of app_ids already re-scanned in this campaign."""
        import json
        try:
            if os.path.exists(RESCAN_PROGRESS_FILE):
                with open(RESCAN_PROGRESS_FILE) as f:
                    return {int(k) for k in json.load(f)}
        except Exception as e:
            print(f"⚠️ Could not read {RESCAN_PROGRESS_FILE}: {e}")
        return set()

    def _mark_rescanned(self, app_id):
        """Record a completed rescan so interrupted campaigns resume."""
        import json
        from datetime import datetime
        try:
            data = {}
            if os.path.exists(RESCAN_PROGRESS_FILE):
                with open(RESCAN_PROGRESS_FILE) as f:
                    data = json.load(f)
            data[str(app_id)] = datetime.now().isoformat(timespec='seconds')
            with open(RESCAN_PROGRESS_FILE, 'w') as f:
                json.dump(data, f, indent=1)
        except Exception as e:
            print(f"⚠️ Could not update {RESCAN_PROGRESS_FILE}: {e}")

    def _get_rescan_games(self):
        """
        Pull ALL games already in the database for re-scanning, thinnest first.

        Every stored game is a candidate — including games with zero options,
        which may simply have been scraped while the scrapers were broken.
        Ordering by total_options_count ascending front-loads the games that
        benefit most. Already-rescanned games (tracked locally in
        rescan_progress.json) are excluded so the campaign can be run in
        --limit sized chunks across many sessions.
        """
        if not self.supabase:
            print("❌ Rescan requires a database connection")
            return []

        done = self._load_rescan_progress()

        # Paginate — Supabase caps selects at 1000 rows by default
        rows = []
        page_size = 1000
        start = 0
        try:
            while True:
                response = (
                    self.supabase.table("games")
                    .select("app_id, title, developer, publisher, release_date, engine, total_options_count")
                    .order("total_options_count", desc=False)
                    .range(start, start + page_size - 1)
                    .execute()
                )
                batch = response.data or []
                rows.extend(batch)
                if len(batch) < page_size:
                    break
                start += page_size
        except Exception as e:
            print(f"⚠️ Rescan query failed: {e}")
            return []

        total_candidates = len(rows)

        games = []
        for row in rows:
            if row['app_id'] in done:
                continue
            games.append({
                'appid': row['app_id'],
                'name': row['title'],
                'developer': row.get('developer') or '',
                'publisher': row.get('publisher') or '',
                'release_date': row.get('release_date') or '',
                'engine': row.get('engine') or 'Unknown',
            })
            if len(games) >= self.max_games:
                break

        remaining = total_candidates - len(done)
        print(f"🔁 Rescan: {total_candidates} games in DB, "
              f"{len(done)} already re-scanned, {max(0, remaining)} remaining")
        if not games and total_candidates:
            print(f"✅ Rescan campaign complete — delete {RESCAN_PROGRESS_FILE} to start a new one")

        return games

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
        """Run method with diagnostics and error handling for generic options issue"""
        print(f"Running in {'TEST' if self.test_mode else 'PRODUCTION'} mode")
        print(f"🔒 Security: Rate limit={self.rate_limit}s, Max games={self.max_games}")
        print(f"🔍 Skip existing games: {'✅' if self.skip_existing else '❌'}")
        
        # Diagnostic counters for the generic options issue
        scraper_stats = {
            'total_games_processed': 0,
            'games_with_any_options': 0,
            'games_with_only_generic_options': 0,
            'games_skipped_existing': 0,
            'scraper_success_rates': {
                'Game-Specific': {'success': 0, 'attempts': 0},
                'PCGamingWiki': {'success': 0, 'attempts': 0},
                'Steam Community': {'success': 0, 'attempts': 0},
                'ProtonDB': {'success': 0, 'attempts': 0}
            }
        }
        
        try:
            # Initial runtime check
            if hasattr(self, 'session_monitor'):
                self.session_monitor.check_runtime_limit()
            
            # Get list of games (limited by max_games) with database checking.
            # Rescan mode re-processes games already in the DB instead of
            # discovering new ones — options are added, never overwritten.
            if self.rescan:
                games = self._get_rescan_games()
            else:
                games = get_steam_game_list(
                    limit=self.max_games,
                    force_refresh=self.force_refresh,
                    cache=self.cache,
                    test_mode=self.test_mode,
                    debug=self.debug,
                    cache_file=self.cache_file,
                    rate_limiter=getattr(self, 'rate_limiter', None),
                    session_monitor=getattr(self, 'session_monitor', None),
                    db_client=self.supabase,  # Pass database client for skip-existing logic
                    skip_existing=self.skip_existing,  # Pass skip_existing setting
                    db_client_wrapper=self.db_client  # Pass the database wrapper
                )
            
            if not games:
                print("⚠️ No new games found to process")
                return
            
            print(f"📋 Found {len(games)} games to process")
            
            # Process each game with diagnostics
            with tqdm(games, desc="Processing games", unit="game") as game_pbar:
                for game in game_pbar:
                    app_id = game['appid']
                    title = game['name']
                    
                    game_pbar.set_description(f"Processing {title[:25]}...")
                    scraper_stats['total_games_processed'] += 1
                    
                    # Check if this game was skipped due to existing data
                    if hasattr(game, '_skipped_existing') and game._skipped_existing:
                        scraper_stats['games_skipped_existing'] += 1
                        continue
                    
                    # Collect options from different sources with detailed tracking
                    all_options = []
                    source_options = {}
                    
                    game_pbar.write(f"\n📋 Processing {title} (App ID: {app_id})")
                    
                    # 1. Game-specific options
                    try:
                        game_pbar.write(f"  🔍 Checking game-specific options...")
                        scraper_stats['scraper_success_rates']['Game-Specific']['attempts'] += 1
                        
                        if self.session_monitor:
                            self.session_monitor.start_scraper_timing("Game-specific")
                        
                        game_specific_options = fetch_game_specific_options(
                            app_id=app_id,
                            title=title,
                            cache=self.cache,
                            engine=game.get('engine'),
                            test_results=getattr(self, 'test_results', None),
                            test_mode=self.test_mode
                        )
                        
                        if self.session_monitor:
                            elapsed = self.session_monitor.end_scraper_timing("Game-specific")
                            timing_info = f" ({elapsed:.1f}s)"
                        else:
                            timing_info = ""
                        
                        if game_specific_options:
                            scraper_stats['scraper_success_rates']['Game-Specific']['success'] += 1
                            source_options['Game-Specific'] = game_specific_options
                            all_options.extend(game_specific_options)
                            
                            # Check if only generic/universal options (this was the bug)
                            generic_commands = {'-windowed', '-fullscreen'}
                            problematic_commands = {'-fps_max', '-nojoy', '-nosplash'}
                            
                            commands = {opt['command'] for opt in game_specific_options}
                            only_generic = commands.issubset(generic_commands)
                            has_problematic = bool(commands & problematic_commands)
                            
                            if only_generic:
                                game_pbar.write(f"  ⚠️ Only universal options found (this is normal for unrecognized engines)")
                            elif has_problematic:
                                game_pbar.write(f"  🚨 WARNING: Found old problematic generic options!")
                        
                        game_pbar.write(f"  ✅ Game-specific: {len(game_specific_options)} options found{timing_info}")
                        
                    except Exception as e:
                        game_pbar.write(f"  ❌ Game-specific: Error - {e}")

                    # 2. PCGamingWiki
                    try:
                        game_pbar.write(f"  🔍 Searching PCGamingWiki...")
                        scraper_stats['scraper_success_rates']['PCGamingWiki']['attempts'] += 1
                        
                        if self.session_monitor:
                            self.session_monitor.start_scraper_timing("PCGamingWiki")
                        
                        pcgaming_options = fetch_pcgamingwiki_launch_options(
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
                            elapsed = self.session_monitor.end_scraper_timing("PCGamingWiki")
                            timing_info = f" ({elapsed:.1f}s)"
                        else:
                            timing_info = ""
                        
                        if pcgaming_options:
                            scraper_stats['scraper_success_rates']['PCGamingWiki']['success'] += 1
                            source_options['PCGamingWiki'] = pcgaming_options
                            all_options.extend(pcgaming_options)
                        
                        game_pbar.write(f"  ✅ PCGamingWiki: {len(pcgaming_options)} options found{timing_info}")
                        
                    except Exception as e:
                        game_pbar.write(f"  ❌ PCGamingWiki: Error - {e}")

                    # 3. Steam Community
                    try:
                        game_pbar.write(f"  🔍 Searching Steam Community guides...")
                        scraper_stats['scraper_success_rates']['Steam Community']['attempts'] += 1
                        
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
                            timing_info = f" ({elapsed:.1f}s)"
                        else:
                            timing_info = ""
                        
                        if steam_community_options:
                            scraper_stats['scraper_success_rates']['Steam Community']['success'] += 1
                            source_options['Steam Community'] = steam_community_options
                            all_options.extend(steam_community_options)
                        
                        game_pbar.write(f"  ✅ Steam Community: {len(steam_community_options)} options found{timing_info}")
                        
                    except Exception as e:
                        game_pbar.write(f"  ❌ Steam Community: Error - {e}")

                    # 4. ProtonDB
                    try:
                        game_pbar.write(f"  🔍 Checking ProtonDB...")
                        scraper_stats['scraper_success_rates']['ProtonDB']['attempts'] += 1
                        
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
                            timing_info = f" ({elapsed:.1f}s)"
                        else:
                            timing_info = ""
                        
                        if protondb_options:
                            scraper_stats['scraper_success_rates']['ProtonDB']['success'] += 1
                            source_options['ProtonDB'] = protondb_options
                            all_options.extend(protondb_options)
                        
                        game_pbar.write(f"  ✅ ProtonDB: {len(protondb_options)} options found{timing_info}")
                        
                    except Exception as e:
                        game_pbar.write(f"  ❌ ProtonDB: Error - {e}")

                    # Deduplication with source priority
                    unique_options = self.deduplicate_with_priority(all_options)
                    
                    # Analyze option quality (detect generic options issue)
                    if unique_options:
                        scraper_stats['games_with_any_options'] += 1
                        
                        # Check for the old problematic generic options
                        problematic_commands = {'-fps_max', '-nojoy', '-nosplash'}
                        generic_commands = {'-windowed', '-fullscreen'}
                        
                        commands = {opt['command'] for opt in unique_options}
                        has_problematic = bool(commands & problematic_commands)
                        only_basic_generic = len(commands) <= 2 and commands.issubset(generic_commands | problematic_commands)
                        
                        if has_problematic:
                            game_pbar.write(f"  🚨 WARNING: Found old problematic options: {commands & problematic_commands}")
                        elif only_basic_generic:
                            scraper_stats['games_with_only_generic_options'] += 1
                            game_pbar.write(f"  ⚠️ Only basic generic options found")

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
                    
                    game_pbar.write(f"\n✅ Completed {title}: {len(unique_options)} unique options found")
                    if source_options:
                        sources_str = ", ".join(f"{k}({len(v)})" for k, v in source_options.items())
                        game_pbar.write(f"   Sources: {sources_str}\n")

                    # Record rescan progress so an interrupted campaign resumes
                    if self.rescan and not self.test_mode:
                        self._mark_rescanned(app_id)
                    
                    # Periodically save cache during execution
                    if app_id % 3 == 0:
                        try:
                            save_cache(self.cache, self.cache_file)
                        except Exception as e:
                            game_pbar.write(f"⚠️ Error saving cache: {e}")

            # Print comprehensive diagnostics for generic options issue
            self.print_scraper_diagnostics(scraper_stats)

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
                save_cache(self.cache, self.cache_file)
            except Exception as cache_error:
                print(f"⚠️ Error saving cache during cleanup: {cache_error}")
                
            if self.test_mode:
                try:
                    save_test_results(self.test_results, self.output_dir)
                except Exception as results_error:
                    print(f"⚠️ Error saving test results during cleanup: {results_error}")
            raise

    def deduplicate_with_priority(self, all_options):
        """Deduplication with source priority to fix conflicts"""
        unique_options = []
        seen_commands = {}  # Track command -> best_option mapping
        
        # Source priority for resolving conflicts (higher = better)
        source_priority = {
            'PCGamingWiki': 9,      # Highest - most reliable
            'Steam Community': 8,   # High - community verified
            'Source Engine': 7,     # High for Source games
            'Unity Engine': 7,      # High for Unity games
            'Unreal Engine': 7,     # High for Unreal games
            'id Tech': 7,           # High for id Tech games
            'Minecraft Java': 8,    # High for Minecraft
            'Creation Engine': 7,   # High for Bethesda games
            'Frostbite Engine': 7,  # High for EA games
            'ProtonDB': 6,          # Medium-high - Linux specific
            'Universal': 3,         # Low - basic universal options
            'Generic': 1,           # Lowest - old generic system
            'Launch Option': 1      # Lowest - old problematic system
        }
        
        for option in all_options:
            cmd = option['command'].strip().lower()
            
            if cmd not in seen_commands:
                seen_commands[cmd] = option
            else:
                # Resolve conflicts by source priority
                existing_option = seen_commands[cmd]
                existing_priority = source_priority.get(existing_option['source'], 0)
                new_priority = source_priority.get(option['source'], 0)
                
                if new_priority > existing_priority:
                    seen_commands[cmd] = option

        # Collapse parameterized twins: when both "-threads" and "-threads 4"
        # survive, keep only the parameterized form — it is strictly more useful.
        parameterized_bases = {cmd.split()[0] for cmd in seen_commands if ' ' in cmd}
        unique_options = [
            opt for cmd, opt in seen_commands.items()
            if ' ' in cmd or cmd not in parameterized_bases
        ]
        
        if self.debug:
            print(f"  🔍 Deduplication: {len(all_options)} → {len(unique_options)} options")
        
        return unique_options
    
    def track_validation_stats(self, option: str, is_valid: bool, reason: str):
        """Track validation statistics for monitoring"""
        self.validation_stats['total_options_processed'] += 1
        
        if is_valid:
            self.validation_stats['options_accepted'] += 1
        else:
            self.validation_stats['options_rejected'] += 1
            self.validation_stats['rejection_reasons'][reason] = \
                self.validation_stats['rejection_reasons'].get(reason, 0) + 1
    
    def print_validation_statistics(self):
        """Print validation statistics at end of run"""
        stats = self.validation_stats
        total = stats['total_options_processed']
        
        if total == 0:
            return
        
        print(f"\n📊 VALIDATION STATISTICS:")
        print(f"   Total options processed: {total}")
        print(f"   Accepted: {stats['options_accepted']} ({stats['options_accepted']/total*100:.1f}%)")
        print(f"   Rejected: {stats['options_rejected']} ({stats['options_rejected']/total*100:.1f}%)")
        
        if stats['rejection_reasons']:
            print(f"   Top rejection reasons:")
            sorted_reasons = sorted(stats['rejection_reasons'].items(), key=lambda x: x[1], reverse=True)
            for reason, count in sorted_reasons[:5]:
                print(f"     {reason}: {count}")

    def print_scraper_diagnostics(self, stats):
        """Print comprehensive diagnostics specifically for the generic options issue"""
        print("\n" + "="*70)
        print("📊 SCRAPER DIAGNOSTICS - GENERIC OPTIONS ISSUE ANALYSIS")
        print("="*70)
        
        print(f"Total games processed: {stats['total_games_processed']}")
        print(f"Games with any options: {stats['games_with_any_options']}")
        print(f"Games with only generic options: {stats['games_with_only_generic_options']}")
        print(f"Games skipped (existing): {stats['games_skipped_existing']}")
        
        if stats['total_games_processed'] > 0:
            success_rate = (stats['games_with_any_options'] / stats['total_games_processed']) * 100
            print(f"Overall success rate: {success_rate:.1f}%")
            
            if stats['games_with_any_options'] > 0:
                generic_rate = (stats['games_with_only_generic_options'] / stats['games_with_any_options']) * 100
                print(f"Generic-only rate: {generic_rate:.1f}%", end="")
                if generic_rate > 50:
                    print(" 🚨 HIGH - Bug likely still present!")
                elif generic_rate > 25:
                    print(" ⚠️ MODERATE - Some issues remain")
                elif generic_rate > 10:
                    print(" ⚠️ LOW - Minor issues")
                else:
                    print(" ✅ GOOD - Diagnostic success")
        
        print("\nScraper Success Rates:")
        for scraper, data in stats['scraper_success_rates'].items():
            if data['attempts'] > 0:
                rate = (data['success'] / data['attempts']) * 100
                status = "✅" if rate > 50 else "⚠️" if rate > 20 else "❌"
                print(f"  {scraper:<15}: {rate:5.1f}% ({data['success']}/{data['attempts']}) {status}")
            else:
                print(f"  {scraper:<15}: No attempts")
        
        print("\n💡 Recommendations:")
        if stats['games_with_only_generic_options'] > stats['games_with_any_options'] * 0.5:
            print("  🚨 HIGH generic-only rate suggests the bug persists")
            print("  → Check if game_specific.py was properly replaced")
            print("  → Verify engine detection is working")
        elif stats['games_with_only_generic_options'] > 0:
            print("  ⚠️ Some games still have only generic options")
            print("  → This is normal for games with unrecognized engines")
        else:
            print("  ✅ No generic-only games found.")
        
        for scraper, data in stats['scraper_success_rates'].items():
            if data['attempts'] > 0:
                rate = (data['success'] / data['attempts']) * 100
                if rate < 20:
                    print(f"  ⚠️ {scraper} has low success rate ({rate:.1f}%) - investigate")
        
        print("="*70)