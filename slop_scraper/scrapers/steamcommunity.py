import re
import time
import os
from bs4 import BeautifulSoup

try:
    # Try relative imports first (when run as module)
    from ..utils.security_config import SecureRequestHandler
except ImportError:
    # Fall back to absolute imports (when run directly)
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.security_config import SecureRequestHandler

def fetch_steam_community_launch_options(app_id, game_title=None, rate_limit=None, debug=False, 
                                       test_results=None, test_mode=False, rate_limiter=None, 
                                       session_monitor=None):
    """
    Steam Community scraper - BYPASS main page filtering approach
    This function fetches launch options from Steam Community guides for a given app_id.
    It uses a more direct approach to find guides without filtering by title.
    This is useful for games with many guides or when titles are inconsistent.
    It extracts launch options from the content of the guides, ensuring strict validation
    to avoid false positives from HTML tags or unrelated text.
    """
    
    # Security validation
    try:
        app_id_int = int(app_id)
        if app_id_int <= 0 or app_id_int > 999999999:
            if debug:
                print(f"⚠️ Invalid app_id: {app_id}")
            return []
    except (ValueError, TypeError):
        if debug:
            print(f"⚠️ Invalid app_id format: {app_id}")
        return []
    
    if rate_limiter:
        rate_limiter.wait_if_needed("scraping", domain="steamcommunity.com")
    elif rate_limit:
        time.sleep(rate_limit)
    
    # Steam Community guides URL
    url = f"https://steamcommunity.com/app/{app_id_int}/guides/"
    
    if debug:
        print(f"🔍 Steam Community: Fetching {url}")
    
    options = []
    try:
        # Use secure request handler with Steam-specific headers
        response = SecureRequestHandler.make_secure_request(
            url, 
            timeout=15, 
            max_size_mb=3,
            debug=debug
        )
        
        # Record request for monitoring
        if session_monitor:
            session_monitor.record_request()
        
        if debug:
            print(f"🔍 Steam Community: Response status {response.status_code}")
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            if debug:
                print(f"🔍 Steam Community: Parsed HTML, length: {len(response.text)} characters")
            
            # Find all guide elements (investigation shows these work consistently)
            guide_elements = soup.select('a[href*="/sharedfiles/filedetails/"]')
            
            if debug:
                print(f"🔍 Steam Community: Found {len(guide_elements)} guide links")
            
            # If we found guides, process the top ones (bypass title filtering entirely)
            guides_to_process = []
            
            for guide_elem in guide_elements[:8]:  # Check top 8 guides regardless of title
                guide_url = guide_elem.get('href')
                if guide_url:
                    # Ensure it's a full URL
                    if guide_url.startswith('/'):
                        guide_url = 'https://steamcommunity.com' + guide_url
                    elif not guide_url.startswith('http'):
                        guide_url = 'https://steamcommunity.com/' + guide_url
                    
                    # Get guide title for logging
                    title = guide_elem.get_text(strip=True)[:100] or "Untitled Guide"
                    
                    guides_to_process.append({
                        'title': title,
                        'url': guide_url
                    })
                    
                    if debug:
                        print(f"🔍 Steam Community: Will check guide: {title[:40]}...")
            
            if debug:
                print(f"🔍 Steam Community: Processing {len(guides_to_process)} guides (bypass filtering)")
            
            # Process guides and extract launch options from their content
            for i, guide in enumerate(guides_to_process):
                try:
                    if debug:
                        print(f"🔍 Steam Community: Processing guide {i+1}/{len(guides_to_process)}: {guide['title'][:30]}...")
                    
                    # Rate limiting between guide requests
                    if rate_limiter:
                        rate_limiter.wait_if_needed("scraping", domain="steamcommunity.com")
                    elif rate_limit:
                        time.sleep(max(1.0, rate_limit))  # Minimum 1 second between guide requests
                    
                    # Fetch guide content
                    guide_response = SecureRequestHandler.make_secure_request(
                        guide['url'], 
                        timeout=20, 
                        max_size_mb=2,
                        debug=debug
                    )
                    
                    if session_monitor:
                        session_monitor.record_request()
                    
                    if guide_response.status_code == 200:
                        guide_soup = BeautifulSoup(guide_response.text, 'html.parser')
                        
                        # Extract launch options from this guide's content
                        extracted_options = extract_launch_options_from_guide_content(
                            guide_soup, 
                            guide['title'],
                            debug=debug
                        )
                        
                        if extracted_options:
                            options.extend(extracted_options)
                            if debug:
                                print(f"🔍 Steam Community: ✅ Found {len(extracted_options)} options in this guide")
                        else:
                            if debug:
                                print(f"🔍 Steam Community: ❌ No launch options found in this guide")
                    
                    else:
                        if debug:
                            print(f"🔍 Steam Community: ❌ Guide request failed: {guide_response.status_code}")
                    
                except Exception as guide_e:
                    if session_monitor:
                        session_monitor.record_error()
                    if debug:
                        print(f"🔍 Steam Community: Error processing guide {guide['url']}: {guide_e}")
                    continue
            
            # Remove duplicates and limit results
            seen_commands = set()
            filtered_options = []
            for option in options:
                cmd = option['command'].lower().strip()
                if cmd not in seen_commands and len(filtered_options) < 15:  # Limit to 15 best options
                    seen_commands.add(cmd)
                    filtered_options.append(option)
            
            options = filtered_options
            
            # Update test statistics
            if test_mode and test_results:
                source = 'Steam Community'
                if source not in test_results['options_by_source']:
                    test_results['options_by_source'][source] = 0
                test_results['options_by_source'][source] += len(options)
            
            if debug:
                print(f"🔍 Steam Community: Final result: {len(options)} unique options found")
                for opt in options[:3]:
                    print(f"🔍 Steam Community:   {opt['command']}: {opt['description'][:50]}...")
            
            return options
        
        else:
            if debug:
                print(f"🔍 Steam Community: HTTP {response.status_code} for app {app_id_int}")
            return []
            
    except Exception as e:
        if session_monitor:
            session_monitor.record_error()
        
        if debug:
            print(f"🔍 Steam Community: Error for app {app_id_int}: {e}")
            import traceback
            traceback.print_exc()
        else:
            print(f"🔍 Steam Community: Error for app {app_id_int}: {e}")
        
        return []

def extract_launch_options_from_guide_content(guide_soup, guide_title, debug=False):
    """
    Extract launch options from individual guide content
    STRICT validation to prevent false positives like HTML tags and invalid patterns
    """
    options = []
    
    # Look for the main guide content area
    content_selectors = [
        '.guide_body',
        '.subSectionContents', 
        '.guide_content',
        '.workshopItemDescription',
        '.guide_section',
        '[class*="guide"]',
        '[class*="content"]'
    ]
    
    guide_content = None
    for selector in content_selectors:
        content = guide_soup.select_one(selector)
        if content:
            guide_content = content
            if debug:
                print(f"🔍 Steam Community: Found content using selector: {selector}")
            break
    
    if not guide_content:
        # Fallback: use the entire body but exclude navigation
        guide_content = guide_soup.find('body')
        if debug:
            print(f"🔍 Steam Community: Using fallback content extraction")
    
    if not guide_content:
        return options
    
    # Method 1: Look for code blocks and pre-formatted text
    code_elements = guide_content.find_all(['code', 'pre', 'tt', 'kbd', 'samp'])
    
    for element in code_elements:
        # Get CLEAN text without HTML tags
        text = element.get_text(strip=True)
        if len(text) > 500:  # Skip very long code blocks
            continue
        
        # Extract potential launch options using STRICT patterns
        extracted_options = extract_steam_launch_options_from_text(text, debug)
        for option in extracted_options:
            # Get context from surrounding text
            parent_text = ""
            if element.parent:
                parent_text = element.parent.get_text(strip=True)[:200]
            
            desc = parent_text if len(parent_text) > len(text) else f"From guide: {guide_title[:50]}"
            
            options.append({
                'command': option,
                'description': desc,
                'source': 'Steam Community'
            })
            
            if debug:
                print(f"🔍 Steam Community: Found in code block: {option}")
    
    # Method 2: Look for paragraphs with launch option context
    if len(options) < 3:  # Only do this expensive search if we haven't found many options
        paragraphs = guide_content.find_all(['p', 'div', 'li'])
        
        for para in paragraphs[:30]:  # Limit for performance
            # Get CLEAN text without HTML tags
            text = para.get_text(strip=True)
            
            if len(text) > 1500:  # Skip very long paragraphs
                continue
            
            text_lower = text.lower()
            
            # Look for paragraphs that discuss launch options
            launch_context_indicators = [
                'launch option', 'launch parameter', 'startup option', 'command line',
                'launch command', 'startup parameter', 'game option', 'boot option',
                'fps', 'performance', 'graphics option', 'video option'
            ]
            
            has_launch_context = any(indicator in text_lower for indicator in launch_context_indicators)
            
            if has_launch_context:
                # Extract commands from this paragraph
                extracted_options = extract_steam_launch_options_from_text(text, debug)
                for option in extracted_options:
                    desc = text[:200] if len(text) <= 200 else text[:200] + "..."
                    
                    options.append({
                        'command': option,
                        'description': desc,
                        'source': 'Steam Community'
                    })
                    
                    if debug:
                        print(f"🔍 Steam Community: Found in paragraph: {option}")
    
    return options

def extract_steam_launch_options_from_text(text, debug=False):
    """
    Extract valid Steam launch options from text using validation
    More lenient to handle different languages and formats while preventing false positives
    """
    options = []
    
    # Patterns for valid Steam launch options
    # Pattern 1: -command (more flexible matching)
    dash_pattern = r'-([a-zA-Z][a-zA-Z0-9_\-]{1,25})'
    dash_commands = re.findall(dash_pattern, text, re.IGNORECASE)
    
    # Pattern 2: -command parameter (with flexible parameter matching)
    dash_with_params_pattern = r'-([a-zA-Z][a-zA-Z0-9_\-]{1,25})\s+([a-zA-Z0-9_\-\.]{1,15})'
    dash_with_params = re.findall(dash_with_params_pattern, text, re.IGNORECASE)
    
    # Pattern 3: +command parameter (Source engine style)
    plus_with_params_pattern = r'\+([a-zA-Z][a-zA-Z0-9_\-]{1,25})\s+([a-zA-Z0-9_\-\.]{1,15})'
    plus_with_params = re.findall(plus_with_params_pattern, text, re.IGNORECASE)
    
    # Pattern 4: Common launch option patterns without spaces (like -fps_max_60)
    compound_pattern = r'-([a-zA-Z][a-zA-Z0-9_\-]{2,30})'
    compound_commands = re.findall(compound_pattern, text, re.IGNORECASE)
    
    if debug:
        print(f"🔍 Steam Community: Text analysis:")
        print(f"   Dash commands found: {dash_commands}")
        print(f"   Dash with params: {dash_with_params}")
        print(f"   Plus with params: {plus_with_params}")
        print(f"   Compound commands: {compound_commands}")
    
    # Process dash commands (no parameters)
    for cmd in dash_commands:
        if is_valid_steam_launch_option(cmd, debug):
            option = f"-{cmd}"
            if option not in [opt for opt in options]:  # Avoid duplicates
                options.append(option)
                if debug:
                    print(f"🔍 Steam Community: Added dash command: {option}")
    
    # Process dash commands with parameters
    for cmd, param in dash_with_params:
        if is_valid_steam_launch_option(cmd, debug) and is_valid_parameter(param):
            option = f"-{cmd} {param}"
            if option not in options:
                options.append(option)
                if debug:
                    print(f"🔍 Steam Community: Added dash+param: {option}")
    
    # Process plus commands with parameters (Source engine)
    for cmd, param in plus_with_params:
        if is_valid_steam_launch_option(cmd, debug) and is_valid_parameter(param):
            option = f"+{cmd} {param}"
            if option not in options:
                options.append(option)
                if debug:
                    print(f"🔍 Steam Community: Added plus+param: {option}")
    
    # Process compound commands (like -fps_max_144)
    for cmd in compound_commands:
        if is_valid_steam_launch_option(cmd, debug):
            option = f"-{cmd}"
            if option not in options and option not in [f"-{c}" for c in dash_commands]:  # Avoid duplicates
                options.append(option)
                if debug:
                    print(f"🔍 Steam Community: Added compound: {option}")
    
    # Remove exact duplicates while preserving order
    unique_options = []
    seen = set()
    for option in options:
        if option.lower() not in seen:
            seen.add(option.lower())
            unique_options.append(option)
    
    if debug:
        print(f"🔍 Steam Community: Final validated options: {unique_options}")
    
    return unique_options[:20]  # Limit to prevent spam


def is_valid_steam_launch_option(cmd, debug=False):
    """
    Validation that's more lenient but still prevents false positives
    """
    if not cmd or not isinstance(cmd, str):
        return False
    
    cmd_lower = cmd.lower().strip()
    
    # Basic length check (more lenient)
    if len(cmd_lower) < 2 or len(cmd_lower) > 35:
        if debug:
            print(f"🔍 Steam Community: Rejected '{cmd}' - invalid length")
        return False
    
    # Must start with a letter
    if not cmd_lower[0].isalpha():
        if debug:
            print(f"🔍 Steam Community: Rejected '{cmd}' - doesn't start with letter")
        return False
    
    # Allow letters, numbers, underscores, and hyphens
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9_\-]*$', cmd_lower):
        if debug:
            print(f"🔍 Steam Community: Rejected '{cmd}' - invalid characters")
        return False
    
    # EXPANDED blacklist for obvious false positives
    false_positives = {
        # HTML/XML related
        'ref', 'img', 'div', 'span', 'href', 'src', 'alt', 'title', 'class', 'style', 'script',
        'html', 'body', 'head', 'meta', 'link', 'strong', 'bold', 'italic', 'table', 'tbody',
        # URL related
        'http', 'https', 'www', 'com', 'net', 'org', 'html', 'php', 'asp', 'jsp',
        # Common words that might appear
        'and', 'the', 'for', 'with', 'this', 'that', 'from', 'will', 'can', 'all',
        'are', 'not', 'you', 'any', 'may', 'use', 'set', 'get', 'new', 'old',
        # Meta references
        'dash', 'slash', 'backslash', 'command', 'option', 'parameter', 'setting',
        # Steam interface terms that aren't launch options
        'steam', 'steamcmd', 'steamapps', 'library', 'install', 'download',
        # File extensions
        'exe', 'dll', 'cfg', 'ini', 'txt', 'log', 'bat', 'sh'
    }
    
    if cmd_lower in false_positives:
        if debug:
            print(f"🔍 Steam Community: Rejected '{cmd}' - blacklisted word")
        return False
    
    # EXPANDED whitelist of known valid options (more comprehensive)
    known_valid_options = {
        # Performance & Graphics
        'fps_max', 'fps-max', 'fps_max_60', 'fps_max_144', 'fps_max_120', 'maxfps',
        'novid', 'nod3d9ex', 'high', 'nojoy', 'nosound', 'noipx', 'console',
        'threads', 'thread', 'fullscreen', 'windowed', 'borderless',
        'refresh', 'refreshrate', 'freq', 'frequency', 'hz',
        'lv', 'autoconfig', 'heapsize', 'mem', 'memory',
        
        # Video/Display options
        'w', 'h', 'width', 'height', 'res', 'resolution',
        'x', 'y', 'posx', 'posy', 'xpos', 'ypos',
        'dxlevel', 'gl', 'opengl', 'directx', 'dx11', 'dx12', 'vulkan',
        
        # Source Engine specific
        'mat_queue_mode', 'cl_showfps', 'r_dynamic', 'cl_interp', 'cl_interp_ratio',
        'cl_updaterate', 'cl_forcepreload', 'cl_cmdrate', 'rate', 'cl_lagcompensation',
        
        # Audio
        'nosound', 'primarysound', 'snoforceformat', 'wavonly', 'dsound',
        
        # Networking
        'port', 'ip', 'connect', 'server', 'dedicated',
        'maxplayers', 'tickrate', 'tick',
        
        # Debug/Development
        'safe', 'autoexec', 'userconfig', 'condebug', 'dev', 'developer',
        'log', 'logaddress', 'debug',
        
        # Game-specific options that might appear
        'game', 'mod', 'applaunch', 'language', 'lang',
        'skipintro', 'nointro', 'intro',
        
        # Common performance tweaks
        'low', 'medium', 'high', 'ultra', 'max', 'min',
        'enable', 'disable', 'on', 'off', 'force',
        
        # Configuration
        'config', 'cfg', 'exec', 'override'
    }
    
    # If it's in the known valid list, definitely accept it
    if cmd_lower in known_valid_options:
        if debug:
            print(f"🔍 Steam Community: Accepted '{cmd}' - known valid option")
        return True
    
    # For unknown options, apply reasonable heuristics
    # Accept if it looks like a realistic command:
    # 1. At least 3 characters
    # 2. Contains letters (not just numbers)
    # 3. Doesn't look like random text
    
    if len(cmd_lower) >= 3:
        # Check if it has a reasonable structure
        has_letters = any(c.isalpha() for c in cmd_lower)
        has_reasonable_structure = True
        
        # Reject if it's all numbers
        if cmd_lower.isdigit():
            has_reasonable_structure = False
        
        # Reject if it has too many consecutive consonants/vowels (likely gibberish)
        consonants = 'bcdfghjklmnpqrstvwxyz'
        vowels = 'aeiou'
        max_consecutive = 4
        
        consecutive_consonants = 0
        consecutive_vowels = 0
        
        for char in cmd_lower:
            if char in consonants:
                consecutive_consonants += 1
                consecutive_vowels = 0
                if consecutive_consonants > max_consecutive:
                    has_reasonable_structure = False
                    break
            elif char in vowels:
                consecutive_vowels += 1
                consecutive_consonants = 0
                if consecutive_vowels > max_consecutive:
                    has_reasonable_structure = False
                    break
            else:
                consecutive_consonants = 0
                consecutive_vowels = 0
        
        if has_letters and has_reasonable_structure:
            if debug:
                print(f"🔍 Steam Community: Accepted '{cmd}' - heuristic validation passed")
            return True
    
    if debug:
        print(f"🔍 Steam Community: Rejected '{cmd}' - failed heuristic validation")
    return False


def is_valid_parameter(param):
    """
    Parameter validation for Steam launch options
    Lenient to handle different formats while preventing false positives
    """
    if not param or not isinstance(param, str):
        return False
    
    param_clean = param.strip()
    
    # Length check (more lenient)
    if len(param_clean) < 1 or len(param_clean) > 25:
        return False
    
    # Allow alphanumeric, dots, underscores, hyphens
    if not re.match(r'^[a-zA-Z0-9_\.\-]+$', param_clean):
        return False
    
    # Reject obvious HTML artifacts
    if param_clean.startswith('<') or param_clean.endswith('>'):
        return False
    
    # Reject if it's just dots or hyphens
    if set(param_clean) <= {'.', '-', '_'}:
        return False
    
    return True