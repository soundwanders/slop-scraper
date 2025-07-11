import re
import time
import os
from bs4 import BeautifulSoup
from urllib.parse import quote

try:
    # Try relative imports first (when run as module)
    from ..utils.security_config import SecureRequestHandler
except ImportError:
    # Fall back to absolute imports (when run directly)
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.security_config import SecureRequestHandler

def format_game_title_for_reddit(title):
    """Format game title for Reddit subreddit search with security validation"""
    if not title or len(title) > 200:
        return None
    
    # Remove special characters and normalize
    formatted = re.sub(r'[^\w\s]', '', title)
    formatted = formatted.strip()
    
    # Remove common suffixes
    suffixes_to_remove = [
        'Definitive Edition', 'Enhanced Edition', 'Special Edition',
        'Game of the Year', 'GOTY', 'Remastered', 'Redux'
    ]
    
    for suffix in suffixes_to_remove:
        formatted = re.sub(rf'\s*{suffix}\s*$', '', formatted, flags=re.IGNORECASE)
    
    # Convert to potential subreddit name (no spaces, camelCase or lowercase)
    subreddit_name = formatted.replace(' ', '')
    
    return subreddit_name

def fetch_reddit_wiki_launch_options(game_title, app_id=None, rate_limit=None, debug=False,
                                   test_results=None, test_mode=False, rate_limiter=None,
                                   session_monitor=None):
    """Fetch launch options from Reddit gaming wikis with security controls"""
    
    # Security validation
    if not game_title or len(game_title) > 200:
        print(f"⚠️ Invalid game title for Reddit wiki: {game_title}")
        return []
    
    if rate_limiter:
        rate_limiter.wait_if_needed("scraping")
    elif rate_limit:
        time.sleep(rate_limit)
    
    options = []
    
    # Generate potential subreddit names
    base_name = format_game_title_for_reddit(game_title)
    if not base_name:
        return []
    
    # Common gaming subreddit patterns
    potential_subreddits = [
        base_name.lower(),                    # lowercase version
        base_name,                             # original case
        f"{base_name.lower()}game",           # with 'game' suffix
        f"{base_name.lower()}gaming",         # with 'gaming' suffix
        re.sub(r'(\d+)$', r'_\1', base_name) # number separated by underscore
    ]
    
    # Remove duplicates while preserving order
    seen = set()
    potential_subreddits = [x for x in potential_subreddits if not (x in seen or seen.add(x))]
    
    if debug:
        print(f"🔒 Searching Reddit wikis for: {potential_subreddits[:3]}")
    
    # Try each potential subreddit (limit to 3 for performance)
    for subreddit in potential_subreddits[:3]:
        try:
            # Check if subreddit exists and has a wiki
            wiki_url = f"https://www.reddit.com/r/{subreddit}/wiki/index.json"
            
            if rate_limiter:
                rate_limiter.wait_if_needed("scraping")
            elif rate_limit:
                time.sleep(rate_limit)
            
            # Add Reddit API headers
            headers = {
                'User-Agent': 'SlopScraper/1.0 (Educational Tool)',
                'Accept': 'application/json'
            }
            
            # Try to access wiki index
            response = SecureRequestHandler.make_secure_request(
                wiki_url, timeout=10, max_size_mb=2
            )
            
            if session_monitor:
                session_monitor.record_request()
            
            if response.status_code == 200:
                # Found a wiki, now look for relevant pages
                wiki_pages = [
                    'config', 'configuration', 'launch_options', 'launchoptions',
                    'performance', 'optimization', 'settings', 'tweaks',
                    'guides/performance', 'guides/optimization'
                ]
                
                for page in wiki_pages:
                    page_url = f"https://www.reddit.com/r/{subreddit}/wiki/{page}.json"
                    
                    if rate_limiter:
                        rate_limiter.wait_if_needed("scraping")
                    elif rate_limit:
                        time.sleep(rate_limit)
                    
                    try:
                        page_response = SecureRequestHandler.make_secure_request(
                            page_url, timeout=10, max_size_mb=1
                        )
                        
                        if session_monitor:
                            session_monitor.record_request()
                        
                        if page_response.status_code == 200:
                            wiki_data = page_response.json()
                            
                            if 'data' in wiki_data and 'content_md' in wiki_data['data']:
                                content = wiki_data['data']['content_md']
                                
                                # Security: Limit content processing
                                if len(content) > 50000:
                                    content = content[:50000]
                                
                                # Parse markdown for launch options
                                launch_option_sections = re.finditer(
                                    r'(?:launch|command|startup)\s*(?:options?|parameters?|arguments?|flags?)[:\s]*\n+(.*?)(?:\n\n|\Z)',
                                    content, re.IGNORECASE | re.DOTALL
                                )
                                
                                for section in launch_option_sections:
                                    section_text = section.group(1)
                                    
                                    # Look for command line options in various formats
                                    # Format 1: `-option` or `--option` in backticks
                                    code_options = re.finditer(r'`([+-]{1,2}[\w\-]+(?:=[^\s`]+)?)`', section_text)
                                    for match in code_options:
                                        cmd = match.group(1)
                                        
                                        # Find description (usually follows the option)
                                        desc_match = re.search(
                                            rf'{re.escape(match.group(0))}\s*[-–—:]*\s*([^`\n]+)',
                                            section_text
                                        )
                                        desc = desc_match.group(1).strip() if desc_match else "No description available"
                                        
                                        if len(cmd) <= 100 and len(desc) <= 500:
                                            options.append({
                                                'command': cmd,
                                                'description': desc[:500],
                                                'source': 'Reddit Wiki'
                                            })
                                    
                                    # Format 2: Tables with options
                                    table_matches = re.finditer(
                                        r'\|?\s*([+-]{1,2}[\w\-]+(?:=[^\s|]+)?)\s*\|?\s*([^|\n]+)',
                                        section_text
                                    )
                                    for match in table_matches:
                                        cmd = match.group(1).strip()
                                        desc = match.group(2).strip()
                                        
                                        # Validate command format
                                        if re.match(r'^[+-]{1,2}[\w\-]+(=.*)?$', cmd):
                                            if len(cmd) <= 100 and len(desc) <= 500:
                                                options.append({
                                                    'command': cmd,
                                                    'description': desc[:500],
                                                    'source': 'Reddit Wiki'
                                                })
                                
                                # Look for Steam-specific launch options
                                steam_section = re.search(
                                    r'steam\s*launch\s*options?[:\s]*\n+(.*?)(?:\n\n|\Z)',
                                    content, re.IGNORECASE | re.DOTALL
                                )
                                
                                if steam_section:
                                    steam_text = steam_section.group(1)
                                    
                                    # Common Steam launch option patterns
                                    steam_options = re.finditer(
                                        r'([+-]{1,2}[\w\-]+(?:=[^\s]+)?)\s*[-–—:]*\s*([^\n]+)',
                                        steam_text
                                    )
                                    
                                    for match in steam_options:
                                        cmd = match.group(1).strip()
                                        desc = match.group(2).strip()
                                        
                                        if re.match(r'^[+-]{1,2}[\w\-]+(=.*)?$', cmd):
                                            if len(cmd) <= 100 and len(desc) <= 500:
                                                options.append({
                                                    'command': cmd,
                                                    'description': f"Reddit community recommendation: {desc[:400]}",
                                                    'source': 'Reddit Wiki'
                                                })
                                
                                # If we found options, no need to check other wiki pages
                                if options:
                                    break
                                    
                    except Exception as page_e:
                        if debug:
                            print(f"🔒 Could not access wiki page {page}: {page_e}")
                        continue
                
                # If we found options from this subreddit, no need to check others
                if options:
                    break
                    
        except Exception as e:
            if debug:
                print(f"🔒 Could not access r/{subreddit}: {e}")
            continue
    
    # If no specific options found, check general PC gaming wikis
    if not options and rate_limiter:
        general_wikis = [
            ('pcgaming', 'launch_options'),
            ('pcmasterrace', 'optimization'),
            ('linux_gaming', 'launch_options')
        ]
        
        for subreddit, wiki_page in general_wikis[:2]:  # Limit to 2 for performance
            try:
                if rate_limiter:
                    rate_limiter.wait_if_needed("scraping")
                elif rate_limit:
                    time.sleep(rate_limit)
                
                url = f"https://www.reddit.com/r/{subreddit}/wiki/{wiki_page}.json"
                response = SecureRequestHandler.make_secure_request(url, timeout=10, max_size_mb=1)
                
                if session_monitor:
                    session_monitor.record_request()
                
                if response.status_code == 200:
                    wiki_data = response.json()
                    if 'data' in wiki_data and 'content_md' in wiki_data['data']:
                        content = wiki_data['data']['content_md']
                        
                        # Look for game-specific section
                        game_section_pattern = re.escape(game_title[:20])  # First 20 chars
                        game_section = re.search(
                            rf'{game_section_pattern}.*?\n+(.*?)(?:\n\n|\Z)',
                            content, re.IGNORECASE | re.DOTALL
                        )
                        
                        if game_section:
                            # Extract options from this section
                            section_text = game_section.group(1)
                            option_matches = re.finditer(
                                r'([+-]{1,2}[\w\-]+(?:=[^\s]+)?)\s*[-–—:]*\s*([^\n]+)',
                                section_text
                            )
                            
                            for match in option_matches:
                                cmd = match.group(1).strip()
                                desc = match.group(2).strip()
                                
                                if re.match(r'^[+-]{1,2}[\w\-]+(=.*)?$', cmd):
                                    if len(cmd) <= 100 and len(desc) <= 500:
                                        options.append({
                                            'command': cmd,
                                            'description': desc[:500],
                                            'source': 'Reddit Wiki'
                                        })
                            
                            if options:
                                break
                                
            except Exception as e:
                if debug:
                    print(f"🔒 Error checking r/{subreddit}: {e}")
                continue
    
    # Deduplicate options
    seen_commands = set()
    unique_options = []
    for option in options:
        cmd = option['command'].lower()
        if cmd not in seen_commands and len(unique_options) < 25:
            seen_commands.add(cmd)
            unique_options.append(option)
    
    # Update test statistics
    if test_mode and test_results:
        source = 'Reddit Wiki'
        if source not in test_results['options_by_source']:
            test_results['options_by_source'][source] = 0
        test_results['options_by_source'][source] += len(unique_options)
    
    if debug:
        print(f"🔒 Found {len(unique_options)} validated options from Reddit wikis")
    
    return unique_options