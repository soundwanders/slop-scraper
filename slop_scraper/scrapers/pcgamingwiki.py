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
    Now with enhanced validation to prevent HTML artifacts and false positives.
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
                    # Apply strict validation to prevent false positives
                    validated_options = validate_pcgaming_options(content_options, debug=debug)
                    options.extend(validated_options)
                    
                    if debug:
                        print(f"🔍 PCGamingWiki API: Extracted {len(content_options)} raw, {len(validated_options)} validated options")
            
            else:
                if debug:
                    print(f"🔍 PCGamingWiki API: Game '{game_title}' not found, trying alternatives...")
                
                # Try alternative search methods
                alt_options = try_alternative_search(game_title, debug=debug)
                validated_alt_options = validate_pcgaming_options(alt_options, debug=debug)
                options.extend(validated_alt_options)
        
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
            print(f"🔍 PCGamingWiki API: Final result: {len(options)} validated options found")
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

def validate_pcgaming_options(options, debug=False):
    """
    Strict validation for PCGamingWiki options to prevent HTML artifacts and false positives
    """
    validated_options = []
    
    for option in options:
        command = option.get('command', '').strip()
        description = option.get('description', '').strip()
        
        # STRICT validation for command
        if not is_valid_launch_command_strict(command, debug=debug):
            if debug:
                print(f"🔍 PCGamingWiki: REJECTED command '{command}' - failed strict validation")
            continue
        
        # Clean and validate description 
        clean_description = clean_wiki_description(description, debug=debug)
        if not clean_description:
            clean_description = f"Launch option from PCGamingWiki"
        
        validated_options.append({
            'command': command,
            'description': clean_description,
            'source': 'PCGamingWiki'
        })
        
        if debug:
            print(f"🔍 PCGamingWiki: ACCEPTED '{command}' with clean description")
    
    return validated_options

def is_valid_launch_command_strict(command, debug=False):
    """
    EXTREMELY strict validation for launch commands to prevent false positives
    """
    if not command or not isinstance(command, str):
        return False
    
    command = command.strip()
    
    # Length check - reasonable launch options are typically 2-30 characters
    if len(command) < 2 or len(command) > 35:
        if debug:
            print(f"🔍 Length check failed for '{command}' (len={len(command)})")
        return False
    
    # Must start with - or + (launch options always do)
    if not (command.startswith('-') or command.startswith('+')):
        if debug:
            print(f"🔍 Prefix check failed for '{command}' (no -/+ prefix)")
        return False
    
    # Remove prefix for further validation
    cmd_body = command[1:]
    
    # Body must start with a letter
    if not cmd_body or not cmd_body[0].isalpha():
        if debug:
            print(f"🔍 Letter check failed for '{command}' (body doesn't start with letter)")
        return False
    
    # Only allow alphanumeric, underscore, dash in body
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9_\-]*$', cmd_body):
        if debug:
            print(f"🔍 Character check failed for '{command}' (invalid chars in body)")
        return False
    
    # BLACKLIST: Obvious false positives and HTML artifacts
    false_positives = {
        # HTML/XML tags
        '-ref', '-/ref', '+ref', '+/ref', '-br', '+br', '-div', '+div', '-span', '+span',
        '-html', '+html', '-xml', '+xml', '-tag', '+tag', '-href', '+href', '-src', '+src',
        
        # Wiki markup artifacts  
        '-pagename', '+pagename', '-pageid', '+pageid', '-infobox', '+infobox',
        '-template', '+template', '-category', '+category', '-namespace', '+namespace',
        
        # Numbers/IDs that got picked up
        '-2011012614', '+2011012614', '-3833', '+3833',
        
        # Random words that aren't launch options
        '-and', '+and', '-the', '+the', '-for', '+for', '-with', '+with', '-are', '+are',
        '-this', '+this', '-that', '+that', '-will', '+will', '-can', '+can', '-may', '+may',
        '-present', '+present', '-unavailable', '+unavailable', '-windows', '+windows',
        
        # File paths/extensions that got picked up
        '-exe', '+exe', '-dll', '+dll', '-cfg', '+cfg', '-ini', '+ini', '-txt', '+txt',
        '-com', '+com', '-net', '+net', '-org', '+org', '-www', '+www',
        
        # Meta references
        '-command', '+command', '-option', '+option', '-parameter', '+parameter',
        '-launch', '+launch', '-startup', '+startup'
    }
    
    if command.lower() in false_positives:
        if debug:
            print(f"🔍 Blacklist check failed for '{command}' (known false positive)")
        return False
    
    # WHITELIST: Known valid launch options (more conservative)
    known_valid = {
        # Performance
        '-fps_max', '-novid', '-high', '-low', '-threads', '-nojoy', '-nosound',
        '+fps_max', '+mat_queue_mode', '+cl_showfps',
        
        # Display  
        '-windowed', '-fullscreen', '-borderless', '-w', '-h', '-width', '-height',
        '-freq', '-refresh', '-dxlevel', '-gl', '-dx11', '-dx12', '-vulkan',
        
        # Engine specific
        '-console', '-condebug', '-autoconfig', '-heapsize', '-safe', '-dev',
        '+developer', '+con_enable', '+exec',
        
        # Game specific
        '-skipintro', '-nointro', '-language', '-applaunch'
    }
    
    if command.lower() in known_valid:
        if debug:
            print(f"🔍 Whitelist check passed for '{command}' (known valid)")
        return True
    
    # For unknown commands, apply heuristic validation
    # More conservative - reject unless it really looks like a launch option
    cmd_lower = command.lower()
    
    # Reject if it contains suspicious patterns
    suspicious_patterns = [
        r'\d{8,}',  # Long numbers (like page IDs)
        r'[<>{}|]', # HTML/markup characters
        r'ref.*ref', # Reference patterns
        r'window.*unavailable', # Wiki text patterns
        r'activation.*prompt', # Descriptive text patterns
    ]
    
    for pattern in suspicious_patterns:
        if re.search(pattern, cmd_lower):
            if debug:
                print(f"🔍 Suspicious pattern check failed for '{command}' (pattern: {pattern})")
            return False
    
    # Final heuristic: if it's not in whitelist and longer than 15 chars, be very suspicious
    if len(command) > 15:
        # Must have typical launch option structure
        if not any(keyword in cmd_lower for keyword in ['fps', 'res', 'window', 'screen', 'force', 'disable', 'enable', 'max', 'min']):
            if debug:
                print(f"🔍 Heuristic check failed for '{command}' (too long without keywords)")
            return False
    
    if debug:
        print(f"🔍 Validation passed for '{command}' (heuristic approval)")
    return True

def clean_wiki_description(description, debug=False):
    """
    Clean wiki description text to remove markup and artifacts
    """
    if not description:
        return ""
    
    # Remove HTML/XML tags
    description = re.sub(r'<[^>]+>', '', description)
    
    # Remove wiki markup
    description = re.sub(r'\{\{[^}]*\}\}', '', description)  # Templates
    description = re.sub(r'\[\[[^]]*\]\]', '', description)  # Links
    description = re.sub(r"'''?([^']*?)'''?", r'\1', description)  # Bold/italic
    description = re.sub(r'<ref[^>]*>.*?</ref>', '', description, flags=re.DOTALL)  # References
    description = re.sub(r'<ref[^>]*/?>', '', description)  # Self-closing refs
    
    # Remove wiki reference artifacts
    description = re.sub(r'\}\}.*?\{\{', ' ', description)
    description = re.sub(r'\|.*?\|', ' ', description)
    
    # Clean up whitespace
    description = re.sub(r'\s+', ' ', description).strip()
    
    # If description is too long or contains artifacts, truncate/clean
    if len(description) > 200:
        description = description[:200] + "..."
    
    # Remove descriptions that are just artifacts
    artifact_patterns = [
        r'^and the .* are present',
        r'.*unavailable.*',
        r'^\d+$',  # Just numbers
        r'^[<>{}|]+$',  # Just markup characters
    ]
    
    for pattern in artifact_patterns:
        if re.match(pattern, description.lower()):
            return ""
    
    # If description is very short and not meaningful, provide default
    if len(description) < 10:
        return "Launch option from PCGamingWiki"
    
    return description

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
                
                # Parse wikitext for launch options with strict validation
                parsed_options = parse_wikitext_for_launch_options_strict(wikitext, debug=debug)
                options.extend(parsed_options)
    
    except Exception as e:
        if debug:
            print(f"🔍 PCGamingWiki API: Error getting page content: {e}")
    
    return options

def parse_wikitext_for_launch_options_strict(wikitext, debug=False):
    """
    Parse MediaWiki wikitext for launch options with STRICT validation
    """
    options = []
    
    # Clean the wikitext first to remove obvious markup
    cleaned_text = clean_wikitext(wikitext)
    
    # Look for launch option patterns in cleaned text
    launch_option_patterns = [
        r'(?<!\w)(-[a-zA-Z][a-zA-Z0-9_\-]{1,25})(?!\w)',  # -command
        r'(?<!\w)(\+[a-zA-Z][a-zA-Z0-9_\-]{1,25})(?!\w)',  # +command
    ]
    
    # Split text into lines for context-aware processing
    lines = cleaned_text.split('\n')
    
    for i, line in enumerate(lines):
        # Only process lines that might contain launch options
        if any(keyword in line.lower() for keyword in 
               ['command', 'launch', 'option', 'parameter', 'argument', 'flag']):
            
            # Get context around this line
            context_start = max(0, i - 1)
            context_end = min(len(lines), i + 2)
            context_lines = lines[context_start:context_end]
            context_text = ' '.join(context_lines)
            
            # Extract launch options from this context
            for pattern in launch_option_patterns:
                matches = re.findall(pattern, line)  # Only search the current line, not context
                
                for match in matches:
                    # Apply strict validation before adding
                    if is_valid_launch_command_strict(match, debug=debug):
                        # Get description from context
                        desc = extract_description_from_context_safe(match, context_text)
                        
                        options.append({
                            'command': match,
                            'description': desc,
                            'source': 'PCGamingWiki'
                        })
                        
                        if debug and len(options) <= 10:
                            print(f"🔍 PCGamingWiki API: Found validated option: {match}")
    
    # Remove duplicates and limit results
    seen_commands = set()
    unique_options = []
    for option in options:
        cmd = option['command'].lower()
        if cmd not in seen_commands:
            seen_commands.add(cmd)
            unique_options.append(option)
    
    return unique_options[:10]  # Strict limit

def clean_wikitext(wikitext):
    """
    Clean wikitext to remove markup that could cause false positives
    """
    # Remove reference tags completely
    cleaned = re.sub(r'<ref[^>]*>.*?</ref>', '', wikitext, flags=re.DOTALL)
    cleaned = re.sub(r'<ref[^>]*/?>', '', cleaned)
    
    # Remove other HTML tags
    cleaned = re.sub(r'<[^>]+>', '', cleaned)
    
    # Remove templates
    cleaned = re.sub(r'\{\{[^}]*\}\}', '', cleaned)
    
    # Remove links but keep link text
    cleaned = re.sub(r'\[\[([^]|]*\|)?([^]]*)\]\]', r'\2', cleaned)
    
    # Remove wiki markup
    cleaned = re.sub(r"'''([^']*?)'''", r'\1', cleaned)  # Bold
    cleaned = re.sub(r"''([^']*?)''", r'\1', cleaned)   # Italic
    
    # Clean up whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned)
    
    return cleaned

def extract_description_from_context_safe(command, context):
    """
    Safely extract description for a command from its context
    """
    lines = context.split('\n')
    
    for line in lines:
        if command in line:
            # Clean up the line
            desc = line.strip()
            
            # Remove the command itself from description
            desc = desc.replace(command, '').strip()
            
            # Clean up wiki markup from description
            desc = clean_wiki_description(desc)
            
            if desc and len(desc) > 5 and len(desc) < 150:
                return desc
    
    return f"Launch option from PCGamingWiki"

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