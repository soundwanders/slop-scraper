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

# Descriptions for Proton/Wine environment variables. Canonical location:
# scrapers/protondb.py imports this rather than defining its own copy, so there
# is one source of truth for "known" env vars.
#
# EVERY ENTRY IS VERIFIED AGAINST THE DOCUMENT OR CODE THAT DEFINES THE
# VARIABLE, and its wording follows that source.
#
# Re-verified 2026-09-14, after 25 published rows were found taking their
# description from this table while it carried claims no source makes: "for
# better performance", "fixes hangs in some games", "up to 4GB of RAM", "DLSS
# and related features". Those are gone. Three variables came out entirely
# because nothing documents them — see UNVERIFIED_ENV_VARS below.
#
# Sources, fetched and read rather than recalled:
#   Proton README      github.com/ValveSoftware/Proton/blob/HEAD/README.md
#   Proton 8.0 README  github.com/ValveSoftware/Proton/blob/proton_8.0/README.md
#   Proton launcher    github.com/ValveSoftware/Proton/blob/HEAD/proton
#   DXVK README        github.com/doitsujin/dxvk/blob/master/README.md
#   dxvk-async README  github.com/Sporif/dxvk-async/blob/master/README.md
#   vkd3d-proton       github.com/HansKristian-Work/vkd3d-proton/blob/master/README.md
#   MangoHud README    github.com/flightlessmango/MangoHud/blob/master/README.md
#   Wine man page      github.com/wine-mirror/wine/blob/wine-9.0/loader/wine.man.in
#   esync README       github.com/ValveSoftware/wine/blob/proton_8.0/README.esync
#   fsync source       github.com/ValveSoftware/wine/blob/proton_5.0/dlls/ntdll/fsync.c
#   libpulse source    gitlab.freedesktop.org/pulseaudio/pulseaudio/-/blob/master/src/pulse/stream.c
#
# These describe the variable when it is SWITCHED ON. The off state is a
# different claim and lives in its own table below.
PROTON_WINE_DESCRIPTIONS = {
    # Proton's own README, which reads as a description as written.
    'PROTON_USE_WINED3D': 'Use OpenGL-based wined3d instead of Vulkan-based DXVK for d3d11, d3d10, and d3d9',
    'PROTON_NO_D3D11': 'Disable d3d11.dll, for d3d11 games which can fall back to and run better with d3d9',
    'PROTON_NO_D3D10': 'Disable d3d10.dll and dxgi.dll, for d3d10 games which can fall back to and run better with d3d9',
    'PROTON_NO_FSYNC': 'Do not use futex-based in-process synchronization primitives',
    'PROTON_FORCE_LARGE_ADDRESS_AWARE': 'Force Wine to enable the LARGE_ADDRESS_AWARE flag for all executables (enabled by default)',
    'PROTON_OLD_GL_STRING': 'Limit the length of the GL extension string, for old games that crash on very long extension strings',
    'PROTON_HIDE_NVIDIA_GPU': 'Force Nvidia GPUs to always be reported as AMD GPUs',
    'PROTON_LOG': 'Write a Proton debug log to $PROTON_LOG_DIR/steam-$APPID.log (your home directory by default)',
    # The README marks these obsolete but still documents what they did, and
    # the rows holding them were written when they worked. The version note is
    # part of the description because without it the text is misleading.
    'PROTON_NO_ESYNC': 'Do not use eventfd-based in-process synchronization primitives (obsoleted in Proton 11.0)',
    'PROTON_USE_SECCOMP': 'Enable a seccomp-bpf filter to emulate native syscalls, required for some DRM protections (obsoleted in Proton 5.13)',
    'PROTON_USE_D9VK': 'Use Vulkan-based DXVK instead of OpenGL-based wined3d for d3d9 (obsoleted in Proton 5.0)',
    # "This used to be called PROTON_USE_WINED3D11, which is now an alias for
    # this same option" (README at proton_3.16 and proton_4.11). The current
    # launcher still reads it: check_environment("PROTON_USE_WINED3D11", ...).
    'PROTON_USE_WINED3D11': 'The original name of PROTON_USE_WINED3D, still accepted as an alias: use OpenGL-based wined3d instead of Vulkan-based DXVK',
    # Proton 8.0's README. The current README documents neither — it has
    # PROTON_DISABLE_NVAPI instead — so the rows holding these are historical.
    'PROTON_ENABLE_NVAPI': "Enable NVIDIA's NVAPI GPU support library",
    'PROTON_DUMP_DEBUG_COMMANDS': 'Write debug scripts for the game into $PROTON_DEBUG_DIR/proton_$USER/ (/tmp by default)',
    # Wine's own man page.
    'WINEDLLOVERRIDES': 'Set the override type and load order for DLLs — native Windows (n) or Wine builtin (b)',
    # Valve's Wine fork: README.esync, and dlls/ntdll/fsync.c, which reads
    # WINEFSYNC with atoi() and enables fsync when it is non-zero.
    'WINEESYNC': 'Turn on eventfd-based synchronization (esync) in Wine builds that implement it',
    'WINEFSYNC': 'Turn on futex-based synchronization (fsync) in Wine builds that implement it',
    # vkd3d-proton's README.
    'VKD3D_CONFIG': 'A list of options that change the behaviour of vkd3d-proton',
    # MangoHud's README: "add MANGOHUD=1 to your shell profile (Vulkan only)".
    'MANGOHUD': 'Enable the MangoHud overlay layer (Vulkan only)',
    # dxvk-async's README. Deliberately says which builds: upstream DXVK
    # documents no such variable, so in a stock build it does nothing.
    'DXVK_ASYNC': 'Enable asynchronous pipeline compilation in DXVK builds patched with dxvk-async',
}

# Environment variables that are terminal setup commands, never launch options.
# Canonical location — scrapers/protondb.py imports this too.
ENV_VAR_BLOCKLIST = {'WINEPREFIX', 'WINESERVER', 'WINELOADER', 'WINEDEBUG'}

# Variables that turn up in scraped community reports but could not be
# confirmed against Proton or DXVK documentation. Some look like typos or
# misremembered variants of real ones (DXVK_ASYNC is real, PROTON_DXVK_ASYNC
# is not; PROTON_USE_WINE3D is PROTON_USE_WINED3D missing a letter). Publishing
# a flag we cannot explain accurately is worse than omitting it, so these are
# rejected at the save gate rather than stored with a vague description.
UNVERIFIED_ENV_VARS = {
    'PROTON_NO_GLSL',
    'PROTON_USE_GALLIUM_NINE',
    'PROTON_DXVK_ASYNC',
    'DXVK_FAKE_DX10_SUPPORT',
    'DXVK_FAKE_DX11_SUPPORT',
    # Typos / placeholders, not real variables
    'PROTON_USE_WINE3D',
    'PROTON_USE_WINE3D11',
    'PROTON_VARIABLE',
    # Added 2026-09-14 by the verification pass over the table above. Both were
    # described here as "legacy" spellings of PROTON_USE_WINED3D, which they are
    # not: the alias Valve documents is PROTON_USE_WINED3D11, and neither of
    # these appears in any Proton README (3.7 through current) or in the
    # launcher, which reads only PROTON_USE_WINED3D and PROTON_USE_WINED3D11.
    # PROTON_USE_WINED3D9 was real in Proton-GE for a while (merged there in
    # November 2022, "forces use of wine's builtin d3d9, while keeping dxvk for
    # d3d10+") and is absent from its current launcher too. A variable no
    # shipping build reads is not a launch option.
    'PROTON_USE_WINED3D9',
    'PROTON_USE_WINED3D10',
}

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
_CAUTION_EXACT = {'-insecure', '+sv_cheats', '-enablefakeip', '+exec',
                  # Alan Wake's American Nightmare: "Deletes save games and
                  # settings for Alan Wake from the Steam Cloud". Irreversible
                  # data loss, which is what 'caution' exists to warn about.
                  '-cleancloud'}

# Flag bodies (lowercased, dash/plus stripped) that reference a specific
# anti-cheat system by name — these bypass or alter anti-cheat behavior and
# are exactly the kind of thing the audit called out as needing a warning.
_ANTICHEAT_KEYWORDS = ('eac_launcher', 'nobattleye', 'noeac')


# What counts as switching a variable OFF depends on who reads the value, and
# guessing it states the opposite of the truth.
#
# Proton's launcher settles it for every PROTON_* variable:
#
#     def nonzero(s):
#         return len(s) > 0 and s != "0"
#
#     def check_environment(self, env_name, config_name):
#         if env_name not in self.env: return False
#         if nonzero(self.env[env_name]): self.compat_config.add(config_name)
#         else:                          self.compat_config.discard(config_name)
#
# So ONLY "0" (or empty) is off. "false", "no" and "off" all switch the setting
# ON. The previous table here treated all four as off, which described
# PROTON_NO_FSYNC=false as keeping fsync enabled when it disables it.
#
# Valve's Wine reads WINEESYNC/WINEFSYNC with atoi(), where "false" IS zero —
# but nothing documents what those look like switched off, so they get no
# description rather than an invented one.
_PROTON_OFF_VALUES = {'0', ''}
# Variables whose documented meaning holds for any value they carry, because
# the value is data (a DLL list, an option list) rather than a switch.
_VALUE_IS_DATA = {'WINEDLLOVERRIDES', 'VKD3D_CONFIG'}
# Documented in exactly one form, so any other value is undocumented.
_DOCUMENTED_ON_VALUE = {'MANGOHUD': '1', 'DXVK_ASYNC': '1'}


def _switch_state(name: str, value: str) -> Optional[str]:
    """'on', 'off', or None when nothing documents how this value is read."""
    if name.startswith('PROTON_'):
        return 'off' if value in _PROTON_OFF_VALUES else 'on'
    if name in ('WINEESYNC', 'WINEFSYNC'):
        digits = re.match(r'[+-]?\d+', value)       # atoi()
        if not digits:
            return None
        return 'on' if int(digits.group(0)) != 0 else None
    if name in _DOCUMENTED_ON_VALUE:
        return 'on' if value == _DOCUMENTED_ON_VALUE[name] else None
    if name in _VALUE_IS_DATA:
        return 'on' if value else None
    return None


# The SWITCHED-OFF form, for the variables whose enabled meaning is documented
# above. Written out rather than negated mechanically: several are themselves
# negative ("NO_D3D11"), so the off state is a double negative. "Explicitly" is
# load-bearing — check_environment DISCARDS the setting, which also overrides a
# per-game default Valve may have shipped. Anything absent here gets no
# description when off.
PROTON_WINE_DISABLED_DESCRIPTIONS = {
    'PROTON_NO_ESYNC': "Explicitly turn off Proton's noesync setting, so eventfd-based synchronization is used",
    'PROTON_NO_FSYNC': "Explicitly turn off Proton's nofsync setting, so futex-based synchronization is used",
    'PROTON_NO_D3D11': "Explicitly turn off Proton's nod3d11 setting, so d3d11.dll stays enabled",
    'PROTON_NO_D3D10': "Explicitly turn off Proton's nod3d10 setting, so d3d10.dll and dxgi.dll stay enabled",
    'PROTON_USE_WINED3D': "Explicitly turn off Proton's wined3d setting, so Vulkan-based DXVK is used",
    'PROTON_USE_WINED3D11': "Explicitly turn off Proton's wined3d setting, so Vulkan-based DXVK is used",
    'PROTON_USE_D9VK': "Explicitly turn off Proton's d9vk setting, so d3d9 uses OpenGL-based wined3d (Proton 4.11; obsoleted in 5.0)",
}


# DXVK's HUD takes a comma-separated list, and each element is documented
# separately in DXVK's README. Composing from the value means the row says what
# THIS value shows rather than what the variable does in general.
_DXVK_HUD_ELEMENTS = {
    'devinfo': 'the GPU name and driver version',
    'fps': 'the frame rate',
    'frametimes': 'a frame time graph',
    'submissions': 'command buffers submitted per frame',
    'drawcalls': 'draw calls and render passes per frame',
    'pipelines': 'the total number of graphics and compute pipelines',
    'descriptors': 'descriptor pools and sets',
    'memory': 'device memory allocated and used',
    'allocations': 'memory chunk suballocation detail',
    'gpuload': 'estimated GPU load',
    'version': 'the DXVK version',
    'api': 'the D3D feature level the application uses',
    'cs': 'worker thread statistics',
    'compiler': 'shader compiler activity',
    'samplers': 'the number of sampler pairs used (D3D9)',
    'swvp': 'the vertex processing mode (D3D9)',
}


def _describe_dxvk_hud(value: str) -> Optional[str]:
    """"DXVK_HUD=fps,compiler" -> what those elements show. None if any is undocumented."""
    if value == 'full':
        return "Show DXVK's HUD with every available element"
    items = ['devinfo', 'fps'] if value == '1' else [
        v.strip().lower() for v in value.split(',') if v.strip()]
    shown = []
    for item in items:
        # scale= and opacity= adjust the HUD rather than adding an element.
        if item.startswith(('scale=', 'opacity=')):
            continue
        if item not in _DXVK_HUD_ELEMENTS:
            return None
        shown.append(_DXVK_HUD_ELEMENTS[item])
    if not shown:
        return None
    # Joined with commas rather than a trailing "and": several of the elements
    # are themselves phrased with "and" ("the GPU name and driver version"),
    # and a second one reads as though it belongs to the first.
    return f"Show DXVK's HUD with {', '.join(shown)}"


def _describe_winearch(value: str) -> Optional[str]:
    """Wine's man page, which also states when the choice takes effect."""
    if value == 'win32':
        return ('Support only 32-bit applications in this Wine prefix '
                '(fixed when the prefix is created)')
    if value == 'win64':
        return ('Support 64-bit applications, and 32-bit ones in WoW64 mode, in this '
                'Wine prefix (fixed when the prefix is created)')
    return None


def _describe_pulse_latency(value: str) -> Optional[str]:
    """libpulse reads this as a millisecond count and sizes the buffer from it."""
    if not value.isdigit() or int(value) <= 0:
        return None
    return f'Ask PulseAudio for a playback buffer of {int(value)} ms'


def _describe_fsync_spincount(value: str) -> Optional[str]:
    """fsync.c: spincount defaults to 100 and is read straight from this value."""
    if not value.lstrip('+').isdigit():
        return None
    return ('How many times fsync retries a contended object before waiting on it '
            '(default 100), in Proton 5.0-era Wine')


# Variables whose meaning depends on the value itself, not on an on/off switch.
_VALUE_DESCRIBERS = {
    'DXVK_HUD': _describe_dxvk_hud,
    'WINEARCH': _describe_winearch,
    'PULSE_LATENCY_MSEC': _describe_pulse_latency,
    'WINEFSYNC_SPINCOUNT': _describe_fsync_spincount,
}

# Every environment variable this repo can account for. Used for tagging, where
# the question is "do we know this variable at all", not "how is it described".
KNOWN_ENV_VARS = set(PROTON_WINE_DESCRIPTIONS) | set(_VALUE_DESCRIBERS)


def describe_env_var(command: str) -> Optional[str]:
    """
    Curated description for an environment-variable option, or None.

    None means nothing here documents what THIS value does — which is stored as
    NULL and rendered as the source link. The value decides the wording, because
    the enabled and disabled forms are different claims and for several
    variables only one of them is documented anywhere.
    """
    if '=' not in command or command.startswith(('-', '+')):
        return None
    name, value = command.split('=', 1)
    value = value.strip()

    describer = _VALUE_DESCRIBERS.get(name)
    if describer:
        return describer(value)

    state = _switch_state(name, value)
    if state == 'on':
        return PROTON_WINE_DESCRIPTIONS.get(name)
    if state == 'off':
        return PROTON_WINE_DISABLED_DESCRIPTIONS.get(name)
    return None


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


# Categories curated for exactly the kind of cosmetic/client-side option
# that's safe to promote out of the unreviewed default: window size, render
# backend, intro-skip, and audio toggles have no meaningful side effects
# beyond the game's own presentation. Network and Debug-Dev are deliberately
# excluded — those can touch multiplayer integrity, dev/cheat tooling, or
# things anti-cheat systems care about, so they stay 'experimental' pending
# case-by-case review (see _CAUTION_EXACT / _ANTICHEAT_KEYWORDS above).
_SAFE_CATEGORIES = {'Display', 'Performance', 'Skip-Intro', 'Audio'}


def classify_risk_level(command: str, source: Optional[str] = None) -> str:
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
        # is considered vetted-safe; anything else is unreviewed. Keyed on the
        # variables we can account for, not on the on-state table alone —
        # DXVK_HUD and WINEARCH are described from their value (see
        # _VALUE_DESCRIBERS) and are no less vetted for it.
        return 'safe' if env_name in KNOWN_ENV_VARS else 'experimental'

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

    # Not individually curated, but classify_categories already recognized it
    # (via exact-flag or keyword match) as belonging to a well-understood,
    # low-impact functional category — that's a real vetting signal, not a
    # guess, so promote it rather than leaving it looking as unreviewed as a
    # genuinely unrecognized flag.
    if _SAFE_CATEGORIES & set(classify_categories(command, source=source)):
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

    if (source == 'ProtonDB' or env_name in KNOWN_ENV_VARS
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
        'risk_level': classify_risk_level(command, source=source),
        'categories': classify_categories(command, source=source),
        'engine_compatibility': classify_engine_compatibility(command, source=source),
    }
