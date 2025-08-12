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
    Steam Community scraper with strict validation to prevent false positives
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
            
            # Filter guides to focus on launch options and performance guides
            relevant_guides = filter_relevant_guides(guide_elements, debug=debug)
            
            if debug:
                print(f"🔍 Steam Community: Processing {len(relevant_guides)} relevant guides")
            
            # Process the most relevant guides
            for i, guide in enumerate(relevant_guides[:5]):  # Limit to top 5 relevant guides
                try:
                    if debug:
                        print(f"🔍 Steam Community: Processing guide {i+1}/{len(relevant_guides[:5])}: {guide['title'][:30]}...")
                    
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
                        
                        # Extract launch options with strict validation
                        extracted_options = extract_launch_options_from_guide_content_strict(
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

def filter_relevant_guides(guide_elements, debug=False):
    """
    Filter guides to focus on those likely to contain launch options
    """
    relevant_guides = []
    
    # Keywords that indicate a guide might contain launch options
    relevant_keywords = [
        'launch', 'option', 'command', 'performance', 'optimize', 'fps', 'fix',
        'setting', 'config', 'tweak', 'parameter', 'argument', 'startup',
        'graphics', 'video', 'resolution', 'crash', 'error', 'problem'
    ]
    
    # Keywords that indicate guides to avoid
    avoid_keywords = [
        'walkthrough', 'guide to', 'story', 'ending', 'achievement', 'trophy',
        'level', 'boss', 'secret', 'easter egg', 'mod', 'cheat', 'save'
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
        title = guide_elem.get_text(strip=True)[:100] or "Untitled Guide"
        title_lower = title.lower()
        
        # Score the guide based on relevance
        relevance_score = 0
        
        # Add points for relevant keywords
        for keyword in relevant_keywords:
            if keyword in title_lower:
                relevance_score += 2
        
        # Subtract points for avoid keywords
        for keyword in avoid_keywords:
            if keyword in title_lower:
                relevance_score -= 3
        
        # Bonus points for explicit launch option mentions
        if 'launch option' in title_lower or 'launch command' in title_lower:
            relevance_score += 5
        
        if 'startup option' in title_lower or 'command line' in title_lower:
            relevance_score += 5
        
        # Only include guides with positive relevance score
        if relevance_score > 0:
            relevant_guides.append({
                'title': title,
                'url': guide_url,
                'score': relevance_score
            })
            
            if debug:
                print(f"🔍 Steam Community: Relevant guide (score {relevance_score}): {title[:40]}...")
    
    # Sort by relevance score (highest first)
    relevant_guides.sort(key=lambda g: g['score'], reverse=True)
    
    return relevant_guides

def extract_launch_options_from_guide_content_strict(guide_soup, guide_title, debug=False):
    """
    Extract launch options with STRICT validation to prevent false positives
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
    
    # Method 1: Look for code blocks and pre-formatted text (most reliable)
    code_elements = guide_content.find_all(['code', 'pre', 'tt', 'kbd', 'samp'])
    
    for element in code_elements:
        text = element.get_text(strip=True)
        if len(text) > 500:  # Skip very long code blocks
            continue
        
        # Extract validated launch options
        extracted_options = extract_validated_steam_launch_options(text, guide_title, debug)
        options.extend(extracted_options)
        
        if debug and extracted_options:
            print(f"🔍 Steam Community: Found {len(extracted_options)} options in code block")
    
    # Method 2: Look for paragraphs with launch option context (only if we haven't found many)
    if len(options) < 3:
        paragraphs = guide_content.find_all(['p', 'div', 'li'])
        
        for para in paragraphs[:20]:  # Limit for performance
            text = para.get_text(strip=True)
            
            if len(text) > 1000:  # Skip very long paragraphs
                continue
            
            text_lower = text.lower()
            
            # Only process paragraphs that explicitly mention launch options
            explicit_indicators = [
                'launch option', 'launch parameter', 'startup option', 'command line option',
                'launch command', 'startup parameter', 'add this to launch options'
            ]
            
            has_explicit_context = any(indicator in text_lower for indicator in explicit_indicators)
            
            if has_explicit_context:
                extracted_options = extract_validated_steam_launch_options(text, guide_title, debug)
                options.extend(extracted_options)
                
                if debug and extracted_options:
                    print(f"🔍 Steam Community: Found {len(extracted_options)} options in explicit paragraph")
    
    return options

def extract_validated_steam_launch_options(text, guide_title, debug=False):
    """
    Extract and validate Steam launch options from text with STRICT validation
    """
    options = []
    
    # Patterns for valid Steam launch options (more conservative)
    patterns = [
        r'(?<!\w)(-[a-zA-Z][a-zA-Z0-9_\-]{1,25})(?=\s|$|[^\w\-])',  # -command
        r'(?<!\w)(\+[a-zA-Z][a-zA-Z0-9_\-]{1,25}(?:\s+[a-zA-Z0-9_\-\.]{1,15})?)(?=\s|$|[^\w\-])',  # +command param
    ]
    
    if debug:
        print(f"🔍 Steam Community: Analyzing text: {text[:100]}...")
    
    all_matches = []
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            if isinstance(match, tuple):
                match = match[0] if match[0] else match[1]
            all_matches.append(match.strip())
    
    if debug:
        print(f"🔍 Steam Community: Raw matches found: {all_matches}")
    
    # Validate each match with STRICT criteria
    for match in all_matches:
        if validate_steam_option(match, debug=debug):
            # Get clean description
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
                print(f"🔍 Steam Community: REJECTED option: {match}")
    
    return options

def validate_steam_option(command: str, debug: bool = False) -> bool:
    """Production-ready validation for Steam Community options"""
    
    validator = LaunchOptionsValidator(ValidationLevel.PERMISSIVE)
    is_valid, reason = validator.validate_option(command, EngineType.SOURCE)
    
    if debug and not is_valid:
        print(f"🔍 Steam Community: Rejected '{command}' - {reason}")
    
    return is_valid

def get_clean_description_for_option(option, context_text, guide_title):
    """
    Get a clean description for a launch option
    """
    # Try to extract meaningful context
    lines = context_text.split('\n')
    
    for line in lines:
        if option in line:
            # Clean the line
            desc = line.strip()
            
            # Remove the option itself
            desc = desc.replace(option, '').strip()
            
            # Remove common prefixes
            prefixes_to_remove = ['add', 'use', 'try', 'set', 'put', 'include', 'apply']
            for prefix in prefixes_to_remove:
                if desc.lower().startswith(prefix):
                    desc = desc[len(prefix):].strip()
            
            # Clean up punctuation
            desc = re.sub(r'^[:\-\.,\s]+', '', desc)
            desc = re.sub(r'[:\-\.,\s]+$', '', desc)
            
            # If we have a meaningful description, use it
            if desc and len(desc) > 10 and len(desc) < 200:
                return desc
    
    # Fallback: generic description
    return f"Launch option from Steam Community guide: {guide_title[:50]}"

def final_validation_and_dedup(options, debug=False):
    """
    Final validation and deduplication step
    """
    validated_options = []
    seen_commands = set()
    
    for option in options:
        command = option.get('command', '').strip()
        
        # Skip if already seen
        if command.lower() in seen_commands:
            continue
        
        # Final validation check
        if validate_steam_option(command, debug=debug):
            seen_commands.add(command.lower())
            validated_options.append(option)
            
            if debug:
                print(f"🔍 Steam Community: Final validation passed for: {command}")
        else:
            if debug:
                print(f"🔍 Steam Community: Final validation failed for: {command}")
    
    # Limit total options to prevent spam
    return validated_options[:15]