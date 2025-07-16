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
    Steam Community scraper 
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
            
            # Look for modern Steam Community guide structure
            possible_guide_selectors = [
                'div.guide_item',           # Old selector
                'div[class*="guide"]',      # Any div with "guide" in class
                'div[class*="Guide"]',      # Capitalized version
                'div[class*="workshopItem"]', # Workshop items
                'div[class*="item"]',       # Generic items
                'a[href*="/sharedfiles/filedetails/"]',  # Direct links to guides
                'div[class*="shared_file"]', # Shared files
                'div[class*="guide_item"]',
                'div[class*="Guide"]', 
                'div[class*="workshopItem"]',
                'a[href*="/guides/"]',
                'div[class*="recommendation"]',
                'div[class*="review"]'
            ]
  
            guides_found = []
            for selector in possible_guide_selectors:
                elements = soup.select(selector)
                if elements:
                    guides_found.extend(elements)
                    if debug:
                        print(f"🔍 Steam Community: Found {len(elements)} elements with selector '{selector}'")
            
            # Remove duplicates while preserving order
            seen = set()
            unique_guides = []
            for guide in guides_found:
                guide_id = id(guide)  # Use object id to identify unique elements
                if guide_id not in seen:
                    seen.add(guide_id)
                    unique_guides.append(guide)
            
            guides = unique_guides
            
            if debug:
                print(f"🔍 Steam Community: Total unique guides found: {len(guides)}")
            
            # Method 2: If no guides found with selectors, search for guide URLs in all links
            if not guides:
                if debug:
                    print("🔍 Steam Community: No guides found with selectors, searching all links...")
                
                all_links = soup.find_all('a', href=True)
                guide_links = []
                
                for link in all_links:
                    href = link.get('href', '')
                    if '/sharedfiles/filedetails/' in href or '/guides/' in href:
                        guide_links.append(link)
                        if debug and len(guide_links) <= 3:
                            print(f"🔍 Steam Community: Found guide link: {href}")
                
                guides = guide_links
                if debug:
                    print(f"🔍 Steam Community: Found {len(guide_links)} guide links")
            
            # Method 3: Search page text for launch-option related content
            if not guides:
                if debug:
                    print("🔍 Steam Community: No guide links found, searching page text...")
                
                page_text = soup.get_text()
                if any(keyword in page_text.lower() for keyword in 
                       ['launch', 'command', 'option', 'parameter', 'fps', 'performance']):
                    
                    # Extract potential launch options from page text
                    lines = page_text.split('\n')
                    for line in lines:
                        if (any(keyword in line.lower() for keyword in 
                                ['launch', 'command', 'option']) and
                            re.search(r'-\w+', line)):
                            
                            # Extract commands from this line
                            commands = re.findall(r'(-{1,2}\w[\w\-]*)', line)
                            for cmd in commands:
                                if len(cmd) <= 50:
                                    options.append({
                                        'command': cmd,
                                        'description': f"Found on Steam Community page: {line.strip()[:100]}",
                                        'source': 'Steam Community'
                                    })
                                    
                                    if debug:
                                        print(f"🔍 Steam Community: Found text option: {cmd}")
            
            # Much more comprehensive keyword filtering
            relevant_guides = []
            
            # Launch Options Keywords list
            launch_keywords = [
                # Direct launch option terms
                'launch', 'command', 'option', 'parameter', 'argument', 'startup',
                # Performance & technical terms  
                'fps', 'performance', 'optimize', 'optimization', 'boost', 'speed',
                'lag', 'stutter', 'smooth', 'framerate', 'frame rate',
                # Configuration terms
                'config', 'configuration', 'setting', 'settings', 'setup', 'install',
                'fix', 'fixing', 'solution', 'resolve', 'problem', 'issue', 'crash',
                'tweak', 'tweaking', 'mod', 'modify', 'adjust',
                # Graphics & display terms
                'graphics', 'visual', 'display', 'resolution', 'fullscreen', 'windowed',
                'vsync', 'anti-aliasing', 'quality', 'low', 'high', 'ultra',
                # Audio terms  
                'audio', 'sound', 'music', 'volume',
                # Platform specific
                'linux', 'proton', 'wine', 'compatibility', 'steam deck',
                # Generic improvement terms
                'improve', 'better', 'enhancement', 'guide', 'tutorial', 'how to',
                'tips', 'tricks', 'help', 'support'
            ]
            
            # Lenient filtering to scrape more guides and prevent missing options
            for guide in guides[:30]: 
                # Extract title from various possible locations
                title = None
                
                # Try different ways to get the title
                title_selectors = [
                    '.guide_title',
                    '.workshopItemTitle', 
                    '.title',
                    'h3',
                    'h4',
                    '.item_title'
                ]
                
                for selector in title_selectors:
                    title_elem = guide.select_one(selector)
                    if title_elem:
                        title = title_elem.get_text(strip=True)
                        break
                
                # If no title found in child elements, check the element itself
                if not title:
                    title = guide.get_text(strip=True)
                    # Limit title length for safety
                    if len(title) > 200:
                        title = title[:200]
                
                if title and len(title) <= 200:
                    title_lower = title.lower()
                    
                    if debug and len(relevant_guides) < 10:  # Show more debug info
                        print(f"🔍 Steam Community: Checking guide: {title[:50]}...")
                    
                    # If ANY keyword matches, include the guide
                    guide_relevant = any(keyword in title_lower for keyword in launch_keywords)
                    
                    # Also include guides that have certain patterns even without keywords
                    pattern_matches = [
                        # Version numbers (like "7.39c") often indicate config guides
                        re.search(r'\d+\.\d+', title_lower),
                        # Brackets often indicate important guides [2025], [FIX], etc.
                        '[' in title and ']' in title,
                        # Keywords that often appear in technical guides
                        any(term in title_lower for term in ['meta', 'build', 'setup', 'config', 'install'])
                    ]
                    
                    if guide_relevant or any(pattern_matches):
                        # Get the guide URL
                        guide_url = None
                        
                        if guide.name == 'a' and guide.get('href'):
                            guide_url = guide['href']
                        else:
                            link_elem = guide.find('a', href=True)
                            if link_elem:
                                guide_url = link_elem['href']
                        
                        if guide_url:
                            # Ensure it's a full URL
                            if guide_url.startswith('/'):
                                guide_url = 'https://steamcommunity.com' + guide_url
                            elif not guide_url.startswith('http'):
                                guide_url = 'https://steamcommunity.com/' + guide_url
                            
                            if len(guide_url) < 500:  # Security check
                                relevant_guides.append({
                                    'title': title[:200],
                                    'url': guide_url
                                })
                                
                                if debug:
                                    match_reason = "keyword" if guide_relevant else "pattern"
                                    print(f"🔍 Steam Community: Relevant guide found ({match_reason}): {title[:30]}...")
            
            if debug:
                print(f"🔍 Steam Community: Found {len(relevant_guides)} relevant guides")
            
            # Process relevant guides (increased limit)
            for guide in relevant_guides[:5]:  # Increased from 3 to 5
                try:
                    if debug:
                        print(f"🔍 Steam Community: Processing guide: {guide['title'][:30]}...")
                    
                    # Rate limiting between guide requests
                    if rate_limiter:
                        rate_limiter.wait_if_needed("scraping", domain="steamcommunity.com")
                    elif rate_limit:
                        time.sleep(rate_limit)
                    
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
                        
                        # Look for guide content in various containers
                        content_selectors = [
                            '.guide_body',
                            '.subSectionContents',
                            '.guide_content',
                            '.workshopItemDescription',
                            '.content'
                        ]
                        
                        guide_content = None
                        for selector in content_selectors:
                            content = guide_soup.select_one(selector)
                            if content:
                                guide_content = content
                                break
                        
                        if not guide_content:
                            # Fallback: use the entire body
                            guide_content = guide_soup.find('body')
                        
                        if guide_content:
                            # Extract launch options from guide content
                            extracted_options = extract_launch_options_from_content(
                                guide_content, 
                                guide['title'],
                                debug=debug
                            )
                            options.extend(extracted_options)
                            
                            if debug and extracted_options:
                                print(f"🔍 Steam Community: Extracted {len(extracted_options)} options from guide")
                    
                except Exception as guide_e:
                    if session_monitor:
                        session_monitor.record_error()
                    if debug:
                        print(f"🔍 Steam Community: Error processing guide {guide['url']}: {guide_e}")
                    continue
            
            # Remove duplicates and limit results
            seen_commands = set()
            filtered_options = []
            for option in options[:30]:
                cmd = option['command'].lower()
                if cmd not in seen_commands and len(filtered_options) < 20:
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
                print(f"🔍 Steam Community: Final result: {len(options)} validated options")
                for opt in options[:3]:
                    print(f"🔍 Steam Community:   {opt['command']}: {opt['description'][:40]}...")
            
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

def extract_launch_options_from_content(content, guide_title, debug=False):
    """Extract launch options from guide content with detection"""
    options = []
    
    # Look for code blocks, pre elements, and quoted text
    code_elements = content.find_all(['code', 'pre', 'tt', 'kbd'])
    
    for element in code_elements:
        text = element.get_text(strip=True)
        if len(text) > 500:
            continue
        
        # Look for launch option patterns
        if any(char in text for char in ['-', '+', '/']):
            # Regex to catch more launch option patterns
            commands = re.findall(r'(-{1,2}[\w\-]+(?:=[\w\-]+)?|\+[\w\-]+(?:=[\w\-]+)?|/[\w\-]+)', text)
            
            for cmd in commands:
                if 2 <= len(cmd) <= 50:  # Reasonable length limits
                    # Get context from surrounding text
                    parent_text = element.parent.get_text(strip=True) if element.parent else ""
                    desc = parent_text[:300] if len(parent_text) > len(text) else f"From guide: {guide_title}"
                    
                    options.append({
                        'command': cmd,
                        'description': desc,
                        'source': 'Steam Community'
                    })
                    
                    if debug:
                        print(f"🔍 Steam Community: Found code option: {cmd}")
    
    # Look for paragraphs mentioning launch options
    if not options:
        paragraphs = content.find_all(['p', 'div'])
        
        for para in paragraphs[:20]:  # Limit for performance
            text = para.get_text()
            
            if len(text) > 1000:
                continue
            
            # Detection - look for more patterns
            launch_indicators = ['launch', 'command', 'option', 'parameter', 'startup']
            has_launch_term = any(term in text.lower() for term in launch_indicators)
            has_command_chars = any(char in text for char in ['-', '+', '/'])
            
            if has_launch_term and has_command_chars:
                # Regex to catch more launch option patterns
                commands = re.findall(r'(-{1,2}[\w\-]+(?:=[\w\-]+)?|\+[\w\-]+(?:=[\w\-]+)?|/[\w\-]+)', text)
                
                for cmd in commands:
                    if 2 <= len(cmd) <= 50:  # Reasonable length limits
                        desc = text[:250] if len(text) <= 250 else text[:250] + "..."
                        
                        options.append({
                            'command': cmd,
                            'description': desc,
                            'source': 'Steam Community'
                        })
                        
                        if debug:
                            print(f"🔍 Steam Community: Found paragraph option: {cmd}")
    
    return options