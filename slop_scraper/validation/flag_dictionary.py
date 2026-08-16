"""
Curated launch-option documentation.

Scraped sources rarely explain a flag well enough to act on. This table is the
authoritative override: where an entry exists it wins over whatever a scraper
produced, because a hand-verified description from primary documentation beats
a sentence lifted out of a forum post.

Every entry carries the source it was verified against. That field is for
maintainers, not the website — it exists so a future reader can re-check a
claim instead of trusting it. Entries whose behaviour could not be confirmed
against primary documentation are deliberately absent rather than guessed:
a flag nobody can explain accurately is worse than no flag at all.

`scope` is set when a flag only works on particular engines. It is folded into
the description shown to users, so nobody pastes an Unreal flag into a Source
game and wonders why nothing happened.
"""

from typing import Optional

# command -> curated documentation
FLAG_DICTIONARY = {
    # ---- id Tech ----------------------------------------------------------
    # Verified against id Software's own Doom 3 source release, which declares
    # each cvar with its help string:
    #
    #   idCVar r_customWidth( "r_customWidth", "720", ...,
    #                         "custom screen width. set r_mode to -1 to activate" );
    #   idCVar r_fullscreen(  "r_fullscreen",  "1",   ...,
    #                         "0 = windowed, 1 = full screen" );
    #
    # That is a stronger authority than a wiki: it is the shipping code. The
    # r_mode -1 dependency below was previously cited to a secondary reference
    # and is now confirmed from the declaration itself.
    '+set r_customwidth': {
        'description': 'Set a custom horizontal resolution',
        'effect': 'Overrides the width used when r_mode is -1. Without r_mode -1 the '
                  'engine uses a preset mode and this value is ignored.',
        'usage_example': '+set r_mode -1 +set r_customwidth 1920 +set r_customheight 1080',
        'authority': 'Doom 3 source (id Software), renderer/RenderSystem_init.cpp — '
                     'idCVar r_customWidth: "custom screen width. set r_mode to -1 to activate"',
    },
    '+set r_customheight': {
        'description': 'Set a custom vertical resolution',
        'effect': 'Overrides the height used when r_mode is -1. Without r_mode -1 the '
                  'engine uses a preset mode and this value is ignored.',
        'usage_example': '+set r_mode -1 +set r_customwidth 1920 +set r_customheight 1080',
        'authority': 'Doom 3 source (id Software), renderer/RenderSystem_init.cpp — '
                     'idCVar r_customHeight: "custom screen height. set r_mode to -1 to activate"',
    },
    '+set r_fullscreen': {
        'description': 'Start fullscreen or windowed',
        'effect': 'Takes 0 for windowed or 1 for full screen. Declared CVAR_ARCHIVE, so '
                  'the value persists into later launches.',
        'usage_example': '+set r_fullscreen 0',
        'authority': 'Doom 3 source (id Software), renderer/RenderSystem_init.cpp — '
                     'idCVar r_fullscreen: "0 = windowed, 1 = full screen"',
        'scope': 'id Tech games',
    },
    '+set r_swapInterval': {
        'description': 'Control vertical sync',
        'effect': 'Sets the OpenGL buffer-swap interval: 0 leaves VSync off, 1 syncs to '
                  'the display refresh. Declared CVAR_ARCHIVE, so it persists.',
        'usage_example': '+set r_swapInterval 1',
        'authority': 'Doom 3 source (id Software), renderer/RenderSystem_init.cpp — '
                     'idCVar r_swapInterval, integer, wraps wglSwapInterval',
        'scope': 'id Tech games',
    },

    # ---- Source engine ----------------------------------------------------
    '-console': {
        'description': 'Enable the developer console',
        'effect': 'Makes the in-game developer console available, opened with the ~ key.',
        'usage_example': '-console',
        'authority': 'Valve Developer Community — Command line options',
    },
    '-w': {
        'description': 'Set the window width in pixels',
        'effect': 'Forces the game to start at the given horizontal resolution instead '
                  'of the saved or auto-detected one. Pass -h as well to set height '
                  'explicitly; on its own, height is derived from the aspect ratio.',
        'usage_example': '-w 1920 -h 1080',
        'authority': 'Valve Developer Community — Command line options',
    },
    '-h': {
        'description': 'Set the window height in pixels',
        'effect': 'Forces the game to start at the given vertical resolution instead of '
                  'the saved or auto-detected one.',
        'usage_example': '-w 1920 -h 1080',
        'authority': 'Valve Developer Community — Command line options',
    },
    '-window': {
        'description': 'Run the game in a window instead of fullscreen',
        'effect': 'Starts windowed rather than exclusive fullscreen. -window, -windowed '
                  'and -sw are synonyms in Source.',
        'usage_example': '-window',
        'authority': 'Valve Developer Community — Command line options',
    },
    '-language': {
        'description': "Set the game's language",
        'effect': 'Loads localisation files for the named language instead of following '
                  'the Steam client language.',
        'usage_example': '-language english',
        'authority': 'Valve Developer Community — Command line options',
    },
    '-refresh': {
        'description': 'Set the monitor refresh rate in Hz',
        'effect': 'Requests the given refresh rate on the display the game opens on.',
        'usage_example': '-refresh 144',
        'authority': 'Valve Developer Community — Command line options',
    },

    # ---- Engine-specific: scope is part of the answer ---------------------
    '-vulkan': {
        'description': 'Use the Vulkan renderer where the game supports it',
        'effect': 'Forces the Vulkan rendering backend instead of DirectX or OpenGL. '
                  'Only has an effect in engines with a Vulkan path; ignored elsewhere.',
        'usage_example': '-vulkan',
        'authority': 'Valve — Source 2 Vulkan support (Dota 2, CS2, Half-Life: Alyx); '
                     'Unreal Engine 4 Vulkan RHI',
        'scope': 'only engines with a Vulkan backend — Source 2, id Tech 6/7, UE4',
    },
    '-nostartupmovies': {
        'description': 'Skip the startup movies',
        'effect': 'Prevents intro and logo movies from playing at launch.',
        'usage_example': '-nostartupmovies',
        'authority': 'Unreal Engine command-line arguments (UE3/UE4)',
        'scope': 'Unreal Engine games',
    },
    '-nomovies': {
        'description': 'Skip intro movies',
        'effect': 'Prevents pre-game cinematic and logo movies from playing. Source '
                  'games use -novid instead.',
        'usage_example': '-nomovies',
        'authority': 'PCGamingWiki per-game pages (Relic Essence-engine titles)',
        'scope': 'game-specific, not an engine-wide standard',
    },
    '-nolauncher': {
        'description': "Skip the game's external launcher",
        'effect': 'Starts the game directly instead of opening its separate launcher or '
                  'configuration window first. The exact spelling varies per title.',
        'usage_example': '-nolauncher',
        'authority': 'PCGamingWiki per-game pages',
        'scope': 'only games that ship a launcher',
    },
    '-height': {
        'description': 'Set the window height in pixels',
        'effect': 'Forces the given vertical resolution. This is a per-game convention '
                  'rather than an engine standard — Source uses -h, Unity uses '
                  '-screen-height.',
        'usage_example': '-height 1080',
        'authority': 'per-game conventions; not a Source or Unity standard',
        'scope': 'game-specific spelling',
    },

    # ---- Source engine, from the Valve Developer Community reference ------
    # The VDC wiki is behind a proof-of-work bot challenge, so these were
    # transcribed from the page by the maintainer rather than fetched. Each
    # description below tracks the wiki's own wording; where it is terse the
    # effect adds only what the same page states elsewhere.
    '-novid': {
        'description': 'Skip the intro video',
        'effect': 'The startup video does not play. Saves several seconds on every '
                  'launch and is the most common Source launch option.',
        'usage_example': '-novid',
        'authority': 'Valve Developer Community — Command line options: "When loading '
                     'a game with this parameter, the intro video will not play."',
        'scope': 'Source engine games',
    },
    '-high': {
        'description': 'Run the game at High process priority',
        'effect': 'Raises the OS scheduling priority of the game process. It does not '
                  'add CPU capacity, so it helps only where something else is '
                  'competing for the processor.',
        'usage_example': '-high',
        'authority': 'Valve Developer Community — Command line options: '
                     '"Sets the game\'s priority to High."',
        'scope': 'Source engine games',
    },
    '-threads': {
        'description': 'Set the size of the engine thread pool',
        'effect': 'Takes a thread count; the default is 3. Setting it above the number '
                  'of cores available does not help.',
        'usage_example': '-threads 4',
        'authority': 'Valve Developer Community — Command line options: "Number of '
                     'threads to allocate for the thread pool, default is 3"',
        'scope': 'Source engine games',
    },
    '-freq': {
        'description': 'Force a specific refresh rate',
        'effect': 'An alias for -refresh; the wiki lists the two as the same option. '
                  'Takes a rate in Hz.',
        'usage_example': '-freq 144',
        'authority': 'Valve Developer Community — Command line options: '
                     '"-freq <rate> — Same as -refresh"',
        'scope': 'Source engine games',
    },
    '-nojoy': {
        'description': 'Disable joystick support',
        'effect': 'Skips joystick initialisation, which can shorten startup. The wiki '
                  'notes it does NOT apply to Left 4 Dead 2.',
        'usage_example': '-nojoy',
        'authority': 'Valve Developer Community — Command line options: '
                     '"Disables joystick support." (not in Left 4 Dead 2)',
        'scope': 'Source engine games, except Left 4 Dead 2',
    },

    # ---- Unity standalone player ------------------------------------------
    # All verified against the Unity Manual, "Standalone Player command line
    # arguments". Platform limits below are Unity's own, not inferences.
    #
    # Note what is NOT here: -force-opengl, on 803 games. Unity documents
    # -force-glcore; -force-opengl does not appear in the manual, and the row
    # claiming 'Unity Documentation' as its source actually links to
    # PCGamingWiki. Undocumented, so no entry.
    '-popupwindow': {
        'description': 'Run in a borderless window',
        'effect': 'Creates the window as a dialog with no frame. Not supported on macOS.',
        'usage_example': '-popupwindow',
        'authority': 'Unity Manual — Standalone Player command line arguments',
        'scope': 'Unity games',
    },
    '-force-d3d11': {
        'description': 'Force the Direct3D 11 renderer',
        'effect': 'Windows only.',
        'usage_example': '-force-d3d11',
        'authority': 'Unity Manual — Standalone Player command line arguments',
        'scope': 'Unity games',
    },
    '-force-d3d12': {
        'description': 'Force the Direct3D 12 renderer',
        'effect': 'Windows only.',
        'usage_example': '-force-d3d12',
        'authority': 'Unity Manual — Standalone Player command line arguments',
        'scope': 'Unity games',
    },
    # -force-opengl and -force-glcore are DIFFERENT backends, not two spellings
    # of one flag. Unity 5.6 documents both; the current manual keeps only
    # -force-glcore on the standalone-player page, which is what makes
    # -force-opengl look like a typo. It is not.
    #
    # Note the asymmetry in Unity's own wording: -force-opengl forces "the
    # game", -force-glcore forces "the Editor". The description below follows
    # that rather than smoothing it over.
    #
    # A caveat that belongs with the flag: game_specific.py emits this to every
    # game detected as Unity, and the catalogue cannot tell which Unity version
    # a build shipped with. On a modern build with no legacy GL backend it does
    # nothing. That is stated in the effect rather than hidden, because a user
    # pasting it and seeing no change deserves to know which case they are in.
    '-force-opengl': {
        'description': 'Force the legacy OpenGL renderer',
        'effect': 'Windows only. Selects Unity\'s LEGACY OpenGL backend, not the core '
                  'profile — use -force-glcore for that. Builds made with newer Unity '
                  'versions may not carry the legacy backend at all, in which case this '
                  'has no effect.',
        'usage_example': '-force-opengl',
        'authority': 'Unity 5.6 Manual — command line arguments: "Force the game to use '
                     'OpenGL for rendering, even if Direct3D is available."',
        'scope': 'Unity games, legacy builds',
    },
    '-force-glcore': {
        'description': 'Force the OpenGL core profile renderer',
        'effect': 'Windows only. The modern counterpart to -force-opengl. Unity\'s 5.6 '
                  'wording scopes it to the Editor; the current manual lists it for the '
                  'standalone player.',
        'usage_example': '-force-glcore',
        'authority': 'Unity Manual — Standalone Player command line arguments; Unity 5.6 '
                     'Manual: "Force the Editor to use OpenGL core profile for rendering."',
        'scope': 'Unity games',
    },
    '-force-vulkan': {
        'description': 'Force the Vulkan renderer',
        'effect': 'Useful where the default backend crashes or performs badly; ignored '
                  'if the build has no Vulkan path.',
        'usage_example': '-force-vulkan',
        'authority': 'Unity Manual — Standalone Player command line arguments',
        'scope': 'Unity games',
    },
    '-force-low-power-device': {
        'description': 'Use the low-power GPU',
        'effect': 'macOS only. Picks the integrated GPU over the discrete one, trading '
                  'performance for battery life.',
        'usage_example': '-force-low-power-device',
        'authority': 'Unity Manual — Standalone Player command line arguments',
        'scope': 'Unity games, macOS',
    },
    '-window-mode': {
        'description': 'Override fullscreen windowed mode',
        'effect': 'Takes exclusive or borderless. Windows only. The flag alone does '
                  'nothing — the value is required.',
        'usage_example': '-window-mode borderless',
        'authority': 'Unity Manual — Standalone Player command line arguments',
        'scope': 'Unity games, Windows',
    },
    '-screen-width': {
        'description': 'Override the screen width',
        'effect': 'Must be an integer from a resolution the game supports. Pair with '
                  '-screen-height; alone it can leave a mismatched aspect ratio.',
        'usage_example': '-screen-width 1920 -screen-height 1080',
        'authority': 'Unity Manual — Standalone Player command line arguments',
        'scope': 'Unity games',
    },
    '-screen-height': {
        'description': 'Override the screen height',
        'effect': 'Must be an integer from a resolution the game supports. Pair with '
                  '-screen-width.',
        'usage_example': '-screen-width 1920 -screen-height 1080',
        'authority': 'Unity Manual — Standalone Player command line arguments',
        'scope': 'Unity games',
    },

    # ---- Unreal Engine ----------------------------------------------------
    # Verified against Epic's "Unreal Engine Command-Line Arguments Reference".
    # Quoted definitions there are terse ("Use all available cores."), so the
    # effect text below adds only what the reference itself states.
    #
    # NOT here, and both high-reach: -sm4 (234 games) and -malloc=system (233).
    # Neither appears in Epic's reference. -sm4's stored description also
    # asserts "Significant performance improvement in UE games", which is a
    # performance claim with nothing behind it.
    '-USEALLAVAILABLECORES': {
        'description': 'Use all available CPU cores',
        'effect': 'Lifts a core-count limit the engine would otherwise apply. Epic '
                  'documents it as "Use all available cores."',
        'usage_example': '-USEALLAVAILABLECORES',
        'authority': 'Unreal Engine Command-Line Arguments Reference (Epic)',
        'scope': 'Unreal Engine games',
    },
    '-dx11': {
        'description': 'Use the DirectX 11 renderer',
        'effect': 'Selects DX11 as the RHI. Ignored by builds without a DX11 path.',
        'usage_example': '-dx11',
        'authority': 'Unreal Engine Command-Line Arguments Reference (Epic)',
        'scope': 'Unreal Engine games',
    },
    '-dx12': {
        'description': 'Use the DirectX 12 renderer',
        'effect': 'Selects DX12 as the RHI. Ignored by builds without a DX12 path.',
        'usage_example': '-dx12',
        'authority': 'Unreal Engine Command-Line Arguments Reference (Epic)',
        'scope': 'Unreal Engine games',
    },
    # -windowed and -fullscreen are NOT Unreal-only, which is how they were
    # first scoped here. Both engines document them independently, and the
    # catalogue attaches -windowed to 465 games of which fewer than half are
    # Unreal. A scope narrower than the truth is its own kind of wrong answer:
    # it tells a Source player the flag will not work for them.
    '-windowed': {
        'description': 'Run in windowed mode',
        'effect': 'Unreal documents pairing it with an explicit resolution. In Source '
                  '-window, -sw and -startwindowed are the same option.',
        'usage_example': '-windowed -ResX=1920 -ResY=1080',
        'authority': 'Unreal Engine Command-Line Arguments Reference (Epic); Valve '
                     'Developer Community — "Forces the engine to start in Windowed mode."',
        'scope': 'Unreal Engine and Source games',
    },
    '-fullscreen': {
        'description': 'Run in fullscreen mode',
        'effect': 'Overrides a saved windowed preference. -full is the same option in '
                  'Source.',
        'usage_example': '-fullscreen',
        'authority': 'Unreal Engine Command-Line Arguments Reference (Epic); Valve '
                     'Developer Community — "Forces the engine to start in fullscreen mode."',
        'scope': 'Unreal Engine and Source games',
    },
    '-ResX': {
        'description': 'Set the window width in pixels',
        'effect': 'Takes its value with = and no space. Epic pairs it with -ResY and '
                  '-windowed.',
        'usage_example': '-windowed -ResX=1920 -ResY=1080',
        'authority': 'Unreal Engine Command-Line Arguments Reference (Epic)',
        'scope': 'Unreal Engine games',
    },
    '-ResY': {
        'description': 'Set the window height in pixels',
        'effect': 'Takes its value with = and no space. Epic pairs it with -ResX and '
                  '-windowed.',
        'usage_example': '-windowed -ResX=1920 -ResY=1080',
        'authority': 'Unreal Engine Command-Line Arguments Reference (Epic)',
        'scope': 'Unreal Engine games',
    },

    # ---- Linux wrapper tools ----------------------------------------------
    # These two are the highest-reach rows in the catalogue (2,038 and 2,013
    # games) and BOTH are stored in a form that does nothing if pasted.
    #
    # Steam substitutes %command% with the game's own executable, so these
    # tools have to wrap it. The bare tool name is not a launch option at all:
    # Feral's README documents "gamemoderun %command%" and MangoHud's
    # documents "mangohud %command%". No stored command in the catalogue
    # contains %command%.
    #
    # The usage_example carries the working form, which is exactly the field
    # for it. The stored command itself still wants renaming — a separate fix,
    # since it changes a UNIQUE key on 4,051 game-option pairs.
    # ---- Proton environment variables -------------------------------------
    # Same defect as gamemode/mangohud, found by the frontend session: 37
    # published rows are bare NAME=VALUE assignments across 402 links, and
    # every one is inert as stored. Steam's launch-options field passes a bare
    # assignment as an ARGUMENT to the game rather than setting it in the
    # environment; it only becomes an env var when it precedes %command%.
    # Valve's own README shows the form: "PROTON_USE_WINED3D=1 %command%".
    #
    # Keyed on the bare variable name — _dictionary_key strips the =value, so
    # PROTON_LOG=1 and PROTON_LOG=+timestamp both resolve here.
    #
    # Two high-reach variables are deliberately absent: PROTON_USE_WINED3D11
    # (55 games) and PROTON_USE_D9VK (52). Neither appears in the current
    # Proton README — they are legacy spellings from before D9VK merged into
    # DXVK — so nothing authoritative says what they do today.
    'PROTON_NO_ESYNC': {
        'description': 'Disable eventfd-based synchronisation',
        'effect': 'Turns off in-process esync primitives. Worth trying for games that '
                  'hang or crash under Proton.',
        'usage_example': 'PROTON_NO_ESYNC=1 %command%',
        'authority': 'ValveSoftware/Proton README: "Do not use eventfd-based '
                     'in-process synchronization primitives."',
        'scope': 'Linux, Proton',
    },
    'PROTON_USE_WINED3D': {
        'description': 'Use wined3d (OpenGL) instead of DXVK',
        'effect': 'Routes d3d11, d3d10 and d3d9 through OpenGL-based wined3d rather '
                  'than Vulkan-based DXVK. Usually slower; a fallback where DXVK fails.',
        'usage_example': 'PROTON_USE_WINED3D=1 %command%',
        'authority': 'ValveSoftware/Proton README: "Use OpenGL-based wined3d instead '
                     'of Vulkan-based DXVK for d3d11, d3d10, and d3d9."',
        'scope': 'Linux, Proton',
    },
    'PROTON_NO_D3D11': {
        'description': 'Disable d3d11.dll',
        'effect': 'For d3d11 games that can fall back to d3d9 and run better that way.',
        'usage_example': 'PROTON_NO_D3D11=1 %command%',
        'authority': 'ValveSoftware/Proton README: "Disable d3d11.dll, for d3d11 games '
                     'which can fall back to and run better with d3d9."',
        'scope': 'Linux, Proton',
    },
    'PROTON_FORCE_LARGE_ADDRESS_AWARE': {
        'description': 'Force the LARGE_ADDRESS_AWARE flag',
        'effect': 'Lets 32-bit executables address more than 2 GB. Valve documents it '
                  'as enabled by default, so setting it explicitly is usually a no-op.',
        'usage_example': 'PROTON_FORCE_LARGE_ADDRESS_AWARE=1 %command%',
        'authority': 'ValveSoftware/Proton README: "Force Wine to enable the '
                     'LARGE_ADDRESS_AWARE flag for all executables. Enabled by default."',
        'scope': 'Linux, Proton',
    },
    'PROTON_LOG': {
        'description': 'Write a Proton debug log',
        'effect': 'Dumps a log to $PROTON_LOG_DIR/steam-$APPID.log. Set to 1 for the '
                  'default channels, or to a string appended to the WINEDEBUG channels.',
        'usage_example': 'PROTON_LOG=1 %command%',
        'authority': 'ValveSoftware/Proton README: "Convenience method for dumping a '
                     'useful debug log to $PROTON_LOG_DIR/steam-$APPID.log."',
        'scope': 'Linux, Proton',
    },
    'PROTON_OLD_GL_STRING': {
        'description': 'Shorten the GL extension string',
        'effect': 'Limits the reported OpenGL extension string length, for old games '
                  'that crash when it is very long.',
        'usage_example': 'PROTON_OLD_GL_STRING=1 %command%',
        'authority': 'ValveSoftware/Proton README: "Set some driver overrides to limit '
                     'the length of the GL extension string, for old games that crash '
                     'on very long extension strings."',
        'scope': 'Linux, Proton',
    },

    'gamemode': {
        'description': 'Run the game under Feral GameMode',
        'effect': 'Applies temporary host optimisations (CPU governor, I/O and process '
                  'priority) for the game\'s lifetime. The bare word does nothing — '
                  'Steam needs the wrapper form.',
        'usage_example': 'gamemoderun %command%',
        'authority': 'FeralInteractive/gamemode README',
        'scope': 'Linux',
    },
    'mangohud': {
        'description': 'Show the MangoHud performance overlay',
        'effect': 'Draws FPS, frame timing and CPU/GPU load over Vulkan and OpenGL '
                  'games. The bare word does nothing — Steam needs the wrapper form.',
        'usage_example': 'mangohud %command%',
        'authority': 'flightlessmango/MangoHud README',
        'scope': 'Linux',
    },
}


def _dictionary_key(command: str) -> Optional[str]:
    """
    Match a stored command to a dictionary entry.

    Commands are stored with their values ("-w 1920", "+set r_customwidth"), so
    an exact match is tried first and then the flag without its trailing value.

    Values attach two ways. Source-style flags separate with a space ("-w 1920")
    and Unreal-style ones with '=' ("-ResX=1920"), so both are stripped. Without
    the '=' case, -ResX=1920 — on 226 games — could never reach an entry keyed
    on -ResX, and the two most-attached Unreal flags in the catalogue would stay
    undocumented no matter what was written here.
    """
    if not command:
        return None
    command = command.strip()
    if command in FLAG_DICTIONARY:
        return command

    # "-w 1920" -> "-w";  "+set r_customwidth 1920" -> "+set r_customwidth"
    parts = command.split(' ')
    for take in range(len(parts) - 1, 0, -1):
        candidate = ' '.join(parts[:take])
        if candidate in FLAG_DICTIONARY:
            return candidate

    # "-ResX=1920" -> "-ResX";  "-malloc=system" -> "-malloc"
    if '=' in command:
        candidate = command.split('=', 1)[0]
        if candidate in FLAG_DICTIONARY:
            return candidate

    return None


def lookup_flag(command: str) -> Optional[dict]:
    """Curated entry for a command, or None. Never raises."""
    key = _dictionary_key(command)
    return FLAG_DICTIONARY.get(key) if key else None


def curated_description(command: str) -> Optional[str]:
    """
    The description to publish, with scope folded in where one applies.

    A scoped flag reads "Skip the startup movies (Unreal Engine games)" so the
    limitation travels with the text instead of living only in our notes.
    """
    entry = lookup_flag(command)
    if not entry:
        return None
    description = entry['description']
    scope = entry.get('scope')
    return f"{description} ({scope})" if scope else description
