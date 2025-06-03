from dotenv import load_dotenv
import os
import time
import json
import requests
import argparse
import signal
import sys
import re
from bs4 import BeautifulSoup
from supabase import create_client
from tqdm import tqdm
from urllib.parse import quote

load_dotenv()

def get_script_dir():
    """Get directory where this script (slop-scraper) is located"""
    script_path = os.path.dirname (os.path.abspath(__file__))
    return script_path

# If env not found, try parent directory (root)
if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    load_dotenv(os.path.join(project_root, ".env"))

class SlopScraper:
    def __init__(self, test_mode=False, cache_file='appdetails_cache.json', rate_limit=None, force_refresh=False, max_games=5, output_dir="./test-output", debug=False):
        self.test_mode = test_mode
        self.force_refresh = force_refresh
        self.rate_limit = rate_limit
        self.cache_file = cache_file
        self.max_games = max_games
        self.output_dir = output_dir
        self.failed_cache = set()
        self.debug = debug
        self.supabase = None
        
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
        
        self.cache = self.load_cache()
        
        # Initialize Supabase connection if not in test mode
        if not self.test_mode:
            self.supabase = self.setup_supabase_connection()
            if self.supabase:
                print("✅ Connected to Supabase successfully")
                # Seed sources if needed
                self.seed_sources()
            else:
                print("Falling back to test mode.")
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
    
    def get_supabase_credentials(self):
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
    
    def setup_supabase_connection(self):
        """Set up connection to Supabase"""
        if self.test_mode:
            return None
            
        url, key = self.get_supabase_credentials()
        
        if not url or not key:
            print("No valid Supabase credentials found.")
            return None
            
        try:
            # Connect to Supabase
            supabase = create_client(url, key)
            
            # Verify database structure
            if self.verify_db_structure(supabase):
                return supabase
            else:
                print("Database structure verification failed.")
                return None
                
        except Exception as e:
            print(f"Error connecting to Supabase: {e}")
            return None
    
    def verify_db_structure(self, supabase):
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
    
    def seed_sources(self):
        """Seed the sources table with common sources if empty"""
        if self.test_mode or not self.supabase:
            return
            
        try:
            # Check if sources table is empty
            result = self.supabase.table("sources").select("count", count="exact").execute()
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
                    self.supabase.table("sources").insert(source).execute()
                
                print(f"✅ Added {len(sources)} sources to the database.")
            else:
                print("✅ Sources table already populated.")
        except Exception as e:
            print(f"⚠️ Error seeding sources: {e}")

    def test_database_connection(self):
        """Test database connection and return status"""
        if self.test_mode:
            print("Running in test mode, database connection not required")
            return True
            
        if not self.supabase:
            print("Database connection not initialized")
            reconnect = input("Would you like to try reconnecting? (y/n): ").lower() == 'y'
            if reconnect:
                self.supabase = self.setup_supabase_connection()
                return self.supabase is not None
            return False
            
        try:
            # Simple query to test connection
            result = self.supabase.table("games").select("count", count="exact").limit(1).execute()
            print("✅ Database connection test successful")
            return True
        except Exception as e:
            print(f"⚠️ Database connection test failed: {e}")
            return False

    def signal_handler(self, sig, frame):
        """Handle shutdown signals gracefully"""
        print("\n\nGracefully shutting down...")
        print("Saving cache and collected data...")
        # Save cache 
        self.save_cache()
        
        # Save test results if in test mode
        if self.test_mode:
            self.save_test_results()
            
        print("Cleanup complete. Exiting.")
        sys.exit(0)

    def load_cache(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                print("⚠️ Cache file is corrupt. Starting fresh.")
                return {}
            except Exception as e:
                print(f"⚠️ Error loading cache: {e}")
                return {}
        return {}

    def save_cache(self):
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f, indent=2)
            print(f"✅ Cache saved to {self.cache_file}")
        except Exception as e:
            print(f"⚠️ Error saving cache: {e}")

    def get_steam_game_list(self, limit=100):
        print(f"Fetching game list (force_refresh={self.force_refresh})...")
        print(f"Debug: Attempting to fetch up to {limit} games")

        if self.test_mode and limit <= 10:
            return [
                {"appid": 570, "name": "Dota 2"},
                {"appid": 730, "name": "Counter-Strike 2"},
                {"appid": 264710, "name": "Subnautica"},
                {"appid": 377840, "name": "Final Fantasy IX"},
                {"appid": 1868140, "name": "Dave the Diver"},
            ][:limit]

        url = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"
        try:
            response = requests.get(url)
            response.raise_for_status()
            all_apps = response.json()['applist']['apps']
            print(f"Fetched {len(all_apps)} total apps")

            # Blocklist of terms to exclude
            blocklist_terms = [
                'dlc', 'soundtrack', 'beta', 'demo', 'test', 'adult', 'hentai', 'xxx', 'mature', 'expansion', 'tool', 'software'
            ]

            # Regex patterns for filtering unwanted games
            blocklist_pattern = re.compile(r'(?i)(' + '|'.join(re.escape(term) for term in blocklist_terms) + ')')
            non_latin_pattern = re.compile(r'[^\x00-\x7F]')
            only_numeric_special = re.compile(r'^[0-9\s\-_+=.,!@#$%^&*()\[\]{}|\\/<>?;:\'"`~]*$')

            # Known game engines to keep
            known_engines = ['unreal', 'unity', 'godot', 'source', 'cryengine', 'frostbite', 'id tech']

            filtered_games = []

            # Use tqdm for processing apps
            with tqdm(total=min(limit * 3, len(all_apps)), desc="Filtering games") as pbar:
                for app in all_apps:
                    if len(filtered_games) >= limit:
                        break

                    app_id = str(app['appid'])
                    name = app['name']
                    pbar.update(1)

                    # Skip invalid or unwanted entries based on blocklist
                    if not name or blocklist_pattern.search(name) or non_latin_pattern.search(name) or only_numeric_special.match(name):
                        continue

                    # Check if the game is using a known engine, if required
                    if not any(engine in name.lower() for engine in known_engines):
                        continue

                    store_data = None
                    if not self.force_refresh and app_id in self.cache:
                        store_data = self.cache[app_id]
                    else:
                        # Fetch detailed data from store if not cached or forced refresh
                        store_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=us&l=en"
                        try:
                            store_res = requests.get(store_url, timeout=5)
                            store_res.raise_for_status()
                            raw = store_res.json()
                            store_data = raw.get(app_id, {}).get("data", {})

                            if store_data:
                                self.cache[app_id] = store_data
                            else:
                                pbar.write(f"⚠️ No valid data for app_id {app_id}. Skipping.")
                                continue
                            time.sleep(0.2)
                        except Exception as e:
                            pbar.write(f"⚠️ Error fetching data for app_id {app_id}: {e}. Skipping.")
                            continue

                    # Validate store_data before proceeding
                    if not store_data or not isinstance(store_data, dict):
                        pbar.write(f"⚠️ Invalid or missing data for app_id {app_id}. Skipping.")
                        continue

                    # Additional validation checks
                    if store_data.get("type") != "game":
                        pbar.write(f"⚠️ app_id {app_id} is not a game. Skipping.")
                        continue
                    if store_data.get("release_date", {}).get("coming_soon", False):
                        pbar.write(f"⚠️ app_id {app_id} is marked as 'coming soon'. Skipping.")
                        continue
                    if store_data.get("is_free", False) and "demo" in store_data.get("name", "").lower():
                        pbar.write(f"⚠️ app_id {app_id} is a demo. Skipping.")
                        continue

                    # Add the game to the filtered list if it passes all checks
                    filtered_games.append({
                        "appid": int(app_id),
                        "name": store_data.get("name", name),
                        "developer": store_data.get("developers", [""])[0],
                        "release_date": store_data.get("release_date", {}).get("date", ""),
                        "engine": store_data.get("engine", "Unknown")
                    })

                    pbar.write(f"✔️ Added: {name}")

            self.save_cache()
            print(f"✅ Final game count: {len(filtered_games)}")
            return filtered_games

        except Exception as e:
            print(f"Error fetching game list: {e}")
            return []

    def format_game_title_for_wiki(self, title):
        """Format game title for PCGamingWiki URL properly"""
        # Replace common special characters
        formatted = title.replace(' ', '_')
        formatted = formatted.replace(':', '')
        formatted = formatted.replace('&', 'and')
        formatted = formatted.replace("'", '')
        formatted = formatted.replace('-', '_')
        # URL encode the result
        return quote(formatted)
    
    def fetch_pcgamingwiki_launch_options(self, game_title):
        """Fetch launch options from PCGamingWiki"""
        # Format game title for URL
        formatted_title = self.format_game_title_for_wiki(game_title)
        url = f"https://www.pcgamingwiki.com/wiki/{formatted_title}"
        
        if self.debug:
            print(f"Fetching PCGamingWiki data from: {url}")
            
        # Add a delay for rate limiting
        if self.rate_limit:
            time.sleep(self.rate_limit)
        
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Try to find more section headers that could contain launch options
                potential_section_ids = [
                    "Command_line_arguments", 
                    "Launch_options", 
                    "Launch_commands",
                    "Parameters", 
                    "Launch_parameters",
                    "Command-line_arguments",
                    "Command_line_parameters",
                    "Steam_launch_options"
                ]
                
                options = []
                
                # Method 1: Find tables in relevant sections
                for section_id in potential_section_ids:
                    section = soup.find(id=section_id)
                    if section:
                        if self.debug:
                            print(f"Found section: {section_id}")
                        
                        # Navigate up to the heading element
                        if section.parent and section.parent.name.startswith('h'):
                            heading = section.parent
                            
                            # Find the next table after this heading
                            table = heading.find_next('table')
                            if table and 'wikitable' in table.get('class', []):
                                if self.debug:
                                    print(f"Found table in section {section_id}")
                                
                                rows = table.find_all('tr')[1:]  # Skip header row
                                for row in rows:
                                    cells = row.find_all('td')
                                    if len(cells) >= 2:
                                        command = cells[0].get_text(strip=True)
                                        description = cells[1].get_text(strip=True)
                                        if command:  # Only add non-empty commands
                                            options.append({
                                                'command': command,
                                                'description': description,
                                                'source': 'PCGamingWiki'
                                            })
                
                # Method 2: Look for lists in relevant sections
                if not options:
                    for section_id in potential_section_ids:
                        section = soup.find(id=section_id)
                        if section and section.parent:
                            heading = section.parent
                            
                            # Find lists (ul/ol) after the heading
                            list_element = heading.find_next(['ul', 'ol'])
                            if list_element:
                                list_items = list_element.find_all('li')
                                for item in list_items:
                                    text = item.get_text(strip=True)
                                    # Try to separate command from description
                                    if ':' in text:
                                        parts = text.split(':', 1)
                                        cmd = parts[0].strip()
                                        desc = parts[1].strip()
                                    elif ' - ' in text:
                                        parts = text.split(' - ', 1)
                                        cmd = parts[0].strip()
                                        desc = parts[1].strip()
                                    elif ' – ' in text:
                                        parts = text.split(' – ', 1)
                                        cmd = parts[0].strip()
                                        desc = parts[1].strip()
                                    else:
                                        # If we can't split, look for patterns like -command or --command
                                        match = re.search(r'(-{1,2}\w+)', text)
                                        if match:
                                            cmd = match.group(1)
                                            desc = text.replace(cmd, '').strip()
                                        else:
                                            cmd = text
                                            desc = "No description available"
                                    
                                    if cmd and cmd.strip():  # Only add non-empty commands
                                        options.append({
                                            'command': cmd,
                                            'description': desc,
                                            'source': 'PCGamingWiki'
                                        })
                
                # Method 3: Look for code blocks or pre elements
                if not options:
                    code_blocks = soup.find_all(['code', 'pre'])
                    for block in code_blocks:
                        text = block.get_text(strip=True)
                        # Check if this looks like a command line argument
                        if text.startswith('-') or text.startswith('/') or text.startswith('+'):
                            parent_text = block.parent.get_text(strip=True) if block.parent else ""
                            if len(parent_text) > len(text):
                                desc = parent_text.replace(text, '', 1).strip()
                            else:
                                desc = "No description available"
                            
                            options.append({
                                'command': text,
                                'description': desc,
                                'source': 'PCGamingWiki'
                            })
                
                # Method 4: Look for text with typical command patterns
                if not options:
                    potential_commands = []
                    for tag in soup.find_all(['p', 'li']):
                        text = tag.get_text()
                        # Look for patterns like -command, --long-option, +option, /option
                        matches = re.finditer(r'(?:^|\s)(-{1,2}[\w\-]+|\+[\w\-]+|\/[\w\-]+)(?:\s|$)', text)
                        for match in matches:
                            cmd = match.group(1)
                            potential_commands.append({
                                'command': cmd,
                                'description': text,
                                'source': 'PCGamingWiki'
                            })
                    
                    # De-duplicate by command
                    seen_commands = set()
                    for cmd in potential_commands:
                        if cmd['command'] not in seen_commands:
                            seen_commands.add(cmd['command'])
                            options.append(cmd)
                
                # Update test statistics
                if self.test_mode:
                    source = 'PCGamingWiki'
                    if source not in self.test_results['options_by_source']:
                        self.test_results['options_by_source'][source] = 0
                    self.test_results['options_by_source'][source] += len(options)
                
                if self.debug:
                    print(f"Found {len(options)} options from PCGamingWiki")
                
                return options
            elif response.status_code == 404:
                if self.debug:
                    print(f"PCGamingWiki page not found for '{game_title}'")
                # Try alternative title formats
                alt_title = game_title.split(':')[0] if ':' in game_title else None
                if alt_title and alt_title != game_title:
                    if self.debug:
                        print(f"Trying alternate title: {alt_title}")
                    return self.fetch_pcgamingwiki_launch_options(alt_title)
                return []
            else:
                if self.debug:
                    print(f"PCGamingWiki returned status code {response.status_code}")
                return []
        except Exception as e:
            print(f"    Error fetching from PCGamingWiki: {e}")
        
        return []
    
    def fetch_steam_community_launch_options(self, game_title, app_id):
        """Fetch launch options from Steam Community guides"""
        # Search for guides containing "launch options" for this game
        url = f"https://steamcommunity.com/app/{app_id}/guides/"
        
        if self.debug:
            print(f"Fetching Steam Community guides from: {url}")
        
        # Add a delay for rate limiting
        if self.rate_limit:
            time.sleep(self.rate_limit)
        
        options = []
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                guides = soup.find_all('div', class_='guide_item')
                
                relevant_guides = []
                for guide in guides:
                    title_elem = guide.find('div', class_='guide_title')
                    if title_elem:
                        title = title_elem.text.lower()
                        if any(keyword in title for keyword in ['launch', 'command', 'option', 'parameter', 'argument', 'fps', 'performance']):
                            link_elem = guide.find('a')
                            if link_elem and 'href' in link_elem.attrs:
                                relevant_guides.append({
                                    'title': title_elem.text,
                                    'url': link_elem['href']
                                })
                
                if self.debug:
                    print(f"Found {len(relevant_guides)} relevant guides")
                
                # Process the most relevant guides (limit to 3 to avoid overloading)
                for guide in relevant_guides[:3]:
                    try:
                        if self.debug:
                            print(f"Processing guide: {guide['title']}")
                        
                        # Add a delay between guide requests
                        if self.rate_limit:
                            time.sleep(self.rate_limit)
                        
                        guide_response = requests.get(guide['url'], timeout=15)
                        if guide_response.status_code == 200:
                            guide_soup = BeautifulSoup(guide_response.text, 'html.parser')
                            guide_content = guide_soup.find('div', class_='guide_body')
                            
                            if guide_content:
                                # Method 1: Look for code blocks or pre elements (common in guides)
                                code_blocks = guide_content.find_all(['code', 'pre'])
                                for block in code_blocks:
                                    text = block.get_text(strip=True)
                                    # Check if this looks like launch options text
                                    if any(symbol in text for symbol in ['-', '+', '/']):
                                        # Try to identify individual options
                                        option_matches = re.finditer(r'(?:^|\s)(-{1,2}[\w\-]+|\+[\w\-]+|\/[\w\-]+)(?:\s|$)', text)
                                        for match in option_matches:
                                            cmd = match.group(1)
                                            # Find surrounding text for context
                                            parent_text = block.parent.get_text(strip=True) if block.parent else ""
                                            # Get the closest paragraph that might describe this command
                                            prev_p = block.find_previous('p')
                                            next_p = block.find_next('p')
                                            if prev_p:
                                                desc = prev_p.get_text(strip=True)
                                            elif next_p:
                                                desc = next_p.get_text(strip=True)
                                            else:
                                                desc = f"Found in guide: {guide['title']}"
                                            
                                            options.append({
                                                'command': cmd,
                                                'description': desc[:200] + "..." if len(desc) > 200 else desc,
                                                'source': 'Steam Community'
                                            })
                                
                                # Method 2: Look for paragraphs with launch options patterns
                                if not any(opt['source'] == 'Steam Community' for opt in options):
                                    for p in guide_content.find_all(['p', 'li']):
                                        text = p.get_text(strip=True)
                                        if 'launch' in text.lower() and any(symbol in text for symbol in ['-', '+', '/']):
                                            # Extract commands that look like options
                                            option_matches = re.finditer(r'(?:^|\s)(-{1,2}[\w\-]+|\+[\w\-]+|\/[\w\-]+)(?:\s|$)', text)
                                            for match in option_matches:
                                                cmd = match.group(1)
                                                options.append({
                                                    'command': cmd,
                                                    'description': text[:200] + "..." if len(text) > 200 else text,
                                                    'source': 'Steam Community'
                                                })
                            
                    except Exception as guide_e:
                        print(f"    Error processing guide {guide['url']}: {guide_e}")
                        continue
                
                # If no specific options found but guides exist, add guide references
                if not options and relevant_guides:
                    for guide in relevant_guides[:3]:
                        options.append({
                            'command': f"See guide: {guide['title']}",
                            'description': f"This guide may contain launch options: {guide['url']}",
                            'source': 'Steam Community'
                        })
                
                # Update test statistics
                if self.test_mode:
                    source = 'Steam Community'
                    if source not in self.test_results['options_by_source']:
                        self.test_results['options_by_source'][source] = 0
                    self.test_results['options_by_source'][source] += len(options)
                
                if self.debug:
                    print(f"Found {len(options)} options from Steam Community")
                
                return options
        except Exception as e:
            print(f"    Error fetching from Steam Community: {e}")
        
        return []
    
    def fetch_steam_launch_options_from_db(self, app_id):
        """Fetch known launch options from our database"""
        if self.test_mode:
            return []
            
        try:
            # Query the launch_options table for this app_id
            result = self.supabase.table("launch_options").select("*").eq("app_id", app_id).execute()
            options = []
            
            if hasattr(result, 'data'):
                for item in result.data:
                    options.append({
                        'command': item['command'],
                        'description': item['description'],
                        'source': item['source'],
                        'verified': item.get('verified', False)
                    })
            
            print(f"✅ Found {len(options)} existing options in database for app_id {app_id}")
            return options
        except Exception as e:
            print(f"⚠️ Database query error: {e}")
            return []
    
    def fetch_game_specific_options(self, title, app_id):
        """Fetch game-specific launch options based on common patterns"""
        options = []
        
        # Source engine games often share common options
        source_engine_options = [
            {
                'command': '-novid',
                'description': 'Skip intro videos when starting the game',
                'source': 'Common Source Engine'
            },
            {
                'command': '-console',
                'description': 'Enable developer console',
                'source': 'Common Source Engine'
            },
            {
                'command': '-windowed',
                'description': 'Run the game in windowed mode',
                'source': 'Common Source Engine'
            },
            {
                'command': '-fullscreen',
                'description': 'Run the game in fullscreen mode',
                'source': 'Common Source Engine'
            },
            {
                'command': '-noborder',
                'description': 'Run the game in borderless windowed mode',
                'source': 'Common Source Engine'
            }
        ]
        
        # Unity engine games often share common options
        unity_engine_options = [
            {
                'command': '-screen-width',
                'description': 'Set screen width (e.g., -screen-width 1920)',
                'source': 'Common Unity Engine'
            },
            {
                'command': '-screen-height',
                'description': 'Set screen height (e.g., -screen-height 1080)',
                'source': 'Common Unity Engine'
            },
            {
                'command': '-popupwindow',
                'description': 'Run in borderless windowed mode',
                'source': 'Common Unity Engine'
            },
            {
                'command': '-window-mode',
                'description': 'Set window mode (values: exclusive, windowed, borderless)',
                'source': 'Common Unity Engine'
            }
        ]
        
        # Unreal Engine games often share common options
        unreal_engine_options = [
            {
                'command': '-windowed',
                'description': 'Run the game in windowed mode',
                'source': 'Common Unreal Engine'
            },
            {
                'command': '-fullscreen',
                'description': 'Run the game in fullscreen mode',
                'source': 'Common Unreal Engine'
            },
            {
                'command': '-presets=',
                'description': 'Specify graphics preset (e.g., -presets=high)',
                'source': 'Common Unreal Engine'
            },
            {
                'command': '-dx12',
                'description': 'Force DirectX 12 rendering',
                'source': 'Common Unreal Engine'
            },
            {
                'command': '-dx11',
                'description': 'Force DirectX 11 rendering',
                'source': 'Common Unreal Engine'
            }
        ]
        
        # Check for known games
        lower_title = title.lower()
        
        # Source engine games
        if any(game in lower_title for game in ['counter-strike', 'half-life', 'portal', 'team fortress', 'left 4 dead', 'garry', 'dota']):
            options.extend(source_engine_options)
        
        # Check for Unity games
        elif 'unity' in lower_title or app_id in self.cache and 'unity' in str(self.cache.get(str(app_id), {})).lower():
            options.extend(unity_engine_options)
        
        # Check for Unreal Engine games
        elif 'unreal' in lower_title or app_id in self.cache and 'unreal' in str(self.cache.get(str(app_id), {})).lower():
            options.extend(unreal_engine_options)
        
        # Common launch options
        general_options = [
            {
                'command': '-fps_max',
                'description': 'Limit maximum FPS (e.g., -fps_max 144)',
                'source': 'Common Launch Option'
            },
            {
                'command': '-nojoy',
                'description': 'Disable joystick/controller support',
                'source': 'Common Launch Option'
            },
            {
                'command': '-nosplash',
                'description': 'Skip splash/intro screens',
                'source': 'Common Launch Option'
            }
        ]
        
        options.extend(general_options)
        
        # Update test statistics
        if self.test_mode and options:
            source = 'Game-Specific Knowledge'
            if source not in self.test_results['options_by_source']:
                self.test_results['options_by_source'][source] = 0
            self.test_results['options_by_source'][source] += len(options)
        
        return options
    
    def save_to_database(self, game, options):
        """Save game and launch options to Supabase"""
        if self.test_mode:
            return

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
            res = self.supabase.table("games").upsert(game_data).execute()
            
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
                        option_res = self.supabase.table("launch_options")\
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
                            self.supabase.table("game_launch_options")\
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

    def save_test_results(self):
        """Save test results to JSON file"""
        if not self.test_mode:
            return
            
        try:
            output_file = os.path.join(self.output_dir, "test_results.json")
            with open(output_file, 'w') as f:
                json.dump(self.test_results, f, indent=4)
            
            print(f"\nTest results saved to {output_file}")
            print(f"Games processed: {self.test_results['games_processed']}")
            print(f"Games with options found: {self.test_results['games_with_options']}")
            print(f"Total options found: {self.test_results['total_options_found']}")
            print("Options by source:")
            for source, count in self.test_results['options_by_source'].items():
                print(f"  {source}: {count}")
        except Exception as e:
            print(f"Error saving test results: {e}")
            print("Try running the script with sudo or check directory permissions")
    
    def save_game_results(self, app_id, title, options):
        """Save individual game results to file"""
        if not self.test_mode:
            return
            
        try:
            game_file = os.path.join(self.output_dir, f"game_{app_id}.json")
            with open(game_file, 'w') as f:
                json.dump({
                    'app_id': app_id,
                    'title': title,
                    'options': options
                }, f, indent=4)
        except Exception as e:
            print(f"  Error saving game data: {e}")
    
    def run(self):
        print(f"Running in {'TEST' if self.test_mode else 'PRODUCTION'} mode")
        
        try:
            # Get list of games (limited by max_games)
            games = self.get_steam_game_list(self.max_games)
            
            # Process each game with better progress indication
            with tqdm(games, desc="Processing games", unit="game") as game_pbar:
                for game in game_pbar:
                    app_id = game['appid']
                    title = game['name']
                    
                    # Update progress bar description
                    game_pbar.set_description(f"Processing {title}")
                    
                    # Check if we already have data in database
                    existing_options = [] if self.test_mode else self.fetch_steam_launch_options_from_db(app_id)
                    
                    # If we already have data and not forcing refresh, skip
                    if existing_options and not self.force_refresh:
                        game_pbar.write(f"Skipping {title} - already have {len(existing_options)} options in database")
                        continue
                    
                    # Collect options from different sources
                    all_options = []
                    
                    # Add game-specific options from our knowledge base
                    game_specific_options = self.fetch_game_specific_options(title, app_id)
                    if game_specific_options:
                        all_options.extend(game_specific_options)
                        game_pbar.write(f"  Added {len(game_specific_options)} game-specific options")

                    # Create a small progress bar for sources
                    sources = [
                        ("PCGamingWiki", lambda: self.fetch_pcgamingwiki_launch_options(title)),
                        ("Steam Community", lambda: self.fetch_steam_community_launch_options(title, app_id))
                    ]
                    
                    with tqdm(sources, desc="Checking sources", leave=False) as source_pbar:
                        for source_name, source_func in source_pbar:
                            source_pbar.set_description(f"Checking {source_name}")
                            try:
                                options = source_func()
                                all_options.extend(options)
                                game_pbar.write(f"  Found {len(options)} options on {source_name}")
                            except Exception as e:
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
                        self.save_game_results(app_id, title, unique_options)
                    else:
                        # Save to database in production mode
                        self.save_to_database(game, unique_options)
                    
                    game_pbar.write(f"Found {len(unique_options)} unique launch options for {title}")
                    
                    # Periodically save cache during execution
                    if game['appid'] % 3 == 0:  # Save every 3 games
                        self.save_cache()

            # Save test results summary
            if self.test_mode:
                self.save_test_results()
                
        except Exception as e:
            print(f"\nError during execution: {e}")
            # Save what we have so far
            self.save_cache()
            if self.test_mode:
                self.save_test_results()
            raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Steam Launch Options Scraper')
    parser.add_argument('--test', action='store_true', help='Run in test mode')
    parser.add_argument('--limit', type=int, default=100, help='Maximum number of games to process')
    parser.add_argument('--rate', type=float, default=2.0, help='Rate limit in seconds between requests')
    parser.add_argument('--output', type=str, default='./test-output', help='Output directory for test results')
    parser.add_argument('--absolute-path', action='store_true', help='Use absolute path for output directory')
    parser.add_argument('--force-refresh', action='store_true', help='Force refresh of game data cache')
    parser.add_argument('--test-db', action='store_true', help='Test database connection and exit')
    
    args = parser.parse_args()
    
    # Convert to absolute path if requested
    if args.absolute_path:
        args.output = os.path.abspath(args.output)
        print(f"Using absolute path: {args.output}")
    
    # Initialize scraper
    scraper = SlopScraper(
        rate_limit=args.rate,
        max_games=args.limit,
        test_mode=args.test,
        output_dir=args.output,
        force_refresh=args.force_refresh
    )
    
    # Only while testing the database connection
    if args.test_db:
        success = scraper.test_database_connection()
        sys.exit(0 if success else 1)
    
    try:
        scraper.run()
    except KeyboardInterrupt:
        # shouldn't be reached if signal handling works
        print("\nScript interrupted. Exiting.")
        sys.exit(1)
