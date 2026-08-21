"""
Launch Options Validation for Steam launch options based on documented commands
"""

import re
from typing import Set, Dict, List, Optional, Tuple
from enum import Enum

class ValidationLevel(Enum):
    """Validation strictness levels"""
    STRICT = "strict"          # Only known-good options
    PERMISSIVE = "permissive"  # Known-good + common patterns
    RELAXED = "relaxed"        # Most patterns allowed

class EngineType(Enum):
    """Supported game engine types"""
    SOURCE = "source"
    UNITY = "unity" 
    UNREAL = "unreal"
    UNIVERSAL = "universal"
    GAME_SPECIFIC = "game_specific"

class LaunchOptionsValidator:
    """
    Production-ready validator for Steam launch options
    
    Validates launch options against comprehensive whitelist of known commands
    from official documentation and community sources.
    """
    
    def __init__(self, validation_level: ValidationLevel = ValidationLevel.PERMISSIVE):
        self.validation_level = validation_level
        self._initialize_whitelists()
        self._initialize_patterns()
        self._initialize_blacklists()
    
    def _initialize_whitelists(self):
        """Initialize comprehensive whitelists based on documented commands"""
        
        # Universal Steam launch options (work across multiple games/engines)
        self.universal_options = {
            # Core display options
            '-novid', '-windowed', '-sw', '-fullscreen', '-noborder', '-borderless',
            '-w', '-h', '-width', '-height', '-refresh', '-freq', '-monitor',
            
            # Graphics API selection
            '-dx9', '-dx11', '-dx12', '-gl', '-vulkan', '-opengl', '-d3d10', '-d3d11', '-d3d12',
            
            # Performance and system
            '-high', '-low', '-console', '-nosound', '-nojoy', '-nosteamcontroller',
            '-safe', '-autoconfig', '-dev', '-condebug', '-allowdebug',
            
            # Legacy but still working
            '-software', '-force_vendor_id', '-force_device_id',
            
            # Platform specific
            '-gamepadui', '-steamdeck', '-force-wayland'
        }
        
        # Source Engine specific options
        self.source_engine_options = {
            # Performance optimization
            '+mat_queue_mode', '-threads', '-nopreload', '-softparticlesdefaultoff',
            '+fps_max', '-heapsize', '-nohltv', '-particles', '-precachefontchars',
            
            # DirectX levels (some deprecated but still recognized)
            '-dxlevel', 
            
            # Audio system
            '-primarysound', '-sndspeed', '-sndmono', '-wavonly', '-snoforceformat',
            
            # Network and server
            '+connect', '-clientport', '-insecure', '-enablefakeip',
            
            # CS:GO/CS2 specific
            '-tickrate', '-d3d9ex', '+cl_forcepreload', '+cl_showfps', '+cl_updaterate',
            '+cl_cmdrate', '+cl_interp', '+cl_interp_ratio', '+rate',
            
            # TF2 specific
            '-sillygibs', '-particles',
            
            # L4D specific
            '-useallavailablecores', '+allow_all_bot_survivor_team',
            
            # GMod specific
            '-multirun', '-noaddons', '-noworkshop',
            
            # Console commands used as launch options
            '+exec', '+sv_cheats', '+developer', '+con_enable', '+mat_motion_blur_percent_of_screen_max',
            '+violence_hblood', '+r_dynamic'
        }
        
        # Unity Engine specific options
        self.unity_options = {
            # Graphics and rendering
            '-force-d3d11', '-force-d3d12', '-force-vulkan', '-force-opengl', '-force-metal',
            '-screen-quality', '-nographics', '-nolog', '-no-stereo-rendering', '-systemallocator',
            
            # Display configuration
            '-screen-width', '-screen-height', '-screen-fullscreen', '-popupwindow',
            '-force-low-power-device',
            
            # Performance
            '-limitfps', '-noWorkshop', '-force-d3d11-no-singlethreaded'
        }
        
        # Unreal Engine specific options
        self.unreal_options = {
            # Graphics and rendering
            '-sm4', '-sm5', '-notexturestreaming', '-lowmemory',
            
            # Performance and system
            '-USEALLAVAILABLECORES', '-ONETHREAD', '-FPS', '-malloc',
            
            # Display configuration
            '-ResX', '-ResY', '-WinX', '-WinY', '-vsync', '-novsync',
            
            # Debugging and development
            '-log', '-debug', '-stat', '-ProfileGPU', '-benchmark',
            
            # Game specific (ARK, Rust, etc.)
            '-nomansky', '-gc.buffer', '-maxMem', '-cpuCount', '-graphics.lodbias'
        }
        
        # Game-specific options
        self.game_specific_options = {
            # GTA V
            '-anisotropicQualityLevel', '-fxaa', '-grassQuality', '-textureQuality',
            '-shadowQuality', '-noInGameDOF',
            
            # VR Games
            '--no-vr', '--fps', '--enable-debug-gui', '--affinity', '--osc',
            '-openvr', '-hmd', '-vrmode',
            
            # Various games
            '-allow_all_bot_survivor_team', '-gamepadui', '-steamdeck'
        }
        
        # Console commands that work as launch options (with + prefix)
        self.console_commands = {
            'fps_max', 'mat_queue_mode', 'cl_showfps', 'cl_forcepreload', 'cl_updaterate',
            'cl_cmdrate', 'cl_interp', 'cl_interp_ratio', 'rate', 'sv_cheats', 'developer',
            'con_enable', 'exec', 'connect', 'mat_motion_blur_percent_of_screen_max',
            'violence_hblood', 'r_dynamic', 'allow_all_bot_survivor_team'
        }
    
    def _initialize_patterns(self):
        """Initialize validation patterns for different option types"""
        
        self.valid_patterns = {
            # Standard options with parameters
            'param_options': [
                r'^-w\s+\d{3,4}$',           # -w 1920
                r'^-h\s+\d{3,4}$',           # -h 1080  
                r'^-refresh\s+\d{2,3}$',     # -refresh 144
                r'^-freq\s+\d{2,3}$',        # -freq 144
                r'^-threads\s+[1-8]$',       # -threads 4
                r'^-dxlevel\s+(80|81|90|95|100)$',  # -dxlevel 95
                r'^-ResX\s*=\s*\d{3,4}$',    # -ResX=1920
                r'^-ResY\s*=\s*\d{3,4}$',    # -ResY=1080
                r'^-screen-width\s+\d{3,4}$', # -screen-width 1920
                r'^-screen-height\s+\d{3,4}$', # -screen-height 1080
                r'^-limitfps\s+\d{2,3}$',    # -limitfps 60
                r'^-FPS\s*=\s*\d{2,3}$',     # -FPS=60
            ],
            
            # Console commands with values
            'console_commands': [
                r'^\+fps_max\s+\d{1,3}$',         # +fps_max 144
                r'^\+mat_queue_mode\s+[0-2]$',    # +mat_queue_mode 2
                r'^\+cl_updaterate\s+\d{2,3}$',   # +cl_updaterate 128
                r'^\+rate\s+\d{4,6}$',            # +rate 128000
            ],
            
            # Common patterns
            'standard_flags': [
                r'^-[a-zA-Z][a-zA-Z0-9_\-]{1,30}$',      # Standard flags
                r'^-force-[a-zA-Z0-9\-]{3,20}$',         # Unity force options
                r'^-no[a-zA-Z]{2,15}$',                   # Disable options
                r'^-USEALLAVAILABLECORES$',               # Unreal specific
                r'^--[a-zA-Z\-]{3,25}$',                 # Double-dash options
            ]
        }
        
        # Engine-specific validation patterns
        self.engine_patterns = {
            EngineType.SOURCE: [
                r'^\+[a-zA-Z_][a-zA-Z0-9_]{2,25}(\s+[a-zA-Z0-9\.\-]{1,10})?$',
                r'^-[a-zA-Z][a-zA-Z0-9_\-]{1,20}(\s+[a-zA-Z0-9\.\-]{1,10})?$'
            ],
            EngineType.UNITY: [
                r'^-force-[a-zA-Z0-9\-]{3,15}$',
                r'^-screen-[a-zA-Z\-]{3,15}(\s+\d{1,4})?$',
                r'^-no[a-zA-Z]{2,15}$'
            ],
            EngineType.UNREAL: [
                r'^-[A-Z][A-Z0-9_]*$',  # Unreal uses CAPS
                r'^-[a-z][a-zA-Z0-9]*=.+$',  # Options with values
                r'^-Res[XY]=\d{3,4}$'
            ]
        }
    
    def _initialize_blacklists(self):
        """Initialize blacklists of dangerous or invalid options"""
        
        # High-risk options that cause crashes or security issues
        self.high_risk_blacklist = {
            '-dxlevel 60', '-dxlevel 70',  # Cause crashes
            '-allow_third_party_software',  # Security risk
            '-heapsize',  # Deprecated, causes crashes on modern systems
            '-32bit',     # Removed from modern games
            '-16bpp',     # Not supported on modern systems
        }
        
        # Deprecated Steam client options
        self.deprecated_blacklist = {
            '-no-browser', '-noreactlogin', '-oldbigpicture'
        }
        
        # Obviously invalid patterns
        self.invalid_patterns = [
            r'^-\d+$',           # Just numbers
            r'^-[a-z]$',         # Single letters
            r'^-and$', '^-the$', '^-for$', '^-with$',  # Common words
            r'^-html?$', '^-div$', '^-span$',          # HTML tags
            r'^-exe$', '^-dll$', '^-com$',             # File extensions
        ]
    
    def validate_option(self, option: str, engine_hint: Optional[EngineType] = None) -> Tuple[bool, str]:
        """
        Validate a single launch option
        
        Args:
            option: The launch option to validate
            engine_hint: Optional hint about the game engine
            
        Returns:
            Tuple of (is_valid, reason)
        """
        
        if not option or not isinstance(option, str):
            return False, "Empty or invalid option"
        
        option = option.strip()
        
        # Basic format validation
        if len(option) < 2 or len(option) > 100:
            return False, "Invalid length"
        
        if not (option.startswith('-') or option.startswith('+') or option.startswith('--')):
            return False, "Must start with -, +, or --"
        
        # Check high-risk blacklist first
        if option in self.high_risk_blacklist:
            return False, "High-risk option (causes crashes or security issues)"
        
        # Check deprecated options
        if option in self.deprecated_blacklist:
            return False, "Deprecated option"
        
        # Check invalid patterns
        for pattern in self.invalid_patterns:
            if re.match(pattern, option.lower()):
                return False, "Matches invalid pattern"
        
        # Validation based on strictness level
        if self.validation_level == ValidationLevel.STRICT:
            return self._validate_strict(option, engine_hint)
        elif self.validation_level == ValidationLevel.PERMISSIVE:
            return self._validate_permissive(option, engine_hint)
        else:  # RELAXED
            return self._validate_relaxed(option, engine_hint)
    
    def _validate_strict(self, option: str, engine_hint: Optional[EngineType]) -> Tuple[bool, str]:
        """Strict validation - only known-good options"""
        
        base_option = option.split()[0].lower()
        
        # Check all whitelists
        all_known_options = (
            self.universal_options | 
            self.source_engine_options | 
            self.unity_options | 
            self.unreal_options | 
            self.game_specific_options
        )
        
        if base_option in {opt.lower() for opt in all_known_options}:
            return True, "Known valid option"
        
        # Check console commands
        if option.startswith('+'):
            command = option[1:].split()[0]
            if command in self.console_commands:
                return True, "Known console command"
        
        # Check parameterized options
        for pattern in self.valid_patterns['param_options']:
            if re.match(pattern, option):
                return True, "Valid parameterized option"
        
        return False, "Option not in strict whitelist"
    
    def _validate_permissive(self, option: str, engine_hint: Optional[EngineType]) -> Tuple[bool, str]:
        """Permissive validation - known options + common patterns"""
        
        # First try strict validation
        is_valid, reason = self._validate_strict(option, engine_hint)
        if is_valid:
            return is_valid, reason
        
        # Check common patterns
        for pattern in self.valid_patterns['standard_flags']:
            if re.match(pattern, option):
                return True, "Matches common pattern"
        
        # Engine-specific pattern matching
        if engine_hint and engine_hint in self.engine_patterns:
            for pattern in self.engine_patterns[engine_hint]:
                if re.match(pattern, option):
                    return True, f"Matches {engine_hint.value} engine pattern"
        
        # Gaming-specific heuristics
        option_lower = option.lower()
        gaming_keywords = [
            'fps', 'res', 'resolution', 'width', 'height', 'window', 'screen', 'display',
            'force', 'disable', 'enable', 'no', 'skip', 'max', 'min', 'set', 'dx', 'gl',
            'vulkan', 'sound', 'audio', 'mouse', 'joy', 'controller', 'thread', 'core',
            'quality', 'level', 'mode', 'buffer', 'memory', 'cache', 'vsync', 'refresh'
        ]
        
        if any(keyword in option_lower for keyword in gaming_keywords):
            return True, "Contains gaming-related keywords"
        
        return False, "Does not match permissive patterns"
    
    def _validate_relaxed(self, option: str, engine_hint: Optional[EngineType]) -> Tuple[bool, str]:
        """Relaxed validation - most reasonable patterns allowed"""
        
        # First try permissive validation
        is_valid, reason = self._validate_permissive(option, engine_hint)
        if is_valid:
            return is_valid, reason
        
        # Very basic format checking for relaxed mode
        option_body = option[1:] if option.startswith(('-', '+')) else option[2:]
        
        # Must contain at least one letter
        if not re.search(r'[a-zA-Z]', option_body):
            return False, "Must contain at least one letter"
        
        # Basic character set validation (alphanumeric + common symbols)
        if not re.match(r'^[a-zA-Z0-9_\-=\.:\s]+$', option_body):
            return False, "Contains invalid characters"
        
        # Reject obviously problematic patterns
        problematic = ['<', '>', '{', '}', '|', ';', '&', '$', '`', '"', "'"]
        if any(char in option for char in problematic):
            return False, "Contains problematic characters"
        
        return True, "Passes relaxed validation"
    
    def validate_options_list(self, options: List[str], engine_hint: Optional[EngineType] = None) -> Dict[str, Tuple[bool, str]]:
        """
        Validate a list of launch options
        
        Args:
            options: List of launch options to validate
            engine_hint: Optional hint about the game engine
            
        Returns:
            Dictionary mapping each option to (is_valid, reason)
        """
        
        results = {}
        for option in options:
            results[option] = self.validate_option(option, engine_hint)
        
        return results
    
    def get_validation_summary(self, options: List[str], engine_hint: Optional[EngineType] = None) -> Dict:
        """Get a summary of validation results"""
        
        results = self.validate_options_list(options, engine_hint)
        
        valid_options = [opt for opt, (valid, _) in results.items() if valid]
        invalid_options = [opt for opt, (valid, _) in results.items() if not valid]
        
        return {
            'total_options': len(options),
            'valid_count': len(valid_options),
            'invalid_count': len(invalid_options),
            'valid_options': valid_options,
            'invalid_options': invalid_options,
            'detailed_results': results,
            'validation_level': self.validation_level.value
        }
    
    def suggest_corrections(self, invalid_option: str) -> List[str]:
        """Suggest corrections for invalid launch options"""
        
        suggestions = []
        option_lower = invalid_option.lower()
        
        # Common corrections
        corrections = {
            '-window': '-windowed',
            '-fullscren': '-fullscreen',
            '-novideo': '-novid',
            '-nojoypad': '-nojoy',
            '-dxlevel9': '-dxlevel 95',
            '-fps': '+fps_max',
            '-threads': '-threads 4',
        }
        
        if option_lower in corrections:
            suggestions.append(corrections[option_lower])
        
        # Pattern-based suggestions
        if 'fps' in option_lower and not option_lower.startswith('+'):
            suggestions.append('+fps_max 0')
        
        if 'resolution' in option_lower or 'res' in option_lower:
            suggestions.extend(['-w 1920 -h 1080', '-ResX=1920 -ResY=1080'])
        
        return suggestions
    
    @classmethod
    def create_for_engine(cls, engine: EngineType, validation_level: ValidationLevel = ValidationLevel.PERMISSIVE):
        """Factory method to create validator optimized for specific engine"""
        
        validator = cls(validation_level)
        
        # Engine-specific optimizations could be added here
        # For example, different default validation levels per engine
        
        return validator

# ============================================================
# FINAL SAVE GATE
# Every scraped option must pass this before reaching the DB,
# regardless of which scraper produced it. Mirrors the reject
# patterns from the 2026-07 vanilla-slops production cleanup.
# ============================================================

# A launch option is what a user pastes into Steam's launch-options box.
# It is never a terminal setup command, a winetricks invocation, or a path.
_PATH_INDICATORS = ('/home/', '~/', 'compatdata/', 'steamapps/', '.steam/', '://', '\\')

# English words that regex extraction plucks out of prose as fake "-flags"
_PROSE_WORDS = {
    'already', 'time', 'game', 'person', 'hosting', 'man', 'day', 'way', 'year',
    'work', 'life', 'world', 'hand', 'part', 'place', 'case', 'week', 'and',
    'company', 'system', 'program', 'question', 'government', 'number', 'the',
    'night', 'point', 'home', 'water', 'room', 'mother', 'area', 'money',
    'story', 'fact', 'month', 'lot', 'right', 'study', 'book', 'eye', 'with',
    'job', 'word', 'business', 'issue', 'side', 'kind', 'head', 'house',
    'service', 'friend', 'father', 'power', 'hour', 'move', 'city', 'out',
    # Verified against production 2026-08-09. Deliberately excludes words that
    # are real flags in lowercase — '-steam' enables the Steam overlay, while
    # '-Steam' is a scraped title fragment. The Title-Case rule below splits
    # those two correctly, so they must not be blocked by word alone.
    'run', 'install', 'start', 'made', 'order', 'based', 'related', 'friendly',
    'click', 'print', 'screen', 'source', 'party', 'line', 'core', 'end',
}

# Wiki/markup tokens that must never appear in a stored description
_DESCRIPTION_MARKUP_TOKENS = ('[[', ']]', '{{', '}}', '<!--', '-->', '====', "''", '#*', '<ref')

# Dangling function words to trim when a description gets cut at markup
_DANGLING_WORDS = {
    'the', 'a', 'an', 'by', 'using', 'use', 'with', 'to', 'of', 'and', 'or',
    'in', 'on', 'at', 'for', 'from', 'via', 'see', 'run', 'is', 'as',
}


# Commands that are not launch options at all — parser artefacts, bare console
# prefixes, and placeholder text scraped as a value. Nothing can be pasted into
# Steam's launch-options box from this list and have any effect.
#
# THIS LIST IS THE WRITE-PATH GATE, and it exists here rather than only in the
# cleanup script for a reason that has now bitten twice. Deleting these rows
# without gating them meant the next scrape simply put them back: '+set' was
# deleted, and a rescan recreated it the same day from a PCGamingWiki page for
# Thirty Flights of Loving. The cleanup is the second half of the fix; this is
# the first half.
#
# Compared against command.strip().lower(), so casing variants are covered.
# An explicit literal set, never a pattern — a pattern over `command` would be
# the unbounded-matching mistake this codebase has had to undo twice, and here
# it would silently reject real flags.
MALFORMED_COMMANDS = frozenset({
    '+set',                      # id Tech console prefix; inert without a cvar and value
    '-set',                      # same
    '-resx',                     # Unreal fragment, value dropped
    '-resy',
    '-resx=',                    # same, '=' kept — also caught by the punctuation rule
    '-resy=',
    '-unskippable-',             # wikitext prose, not a flag
    '-resx=desiredwidth',        # Epic's syntax placeholder taken literally
    '-resy=desiredheight',
    '-malloc=system',            # not Unreal syntax; Unreal uses bare -ansimalloc etc.
    'proton_force_large_address_aware=1configuration',   # value welded to the next word
})


# Wrapper tools: programs that RUN the game rather than arguments passed to it.
#
# Steam replaces %command% with the game's executable, so the tool has to be
# written in front of it. Without the placeholder the launch options box gets a
# bare program name, which Steam appends as an argument to the game — the tool
# never runs, and nothing reports an error.
#
# Kept as data next to MALFORMED_COMMANDS because they are the same kind of
# fact: a short list of exact strings, read by a human, that the write path
# consults. WRAPPER_NORMALISED is what a scraper should store when it sees any
# spelling of the tool in a user's report.
WRAPPER_COMMANDS = frozenset({
    'gamemoderun %command%',
    'mangohud %command%',
})

WRAPPER_BARE_NAMES = frozenset({
    'gamemode',
    'gamemoderun',
    'mangohud',
})

WRAPPER_NORMALISED = {
    'gamemode':    'gamemoderun %command%',   # the binary is gamemoderun
    'gamemoderun': 'gamemoderun %command%',
    'mangohud':    'mangohud %command%',
}


def is_valid_launch_option(command: str, description: str = None) -> Tuple[bool, str]:
    """
    Final gate for a scraped launch option COMMAND before database save.

    Returns (is_valid, reason). The description is not judged here (it is
    cleaned separately by clean_option_description) but accepted for
    signature compatibility with call sites that have both.
    """
    if not command or not isinstance(command, str):
        return False, "Empty command"

    command = command.strip()

    if len(command) < 2:
        return False, "Too short"

    # Known non-options. Checked early so nothing downstream can rescue one.
    if command.lower() in MALFORMED_COMMANDS:
        return False, "Known parser artefact, not a launch option"

    # Terminal setup commands, never Steam launch options
    if command.startswith('WINEPREFIX='):
        return False, "WINEPREFIX is a terminal setup command, not a launch option"

    # Filesystem paths mean it was scraped out of a shell command
    if any(ind in command for ind in _PATH_INDICATORS):
        return False, "Contains filesystem path"

    # Truncated captures and placeholder fragments ({path, <path>, ~/[steam)
    if any(ch in command for ch in '<{[>}]'):
        return False, "Contains placeholder/bracket fragment"

    # Punctuation grabbed from surrounding prose
    if command[-1] in '.,)]=;:':
        return False, "Ends in punctuation (scraped from prose)"

    # At most one space: 'flag value' is fine, sentences are not
    if command.count(' ') > 1:
        return False, "Multiple spaces (prose fragment, not a flag)"

    # Env-var style: NAME=value with an UPPERCASE name (PROTON_NO_ESYNC=1,
    # DXVK_HUD=fps, WINEDLLOVERRIDES=..., MANGOHUD=1)
    if '=' in command and not command.startswith(('-', '+')):
        name, value = command.split('=', 1)
        if not re.match(r'^[A-Z][A-Z0-9_]+$', name):
            return False, "Assignment without a valid env-var name"
        # A value holding a path or a shell expansion means the whole thing was
        # lifted out of a terminal command, not a Steam launch option
        # (WINE=$proton-i/dist/bin/wine). The generic path check above misses
        # these because they carry no recognisable path prefix.
        if '/' in value or '$' in value:
            return False, "Env-var value is a path or shell expansion"
        # A digit run running straight into letters is the value welded to the
        # next word on the page — PROTON_FORCE_LARGE_ADDRESS_AWARE=1configuration
        # came from a heading that followed the value with no whitespace. It
        # reads as a plausible setting, which is why it survived every other
        # check here and was published. Real values are numeric (1, 0), a word
        # (fps, win32) or a channel string (+timestamp); none begin with digits
        # and continue into letters.
        if re.match(r'^\d+[A-Za-z]', value):
            return False, "Env-var value ran into the next word (scrape artefact)"
        # Variables we cannot document accurately — see UNVERIFIED_ENV_VARS.
        try:
            from .metadata_tagging import UNVERIFIED_ENV_VARS
        except ImportError:
            from metadata_tagging import UNVERIFIED_ENV_VARS
        if name in UNVERIFIED_ENV_VARS:
            return False, "Unverified environment variable (cannot be documented accurately)"
        return True, "Environment variable option"

    # Wrapper commands.
    #
    # These tools RUN the game rather than being passed to it, so Steam's
    # %command% placeholder is not optional decoration — it is the entire
    # mechanism. 'gamemoderun %command%' works; a bare 'gamemode' pasted into
    # the launch options box does nothing at all.
    #
    # The bare names are rejected rather than accepted-and-fixed because this
    # is the write path: 2,095 games held 'gamemode' as their launch option
    # for months, and the only reason it kept coming back was that nothing
    # here ever said no to it.
    if command in WRAPPER_COMMANDS:
        return True, "Wrapper command in its working form"
    if command in WRAPPER_BARE_NAMES:
        return False, "Wrapper tool name without %command% (inert when pasted)"

    # Everything else must be a -flag / +flag / --flag
    if not command.startswith(('-', '+')):
        return False, "Not a flag, env var, or known wrapper"

    body = command.lstrip('+-').split(' ')[0]

    if not body or not re.search(r'[a-zA-Z]', body):
        return False, "No letters in flag body"

    # Prose words captured as flags (-already, -out)
    if body.lower() in _PROSE_WORDS:
        return False, "Bare English word, not a flag"

    # Title-Case hyphenated phrases are prose/titles (-Out-Of-Luck)
    parts = body.split('-')
    if len(parts) >= 2 and any(p and p[0].isupper() for p in parts):
        return False, "Title-Case hyphenated phrase (prose fragment)"

    # A single Title-Case word is a scraped page/section fragment, never a
    # flag (-Xbox, -Mods, -Install, -Jaycee). Real options are lowercase
    # (-novid), ALLCAPS (-USEALLAVAILABLECORES), or carry internal capitals
    # (-ResX, -EpicPortal, -NoSplash) — none of which match this.
    # Case-sensitive on purpose: '-steam' is a real flag, '-Steam' is not.
    if re.match(r'^[A-Z][a-z]+$', body):
        return False, "Single Title-Case word (page/section fragment)"

    # Hash/GUID fragments scraped out of URLs and asset names. Restricted to
    # hex characters so technical flags that mix letters and digits
    # (-force-d3d11, -r1600x900x32, -glcore42) can never match.
    if re.search(r'(?i)[0-9a-f]{8,}', body):
        return False, "Hash/GUID fragment, not a flag"

    return True, "Valid flag"


def clean_option_description(description: str, min_length: int = 12) -> Optional[str]:
    """
    Clean a scraped description for database save, or return None.

    Cuts at the first wiki-markup token (handles UNCLOSED markup like
    '[[Glossary:Command line arguments' that closed-pair regexes miss),
    trims dangling function words left by the cut, and refuses fragments
    that are too short to mean anything. None means "store no description"
    — callers should prefer that over a polluted fragment.
    """
    if not description or not isinstance(description, str):
        return None

    text = description.strip()

    # Cut at the first markup token, wherever it appears
    cut_at = len(text)
    for token in _DESCRIPTION_MARKUP_TOKENS:
        idx = text.find(token)
        if idx != -1:
            cut_at = min(cut_at, idx)
    text = text[:cut_at]

    # Remove leftover markup characters and collapse whitespace.
    #
    # Angle brackets are NOT stripped when they wrap a single bare word, which
    # is how documentation writes a placeholder:
    #
    #   "Write a Proton debug log to $HOME/steam-<appid>.log"
    #
    # Blanking those produced "$HOME/steam-.log" — still a plausible-looking
    # sentence, which is what made it dangerous: it reads as repaired rather
    # than damaged. Real leftover markup at this point is unbalanced or
    # contains punctuation, and is still removed.
    text = re.sub(r'<(?![A-Za-z][A-Za-z0-9_]*>)', ' ', text)
    text = re.sub(r'(?<![<][A-Za-z])(?<![A-Za-z0-9_])>', ' ', text)
    text = re.sub(r'[{}|]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    # Trim trailing punctuation and dangling function words ("Use the -x by")
    words = text.rstrip(' .,:;-–—(').split(' ')
    while words and words[-1].lower().strip('.,:;()') in _DANGLING_WORDS:
        words.pop()
    text = ' '.join(words).rstrip(' .,:;-–—(').strip()

    if len(text) < min_length:
        return None

    return text


# Convenience functions for integration
def engine_type_for(engine_name: Optional[str]) -> EngineType:
    """
    Map a games.engine value onto the EngineType the validator understands.

    This is the single place that translation happens. It used to happen twice:
    `validate_launch_option` did `EngineType(engine_hint.lower())`, which only
    accepts the raw enum values 'source'/'unity'/'unreal' and therefore threw a
    ValueError on every real catalogue value ('Source Engine', 'Unity Engine'),
    silently falling back to no hint at all; and
    scrapers/game_specific.py kept its own dict keyed on the lowercased display
    names. Two mappings meant fixing one did not fix the other — the same
    duplication that let cleaned-up descriptions be reinstated by the next
    scrape.

    An engine hint only ever ADDS an acceptance path in _validate_permissive;
    it can never reject an option that would otherwise pass. So an unrecognised
    engine costs recall, not correctness, and UNIVERSAL is a safe default.

    Valve's three generations share console-command syntax closely enough that
    GoldSrc, Source and Source 2 all map to SOURCE. Everything outside the
    three families the validator has patterns for stays UNIVERSAL rather than
    being forced into an approximate bucket — id Tech's `+set name value` looks
    Source-like, but claiming that similarity here would loosen validation for
    a family whose flags nobody has actually checked against these patterns.
    """
    if not engine_name:
        return EngineType.UNIVERSAL

    name = str(engine_name).strip().lower()

    if name in ('source engine', 'source', 'source 2', 'goldsrc'):
        return EngineType.SOURCE
    if name in ('unity engine', 'unity'):
        return EngineType.UNITY
    if name in ('unreal engine', 'unreal'):
        return EngineType.UNREAL

    return EngineType.UNIVERSAL


def validate_launch_option(option: str, engine_hint: str = None, strict: bool = False) -> bool:
    """
    Simple function to validate a single launch option
    
    Args:
        option: Launch option to validate
        engine_hint: A games.engine value ('Source Engine', 'Unity Engine',
            'GoldSrc', ...) or a bare enum value ('source'). Unrecognised
            names fall back to UNIVERSAL rather than raising.
        strict: Use strict validation mode

    Returns:
        True if valid, False otherwise
    """

    level = ValidationLevel.STRICT if strict else ValidationLevel.PERMISSIVE
    engine = engine_type_for(engine_hint)

    validator = LaunchOptionsValidator(level)
    is_valid, _ = validator.validate_option(option, engine)
    
    return is_valid

def get_recommended_options(engine: str = None) -> List[str]:
    """Get list of recommended launch options for an engine"""
    
    recommendations = {
        'source': ['-novid', '-console', '+fps_max 0', '+mat_queue_mode 2', '-nojoy'],
        'unity': ['-force-d3d11', '-screen-width 1920', '-screen-height 1080'],
        'unreal': ['-USEALLAVAILABLECORES', '-sm4', '-d3d11'],
        'universal': ['-novid', '-windowed', '-noborder', '-high']
    }
    
    return recommendations.get(engine, recommendations['universal'])

# Test function for development
def test_validator():
    """Test the validator with various options"""
    
    validator = LaunchOptionsValidator(ValidationLevel.PERMISSIVE)
    
    test_options = [
        '-novid',           # Should pass - universal
        '+fps_max 144',     # Should pass - Source console command
        '-force-d3d11',     # Should pass - Unity
        '-USEALLAVAILABLECORES',  # Should pass - Unreal
        '-invalidoption',   # Should fail - not in whitelist
        '-dxlevel 70',      # Should fail - dangerous
        '-w 1920 -h 1080',  # Should pass - parameterized
        '--no-vr',          # Should pass - VR option
        '+exec autoexec',   # Should pass - console command
        '<script>',         # Should fail - invalid characters
    ]
    
    print("Testing Launch Options Validator")
    print("=" * 50)
    
    for option in test_options:
        is_valid, reason = validator.validate_option(option)
        status = "✅ VALID" if is_valid else "❌ INVALID"
        print(f"{status:<10} {option:<20} - {reason}")
    
    print("\nValidation Summary:")
    summary = validator.get_validation_summary(test_options)
    print(f"Total: {summary['total_options']}, Valid: {summary['valid_count']}, Invalid: {summary['invalid_count']}")

if __name__ == "__main__":
    test_validator()