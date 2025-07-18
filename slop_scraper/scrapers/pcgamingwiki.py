import re
import time
import os
import requests
from urllib.parse import quote

try:
    # Try relative imports first (when run as module)
    from ..utils.security_config import SecureRequestHandler
except ImportError:
    # Fall back to absolute imports (when run directly)
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.security_config import SecureRequestHandler

def fetch_pcgamingwiki_launch_options(game_title, rate_limit=None, debug=False, test_results=None, 
                                    test_mode=False, rate_limiter=None, session_monitor=None):
    """
    Fetches launch options for a game from PCGamingWiki using the official API.
    It formats the game title according to MediaWiki standards, searches for the game page,
    and extracts launch options from the page content.
    Parameters:
        game_title (str): The title of the game to search for.
        rate_limit (float): Optional rate limit in seconds between requests.
        debug (bool): If True, prints debug information.
        test_results (dict): Optional dictionary to store test results.
        test_mode (bool): If True, runs in test mode without making actual requests.
        rate_limiter (SecureRequestHandler): Optional rate limiter instance.
        session_monitor: Optional session monitor for tracking requests and errors.
    Returns:
        list: A list of launch options found for the game, each option is a dict with
              'command', 'description', and 'source' keys.
    This function uses the official PCGamingWiki API to search for the game page,
    retrieves the page content, and extracts launch options from the wikitext.
    It handles rate limiting and session monitoring if provided.
    If the game is not found, it tries alternative search methods to find similar games.
    If debug mode is enabled, it prints detailed information about the process.
    If test mode is enabled, it updates the test results with the number of options found.
    Note: This is designed to be ethical and respects the PCGamingWiki API usage guidelines
    by using the official API endpoints and adhering to rate limits
    """
    
    # Security validation
    if not game_title or len(game_title) > 200:
        if debug:
            print("⚠️ Invalid game title for PCGamingWiki lookup")
        return []
    
    if rate_limiter:
        rate_limiter.wait_if_needed("scraping", domain="pcgamingwiki.com")
    elif rate_limit:
        time.sleep(rate_limit)
    
    if debug:
        print(f"🔍 PCGamingWiki API: Looking up '{game_title}' using official API")
    
    options = []
    
    try:
        # Method 1: Try to find the game using official Cargo API
        page_name = format_game_title_for_api(game_title)
        
        # Official API endpoint to search for the game
        search_url = "https://www.pcgamingwiki.com/w/api.php"
        search_params = {
            "action": "cargoquery",
            "tables": "Infobox_game",
            "fields": "Infobox_game._pageName=Page,Infobox_game._pageID=PageID",
            "where": f'Infobox_game._pageName="{page_name}"',
            "format": "json",
            "limit": "1"
        }
        
        if debug:
            print(f"🔍 PCGamingWiki API: Searching for page: {page_name}")
        
        response = requests.get(search_url, params=search_params, timeout=15)
        
        if session_monitor:
            session_monitor.record_request()
        
        if debug:
            print(f"🔍 PCGamingWiki API: Search response status: {response.status_code}")
        
        if response.status_code == 200:
            search_data = response.json()
            
            if search_data.get("cargoquery") and len(search_data["cargoquery"]) > 0:
                # Found the game page
                page_info = search_data["cargoquery"][0]["title"]
                page_id = page_info.get("PageID")
                found_page_name = page_info.get("Page")
                
                if debug:
                    print(f"🔍 PCGamingWiki API: Found page '{found_page_name}' (ID: {page_id})")
                
                # Method 2: Get the page content using official API
                if page_id:
                    content_options = get_launch_options_from_page_api(page_id, debug=debug)
                    options.extend(content_options)
                    
                    if debug:
                        print(f"🔍 PCGamingWiki API: Extracted {len(content_options)} options from page content")
            
            else:
                if debug:
                    print(f"🔍 PCGamingWiki API: Game '{game_title}' not found, trying alternatives...")
                
                # Try alternative search methods
                alt_options = try_alternative_search(game_title, debug=debug)
                options.extend(alt_options)
        
        else:
            if debug:
                print(f"🔍 PCGamingWiki API: Search failed with status {response.status_code}")
        
        # Update test statistics
        if test_mode and test_results:
            source = 'PCGamingWiki'
            if source not in test_results['options_by_source']:
                test_results['options_by_source'][source] = 0
            test_results['options_by_source'][source] += len(options)
        
        if debug:
            print(f"🔍 PCGamingWiki API: Final result: {len(options)} options found")
            for opt in options[:3]:
                print(f"🔍 PCGamingWiki API:   {opt['command']}: {opt['description'][:40]}...")
        
        return options
        
    except Exception as e:
        if session_monitor:
            session_monitor.record_error()
        
        if debug:
            print(f"🔍 PCGamingWiki API: Error for '{game_title}': {e}")
        else:
            print(f"🔍 PCGamingWiki API: Error for '{game_title}': {e}")
        
        return []

def format_game_title_for_api(title):
    """Format game title for PCGamingWiki API search"""
    # PCGamingWiki uses MediaWiki naming conventions
    formatted = title.strip()
    
    # Replace spaces with underscores (MediaWiki standard)
    formatted = formatted.replace(' ', '_')
    
    # Remove special characters that cause API issues
    formatted = formatted.replace(':', '')
    formatted = formatted.replace('&', 'and')
    formatted = formatted.replace("'", '')
    formatted = formatted.replace('"', '')
    
    # Capitalize first letter (MediaWiki standard)
    if formatted:
        formatted = formatted[0].upper() + formatted[1:] if len(formatted) > 1 else formatted.upper()
    
    return formatted

def get_launch_options_from_page_api(page_id, debug=False):
    """Get launch options from a PCGamingWiki page using official API"""
    options = []
    
    try:
        # Get page content using official MediaWiki API
        content_url = "https://www.pcgamingwiki.com/w/api.php"
        content_params = {
            "action": "parse",
            "format": "json",
            "pageid": page_id,
            "prop": "wikitext"
        }
        
        response = requests.get(content_url, params=content_params, timeout=15)
        
        if response.status_code == 200:
            content_data = response.json()
            
            if "parse" in content_data and "wikitext" in content_data["parse"]:
                wikitext = content_data["parse"]["wikitext"]["*"]
                
                if debug:
                    print(f"🔍 PCGamingWiki API: Retrieved {len(wikitext)} characters of wikitext")
                
                # Parse wikitext for launch options
                parsed_options = parse_wikitext_for_launch_options(wikitext, debug=debug)
                options.extend(parsed_options)
    
    except Exception as e:
        if debug:
            print(f"🔍 PCGamingWiki API: Error getting page content: {e}")
    
    return options

def parse_wikitext_for_launch_options(wikitext, debug=False):
    """Parse MediaWiki wikitext for launch options"""
    options = []
    
    # Look for common launch option patterns in wikitext
    launch_option_patterns = [
        r'-\w+[\w\-]*',  # Standard command line options
        r'\+\w+[\w\-]*', # Plus-style options  
        r'/\w+[\w\-]*'   # Slash-style options
    ]
    
    # Split wikitext into lines for processing
    lines = wikitext.split('\n')
    
    for i, line in enumerate(lines):
        # Look for sections that might contain launch options
        if any(keyword in line.lower() for keyword in 
               ['command', 'launch', 'option', 'parameter', 'argument']):
            
            # Check this line and surrounding lines for launch options
            context_start = max(0, i - 2)
            context_end = min(len(lines), i + 5)
            context_lines = lines[context_start:context_end]
            context_text = '\n'.join(context_lines)
            
            # Extract launch options from context
            for pattern in launch_option_patterns:
                matches = re.findall(pattern, context_text)
                
                for match in matches:
                    if len(match) <= 50:  # Reasonable length check
                        # Get description from surrounding context
                        desc = extract_description_from_context(match, context_text)
                        
                        options.append({
                            'command': match,
                            'description': desc[:300],  # Limit description length
                            'source': 'PCGamingWiki'
                        })
                        
                        if debug and len(options) <= 5:
                            print(f"🔍 PCGamingWiki API: Found option: {match}")
    
    # Remove duplicates
    seen_commands = set()
    unique_options = []
    for option in options:
        if option['command'] not in seen_commands:
            seen_commands.add(option['command'])
            unique_options.append(option)
    
    return unique_options[:15]  # Limit total options

def extract_description_from_context(command, context):
    """Extract description for a command from its context"""
    lines = context.split('\n')
    
    for line in lines:
        if command in line:
            # Clean up the line and use as description
            desc = line.strip()
            # Remove wiki markup
            desc = re.sub(r'\{\{[^}]*\}\}', '', desc)  # Remove templates
            desc = re.sub(r'\[\[[^]]*\]\]', '', desc)  # Remove links
            desc = re.sub(r"'''?([^']*?)'''?", r'\1', desc)  # Remove bold/italic
            desc = desc.strip()
            
            if desc and len(desc) > len(command):
                return desc
    
    return f"Launch option found in PCGamingWiki"

def try_alternative_search(game_title, debug=False):
    """Try alternative search methods when exact match fails"""
    options = []
    
    # Try searching without special characters
    simplified_title = re.sub(r'[^\w\s]', '', game_title)
    
    if simplified_title != game_title:
        if debug:
            print(f"🔍 PCGamingWiki API: Trying simplified title: {simplified_title}")
        
        # Use the general search API
        search_url = "https://www.pcgamingwiki.com/w/api.php"
        search_params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": simplified_title,
            "srlimit": "3"
        }
        
        try:
            response = requests.get(search_url, params=search_params, timeout=10)
            
            if response.status_code == 200:
                search_data = response.json()
                
                if "query" in search_data and "search" in search_data["query"]:
                    search_results = search_data["query"]["search"]
                    
                    # Try the first search result
                    if search_results:
                        first_result = search_results[0]
                        page_id = first_result.get("pageid")
                        
                        if page_id and debug:
                            print(f"🔍 PCGamingWiki API: Found alternative page ID: {page_id}")
                        
                        if page_id:
                            alt_options = get_launch_options_from_page_api(page_id, debug=debug)
                            options.extend(alt_options)
        
        except Exception as e:
            if debug:
                print(f"🔍 PCGamingWiki API: Alternative search error: {e}")
    
    return options