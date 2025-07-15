import re
import time
import os
from bs4 import BeautifulSoup
from urllib.parse import quote
import random

try:
    # Try relative imports first (when run as module)
    from ..utils.security_config import SecureRequestHandler
except ImportError:
    # Fall back to absolute imports (when run directly)
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.security_config import SecureRequestHandler

def get_cloudflare_bypass_headers():
    """Get headers designed to bypass Cloudflare protection"""
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ]
    
    return {
        'User-Agent': random.choice(user_agents),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Sec-CH-UA': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        'Sec-CH-UA-Mobile': '?0',
        'Sec-CH-UA-Platform': '"Windows"',
        'Cache-Control': 'max-age=0',
        'Referer': 'https://www.pcgamingwiki.com/',
    }

def make_cloudflare_request(url, debug=False):
    """Make request with Cloudflare bypass techniques"""
    import requests
    
    headers = get_cloudflare_bypass_headers()
    
    session = requests.Session()
    
    # Add random delay to appear more human
    time.sleep(random.uniform(1.0, 3.0))
    
    try:
        if debug:
            print(f"🔍 Attempting Cloudflare bypass for: {url}")
        
        response = session.get(
            url,
            headers=headers,
            timeout=20,
            allow_redirects=True
        )
        
        if debug:
            print(f"🔍 Response status: {response.status_code}")
            if 'cf-mitigated' in response.headers:
                print(f"🔍 Cloudflare mitigation detected: {response.headers.get('cf-mitigated')}")
        
        return response
        
    except Exception as e:
        if debug:
            print(f"🔍 Request failed: {e}")
        raise

def format_game_title_for_wiki(title):
    """Format game title for PCGamingWiki URL properly"""
    if not title or len(title) > 200: 
        return "invalid"
    
    # More comprehensive title formatting
    formatted = title.strip()
    
    # Handle common patterns
    formatted = formatted.replace(' ', '_')
    formatted = formatted.replace(':', '')
    formatted = formatted.replace('&', 'and')
    formatted = formatted.replace("'", '')
    formatted = formatted.replace('-', '_')
    formatted = formatted.replace('.', '')
    formatted = formatted.replace(',', '')
    formatted = formatted.replace('!', '')
    formatted = formatted.replace('?', '')
    
    # Remove problematic characters
    formatted = re.sub(r'[<>"\'\\/\[\](){}]', '', formatted)
    
    # Handle multiple underscores
    formatted = re.sub(r'_+', '_', formatted)
    formatted = formatted.strip('_')
    
    # URL encode the result
    return quote(formatted)

def fetch_pcgamingwiki_launch_options(game_title, rate_limit=None, debug=False, test_results=None, 
                                    test_mode=False, rate_limiter=None, session_monitor=None):
    """
    PCGamingWiki scraper with Cloudflare bypass and improved error handling
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
    
    # Format game title for URL
    formatted_title = format_game_title_for_wiki(game_title)
    if formatted_title == "invalid":
        if debug:
            print(f"⚠️ Could not format title for PCGamingWiki: {game_title}")
        return []
        
    url = f"https://www.pcgamingwiki.com/wiki/{formatted_title}"
    
    if debug:
        print(f"🔍 PCGamingWiki: Attempting to fetch {url}")
    
    try:
        # FIRST: Try with Cloudflare bypass
        response = make_cloudflare_request(url, debug=debug)
        
        # Record request for monitoring
        if session_monitor:
            session_monitor.record_request()
        
        if response.status_code == 403:
            if debug:
                print(f"🔍 PCGamingWiki: Still blocked (403), trying alternative approach...")
            
            # Try a different approach - use a different user agent and delay
            time.sleep(random.uniform(2.0, 5.0))
            
            # Try again with different headers
            alt_headers = get_cloudflare_bypass_headers()
            alt_headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15'
            
            import requests
            response = requests.get(url, headers=alt_headers, timeout=20)
            
            if debug:
                print(f"🔍 PCGamingWiki: Second attempt status: {response.status_code}")
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            if debug:
                print(f"🔍 PCGamingWiki: Successfully parsed HTML, length: {len(response.text)} characters")
            
            options = []
            
            # SEARCH METHOD: Look for any content that might contain launch options
            launch_keywords = [
                'command', 'launch', 'option', 'parameter', 'argument', 
                'startup', 'execution', 'line', 'cli'
            ]
            
            # Method 1: Search all headings for relevant sections
            all_headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            relevant_sections = []
            
            for heading in all_headings:
                heading_text = heading.get_text().lower()
                if any(keyword in heading_text for keyword in launch_keywords):
                    relevant_sections.append(heading)
                    if debug:
                        print(f"🔍 PCGamingWiki: Found relevant section: '{heading.get_text().strip()}'")
            
            # Method 2: For each relevant section, extract launch options
            for section in relevant_sections:
                current = section
                
                # Look for tables, lists, or paragraphs after this heading
                for _ in range(10):  # Check next 10 siblings
                    current = current.find_next_sibling()
                    if not current:
                        break
                    
                    # Check tables
                    if current.name == 'table':
                        rows = current.find_all('tr')
                        if len(rows) > 1:
                            for row in rows[1:]:  # Skip header
                                cells = row.find_all(['td', 'th'])
                                if len(cells) >= 2:
                                    command = cells[0].get_text(strip=True)
                                    description = cells[1].get_text(strip=True)
                                    
                                    if (command and description and 
                                        len(command) <= 100 and len(description) <= 500 and
                                        re.match(r'^[-+/]\w+', command.strip())):
                                        
                                        options.append({
                                            'command': command[:100],
                                            'description': description[:500],
                                            'source': 'PCGamingWiki'
                                        })
                                        
                                        if debug:
                                            print(f"🔍 PCGamingWiki: Found table option: {command}")
                        break
                    
                    # Check lists
                    elif current.name in ['ul', 'ol']:
                        items = current.find_all('li')
                        for item in items:
                            text = item.get_text(strip=True)
                            if len(text) > 1000:
                                continue
                            
                            # Extract command and description
                            cmd, desc = None, None
                            
                            # Try different parsing methods
                            for sep in [':', ' - ', ' – ', ' — ', ' | ']:
                                if sep in text:
                                    parts = text.split(sep, 1)
                                    if re.match(r'^[-+/]\w+', parts[0].strip()):
                                        cmd = parts[0].strip()
                                        desc = parts[1].strip()
                                        break
                            
                            if not cmd:
                                match = re.search(r'^(-{1,2}\w+|\+\w+|/\w+)', text)
                                if match:
                                    cmd = match.group(1)
                                    desc = text.replace(cmd, '').strip()
                            
                            if cmd and desc and len(cmd) <= 100 and len(desc) <= 500:
                                options.append({
                                    'command': cmd[:100],
                                    'description': desc[:500],
                                    'source': 'PCGamingWiki'
                                })
                                
                                if debug:
                                    print(f"🔍 PCGamingWiki: Found list option: {cmd}")
                        break
            
            # Method 3: If no structured content found, search all text
            if not options:
                if debug:
                    print("🔍 PCGamingWiki: No structured content found, searching all text...")
                
                # Search for launch option patterns in all text
                all_text = soup.get_text()
                
                # Look for sections mentioning launch options
                lines = all_text.split('\n')
                for i, line in enumerate(lines):
                    if (any(keyword in line.lower() for keyword in launch_keywords) and
                        any(char in line for char in ['-', '+', '/'])):
                        
                        # Look at this line and surrounding lines
                        context_start = max(0, i - 2)
                        context_end = min(len(lines), i + 3)
                        context_lines = lines[context_start:context_end]
                        context_text = ' '.join(context_lines)
                        
                        # Extract potential commands
                        matches = re.finditer(r'(-{1,2}\w[\w\-]*|\+\w[\w\-]*|/\w[\w\-]*)', context_text)
                        for match in matches:
                            cmd = match.group(1)
                            if len(cmd) <= 50:
                                # Get surrounding context
                                start = max(0, match.start() - 30)
                                end = min(len(context_text), match.end() + 50)
                                desc = context_text[start:end].strip()
                                
                                options.append({
                                    'command': cmd,
                                    'description': desc[:300],
                                    'source': 'PCGamingWiki'
                                })
                
                # Remove duplicates
                seen = set()
                unique_options = []
                for opt in options:
                    if opt['command'] not in seen:
                        seen.add(opt['command'])
                        unique_options.append(opt)
                options = unique_options[:15]  # Limit results
            
            # Update test statistics
            if test_mode and test_results:
                source = 'PCGamingWiki'
                if source not in test_results['options_by_source']:
                    test_results['options_by_source'][source] = 0
                test_results['options_by_source'][source] += len(options)
            
            if debug:
                print(f"🔍 PCGamingWiki: Final result: {len(options)} options found")
                for opt in options[:3]:
                    print(f"🔍 PCGamingWiki:   {opt['command']}: {opt['description'][:40]}...")
            
            return options
            
        elif response.status_code == 403:
            if debug:
                print(f"🔍 PCGamingWiki: Still blocked by Cloudflare (403) for '{game_title}'")
                print(f"🔍 PCGamingWiki: This site requires more advanced bypass techniques")
            return []
            
        elif response.status_code == 404:
            if debug:
                print(f"🔍 PCGamingWiki: Page not found (404) for '{game_title}'")
            
            # Try alternative titles
            alt_titles = []
            if ':' in game_title:
                alt_titles.append(game_title.split(':')[0].strip())
            
            for pattern in [r'\s+(Edition|HD|Remastered).*$', r'\s+\(\d{4}\).*$']:
                alt_title = re.sub(pattern, '', game_title, flags=re.IGNORECASE).strip()
                if alt_title != game_title and alt_title not in alt_titles:
                    alt_titles.append(alt_title)
            
            for alt_title in alt_titles[:1]:  # Try only one alternative
                if len(alt_title) > 3:
                    if debug:
                        print(f"🔍 PCGamingWiki: Trying alternate: {alt_title}")
                    result = fetch_pcgamingwiki_launch_options(
                        alt_title, rate_limit=rate_limit, debug=debug, 
                        test_results=test_results, test_mode=test_mode
                    )
                    if result:
                        return result
            
            return []
        else:
            if debug:
                print(f"🔍 PCGamingWiki: Unexpected status {response.status_code} for '{game_title}'")
            return []
            
    except Exception as e:
        if session_monitor:
            session_monitor.record_error()
        
        if debug:
            print(f"🔍 PCGamingWiki: Exception for '{game_title}': {e}")
            import traceback
            traceback.print_exc()
        else:
            print(f"🔍 PCGamingWiki: Error for '{game_title}': {e}")
        
        return []