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
    
    # Setup-only env vars (WINEPREFIX=...) are terminal commands, never
    # launch options — reject before the permissive patterns can accept them
    if '=' in command and command.split('=', 1)[0] in _ENV_VAR_BLOCKLIST:
        if debug:
            print(f"🔍 ProtonDB: Rejected '{command}' - setup-only environment variable")
        return False

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

# Curated descriptions for the common Proton/Wine environment variables.
# Keyed by variable NAME — any value maps to the name's description.
# Report notes are anecdotal prose; scraping description text out of them
# produced truncated fragments in production. A static table is accurate
# and clean; unknown vars get a clean generic instead of a fragment.
PROTON_WINE_DESCRIPTIONS = {
    'PROTON_NO_ESYNC': 'Disable eventfd-based synchronization (fixes hangs in some games)',
    'PROTON_NO_FSYNC': 'Disable futex-based synchronization',
    'PROTON_USE_WINED3D': 'Use OpenGL-based WineD3D instead of Vulkan-based DXVK',
    'PROTON_USE_D9VK': 'Translate Direct3D 9 to Vulkan for better performance (D9VK)',
    'PROTON_NO_D3D11': 'Disable Direct3D 11 support (forces older rendering path)',
    'PROTON_NO_D3D10': 'Disable Direct3D 10 support',
    'PROTON_FORCE_LARGE_ADDRESS_AWARE': 'Let 32-bit games use up to 4GB of RAM',
    'PROTON_ENABLE_NVAPI': 'Enable NVIDIA NVAPI support (DLSS and related features)',
    'PROTON_HIDE_NVIDIA_GPU': 'Hide NVIDIA GPU identity from the game',
    'PROTON_USE_SECCOMP': 'Enable seccomp-bpf filter (legacy Proton versions)',
    'DXVK_HUD': 'Show the DXVK performance HUD overlay (e.g. DXVK_HUD=fps)',
    'DXVK_ASYNC': 'Compile shaders asynchronously to reduce stutter (dxvk-async builds)',
    'DXVK_FRAME_RATE': 'Cap the frame rate at the DXVK level',
    'VKD3D_CONFIG': 'VKD3D-Proton (DirectX 12) configuration flags',
    'WINEDLLOVERRIDES': 'Override how Wine loads specific Windows DLLs',
    'WINEARCH': 'Set the Wine architecture (win64 or win32)',
    'WINEESYNC': 'Toggle eventfd-based synchronization in Wine',
    'WINEFSYNC': 'Toggle futex-based synchronization in Wine',
    'MANGOHUD': 'Enable the MangoHud performance overlay',
    'PULSE_LATENCY_MSEC': 'Set PulseAudio latency in ms (fixes crackling audio)',
}

# Environment variables that are terminal setup commands, never launch options
_ENV_VAR_BLOCKLIST = {'WINEPREFIX', 'WINESERVER', 'WINELOADER', 'WINEDEBUG'}


def extract_options_from_reports(reports, debug=False):
    """
    Extract launch options from ProtonDB report notes.

    Report notes are free-form prose, so extraction is tiered by signal:
      - Environment variables (PROTON_*=, DXVK_*=, WINE*=) are unambiguous
        and kept whenever seen — except setup-only vars like WINEPREFIX,
        which belong to terminal commands, not Steam launch options.
      - Bare -flag tokens are kept only when they appear next to %command%
        (i.e. inside an actual launch-option string) or in at least two
        independent reports — a single prose match is likely junk.

    Descriptions come from the curated PROTON_WINE_DESCRIPTIONS table, never
    from report text: report fragments shipped truncated anecdotes to prod.
    """
    try:
        from ..validation import is_valid_launch_option
    except ImportError:
        from validation import is_valid_launch_option

    env_var_pattern = re.compile(r'\b((?:PROTON|DXVK|VKD3D|WINE|MANGOHUD|PULSE)[A-Z0-9_]*)=([^\s\'"`]{1,60})')
    wrapper_pattern = re.compile(r'\b(gamemoderun|gamemode|mangohud)\b')
    # Anchored: must not continue a word ("90fps-ish" must not yield "-ish")
    flag_pattern = re.compile(r'(?<![\w\-])(-[a-zA-Z][a-zA-Z0-9_\-]{2,30})\b')

    # command -> {'count', 'high_signal'}
    found = {}

    def _record(cmd, high_signal):
        # Strip punctuation the regex grabbed from surrounding prose
        # ("PROTON_NO_ESYNC=1)" / "PROTON_NO_D3D10=1." / "...=1,")
        cmd = cmd.strip().rstrip('.,)];:')[:100]
        if not cmd:
            return
        entry = found.setdefault(cmd, {'count': 0, 'high_signal': False})
        entry['count'] += 1
        entry['high_signal'] = entry['high_signal'] or high_signal

    for report in reports[:100]:
        if not isinstance(report, dict):
            continue

        text = str(report.get('notes') or '')[:2000]
        if not text:
            continue

        for m in env_var_pattern.finditer(text):
            var_name = m.group(1)
            if var_name in _ENV_VAR_BLOCKLIST:
                continue
            _record(m.group(0), high_signal=True)

        for m in wrapper_pattern.finditer(text):
            _record(m.group(1).replace('gamemoderun', 'gamemode'), high_signal=True)

        for m in flag_pattern.finditer(text):
            # Flags are only trustworthy inside a launch-option string
            nearby = text[max(0, m.start() - 80):m.end() + 80].lower()
            near_command = '%command%' in nearby or 'launch option' in nearby
            _record(m.group(1), high_signal=near_command)

    options = []
    for cmd, entry in found.items():
        if not entry['high_signal'] and entry['count'] < 2:
            continue

        # Final structural check (paths, placeholders, prose words, ...)
        is_valid, reason = is_valid_launch_option(cmd)
        if not is_valid:
            if debug:
                print(f"🔍 ProtonDB: Rejected '{cmd}' - {reason}")
            continue

        # Description from the curated table only — never from report prose
        if cmd == 'gamemode':
            desc = 'Enable GameMode for performance optimization'
        elif cmd == 'mangohud':
            desc = 'Enable MangoHud overlay for performance monitoring'
        elif '=' in cmd:
            var_name = cmd.split('=', 1)[0]
            desc = PROTON_WINE_DESCRIPTIONS.get(var_name, 'Proton/Wine compatibility option')
        else:
            desc = 'Launch option reported by ProtonDB users'

        options.append({
            'command': cmd,
            'description': desc,
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

