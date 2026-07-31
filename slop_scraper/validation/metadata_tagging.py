"""
Metadata tagging for launch_options: risk level, functional categories, and
engine compatibility. Built in response to the 2026-07 site audit, which
flagged that raw command strings give users no signal about safety or
relevance ("Lack of Context & Risk Warnings", "Community Verification &
Tagging System").

Everything here is a PURE function of data already on hand (the command
string, and optionally the source/engine that produced it) — no network
calls. That's deliberate: it means every option already in the database can
be tagged retroactively by a local backfill script, with zero re-scraping.
"""

import re
from typing import List, Optional

from .options_validator import LaunchOptionsValidator, ValidationLevel

# Curated descriptions for common Proton/Wine environment variables.
# Canonical location: scrapers/protondb.py imports this rather than defining
# its own copy, so there is one source of truth for "known" env vars.
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

# Environment variables that are terminal setup commands, never launch options.
# Canonical location — scrapers/protondb.py imports this too.
ENV_VAR_BLOCKLIST = {'WINEPREFIX', 'WINESERVER', 'WINELOADER', 'WINEDEBUG'}

# Shared validator instance purely to reuse its curated engine option sets —
# not used for its validate_option() behavior here.
_validator = LaunchOptionsValidator(ValidationLevel.PERMISSIVE)

# game_specific.py's engine-tagged scrapers set `source` to one of these
# exact strings — a much stronger engine signal than pattern-matching the
# command, since it reflects which specific game the option was found for.
_SOURCE_TO_ENGINE = {
    'Source Engine': 'Source Engine',
    'Unity Engine': 'Unity Engine',
    'Unreal Engine': 'Unreal Engine',
    'id Tech': 'id Tech',
    'Creation Engine': 'Creation Engine',
    'Frostbite Engine': 'Frostbite Engine',
}

# Explicit risk overrides. These are syntactically valid (they already pass
# the save gate) but carry real, well-documented risk: disabling anti-cheat,
# enabling cheat commands, or touching DLL loading in ways some anti-cheat
# systems flag. This list is intentionally small and conservative — anything
# not clearly documented as risky falls through to 'safe' or 'experimental'
# rather than being guessed at.
_CAUTION_EXACT = {'-insecure', '+sv_cheats', '-enablefakeip', '+exec'}

# Flag bodies (lowercased, dash/plus stripped) that reference a specific
# anti-cheat system by name — these bypass or alter anti-cheat behavior and
# are exactly the kind of thing the audit called out as needing a warning.
_ANTICHEAT_KEYWORDS = ('eac_launcher', 'nobattleye', 'noeac')


def _base_flag(command: str) -> str:
    """
    The flag/variable itself, without any trailing value:
      `-threads 4`   -> `-threads`   (space-separated value)
      `-ResX=1920`   -> `-ResX`      (Unreal-style =value on a dash flag)
      `PROTON_NO_ESYNC=1` -> unchanged (bare env var; name extracted separately)
    """
    if not command:
        return ''
    base = command.strip().split(' ')[0]
    if base.startswith(('-', '+')) and '=' in base:
        base = base.split('=', 1)[0]
    return base


def _env_var_name(base: str) -> Optional[str]:
    """`PROTON_NO_ESYNC=1` -> `PROTON_NO_ESYNC`; None for dash/plus flags —
    those had any `=value` already stripped by _base_flag."""
    if base.startswith(('-', '+')):
        return None
    if '=' in base:
        return base.split('=', 1)[0]
    return None


def _flag_body(base: str) -> str:
    """`-DisableFramerateLimiter` -> `disableframeratelimiter`. Lowercased and
    stripped of leading -/-- /+ so keyword substring checks are case- and
    dash-style-insensitive (real scraped data mixes -resx, -ResX, +ScreenWidth
    for what's functionally the same flag)."""
    return base.lstrip('-+').lower()


def classify_risk_level(command: str) -> str:
    """
    'safe' = known-good, no side effects.
    'caution' = can affect anti-cheat, saves, cloud-sync, or security.
    'experimental' = unverified/unrecognized — the default for anything not
    explicitly vetted, so unreviewed community finds never look as trustworthy
    as a curated, known-good flag.
    """
    if not command:
        return 'experimental'

    base = _base_flag(command)
    env_name = _env_var_name(base)
    body = _flag_body(base)

    if base in _CAUTION_EXACT:
        return 'caution'
    if env_name == 'WINEDLLOVERRIDES':
        return 'caution'
    if any(kw in body for kw in _ANTICHEAT_KEYWORDS):
        return 'caution'

    if env_name:
        # Any curated Proton/Wine env var (minus the caution override above)
        # is considered vetted-safe; anything else is unreviewed.
        return 'safe' if env_name in PROTON_WINE_DESCRIPTIONS else 'experimental'

    if base.lower() in ('gamemode', 'gamemoderun', 'mangohud'):
        return 'safe'

    known_safe = (
        _validator.universal_options
        | _validator.source_engine_options
        | _validator.unity_options
        | _validator.unreal_options
        | _validator.game_specific_options
    )
    if base in known_safe or (base.startswith('+') and base[1:] in _validator.console_commands):
        return 'safe'

    return 'experimental'


# Each category matches on TWO axes:
#   - flags: exact base-flag match (case-sensitive whole-string equality) —
#     safe even for short/generic-looking tokens like '-dev' or '-log',
#     since equality can't false-positive the way a substring can.
#   - keywords: substring match against the lowercased, dash-stripped flag
#     body — catches spelling/case variants across sources (-resx, -ResX,
#     +ScreenWidth all mean the same thing) but must stay specific enough
#     to avoid false hits (e.g. no bare 'dev', which would match inside
#     '-force_device_id'; no bare 'log', which would match inside '-nologo').
# Curated against ~580 real commands from production; residual
# "Uncategorized" rows are expected to be genuinely obscure, game-specific
# flags rather than a classifier gap.
_CATEGORY_RULES = {
    'Skip-Intro': (
        {'-novid', '-skipintro'},
        ('novid', 'skipintro', 'skip_intro', 'nomovie', 'novideo', 'skipmovie',
         'nostartupmovie', 'blitmovietobackground', 'nologo', 'nointro',
         'skipstartscreen', 'skipfeflowintro', 'skipstartup', 'skip_launcher',
         'unskippable', 'skipbootsequence', 'skipmoviesasap', 'showloadingscreen',
         'nosplash', 'introcinematic', 'nocinematic'),
    ),
    'Display': (
        {'-w', '-h', '-width', '-height', '-windowed', '-fullscreen', '-noborder',
         '-borderless', '-sw', '-refresh', '-freq', '-monitor', '-dx9', '-dx11',
         '-dx12', '-gl', '-vulkan', '-opengl', '-d3d10', '-d3d11', '-d3d12',
         '-software', '-screen-width', '-screen-height', '-screen-fullscreen',
         '-popupwindow', '-force-d3d11', '-force-d3d12', '-force-vulkan',
         '-force-opengl', '-force-metal', '-ResX', '-ResY', '-WinX', '-WinY',
         '-vsync', '-novsync', '-sm4', '-sm5', '-res'},
        ('resx', 'resy', 'resolution', 'screenwidth', 'screenheight', 'winx',
         'winy', 'xpos', 'ypos', 'xres', 'yres', 'windowsize', 'fullscreen',
         'fullwindow', 'windowgui', 'window-mode', 'subwindow', 'borderless',
         'noborder', 'widescreen', 'stretchaspect', 'aspectratio', 'fov',
         'displayconfig', 'monitor', 'refresh', 'vsync', 'nosync', 'gamma',
         'brightness', 'shadow', 'msaa', 'aliasing', 'antialias', 'multisample',
         'backbuffer', 'triplebuffer', 'mipfade', 'miplevel', 'blur', 'grain',
         'flicker', 'noglow', 'ssao', 'quality', 'detail', 'adapter', 'vidmem',
         'video_memory', 'dxlevel', 'directx', 'd3d', 'dx9', 'dx10', 'dx11',
         'dx12', 'opengl', 'gl_', 'glcore', 'vulkan', 'metal', 'sm3', 'sm4',
         'sm5', 'renderprofile', 'oldgameui', 'windowed', 'popupwindow',
         'bpp', 'shader', 'hdr', 'aniso', 'stereo', 'chroma'),
    ),
    'Performance': (
        {'-threads', '+fps_max', '-high', '-low', '+mat_queue_mode', '-nopreload',
         '-softparticlesdefaultoff', '-limitfps', '-USEALLAVAILABLECORES',
         '-ONETHREAD', '-malloc', '+cl_updaterate', '+cl_cmdrate', '+rate',
         '-nojoy', '-nosteamcontroller', '-precachefontchars', '-notexturestreaming',
         '-lowmemory'},
        ('thread', 'preload', 'cache', 'cpucount', 'cpu_count', 'processpriority',
         'framerate', 'limitfps', 'fps', 'benchmark', 'malloc', 'memory',
         'lowmemory', 'xmx', 'xms', 'vmoption', 'g1gc', 'usecache', 'nocache',
         'ignorepipelinecache', 'useallavailablecores', 'onethread', 'texturepool',
         'texturestreaming', 'precachefontchars', 'softparticles'),
    ),
    'Audio': (
        {'-nosound', '-primarysound', '-sndspeed', '-sndmono', '-wavonly', '-snoforceformat'},
        ('sound', 'audio', 'mute', 'volume', 'wavonly', 'snoforceformat',
         'sndspeed', 'sndmono', 'voicelanguage', 'disableeffectsound', 'music'),
    ),
    'Network': (
        {'+connect', '-clientport', '-insecure', '-enablefakeip', '-tickrate',
         '+cl_interp', '+cl_interp_ratio'},
        ('connect', 'clientport', 'insecure', 'enablefakeip', 'tickrate',
         'cl_interp', 'maxplayers', 'reliableport', 'battleye', 'noipx'),
    ),
    'Debug-Dev': (
        {'-console', '-dev', '-condebug', '-allowdebug', '+exec', '+sv_cheats',
         '+developer', '-log', '-debug', '-stat', '-ProfileGPU', '-benchmark',
         '+con_enable'},
        ('condebug', 'allowdebug', 'sv_cheats', 'developer', 'devmode', 'debug',
         'profilegpu', 'con_enable', 'toconsole', 'verify', 'fileopenlog',
         'log_voice', 'showerr', 'clear_achievements', 'clearstats',
         'disableachievements'),
    ),
}


def classify_categories(command: str, source: Optional[str] = None) -> List[str]:
    """
    Functional tags for UI badges. An option can belong to several — e.g. an
    env var can be both Performance and Proton-Deck.
    """
    if not command:
        return []

    base = _base_flag(command)
    env_name = _env_var_name(base)
    body = _flag_body(base)
    categories = []

    if (source == 'ProtonDB' or env_name in PROTON_WINE_DESCRIPTIONS
            or base.lower() in ('gamemode', 'gamemoderun', 'mangohud')
            or 'steamdeck' in body or 'gamepadui' in body):
        categories.append('Proton-Deck')

    for category, (flags, keywords) in _CATEGORY_RULES.items():
        if base in flags or any(kw in body for kw in keywords):
            categories.append(category)

    if not categories:
        categories.append('Uncategorized')

    return categories


def classify_engine_compatibility(command: str, source: Optional[str] = None) -> List[str]:
    """
    Which game engines this option is known to apply to. Proton/Wine env
    vars are 'Universal' here (they work regardless of the game's engine) —
    their Proton/Deck relevance is a category tag, not an engine.
    """
    if not command:
        return []

    # The scraper that found this already told us the engine, when it's a
    # game_specific.py engine-block result — trust that over pattern-matching.
    if source in _SOURCE_TO_ENGINE:
        return [_SOURCE_TO_ENGINE[source]]

    base = _base_flag(command)
    env_name = _env_var_name(base)

    if env_name or base.lower() in ('gamemode', 'gamemoderun', 'mangohud'):
        return ['Universal']

    if base in _validator.universal_options:
        return ['Universal']
    if base in _validator.source_engine_options or (base.startswith('+') and base[1:] in _validator.console_commands):
        return ['Source Engine']
    if base in _validator.unity_options:
        return ['Unity Engine']
    if base in _validator.unreal_options:
        return ['Unreal Engine']

    return []


def classify_option_metadata(command: str, source: Optional[str] = None) -> dict:
    """Convenience wrapper: all three classifications for one command."""
    return {
        'risk_level': classify_risk_level(command),
        'categories': classify_categories(command, source=source),
        'engine_compatibility': classify_engine_compatibility(command, source=source),
    }
