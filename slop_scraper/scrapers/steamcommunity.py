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
    Extract valid Steam launch options from text using STRICT validation
    Based on actual Steam launch option patterns
    """
    options = []
    
    # STRICT patterns for valid Steam launch options only
    # Pattern 1: -command (dash commands without parameters)
    dash_commands = re.findall(r'-([a-zA-Z][a-zA-Z0-9_]*)', text)
    
    # Pattern 2: -command parameter (dash commands with parameters)  
    dash_with_params = re.findall(r'-([a-zA-Z][a-zA-Z0-9_]*)\s+([a-zA-Z0-9_]+)', text)
    
    # Pattern 3: +command parameter (plus commands with parameters)
    plus_with_params = re.findall(r'\+([a-zA-Z][a-zA-Z0-9_]*)\s+([a-zA-Z0-9_]+)', text)
    
    # Process dash commands (no parameters)
    for cmd in dash_commands:
        if is_valid_steam_launch_option(cmd):
            options.append(f"-{cmd}")
    
    # Process dash commands with parameters
    for cmd, param in dash_with_params:
        if is_valid_steam_launch_option(cmd) and is_valid_parameter(param):
            options.append(f"-{cmd} {param}")
    
    # Process plus commands with parameters
    for cmd, param in plus_with_params:
        if is_valid_steam_launch_option(cmd) and is_valid_parameter(param):
            options.append(f"+{cmd} {param}")
    
    # Remove duplicates while preserving order
    seen = set()
    unique_options = []
    for option in options:
        if option not in seen:
            seen.add(option)
            unique_options.append(option)
            
            if debug:
                print(f"🔍 Steam Community: Validated option: {option}")
    
    return unique_options

def is_valid_steam_launch_option(cmd):
    """
    Validate that a command name is a valid Steam launch option
    Based on real Steam launch option patterns
    """
    cmd_lower = cmd.lower().strip()
    
    # Must be reasonable length (not too short or too long)
    if len(cmd_lower) < 2 or len(cmd_lower) > 30:
        return False
    
    # Must start with a letter (not number or symbol)
    if not cmd_lower[0].isalpha():
        return False
    
    # Must contain only letters, numbers, and underscores
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', cmd_lower):
        return False
    
    # Filter out obvious false positives
    false_positives = [
        'ref', 'img', 'div', 'span', 'href', 'src', 'alt', 'title',  # HTML-related
        'http', 'https', 'www', 'com', 'net', 'org',  # URL-related
        'and', 'the', 'for', 'with', 'this', 'that',  # Common words
        'dash', 'slash', 'backslash',  # Meta references
    ]
    
    if cmd_lower in false_positives:
        return False
    
    # Known valid Steam launch options (whitelist approach for high confidence)
    known_valid_options = [
        # Common performance options
        'fps_max', 'novid', 'nod3d9ex', 'high', 'nojoy', 'console', 'threads', 'fullscreen',
        'windowed', 'refresh', 'refreshrate', 'freq', 'lv', 'autoconfig', 'heapsize',
        # Source engine options
        'mat_queue_mode', 'cl_showfps', 'r_dynamic', 'cl_interp', 'cl_interp_ratio',
        'cl_updaterate', 'cl_forcepreload', 'cl_cmdrate', 'rate', 'cl_lagcompensation',
        # Graphics options
        'gl_clear', 'gl_texturemode', 'gl_ansio', 'r_speeds', 'r_drawviewmodel',
        # Audio options
        'nosound', 'primarysound', 'snoforceformat', 'wavonly',
        # Other common options
        'safe', 'autoexec', 'userconfig', 'game', 'steam', 'applaunch', 'dev', 'condebug'
    ]
    
    # If it's in the known valid list, it's definitely good
    if cmd_lower in known_valid_options:
        return True
    
    # For unknown options, apply stricter validation
    # Must be at least 3 characters and look like a real command
    if len(cmd_lower) >= 3 and not cmd_lower.isdigit():
        return True
    
    return False

def is_valid_parameter(param):
    """
    Validate that a parameter value is reasonable for a Steam launch option
    """
    param_lower = param.lower().strip()
    
    # Must be reasonable length
    if len(param_lower) < 1 or len(param_lower) > 20:
        return False
    
    # Must contain only letters, numbers, and basic symbols
    if not re.match(r'^[a-zA-Z0-9_\.]+$', param_lower):
        return False
    
    # Filter out HTML-like parameters
    if param_lower.startswith('<') or param_lower.endswith('>'):
        return False
    
    return True