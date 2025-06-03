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
    """Fetch launch options from PCGamingWiki with security controls"""
    
    # Security validation
    if not game_title or len(game_title) > 200:
        print("⚠️ Invalid game title for PCGamingWiki lookup")
        return []
    
    if rate_limiter:
        rate_limiter.wait_if_needed("scraping")  # ← "Scraping" type
    elif rate_limit:
        time.sleep(rate_limit)
    
    # Format game title for URL
    formatted_title = format_game_title_for_wiki(game_title)
    if formatted_title == "invalid":
        print(f"⚠️ Could not format title for PCGamingWiki: {game_title}")
        return []
        
    url = f"https://www.pcgamingwiki.com/wiki/{formatted_title}"
    
    if debug:
        print(f"🔒 Fetching PCGamingWiki data securely from: {url}")
    
    try:
        # Use secure request handler
        response = SecureRequestHandler.make_secure_request(url, timeout=15, max_size_mb=5)
        
        # Record request for monitoring
        if session_monitor:
            session_monitor.record_request()
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try to find more section headers that could contain launch options
            potential_section_ids = [
                "Command_line_arguments", 
                "Launch_options", 
                "Launch_commands",
                "Parameters", 
                "Launch_parameters",
                "Command-line_arguments",
                "Command_line_parameters",
                "Steam_launch_options"
            ]
            
            options = []
            
            # Method 1: Find tables in relevant sections
            for section_id in potential_section_ids:
                section = soup.find(id=section_id)
                if section:
                    if debug:
                        print(f"🔒 Found section: {section_id}")
                    
                    # Navigate up to the heading element
                    if section.parent and section.parent.name.startswith('h'):
                        heading = section.parent
                        
                        # Find the next table after this heading
                        table = heading.find_next('table')
                        if table and 'wikitable' in table.get('class', []):
                            if debug:
                                print(f"🔒 Found table in section {section_id}")
                            
                            rows = table.find_all('tr')[1:]  # Skip header row
                            for row in rows:
                                cells = row.find_all('td')
                                if len(cells) >= 2:
                                    command = cells[0].get_text(strip=True)
                                    description = cells[1].get_text(strip=True)
                                    
                                    # Security: Validate and limit field lengths
                                    if command and len(command) <= 100 and len(description) <= 500:
                                        # Security: Basic command validation
                                        if re.match(r'^[-+/]\w+', command.strip()):
                                            options.append({
                                                'command': command[:100],
                                                'description': description[:500],
                                                'source': 'PCGamingWiki'
                                            })
            
            # Method 2: Look for lists in relevant sections
            if not options:
                for section_id in potential_section_ids:
                    section = soup.find(id=section_id)
                    if section and section.parent:
                        heading = section.parent
                        
                        # Find lists (ul/ol) after the heading
                        list_element = heading.find_next(['ul', 'ol'])
                        if list_element:
                            list_items = list_element.find_all('li')
                            for item in list_items:
                                text = item.get_text(strip=True)
                                
                                # Security: Limit text processing length
                                if len(text) > 1000:
                                    continue
                                
                                # Try to separate command from description
                                cmd, desc = None, None
                                if ':' in text:
                                    parts = text.split(':', 1)
                                    cmd = parts[0].strip()
                                    desc = parts[1].strip()
                                elif ' - ' in text:
                                    parts = text.split(' - ', 1)
                                    cmd = parts[0].strip()
                                    desc = parts[1].strip()
                                elif ' – ' in text:
                                    parts = text.split(' – ', 1)
                                    cmd = parts[0].strip()
                                    desc = parts[1].strip()
                                else:
                                    # If we can't split, look for patterns like -command or --command
                                    match = re.search(r'(-{1,2}\w+)', text)
                                    if match:
                                        cmd = match.group(1)
                                        desc = text.replace(cmd, '').strip()
                                    else:
                                        cmd = text
                                        desc = "No description available"
                                
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
            
            # Method 3: Look for code blocks or pre elements (limited for security)
            if not options:
                code_blocks = soup.find_all(['code', 'pre'])[:10]  # Limit processing
                for block in code_blocks:
                    text = block.get_text(strip=True)
                    
                    # Security: Limit block text length
                    if len(text) > 200:
                        continue
                        
                    # Check if this looks like a command line argument
                    if text.startswith('-') or text.startswith('/') or text.startswith('+'):
                        # Basic validation
                        if re.match(r'^[-+/]\w+', text):
                            parent_text = block.parent.get_text(strip=True) if block.parent else ""
                            if len(parent_text) > len(text) and len(parent_text) <= 500:
                                desc = parent_text.replace(text, '', 1).strip()
                            else:
                                desc = "No description available"
                            
                            options.append({
                                'command': text[:100],
                                'description': desc[:500],
                                'source': 'PCGamingWiki'
                            })
            
            # Method 4: Look for text with typical command patterns (limited)
            if not options:
                potential_commands = []
                tags = soup.find_all(['p', 'li'])[:20]  # Limit processing for security
                
                for tag in tags:
                    text = tag.get_text()
                    
                    # Security: Limit text processing
                    if len(text) > 1000:
                        continue
                        
                    # Look for patterns like -command, --long-option, +option, /option
                    matches = re.finditer(r'(?:^|\s)(-{1,2}\w[\w\-]*|\+\w[\w\-]*|\/\w[\w\-]*)(?:\s|$)', text)
                    for match in matches:
                        cmd = match.group(1)
                        if len(cmd) <= 50:  # Security: reasonable command length
                            potential_commands.append({
                                'command': cmd,
                                'description': text[:500],  # Limit description
                                'source': 'PCGamingWiki'
                            })
                
                # De-duplicate by command (limit total for security)
                seen_commands = set()
                for cmd in potential_commands[:20]:  # Limit results
                    if cmd['command'] not in seen_commands:
                        seen_commands.add(cmd['command'])
                        options.append(cmd)
            
            # Security: Limit total options returned
            options = options[:50]
            
            # Update test statistics
            if test_mode and test_results:
                source = 'PCGamingWiki'
                if source not in test_results['options_by_source']:
                    test_results['options_by_source'][source] = 0
                test_results['options_by_source'][source] += len(options)
            
            if debug:
                print(f"🔒 Found {len(options)} validated options from PCGamingWiki")
            
            return options
            
        elif response.status_code == 404:
            if debug:
                print(f"🔒 PCGamingWiki page not found for '{game_title}'")
            # Try alternative title formats (security: limit recursion)
            alt_title = game_title.split(':')[0] if ':' in game_title else None
            if alt_title and alt_title != game_title and len(alt_title) > 3:
                if debug:
                    print(f"🔒 Trying alternate title: {alt_title}")
                # Prevent infinite recursion by not passing rate_limiter/session_monitor
                return fetch_pcgamingwiki_launch_options(
                    alt_title, rate_limit=rate_limit, debug=debug, 
                    test_results=test_results, test_mode=test_mode
                )
            return []
        else:
            if debug:
                print(f"🔒 PCGamingWiki returned status code {response.status_code}")
            return []
            
    except Exception as e:
        if session_monitor:
            session_monitor.record_error()
        print(f"🔒 Error fetching from PCGamingWiki: {e}")
        return []