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

# Convenience functions for integration
def validate_launch_option(option: str, engine_hint: str = None, strict: bool = False) -> bool:
    """
    Simple function to validate a single launch option
    
    Args:
        option: Launch option to validate
        engine_hint: Engine type hint ('source', 'unity', 'unreal', etc.)
        strict: Use strict validation mode
        
    Returns:
        True if valid, False otherwise
    """
    
    level = ValidationLevel.STRICT if strict else ValidationLevel.PERMISSIVE
    engine = None
    
    if engine_hint:
        try:
            engine = EngineType(engine_hint.lower())
        except ValueError:
            pass
    
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