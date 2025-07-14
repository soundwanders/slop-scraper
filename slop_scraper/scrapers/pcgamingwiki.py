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

def format_game_title_for_wiki(title):
    """Format game title for PCGamingWiki URL properly with security validation"""
    if not title or len(title) > 200: 
        return "invalid"
    
    # Replace common special characters
    formatted = title.replace(' ', '_')
    formatted = formatted.replace(':', '')
    formatted = formatted.replace('&', 'and')
    formatted = formatted.replace("'", '')
    formatted = formatted.replace('-', '_')
    
    # Security: Remove potentially dangerous characters
    formatted = re.sub(r'[<>"\'\\/]', '', formatted)
    
    # URL encode the result
    return quote(formatted)

def fetch_pcgamingwiki_launch_options(game_title, rate_limit=None, debug=False, test_results=None, 
                                    test_mode=False, rate_limiter=None, session_monitor=None):
    """Fetch launch options from PCGamingWiki with debugging and error handling"""
    
    # Security validation
    if not game_title or len(game_title) > 200:
        print("⚠️ Invalid game title for PCGamingWiki lookup")
        return []
    
    if rate_limiter:
        rate_limiter.wait_if_needed("scraping", domain="pcgamingwiki.com")
    elif rate_limit:
        time.sleep(rate_limit)
    
    # Format game title for URL
    formatted_title = format_game_title_for_wiki(game_title)
    if formatted_title == "invalid":
        print(f"⚠️ Could not format title for PCGamingWiki: {game_title}")
        return []
        
    url = f"https://www.pcgamingwiki.com/wiki/{formatted_title}"
    
    if debug:
        print(f"🔍 PCGamingWiki: Fetching {url}")
    
    try:
        # Better User-Agent that's less likely to be blocked
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
        
        # Use secure request handler
        response = SecureRequestHandler.make_secure_request(url, timeout=15, max_size_mb=5)
        
        # Record request for monitoring
        if session_monitor:
            session_monitor.record_request()
        
        if debug:
            print(f"🔍 PCGamingWiki: Response status {response.status_code}")
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            if debug:
                print(f"🔍 PCGamingWiki: Parsed HTML, length: {len(response.text)}")
            
            # More comprehensive section headers
            potential_section_ids = [
                "Command_line_arguments", 
                "Launch_options", 
                "Launch_commands",
                "Parameters", 
                "Launch_parameters",
                "Command-line_arguments",
                "Command_line_parameters",
                "Steam_launch_options",
                "Command_line_options",
                "Startup_parameters",
                "Execution_parameters"
            ]
            
            options = []
            sections_found = []
            
            # Method 1: Find tables in relevant sections
            for section_id in potential_section_ids:
                section = soup.find(id=section_id)
                if section:
                    sections_found.append(section_id)
                    if debug:
                        print(f"🔍 PCGamingWiki: Found section: {section_id}")
                    
                    # Navigate up to the heading element
                    if section.parent and section.parent.name.startswith('h'):
                        heading = section.parent
                        
                        # Find the next table after this heading
                        table = heading.find_next('table')
                        if table and 'wikitable' in table.get('class', []):
                            if debug:
                                print(f"🔍 PCGamingWiki: Found table in section {section_id}")
                            
                            rows = table.find_all('tr')[1:]  # Skip header row
                            for row_idx, row in enumerate(rows):
                                cells = row.find_all('td')
                                if len(cells) >= 2:
                                    command = cells[0].get_text(strip=True)
                                    description = cells[1].get_text(strip=True)
                                    
                                    if debug and row_idx < 3:  # Show first few for debugging
                                        print(f"🔍 PCGamingWiki: Row {row_idx}: {command} -> {description[:50]}...")
                                    
                                    # Security: Validate and limit field lengths
                                    if command and len(command) <= 100 and len(description) <= 500:
                                        # Security: Basic command validation
                                        if re.match(r'^[-+/]\w+', command.strip()):
                                            options.append({
                                                'command': command[:100],
                                                'description': description[:500],
                                                'source': 'PCGamingWiki'
                                            })
            
            if debug:
                print(f"🔍 PCGamingWiki: Found {len(sections_found)} sections: {sections_found}")
            
            # Method 2: list search with better context awareness
            if not options:
                if debug:
                    print("🔍 PCGamingWiki: No table results, trying list method...")
                
                for section_id in potential_section_ids:
                    section = soup.find(id=section_id)
                    if section and section.parent:
                        heading = section.parent
                        
                        # Look for lists within a reasonable distance from the heading
                        next_elements = heading.find_next_siblings(limit=5)
                        for element in next_elements:
                            list_element = element.find(['ul', 'ol']) if hasattr(element, 'find') else None
                            if not list_element and element.name in ['ul', 'ol']:
                                list_element = element
                            
                            if list_element:
                                if debug:
                                    print(f"🔍 PCGamingWiki: Found list in section {section_id}")
                                
                                list_items = list_element.find_all('li')
                                for item_idx, item in enumerate(list_items):
                                    text = item.get_text(strip=True)
                                    
                                    if debug and item_idx < 3:
                                        print(f"🔍 PCGamingWiki: List item {item_idx}: {text[:50]}...")
                                    
                                    # Security: Limit text processing length
                                    if len(text) > 1000:
                                        continue
                                    
                                    # Multiple separator patterns
                                    cmd, desc = None, None
                                    separators = [':', ' - ', ' – ', ' — ', ' | ']
                                    
                                    for sep in separators:
                                        if sep in text:
                                            parts = text.split(sep, 1)
                                            cmd = parts[0].strip()
                                            desc = parts[1].strip()
                                            break
                                    
                                    if not cmd:
                                        # Look for patterns like -command or --command at start
                                        match = re.search(r'^(-{1,2}\w+)', text)
                                        if match:
                                            cmd = match.group(1)
                                            desc = text.replace(cmd, '').strip()
                                        else:
                                            # Look for patterns anywhere in text
                                            match = re.search(r'(-{1,2}\w+)', text)
                                            if match:
                                                cmd = match.group(1)
                                                desc = text.replace(cmd, '').strip()
                                    
                                    # Security: Validate command and description
                                    if (cmd and cmd.strip() and len(cmd) <= 100 and 
                                        desc and len(desc) <= 500):
                                        # Basic security check for command format
                                        if re.match(r'^[-+/]\w+', cmd.strip()):
                                            options.append({
                                                'command': cmd[:100],
                                                'description': desc[:500],
                                                'source': 'PCGamingWiki'
                                            })
            
            # Method 3: code block search with better context
            if not options:
                if debug:
                    print("🔍 PCGamingWiki: No list results, trying code block method...")
                
                code_blocks = soup.find_all(['code', 'pre', 'kbd', 'samp'])[:15]  # Include more code-like elements
                for block_idx, block in enumerate(code_blocks):
                    text = block.get_text(strip=True)
                    
                    if debug and block_idx < 5:
                        print(f"🔍 PCGamingWiki: Code block {block_idx}: {text[:30]}...")
                    
                    # Security: Limit block text length
                    if len(text) > 200:
                        continue
                        
                    # Check if this looks like a command line argument
                    if text.startswith('-') or text.startswith('/') or text.startswith('+'):
                        # Basic validation
                        if re.match(r'^[-+/]\w+', text):
                            # Look for description in surrounding context
                            desc = "No description available"
                            
                            # Check parent elements for description
                            parent = block.parent
                            if parent:
                                parent_text = parent.get_text(strip=True)
                                if len(parent_text) > len(text) and len(parent_text) <= 500:
                                    desc = parent_text.replace(text, '', 1).strip()
                                
                                # Also check siblings
                                if desc == "No description available" or len(desc) < 10:
                                    next_sibling = parent.find_next_sibling()
                                    if next_sibling:
                                        sibling_text = next_sibling.get_text(strip=True)
                                        if len(sibling_text) <= 300:
                                            desc = sibling_text
                            
                            options.append({
                                'command': text[:100],
                                'description': desc[:500],
                                'source': 'PCGamingWiki'
                            })
            
            # Method 4: text pattern search with better validation
            if not options:
                if debug:
                    print("🔍 PCGamingWiki: No code block results, trying text pattern method...")
                
                # Look for paragraphs that might contain launch options
                paragraphs = soup.find_all(['p', 'div'])[:30]  # Increased search scope
                
                for para_idx, para in enumerate(paragraphs):
                    text = para.get_text()
                    
                    # Security: Limit text processing
                    if len(text) > 1000:
                        continue
                    
                    # Look for launch option keywords in the paragraph
                    if any(keyword in text.lower() for keyword in ['launch', 'command', 'argument', 'parameter', 'option']):
                        if debug and para_idx < 5:
                            print(f"🔍 PCGamingWiki: Relevant paragraph {para_idx}: {text[:50]}...")
                        
                        # Look for patterns like -command, --long-option, +option, /option
                        matches = re.finditer(r'(?:^|\s)(-{1,2}\w[\w\-]*|\+\w[\w\-]*|\/\w[\w\-]*)(?:\s|$|[,.!?])', text)
                        for match in matches:
                            cmd = match.group(1)
                            if len(cmd) <= 50:  # Security: reasonable command length
                                # Extract surrounding context for description
                                start_pos = max(0, match.start() - 50)
                                end_pos = min(len(text), match.end() + 100)
                                context = text[start_pos:end_pos].strip()
                                
                                options.append({
                                    'command': cmd,
                                    'description': context[:500],  # Limit description
                                    'source': 'PCGamingWiki'
                                })
                
                # De-duplicate by command (limit total for security)
                seen_commands = set()
                unique_options = []
                for cmd in options[:20]:  # Limit results
                    if cmd['command'] not in seen_commands:
                        seen_commands.add(cmd['command'])
                        unique_options.append(cmd)
                options = unique_options
            
            # Security: Limit total options returned
            options = options[:50]
            
            # Update test statistics
            if test_mode and test_results:
                source = 'PCGamingWiki'
                if source not in test_results['options_by_source']:
                    test_results['options_by_source'][source] = 0
                test_results['options_by_source'][source] += len(options)
            
            if debug:
                print(f"🔍 PCGamingWiki: Final result: {len(options)} validated options")
                if options:
                    print(f"🔍 PCGamingWiki: Sample options: {[opt['command'] for opt in options[:3]]}")
            
            return options
            
        elif response.status_code == 404:
            if debug:
                print(f"🔍 PCGamingWiki: Page not found for '{game_title}'")
            
            # Try alternative title formats with better logic
            alt_titles = []
            
            # Remove subtitle after colon
            if ':' in game_title:
                alt_titles.append(game_title.split(':')[0].strip())
            
            # Remove edition/version info
            edition_patterns = [r'\s+(Edition|Version|HD|Remastered|Director\'s Cut|Enhanced|Definitive).*$']
            for pattern in edition_patterns:
                alt_title = re.sub(pattern, '', game_title, flags=re.IGNORECASE).strip()
                if alt_title != game_title and alt_title not in alt_titles:
                    alt_titles.append(alt_title)
            
            # Try alternative titles (prevent infinite recursion)
            for alt_title in alt_titles[:2]:  # Limit to 2 alternatives
                if len(alt_title) > 3:
                    if debug:
                        print(f"🔍 PCGamingWiki: Trying alternate title: {alt_title}")
                    # Prevent infinite recursion by not passing rate_limiter/session_monitor
                    result = fetch_pcgamingwiki_launch_options(
                        alt_title, rate_limit=rate_limit, debug=debug, 
                        test_results=test_results, test_mode=test_mode
                    )
                    if result:
                        return result
            
            return []
            
        else:
            if debug:
                print(f"🔍 PCGamingWiki: HTTP {response.status_code} for '{game_title}'")
            return []
            
    except Exception as e:
        if session_monitor:
            session_monitor.record_error()
        print(f"🔍 PCGamingWiki: Error for '{game_title}': {e}")
        if debug:
            import traceback
            print(f"🔍 PCGamingWiki: Full traceback: {traceback.format_exc()}")
        return []