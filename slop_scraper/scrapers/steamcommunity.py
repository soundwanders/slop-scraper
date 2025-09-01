import re
import time
import os
from bs4 import BeautifulSoup

try:
    # Try relative imports first (when run as module)
    from ..utils.security_config import SecureRequestHandler
    from ..validation import LaunchOptionsValidator, ValidationLevel, EngineType
except ImportError:
    # Fall back to absolute imports (when run directly)
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.security_config import SecureRequestHandler
    from validation import LaunchOptionsValidator, ValidationLevel, EngineType

def fetch_steam_community_launch_options(app_id, game_title=None, rate_limit=None, debug=False, 
                                       test_results=None, test_mode=False, rate_limiter=None, 
                                       session_monitor=None):
    """
    Steam Community scraper with launch option extraction
    and strict validation to prevent unwanted strings or chars like HTML artifacts
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
            
            # Find all guide elements
            guide_elements = soup.select('a[href*="/sharedfiles/filedetails/"]')
            
            if debug:
                print(f"🔍 Steam Community: Found {len(guide_elements)} guide links")
            
            # Filter guides with improved criteria
            relevant_guides = filter_relevant_guides_improved(guide_elements, debug=debug)
            
            if debug:
                print(f"🔍 Steam Community: Processing {len(relevant_guides)} relevant guides")
            
            # Process more guides for better success rate
            for i, guide in enumerate(relevant_guides[:10]):  # Increased from 5 to 10
                try:
                    if debug:
                        print(f"🔍 Steam Community: Processing guide {i+1}/{len(relevant_guides[:10])}: {guide['title'][:40]}...")
                    
                    # Rate limiting between guide requests
                    if rate_limiter:
                        rate_limiter.wait_if_needed("scraping", domain="steamcommunity.com")
                    elif rate_limit:
                        time.sleep(max(1.0, rate_limit))
                    
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
                        
                        # Extract launch options with improved cleaning and validation
                        extracted_options = extract_launch_options_clean_and_validated(
                            guide_soup, 
                            guide['title'],
                            debug=debug
                        )
                        
                        if extracted_options:
                            options.extend(extracted_options)
                            if debug:
                                print(f"🔍 Steam Community: ✅ Found {len(extracted_options)} validated options")
                        else:
                            if debug:
                                print(f"🔍 Steam Community: ❌ No valid launch options found")
                    
                    else:
                        if debug:
                            print(f"🔍 Steam Community: ❌ Guide request failed: {guide_response.status_code}")
                    
                except Exception as guide_e:
                    if session_monitor:
                        session_monitor.record_error()
                    if debug:
                        print(f"🔍 Steam Community: Error processing guide {guide['url']}: {guide_e}")
                    continue
            
            # Apply final validation and deduplication
            validated_options = final_validation_and_dedup(options, debug=debug)
            options = validated_options
            
            # Update test statistics
            if test_mode and test_results:
                source = 'Steam Community'
                if source not in test_results['options_by_source']:
                    test_results['options_by_source'][source] = 0
                test_results['options_by_source'][source] += len(options)
            
            if debug:
                print(f"🔍 Steam Community: Final result: {len(options)} validated options found")
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

def filter_relevant_guides_improved(guide_elements, debug=False):
    """
    Improved guide filtering - better success rate while maintaining quality
    """
    relevant_guides = []
    
    # Expanded relevant keywords for better coverage
    relevant_keywords = [
        'launch', 'option', 'command', 'performance', 'optimize', 'fps', 'fix',
        'setting', 'config', 'tweak', 'parameter', 'argument', 'startup',
        'graphics', 'video', 'resolution', 'crash', 'error', 'problem',
        'improve', 'boost', 'better', 'smooth', 'run', 'setup', 'install'
    ]
    
    # More targeted avoid keywords (less restrictive but still quality-focused)
    avoid_keywords = [
        'walkthrough complete', 'story walkthrough', 'boss guide', 'achievement guide',
        'save file', 'cheat engine', 'trainer', 'hack'
        # Removed: 'guide to', 'mod', 'level' - these often contain launch options
    ]
    
    for guide_elem in guide_elements:
        guide_url = guide_elem.get('href')
        if not guide_url:
            continue
            
        # Ensure it's a full URL
        if guide_url.startswith('/'):
            guide_url = 'https://steamcommunity.com' + guide_url
        elif not guide_url.startswith('http'):
            guide_url = 'https://steamcommunity.com/' + guide_url
        
        # Get guide title
        title = guide_elem.get_text(strip=True)[:150] or "Untitled Guide"
        title_lower = title.lower()
        
        # Improved scoring system
        relevance_score = 0
        
        # Add points for relevant keywords
        for keyword in relevant_keywords:
            if keyword in title_lower:
                relevance_score += 1
        
        # Subtract points for avoid keywords (but less harsh)
        for keyword in avoid_keywords:
            if keyword in title_lower:
                relevance_score -= 2
        
        # Bonus points for explicit launch option mentions
        if 'launch option' in title_lower or 'launch command' in title_lower:
            relevance_score += 5
        
        if 'startup option' in title_lower or 'command line' in title_lower:
            relevance_score += 4
            
        if 'properties' in title_lower and ('steam' in title_lower or 'game' in title_lower):
            relevance_score += 2
        
        # Include guides with neutral or positive scores
        if relevance_score >= 0:
            relevant_guides.append({
                'title': title,
                'url': guide_url,
                'score': relevance_score
            })
            
            if debug:
                print(f"🔍 Steam Community: Relevant guide (score {relevance_score}): {title[:50]}...")
    
    # Sort by relevance score (highest first)
    relevant_guides.sort(key=lambda g: g['score'], reverse=True)
    
    return relevant_guides

def extract_launch_options_clean_and_validated(guide_soup, guide_title, debug=False):
    """
    PRODUCTION VERSION: Extract launch options with thorough cleaning and validation
    Prevents HTML artifacts while finding legitimate options
    """
    options = []
    
    # Find guide content using established selectors
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
        guide_content = guide_soup.find('body')
        if debug:
            print(f"🔍 Steam Community: Using fallback content extraction")
    
    if not guide_content:
        return options

    # Method 1: Extract from code blocks and formatted text (highest quality)
    code_elements = guide_content.find_all(['code', 'pre', 'tt', 'kbd', 'samp'])
    
    for element in code_elements:
        clean_text = get_clean_text_from_element(element)
        
        if clean_text and len(clean_text.strip()) > 0:
            extracted_options = extract_validated_steam_options(clean_text, guide_title, debug)
            options.extend(extracted_options)
            
            if debug and extracted_options:
                print(f"🔍 Steam Community: Found {len(extracted_options)} clean options in code block")

    # Method 2: Extract from paragraphs with explicit launch option context
    if len(options) < 5:  # Process more if we haven't found many
        paragraphs = guide_content.find_all(['p', 'div', 'li', 'td'])
        
        for para in paragraphs[:30]:  # Increased from 20
            clean_text = get_clean_text_from_element(para)
            
            if not clean_text or len(clean_text) > 800:
                continue
            
            # Only process text that explicitly mentions launch options
            if has_explicit_launch_option_context(clean_text):
                extracted_options = extract_validated_steam_options(clean_text, guide_title, debug)
                options.extend(extracted_options)
                
                if debug and extracted_options:
                    print(f"🔍 Steam Community: Found {len(extracted_options)} options in paragraph")
    
    return options

def get_clean_text_from_element(element):
    """
    Extract clean text from HTML element, removing artifacts that cause database pollution
    KEY IMPROVEMENT: Thorough HTML cleaning prevents <ref>hmo and similar artifacts
    """
    if not element:
        return ""
    
    try:
        # Remove problematic elements completely
        for unwanted in element(["script", "style", "ref", "sup", "a"]):
            unwanted.extract()
        
        # Get text with preserved spacing
        text = element.get_text(separator=' ')
        
        # Apply comprehensive cleaning
        text = clean_extracted_text(text)
        
        return text
        
    except Exception:
        return ""

def clean_extracted_text(text):
    """
    Comprehensive text cleaning to prevent database pollution
    Removes HTML artifacts, BB code, and other junk that was causing issues
    """
    if not text:
        return ""
    
    # Remove HTML artifacts that sneak through
    text = re.sub(r'<[^>]+>', '', text)  # Remove HTML tags
    text = re.sub(r'&[a-zA-Z0-9#]+;', '', text)  # Remove HTML entities
    text = re.sub(r'\[/?[a-zA-Z0-9="\s]+\]', '', text)  # Remove BB code
    
    # Remove Steam Community specific artifacts
    text = re.sub(r'https?://[^\s]+', ' ', text)  # Remove URLs
    text = re.sub(r'steamcommunity\.com[^\s]*', ' ', text)  # Remove Steam URLs
    text = re.sub(r'Right-click.*?Properties.*?General.*?Launch Options', 'Launch Options', text, flags=re.IGNORECASE)
    
    # Remove common UI artifacts that were causing pollution
    text = re.sub(r'properties[/\-]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'[<>{}|]+', ' ', text)  # Remove bracket artifacts
    text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
    
    return text.strip()

def has_explicit_launch_option_context(text):
    """
    Strict context checking - only process text explicitly about launch options
    Prevents false positives while ensuring we capture legitimate options
    """
    if not text or len(text) < 10:
        return False
        
    text_lower = text.lower()
    
    # Must contain explicit launch option terminology
    explicit_indicators = [
        'launch option', 'launch parameter', 'launch command',
        'startup option', 'startup parameter', 'command line option',
        'steam launch', 'game properties', 'launch properties',
        'add to launch options', 'set launch options',
        'properties > general > launch options',
        'properties → general → launch options',
        'right click properties general',
        'steam properties launch'
    ]
    
    # Also accept if contains common launch options (high confidence)
    common_options_mentioned = [
        '-novid', '-windowed', '-fullscreen', '-console', '-high', '-dx11', '-dx12'
    ]
    
    has_explicit = any(indicator in text_lower for indicator in explicit_indicators)
    has_common_options = any(option in text_lower for option in common_options_mentioned)
    
    return has_explicit or has_common_options

def extract_validated_steam_options(text, guide_title, debug=False):
    """
    PRODUCTION VERSION: Extract and validate Steam launch options
    Uses comprehensive patterns and strict validation against known options
    """
    if not text or len(text.strip()) < 3:
        return []
    
    options = []
    
    # Comprehensive extraction patterns based on commands.md reference
    patterns = [
        # Universal Steam options (most common)
        r'(?:^|\s)(-(?:novid|windowed|fullscreen|console|high|low|noborder|sw)(?:\s|$))',
        
        # Graphics API options
        r'(?:^|\s)(-(?:dx9|dx11|dx12|gl|vulkan|opengl)(?:\s|$))',
        
        # Parameterized options (with values)
        r'(?:^|\s)(-(?:w|h|refresh|freq)\s+\d{3,5}(?:\s|$))',
        r'(?:^|\s)(-dxlevel\s+(?:80|81|90|95|100)(?:\s|$))',
        r'(?:^|\s)(-threads\s+[1-8](?:\s|$))',
        
        # Console commands (+ prefix)
        r'(?:^|\s)(\+(?:fps_max|mat_queue_mode|cl_forcepreload|cl_showfps|exec|connect)\s*\d*(?:\s|$))',
        
        # Unity engine options
        r'(?:^|\s)(-(?:force-d3d11|force-d3d12|force-vulkan|force-opengl|force-metal)(?:\s|$))',
        r'(?:^|\s)(-(?:screen-width|screen-height|screen-quality)\s*\d*(?:\s|$))',
        r'(?:^|\s)(-(?:nographics|nolog|no-stereo-rendering|popupwindow)(?:\s|$))',
        
        # Unreal engine options
        r'(?:^|\s)(-(?:USEALLAVAILABLECORES|ONETHREAD|sm4|sm5|borderless|lowmemory)(?:\s|$))',
        r'(?:^|\s)(-(?:ResX|ResY)=\d{3,5}(?:\s|$))',
        r'(?:^|\s)(-malloc=\w+(?:\s|$))',
        
        # Source engine specific
        r'(?:^|\s)(-(?:nopreload|softparticlesdefaultoff|primarysound|sndmono|insecure|enablefakeip)(?:\s|$))',
        r'(?:^|\s)(-(?:multirun|noaddons|noworkshop|useallavailablecores|sillygibs)(?:\s|$))',
        
        # Performance and debugging
        r'(?:^|\s)(-(?:nosound|nojoy|dev|safe|autoconfig|condebug|allowdebug|showfps)(?:\s|$))',
    ]
    
    # Extract using comprehensive patterns
    all_matches = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            if isinstance(match, tuple):
                match = next(m for m in match if m.strip())
            clean_match = match.strip()
            if clean_match and len(clean_match) > 1:
                all_matches.append(clean_match)
    
    if debug and all_matches:
        print(f"🔍 Steam Community: Pattern matches found: {all_matches}")
    
    # STRICT validation against known Steam launch options
    for match in all_matches:
        if validate_against_commands_reference(match, debug=debug):
            description = get_clean_description_for_option(match, text, guide_title)
            
            options.append({
                'command': match,
                'description': description,
                'source': 'Steam Community'
            })
            
            if debug:
                print(f"🔍 Steam Community: VALIDATED option: {match}")
        else:
            if debug:
                print(f"🔍 Steam Community: REJECTED unknown option: {match}")
    
    return options

def validate_against_commands_reference(command, debug=False):
    """
    Use existing LaunchOptionsValidator for validation
    IMPROVED: Uses your comprehensive validation system instead of duplicating logic
    """
    validator = LaunchOptionsValidator(ValidationLevel.PERMISSIVE)
    is_valid, reason = validator.validate_option(command, EngineType.UNIVERSAL)
    
    if debug and not is_valid:
        print(f"🔍 Steam Community: Validation rejected '{command}' - {reason}")
    
    return is_valid

def get_clean_description_for_option(option, context_text, guide_title):
    """
    Generate clean descriptions that won't pollute the database
    Removes artifacts while preserving meaningful context
    """
    # Clean the context text thoroughly
    clean_context = clean_extracted_text(context_text)
    
    # Try to find meaningful description
    lines = clean_context.split('.')
    
    for line in lines:
        line = line.strip()
        if option in line and len(line) > len(option) + 5:
            # Clean the line further
            desc = line.replace(option, '').strip()
            
            # Remove common prefixes that add no value
            prefixes_to_remove = [
                'add', 'use', 'try', 'set', 'put', 'include', 'apply',
                'right click', 'properties', 'general', 'launch options'
            ]
            
            for prefix in prefixes_to_remove:
                if desc.lower().startswith(prefix):
                    desc = desc[len(prefix):].strip()
            
            # Clean up punctuation and artifacts
            desc = re.sub(r'^[:\-\.,\s]+', '', desc)
            desc = re.sub(r'[:\-\.,\s]+$', '', desc)
            
            # Ensure option description is clean and meaningful
            if desc and len(desc) > 10 and len(desc) < 200:
                # Final artifact check
                if not re.search(r'[<>{}|]', desc) and not desc.startswith('/'):
                    return desc
    
    # Fallback to safe, generic description
    return f"Launch option from Steam Community guide"

def final_validation_and_dedup(options, debug=False):
    """
    Final validation and deduplication with quality checks
    """
    validated_options = []
    seen_commands = set()
    
    for option in options:
        command = option.get('command', '').strip()
        description = option.get('description', '').strip()
        
        # Skip if already seen
        if command.lower() in seen_commands:
            continue
        
        # Final quality check - no artifacts in command or description
        if (command and len(command) >= 2 and 
            not re.search(r'[<>{}|]', command) and 
            not command.startswith('/') and
            not re.search(r'[<>{}|]', description)):
            
            seen_commands.add(command.lower())
            validated_options.append(option)
            
            if debug:
                print(f"🔍 Steam Community: Final validation passed for: {command}")
        else:
            if debug:
                print(f"🔍 Steam Community: Final validation failed for: {command}")
    
    # Limit total options to prevent spam (increased slightly for better coverage)
    return validated_options[:20]