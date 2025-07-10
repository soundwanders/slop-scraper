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
    """Fetch launch options from Steam Community guides with security controls"""
    
    # Security validation
    try:
        app_id_int = int(app_id)
        if app_id_int <= 0 or app_id_int > 999999999:
            print(f"⚠️ Invalid app_id: {app_id}")
            return []
    except (ValueError, TypeError):
        print(f"⚠️ Invalid app_id format: {app_id}")
        return []
    
    if rate_limiter:
        rate_limiter.wait_if_needed("scraping")  # ← "Scraping" type
    elif rate_limit:
        time.sleep(rate_limit)
    
    # Search for guides containing "launch options" for this game
    url = f"https://steamcommunity.com/app/{app_id_int}/guides/"
    
    if debug:
        print(f"🔒 Fetching Steam Community guides securely from: {url}")
    
    options = []
    try:
        # Use secure request handler
        response = SecureRequestHandler.make_secure_request(url, timeout=15, max_size_mb=3)
        
        # Record request for monitoring
        if session_monitor:
            session_monitor.record_request()
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            guides = soup.find_all('div', class_='guide_item')
            
            # Security: Limit number of guides processed
            guides = guides[:10] if guides else []
            
            relevant_guides = []
            for guide in guides:
                title_elem = guide.find('div', class_='guide_title')
                if title_elem:
                    title = title_elem.text.lower()
                    
                    # Security: Validate title length
                    if len(title) > 200:
                        continue
                        
                    if any(keyword in title for keyword in ['launch', 'command', 'option', 'parameter', 'argument', 'fps', 'performance']):
                        link_elem = guide.find('a')
                        if link_elem and 'href' in link_elem.attrs:
                            guide_url = link_elem['href']
                            
                            # Security: Validate URL
                            if (guide_url.startswith('https://steamcommunity.com/') and 
                                len(guide_url) < 500):
                                relevant_guides.append({
                                    'title': title_elem.text[:200],  # Limit title length
                                    'url': guide_url
                                })
            
            if debug:
                print(f"🔒 Found {len(relevant_guides)} relevant guides")
            
            # Process the most relevant guides (limit to 3 to avoid overloading)
            for guide in relevant_guides[:3]:
                try:
                    if debug:
                        print(f"🔒 Processing guide: {guide['title']}")
                    
                    # Apply scraping rate limiting between guide requests
                    if rate_limiter:
                        rate_limiter.wait_if_needed("scraping")  # ← Scraping type
                    elif rate_limit:
                        time.sleep(rate_limit)
                    
                    # Use secure request handler for guide content
                    guide_response = SecureRequestHandler.make_secure_request(
                        guide['url'], timeout=20, max_size_mb=2
                    )
                    
                    # Record request
                    if session_monitor:
                        session_monitor.record_request()
                    
                    if guide_response.status_code == 200:
                        guide_soup = BeautifulSoup(guide_response.text, 'html.parser')
                        guide_content = guide_soup.find('div', class_='guide_body')
                        
                        if guide_content:
                            # Method 1: Look for code blocks or pre elements (common in guides)
                            code_blocks = guide_content.find_all(['code', 'pre'])[:5]  # Limit for security
                            for block in code_blocks:
                                text = block.get_text(strip=True)
                                
                                # Security: Limit text length
                                if len(text) > 500:
                                    continue
                                
                                # Check if this looks like launch options text
                                if any(symbol in text for symbol in ['-', '+', '/']):
                                    # Try to identify individual options
                                    option_matches = re.finditer(r'(?:^|\s)(-{1,2}\w[\w\-]*|\+\w[\w\-]*|\/\w[\w\-]*)(?:\s|$)', text)
                                    for match in option_matches:
                                        cmd = match.group(1)
                                        
                                        # Security: Validate command length and format
                                        if len(cmd) <= 50 and re.match(r'^[-+/]\w+', cmd):
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
                                            
                                            # Security: Limit description length
                                            desc = desc[:300] + "..." if len(desc) > 300 else desc
                                            
                                            options.append({
                                                'command': cmd,
                                                'description': desc,
                                                'source': 'Steam Community'
                                            })
                            
                            # Method 2: Look for paragraphs with launch options patterns
                            if not any(opt['source'] == 'Steam Community' for opt in options):
                                paragraphs = guide_content.find_all(['p', 'li'])[:15]  # Limit for security
                                for p in paragraphs:
                                    text = p.get_text(strip=True)
                                    
                                    # Security: Limit text processing
                                    if len(text) > 1000:
                                        continue
                                    
                                    if 'launch' in text.lower() and any(symbol in text for symbol in ['-', '+', '/']):
                                        # Extract commands that look like options
                                        option_matches = re.finditer(r'(?:^|\s)(-{1,2}\w[\w\-]*|\+\w[\w\-]*|\/\w[\w\-]*)(?:\s|$)', text)
                                        for match in option_matches:
                                            cmd = match.group(1)
                                            
                                            # Security: Validate command
                                            if len(cmd) <= 50 and re.match(r'^[-+/]\w+', cmd):
                                                desc = text[:300] + "..." if len(text) > 300 else text
                                                options.append({
                                                    'command': cmd,
                                                    'description': desc,
                                                    'source': 'Steam Community'
                                                })
                        
                except Exception as guide_e:
                    if session_monitor:
                        session_monitor.record_error()
                    print(f"🔒 Error processing guide {guide['url']}: {guide_e}")
                    continue
            
            # Security: Limit total options and deduplicate
            seen_commands = set()
            filtered_options = []
            for option in options[:30]: 
                cmd = option['command'].lower()
                if cmd not in seen_commands and len(filtered_options) < 20:
                    seen_commands.add(cmd)
                    filtered_options.append(option)
            
            options = filtered_options
            
            # If no specific options found but guides exist, add guide references (limited)
            if not options and relevant_guides:
                for guide in relevant_guides[:2]:
                    options.append({
                        'command': f"See guide: {guide['title'][:50]}",
                        'description': f"This guide may contain launch options: {guide['url']}",
                        'source': 'Steam Community'
                    })
            
            # Update test statistics
            if test_mode and test_results is not None:
                source = 'Steam Community' 
                test_results.setdefault('options_by_source', {})
                test_results['options_by_source'].setdefault(source, 0)
                test_results['options_by_source'][source] += len(options)

            if debug:
                print(f"🔒 Found {len(options)} validated options from Steam Community")
            
            return options
            
    except Exception as e:
        if session_monitor:
            session_monitor.record_error()
        print(f"🔒 Error fetching from Steam Community: {e}")
    
    return []