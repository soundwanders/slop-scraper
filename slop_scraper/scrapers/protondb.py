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

            # ProtonDB's own detailed report endpoints are no longer publicly
            # accessible, but the community mirror at protondb.max-p.me serves
            # the historical report dump (through ~2019) including user notes,
            # which contain real game-specific launch options. Older games —
            # the bulk of our zero-option backlog — are well covered.
            try:
                if rate_limiter:
                    rate_limiter.wait_if_needed("scraping", domain="protondb.max-p.me")

                reports_response = SecureRequestHandler.make_secure_request(
                    f"https://protondb.max-p.me/games/{app_id_int}/reports/",
                    timeout=15,
                    max_size_mb=5,
                    debug=debug
                )

                if session_monitor:
                    session_monitor.record_request()

                if reports_response.status_code == 200:
                    reports = reports_response.json()
                    if isinstance(reports, list) and reports:
                        if debug:
                            print(f"🔍 ProtonDB: Mirror returned {len(reports)} detailed reports")
                        report_options = extract_options_from_reports(reports, debug=debug)
                        options.extend(
                            opt for opt in report_options
                            if validate_protondb_option(opt['command'], debug=debug)
                        )
            except Exception as mirror_e:
                if debug:
                    print(f"🔍 ProtonDB: Report mirror unavailable: {mirror_e}")

            # Add universally safe Linux performance wrappers if the game
            # has ProtonDB reports but no specific options were found in the reports.
            # Only gamemode/mangohud are added here — they are safe for any Linux game
            # and don't depend on the game's specific engine or configuration.
            # Tier-specific PROTON_/DXVK_ environment variables are intentionally
            # excluded because they are not verified for this particular game.
            if total_reports > 0 and not options:
                if debug:
                    print(f"🔍 ProtonDB: No specific options found, adding Linux wrapper options")

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

                if debug:
                    print(f"🔍 ProtonDB: Added 2 Linux wrapper options")
        
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
            # Env var names can contain digits (PROTON_USE_D9VK, DXVK_HUD...)
            r'^PROTON_[A-Z0-9_]+=.+$',   # Proton environment variables
            r'^DXVK_[A-Z0-9_]+=.+$',     # DXVK settings
            r'^VKD3D_[A-Z0-9_]+=.+$',    # VKD3D settings
            r'^WINE[A-Z0-9_]*=.+$',      # Wine settings (WINEESYNC, WINEDLLOVERRIDES...)
            r'^MANGOHUD[A-Z0-9_]*=.+$',  # MangoHud config
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
    """
    Extract launch options from ProtonDB report notes.

    Report notes are free-form prose, so extraction is tiered by signal:
      - Environment variables (PROTON_*=, DXVK_*=, WINE*=) are unambiguous
        and kept whenever seen.
      - Bare -flag tokens are kept only when they appear next to %command%
        (i.e. inside an actual launch-option string) or in at least two
        independent reports — a single prose match is likely junk.
    """
    env_var_pattern = re.compile(r'\b(?:PROTON|DXVK|VKD3D|WINE|MANGOHUD)[A-Z0-9_]*=[^\s\'"`]{1,60}')
    wrapper_pattern = re.compile(r'\b(gamemoderun|gamemode|mangohud)\b')
    # Anchored: must not continue a word ("90fps-ish" must not yield "-ish")
    flag_pattern = re.compile(r'(?<![\w\-])(-[a-zA-Z][a-zA-Z0-9_\-]{2,30})\b')

    # command -> {'count', 'context', 'high_signal'}
    found = {}

    def _record(cmd, context, high_signal):
        cmd = cmd.strip()[:100]
        entry = found.setdefault(cmd, {'count': 0, 'context': context, 'high_signal': False})
        entry['count'] += 1
        entry['high_signal'] = entry['high_signal'] or high_signal

    for report in reports[:100]:
        if not isinstance(report, dict):
            continue

        text = str(report.get('notes') or '')[:2000]
        if not text:
            continue

        for m in env_var_pattern.finditer(text):
            context = re.sub(r'\s+', ' ', text[max(0, m.start() - 60):m.end() + 60]).strip()
            _record(m.group(0), context, high_signal=True)

        for m in wrapper_pattern.finditer(text):
            _record(m.group(1).replace('gamemoderun', 'gamemode'), '', high_signal=True)

        for m in flag_pattern.finditer(text):
            # Flags are only trustworthy inside a launch-option string
            nearby = text[max(0, m.start() - 80):m.end() + 80].lower()
            near_command = '%command%' in nearby or 'launch option' in nearby
            context = re.sub(r'\s+', ' ', text[max(0, m.start() - 60):m.end() + 60]).strip()
            _record(m.group(1), context, high_signal=near_command)

    options = []
    for cmd, entry in found.items():
        if not entry['high_signal'] and entry['count'] < 2:
            continue

        context = entry['context'][:200]
        if cmd.startswith('PROTON_'):
            desc = f"Proton compatibility option: {context}"
        elif cmd.startswith('DXVK_'):
            desc = f"DXVK graphics option: {context}"
        elif cmd.startswith('VKD3D_'):
            desc = f"VKD3D DirectX 12 option: {context}"
        elif cmd.startswith(('WINE', 'MANGOHUD')):
            desc = f"Wine/overlay environment option: {context}"
        elif cmd == 'gamemode':
            desc = "Enable GameMode for performance optimization"
        elif cmd == 'mangohud':
            desc = "Enable MangoHud overlay for performance monitoring"
        else:
            desc = f"From ProtonDB user reports: {context}" if context else "From ProtonDB user reports"

        options.append({
            'command': cmd,
            'description': desc[:500],
            'source': 'ProtonDB'
        })

        if debug and len(options) <= 8:
            print(f"🔍 ProtonDB: Found option: {cmd} (seen {entry['count']}x)")

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

