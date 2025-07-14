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

def fetch_protondb_launch_options(app_id, game_title=None, rate_limit=None, debug=False, 
                                 test_results=None, test_mode=False, rate_limiter=None, 
                                 session_monitor=None):
    """Fetch launch options from ProtonDB reports with security controls"""
    
    # Security validation
    try:
        app_id_int = int(app_id)
        if app_id_int <= 0 or app_id_int > 999999999:
            print(f"⚠️ Invalid app_id for ProtonDB: {app_id}")
            return []
    except (ValueError, TypeError):
        print(f"⚠️ Invalid app_id format for ProtonDB: {app_id}")
        return []
    
    if rate_limiter:
        rate_limiter.wait_if_needed("scraping", domain="protondb.com")
    elif rate_limit:
        time.sleep(rate_limit)
    
    # ProtonDB API endpoint for game reports
    url = f"https://www.protondb.com/api/v1/reports/summaries/{app_id_int}.json"
    
    if debug:
        print(f"🔒 Fetching ProtonDB data securely from: {url}")
    
    options = []
    try:
        # First, get the summary to check if the game exists
        response = SecureRequestHandler.make_secure_request(url, timeout=15, max_size_mb=2)
        
        # Record request for monitoring
        if session_monitor:
            session_monitor.record_request()
        
        if response.status_code == 200:
            summary_data = response.json()
            
            # Check if there are reports
            if not summary_data or summary_data.get('total', 0) == 0:
                if debug:
                    print(f"🔒 No ProtonDB reports found for app_id {app_id_int}")
                return []
            
            # Now fetch detailed reports (limited for security)
            reports_url = f"https://www.protondb.com/api/v1/reports/summaries/{app_id_int}/reports"
            
            if rate_limiter:
                rate_limiter.wait_if_needed("scraping", domain="protondb.com")
            elif rate_limit:
                time.sleep(rate_limit)
            
            reports_response = SecureRequestHandler.make_secure_request(
                reports_url, timeout=20, max_size_mb=5
            )
            
            if session_monitor:
                session_monitor.record_request()
            
            if reports_response.status_code == 200:
                reports_data = reports_response.json()
                
                # Parse reports for launch options
                launch_option_patterns = [
                    r'PROTON_[A-Z_]+=[^\s]+',  # Proton environment variables
                    r'DXVK_[A-Z_]+=[^\s]+',    # DXVK settings
                    r'VKD3D_[A-Z_]+=[^\s]+',   # VKD3D settings
                    r'WINE_[A-Z_]+=[^\s]+',    # Wine settings
                    r'gamemode',                # GameMode mentions
                    r'mangohud',                # MangoHud mentions
                    r'%command%[^"\']+',        # Steam launch option patterns
                    r'-[a-zA-Z][a-zA-Z0-9\-_]*' # Standard command line options
                ]
                
                combined_pattern = '|'.join(launch_option_patterns)
                option_regex = re.compile(combined_pattern)
                
                found_options = {}  # Use dict to track options and their descriptions
                
                # Security: Limit number of reports processed
                for report in reports_data[:50]:
                    if not isinstance(report, dict):
                        continue
                    
                    # Check various fields for launch options
                    fields_to_check = ['notes', 'protonVersion', 'specs']
                    
                    for field in fields_to_check:
                        if field not in report:
                            continue
                            
                        text = str(report[field])
                        
                        # Security: Limit text processing
                        if len(text) > 2000:
                            text = text[:2000]
                        
                        # Find launch options in text
                        matches = option_regex.findall(text)
                        
                        for match in matches:
                            # Clean up the match
                            match = match.strip()
                            
                            # Skip if too long or suspicious
                            if len(match) > 100 or len(match) < 2:
                                continue
                            
                            # Extract context for description
                            context_start = max(0, text.find(match) - 50)
                            context_end = min(len(text), text.find(match) + len(match) + 50)
                            context = text[context_start:context_end].strip()
                            
                            # Clean up context
                            context = re.sub(r'\s+', ' ', context)
                            if len(context) > 200:
                                context = context[:200] + "..."
                            
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
                            
                            # Store unique options
                            if match not in found_options:
                                found_options[match] = desc
                
                # Convert to list format
                for cmd, desc in found_options.items():
                    # Additional validation for command format
                    if cmd.startswith('-') and not re.match(r'^-[a-zA-Z][\w\-]*$', cmd):
                        continue
                    
                    options.append({
                        'command': cmd[:100],
                        'description': desc[:500],
                        'source': 'ProtonDB'
                    })
                
                # Add common Proton options if we found related reports
                if summary_data.get('tier') in ['platinum', 'gold', 'silver']:
                    common_proton_options = [
                        {
                            'command': 'PROTON_ENABLE_NVAPI=1',
                            'description': 'Enable Nvidia API support for better GPU compatibility',
                            'source': 'ProtonDB'
                        },
                        {
                            'command': 'PROTON_HIDE_NVIDIA_GPU=0',
                            'description': 'Ensure Nvidia GPU is visible to the game',
                            'source': 'ProtonDB'
                        },
                        {
                            'command': 'PROTON_FORCE_LARGE_ADDRESS_AWARE=1',
                            'description': 'Allow 32-bit games to use more than 2GB of RAM',
                            'source': 'ProtonDB'
                        }
                    ]
                    
                    # Add common options if not already found
                    existing_commands = {opt['command'] for opt in options}
                    for common_opt in common_proton_options:
                        if common_opt['command'] not in existing_commands:
                            options.append(common_opt)
                
                # Security: Limit total options returned
                options = options[:30]
                
                # Update test statistics
                if test_mode and test_results:
                    source = 'ProtonDB'
                    if source not in test_results['options_by_source']:
                        test_results['options_by_source'][source] = 0
                    test_results['options_by_source'][source] += len(options)
                
                if debug:
                    print(f"🔒 Found {len(options)} validated options from ProtonDB")
                
        elif response.status_code == 404:
            if debug:
                print(f"🔒 Game not found on ProtonDB for app_id {app_id_int}")
        else:
            if debug:
                print(f"🔒 ProtonDB returned status code {response.status_code}")
                
    except Exception as e:
        if session_monitor:
            session_monitor.record_error()
        print(f"🔒 Error fetching from ProtonDB: {e}")
    
    return options