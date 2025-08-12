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

def fetch_protondb_launch_options(app_id, game_title=None, rate_limit=None, debug=False, 
                                 test_results=None, test_mode=False, rate_limiter=None, 
                                 session_monitor=None):
    """
    ProtonDB scraper with updated API endpoints and fallback methods
    """
    
    # Security validation
    try:
        app_id_int = int(app_id)
        if app_id_int <= 0 or app_id_int > 999999999:
            if debug:
                print(f"⚠️ Invalid app_id for ProtonDB: {app_id}")
            return []
    except (ValueError, TypeError):
        if debug:
            print(f"⚠️ Invalid app_id format for ProtonDB: {app_id}")
        return []
    
    if rate_limiter:
        rate_limiter.wait_if_needed("scraping", domain="protondb.com")
    elif rate_limit:
        time.sleep(rate_limit)
    
    options = []
    
    if debug:
        print(f"🔍 ProtonDB: Starting lookup for app_id {app_id_int}")
    
    try:
        # Method 1: Try the summary API first (this was working in debug)
        summary_url = f"https://www.protondb.com/api/v1/reports/summaries/{app_id_int}.json"
        
        if debug:
            print(f"🔍 ProtonDB: Fetching summary from {summary_url}")
        
        response = SecureRequestHandler.make_secure_request(
            summary_url, 
            timeout=15, 
            max_size_mb=2,
            debug=debug
        )
        
        if session_monitor:
            session_monitor.record_request()
        
        if response.status_code == 200:
            summary_data = response.json()
            
            if debug:
                print(f"🔍 ProtonDB: Summary data: {summary_data}")
            
            total_reports = summary_data.get('total', 0)
            tier = summary_data.get('trendingTier', 'unknown')
            
            if debug:
                print(f"🔍 ProtonDB: Found {total_reports} reports, tier: {tier}")
            
            if total_reports == 0:
                if debug:
                    print(f"🔍 ProtonDB: No reports found for app_id {app_id_int}")
                return []
            
            # Method 2: Try different API endpoints for detailed reports
            detailed_endpoints = [
                f"https://www.protondb.com/api/v1/reports/summaries/{app_id_int}/reports",
                f"https://www.protondb.com/api/v1/reports/{app_id_int}",
                f"https://www.protondb.com/reports/{app_id_int}.json"
            ]
            
            detailed_data = None
            working_endpoint = None
            
            for endpoint in detailed_endpoints:
                try:
                    if debug:
                        print(f"🔍 ProtonDB: Trying detailed endpoint: {endpoint}")
                    
                    if rate_limiter:
                        rate_limiter.wait_if_needed("scraping", domain="protondb.com")
                    elif rate_limit:
                        time.sleep(rate_limit)
                    
                    detailed_response = SecureRequestHandler.make_secure_request(
                        endpoint, 
                        timeout=20, 
                        max_size_mb=5,
                        debug=debug
                    )
                    
                    if session_monitor:
                        session_monitor.record_request()
                    
                    if detailed_response.status_code == 200:
                        detailed_data = detailed_response.json()
                        working_endpoint = endpoint
                        if debug:
                            print(f"🔍 ProtonDB: Success with endpoint: {endpoint}")
                        break
                    else:
                        if debug:
                            print(f"🔍 ProtonDB: Endpoint {endpoint} returned {detailed_response.status_code}")
                
                except Exception as e:
                    if debug:
                        print(f"🔍 ProtonDB: Endpoint {endpoint} failed: {e}")
                    continue
            
            # Method 3: If API endpoints don't work, try scraping the web page
            if not detailed_data:
                if debug:
                    print(f"🔍 ProtonDB: API endpoints failed, trying web scraping...")
                
                try:
                    web_url = f"https://www.protondb.com/app/{app_id_int}"
                    
                    if rate_limiter:
                        rate_limiter.wait_if_needed("scraping", domain="protondb.com")
                    elif rate_limit:
                        time.sleep(rate_limit)
                    
                    web_response = SecureRequestHandler.make_secure_request(
                        web_url, 
                        timeout=20, 
                        max_size_mb=3,
                        debug=debug
                    )
                    
                    if session_monitor:
                        session_monitor.record_request()
                    
                    if web_response.status_code == 200:
                        if debug:
                            print(f"🔍 ProtonDB: Successfully fetched web page")
                        
                        # Parse the web page for launch options
                        soup = BeautifulSoup(web_response.text, 'html.parser')
                        
                        # Look for reports containing launch options
                        web_options = extract_options_from_protondb_page(soup, debug=debug)
                        options.extend(web_options)
                        
                        if debug:
                            print(f"🔍 ProtonDB: Extracted {len(web_options)} options from web page")
                    
                except Exception as web_e:
                    if debug:
                        print(f"🔍 ProtonDB: Web scraping failed: {web_e}")
            
            # Method 4: Process detailed API data if we got it
            if detailed_data:
                if debug:
                    print(f"🔍 ProtonDB: Processing detailed data from {working_endpoint}")
                
                # Handle different data structures
                reports = []
                if isinstance(detailed_data, list):
                    reports = detailed_data
                elif isinstance(detailed_data, dict):
                    reports = detailed_data.get('reports', detailed_data.get('data', []))
                
                if debug:
                    print(f"🔍 ProtonDB: Found {len(reports)} detailed reports")
                
                # Extract launch options from reports
                api_options = extract_options_from_reports(reports, debug=debug)
                options.extend(api_options)
                
                if debug:
                    print(f"🔍 ProtonDB: Extracted {len(api_options)} options from API reports")
            
            # Method 5: Add tier-based common options if we found the game but no specific options
            if total_reports > 0 and not options:
                if debug:
                    print(f"🔍 ProtonDB: No specific options found, adding tier-based options")
                
                tier_options = get_tier_based_options(tier, summary_data)
                options.extend(tier_options)
                
                if debug:
                    print(f"🔍 ProtonDB: Added {len(tier_options)} tier-based options")
        
        elif response.status_code == 404:
            if debug:
                print(f"🔍 ProtonDB: Game not found (404) for app_id {app_id_int}")
        else:
            if debug:
                print(f"🔍 ProtonDB: Summary API returned {response.status_code}")
        
        # Remove duplicates and limit results
        seen_commands = set()
        unique_options = []
        for option in options:
            cmd = option['command'].lower()
            if cmd not in seen_commands:
                seen_commands.add(cmd)
                unique_options.append(option)
        
        options = unique_options[:25]  # Limit total options
        
        # Update test statistics
        if test_mode and test_results:
            source = 'ProtonDB'
            if source not in test_results['options_by_source']:
                test_results['options_by_source'][source] = 0
            test_results['options_by_source'][source] += len(options)
        
        if debug:
            print(f"🔍 ProtonDB: Final result: {len(options)} validated options")
            for opt in options[:3]:
                print(f"🔍 ProtonDB:   {opt['command']}: {opt['description'][:40]}...")
        
        return options
                
    except Exception as e:
        if session_monitor:
            session_monitor.record_error()
        
        if debug:
            print(f"🔍 ProtonDB: Error for app_id {app_id_int}: {e}")
            import traceback
            traceback.print_exc()
        else:
            print(f"🔍 ProtonDB: Error for app_id {app_id_int}: {e}")
        
        return []

def validate_protondb_option(command: str, debug: bool = False) -> bool:
    """Relaxed validation for ProtonDB options (includes Wine/Proton specifics)"""
    
    validator = LaunchOptionsValidator(ValidationLevel.RELAXED)
    is_valid, reason = validator.validate_option(command, EngineType.UNIVERSAL)
    
    # ProtonDB has many environment variables and special options
    if not is_valid:
        # Additional ProtonDB-specific patterns
        protondb_patterns = [
            r'^PROTON_[A-Z_]+=.+$',     # Proton environment variables
            r'^DXVK_[A-Z_]+=.+$',       # DXVK settings
            r'^VKD3D_[A-Z_]+=.+$',      # VKD3D settings
            r'^gamemode$',               # GameMode
            r'^mangohud$',               # MangoHud
        ]
        
        import re
        for pattern in protondb_patterns:
            if re.match(pattern, command):
                is_valid = True
                reason = "ProtonDB-specific option"
                break
    
    if debug and not is_valid:
        print(f"🔍 ProtonDB: Rejected '{command}' - {reason}")
    
    return is_valid

def extract_options_from_reports(reports, debug=False):
    """Extract launch options from ProtonDB API reports"""
    options = []
    
    # Patterns for different types of launch options
    launch_option_patterns = [
        r'PROTON_[A-Z_]+=[^\s]+',     # Proton environment variables
        r'DXVK_[A-Z_]+=[^\s]+',       # DXVK settings
        r'VKD3D_[A-Z_]+=[^\s]+',      # VKD3D settings  
        r'WINE_[A-Z_]+=[^\s]+',       # Wine settings
        r'gamemode\b',                 # GameMode
        r'mangohud\b',                 # MangoHud
        r'%command%[^"\']+',          # Steam launch option patterns
        r'-[a-zA-Z][a-zA-Z0-9\-_]*'   # Standard command line options
    ]
    
    combined_pattern = '|'.join(launch_option_patterns)
    option_regex = re.compile(combined_pattern)
    
    # Process reports (limit for performance)
    for i, report in enumerate(reports[:30]):
        if not isinstance(report, dict):
            continue
        
        if debug and i < 5:
            print(f"🔍 ProtonDB: Processing report {i+1}: {list(report.keys())}")
        
        # Check various fields for launch options
        fields_to_check = [
            'notes', 'body', 'content', 'text', 'comment', 
            'protonVersion', 'specs', 'configuration'
        ]
        
        for field in fields_to_check:
            if field not in report:
                continue
                
            text = str(report[field])
            
            # Skip very long text for performance
            if len(text) > 2000:
                text = text[:2000]
            
            # Find launch options in text
            matches = option_regex.findall(text)
            
            for match in matches:
                if isinstance(match, tuple):
                    match = next(m for m in match if m)  # Get first non-empty match
                
                match = match.strip()
                
                # Skip if too long or too short
                if len(match) > 100 or len(match) < 2:
                    continue
                
                # Extract context for description
                match_pos = text.find(match)
                if match_pos >= 0:
                    context_start = max(0, match_pos - 50)
                    context_end = min(len(text), match_pos + len(match) + 50)
                    context = text[context_start:context_end].strip()
                    
                    # Clean up context
                    context = re.sub(r'\s+', ' ', context)
                    if len(context) > 200:
                        context = context[:200] + "..."
                else:
                    context = f"Found in ProtonDB report"
                
                # Determine description based on option type
                if match.startswith('PROTON_'):
                    desc = f"Proton compatibility option: {context}"
                elif match.startswith('DXVK_'):
                    desc = f"DXVK graphics option: {context}"
                elif match.startswith('VKD3D_'):
                    desc = f"VKD3D DirectX 12 option: {context}"
                elif match.startswith('WINE_'):
                    desc = f"Wine compatibility option: {context}"
                elif 'gamemode' in match.lower():
                    desc = "Enable GameMode for performance optimization"
                elif 'mangohud' in match.lower():
                    desc = "Enable MangoHud overlay for performance monitoring"
                else:
                    desc = f"Found in ProtonDB report: {context}"
                
                options.append({
                    'command': match[:100],
                    'description': desc[:500],
                    'source': 'ProtonDB'
                })
                
                if debug and len(options) <= 5:
                    print(f"🔍 ProtonDB: Found option: {match}")
    
    return options

def extract_options_from_protondb_page(soup, debug=False):
    """Extract launch options from ProtonDB web page HTML"""
    options = []
    
    # Look for report containers
    report_selectors = [
        'div[class*="report"]',
        'div[class*="Review"]', 
        'div[class*="comment"]',
        'div[class*="note"]'
    ]
    
    reports = []
    for selector in report_selectors:
        elements = soup.select(selector)
        reports.extend(elements)
        if debug and elements:
            print(f"🔍 ProtonDB: Found {len(elements)} elements with selector '{selector}'")
    
    # Process report elements
    for i, report in enumerate(reports[:20]):  # Limit for performance
        text = report.get_text()
        
        if len(text) > 1500:
            continue
        
        # Look for launch option patterns
        if any(keyword in text.lower() for keyword in 
               ['proton', 'launch', 'command', 'dxvk', 'gamemode', 'option']):
            
            patterns = [
                r'PROTON_[A-Z_]+=[^\s]+',
                r'DXVK_[A-Z_]+=[^\s]+',
                r'-[a-zA-Z][a-zA-Z0-9\-_]*'
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, text)
                for match in matches:
                    if len(match) <= 50:
                        options.append({
                            'command': match,
                            'description': f"Found on ProtonDB page: {text[:100]}...",
                            'source': 'ProtonDB'
                        })
                        
                        if debug:
                            print(f"🔍 ProtonDB: Found web option: {match}")
    
    return options

def get_tier_based_options(tier, summary_data):
    """Get common options based on ProtonDB tier rating"""
    options = []
    
    # Add tier-appropriate options
    if tier in ['platinum', 'gold']:
        # High compatibility - add standard Proton options
        options.extend([
            {
                'command': 'PROTON_ENABLE_NVAPI=1',
                'description': 'Enable Nvidia API support for better GPU compatibility',
                'source': 'ProtonDB'
            },
            {
                'command': 'PROTON_HIDE_NVIDIA_GPU=0',
                'description': 'Ensure Nvidia GPU is visible to the game',
                'source': 'ProtonDB'
            }
        ])
    
    elif tier in ['silver', 'bronze']:
        # Medium compatibility - may need tweaks
        options.extend([
            {
                'command': 'PROTON_FORCE_LARGE_ADDRESS_AWARE=1',
                'description': 'Allow 32-bit games to use more than 2GB of RAM',
                'source': 'ProtonDB'
            },
            {
                'command': 'DXVK_ASYNC=1',
                'description': 'Enable DXVK async for potentially better performance',
                'source': 'ProtonDB'
            }
        ])
    
    # Add performance options for all tiers
    if tier != 'borked':
        options.extend([
            {
                'command': 'gamemode',
                'description': 'Enable GameMode for Linux performance optimization',
                'source': 'ProtonDB'
            },
            {
                'command': 'mangohud',
                'description': 'Enable MangoHud overlay for performance monitoring',
                'source': 'ProtonDB'
            }
        ])
    
    return options