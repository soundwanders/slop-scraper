import os

try:
    # Try relative imports first (when run as module)
    from ..validation import (
        LaunchOptionsValidator, ValidationLevel, EngineType, engine_type_for)
except ImportError:
    # Fall back to absolute imports (when run directly)
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from validation import (
        LaunchOptionsValidator, ValidationLevel, EngineType, engine_type_for)

"""
Game-Specific Launch Options Scraper
"""

# games.engine values that each block of options actually applies to.
#
# These blocks used to be selected by matching franchise names against the
# game's title, developer, publisher, categories and genres all concatenated
# together — 'portal', 'dota', 'doom', 'fallout', 'battlefield'. That is the
# same unbounded-substring mistake that had to be removed from engine
# detection, except here it decides which flags get ATTACHED TO GAMES:
#
#   Portal Knights (Unity)        collected -novid, -console, +fps_max
#   Doom & Destiny (an indie RPG) collected +set r_customwidth
#   any game whose blurb said "fallout"  collected -skipintro
#
# The engine is now known from a sourced feed (PCGamingWiki), and it is passed
# into this function, so the flags can be keyed on what the game actually runs
# rather than on what its name resembles.
#
# Membership is deliberately narrow. A family is listed only where the block's
# flags are documented for it:
#   - GoldSrc is NOT in the Source group. These are Source-era flags (-novid,
#     -threads) and GoldSrc's support for them is not established here.
#   - Gamebryo is NOT in the Creation group, and Kex Engine is NOT in id Tech,
#     for the same reason.
# Those games still get options from PCGamingWiki, Steam Community and
# ProtonDB, which document per-game rather than per-family.
_ENGINE_OPTION_FAMILIES = {
    'source':     ('source engine', 'source 2'),
    'unity':      ('unity engine',),
    'unreal':     ('unreal engine',),
    'idtech':     ('id tech',),
    'creation':   ('creation engine',),
    'frostbite':  ('frostbite engine',),
    'minecraft':  ('java (minecraft)',),
}


def _option_family(engine):
    """
    games.engine value -> which block of engine-specific options applies.

    Returns None when the engine is unknown or has no documented block, in
    which case NO engine-specific options are emitted. That is the point: an
    unknown engine means we do not know which flags are valid, and guessing
    from the title is exactly what produced the wrong attachments above.
    """
    if not engine:
        return None
    name = str(engine).strip().lower()
    if name in ('unknown', 'none', 'null', ''):
        return None
    for family, members in _ENGINE_OPTION_FAMILIES.items():
        if name in members:
            return family
    return None


def fetch_game_specific_options(app_id, title, cache, engine=None, test_results=None, test_mode=False):
    """
    Fetch game-specific launch options based on engine detection and game patterns
    launch options for various game engines and specific games.
    :param app_id: The Steam application ID of the game
    :param title: The title of the game
    :param cache: Cache object to retrieve game metadata
    :param engine: Already-detected engine name (e.g. from the games table or
                   extract_engine); used directly so games whose metadata is not
                   in the local cache still get engine-specific options
    :param test_results: Optional dictionary to store test results for validation
    :param test_mode: Boolean indicating if the function is in test mode
    :return: List of launch options with descriptions and sources
    :raises ValueError: If app_id is not a valid integer or title is empty
    :raises TypeError: If cache is not a valid cache object
    :raises Exception: If an unexpected error occurs during processing
    """
    options = []
    
    # Get game data from cache
    game_data = cache.get(str(app_id), {})
    title = game_data.get('name', title) or 'Unknown Game Title'
    lower_title = title.lower()
    
    # Extract additional game metadata
    developers = game_data.get('developers', [])
    publishers = game_data.get('publishers', [])
    categories = game_data.get('categories', [])
    genres = game_data.get('genres', [])
    
    # Create comprehensive text for pattern matching
    developer_text = ""
    if isinstance(developers, list):
        developer_text = " ".join(developers).lower()
    elif isinstance(developers, str):
        developer_text = developers.lower()
    
    publisher_text = ""
    if isinstance(publishers, list):
        publisher_text = " ".join(publishers).lower()
    elif isinstance(publishers, str):
        publisher_text = publishers.lower()
    
    category_text = ""
    if isinstance(categories, list):
        category_text = " ".join([cat.get('description', '') for cat in categories if isinstance(cat, dict)]).lower()
    
    genre_text = ""
    if isinstance(genres, list):
        genre_text = " ".join([genre.get('description', '') for genre in genres if isinstance(genre, dict)]).lower()
    
    # Kept for the non-engine heuristics further down (the "is this a PC game"
    # check). It is deliberately NOT used to choose an engine any more.
    all_text = f"{lower_title} {developer_text} {publisher_text} {category_text} {genre_text}"

    # ENGINE-SPECIFIC OPTIONS, selected by the game's actual engine.
    engine_family = _option_family(engine)

    # 1. SOURCE ENGINE GAMES
    if engine_family == 'source':
        options.extend([
            {
                'command': '-novid',
                'description': 'Skip intro videos when starting the game',
                'source': 'Source Engine'
            },
            {
                'command': '-console',
                'description': 'Enable developer console',
                'source': 'Source Engine'
            },
            {
                'command': '-high',
                'description': 'Set high CPU priority for the game process',
                'source': 'Source Engine'
            },
            {
                'command': '-threads',
                'description': 'Force engine to use specified number of threads (e.g., -threads 4)',
                'source': 'Source Engine'
            },
            {
                'command': '-nojoy',
                'description': 'Disable joystick/controller support',
                'source': 'Source Engine'
            },
            {
                'command': '-freq',
                'description': 'Set monitor refresh rate (e.g., -freq 144)',
                'source': 'Source Engine'
            },
            {
                'command': '-w',
                'description': 'Set screen width in pixels (e.g., -w 1920)',
                'source': 'Source Engine'
            },
            {
                'command': '-h',
                'description': 'Set screen height in pixels (e.g., -h 1080)',
                'source': 'Source Engine'
            },
            {
                'command': '+fps_max',
                'description': 'Set maximum FPS (e.g., +fps_max 144)',
                'source': 'Source Engine'
            }
        ])
    
    # 2. UNITY ENGINE GAMES
    elif engine_family == 'unity':
        options.extend([
            {
                'command': '-screen-width',
                'description': 'Set horizontal screen resolution (e.g., -screen-width 1920)',
                'source': 'Unity Engine'
            },
            {
                'command': '-screen-height',
                'description': 'Set vertical screen resolution (e.g., -screen-height 1080)',
                'source': 'Unity Engine'
            },
            {
                'command': '-popupwindow',
                'description': 'Run in borderless windowed mode',
                'source': 'Unity Engine'
            },
            {
                'command': '-window-mode',
                'description': 'Set window mode: exclusive, windowed, or borderless',
                'source': 'Unity Engine'
            },
            {
                'command': '-force-opengl',
                'description': 'Force Unity to use OpenGL renderer',
                'source': 'Unity Engine'
            },
            {
                'command': '-force-d3d11',
                'description': 'Force Unity to use DirectX 11 renderer',
                'source': 'Unity Engine'
            },
            {
                'command': '-force-d3d12',
                'description': 'Force Unity to use DirectX 12 renderer',
                'source': 'Unity Engine'
            },
            {
                'command': '-force-vulkan',
                'description': 'Force Unity to use Vulkan renderer',
                'source': 'Unity Engine'
            },
            {
                'command': '-force-low-power-device',
                'description': 'Force low power device mode for better battery life',
                'source': 'Unity Engine'
            }
        ])
    
    # 3. UNREAL ENGINE GAMES
    elif engine_family == 'unreal':
        options.extend([
            # Emitted with a concrete value: Unreal requires -ResX=<number>,
            # and a bare '-ResX=' is rejected by the save gate as ending in
            # punctuation, so the old form could never be stored at all.
            {
                'command': '-ResX=1920',
                'description': 'Set horizontal resolution (substitute your own width)',
                'source': 'Unreal Engine'
            },
            {
                'command': '-ResY=1080',
                'description': 'Set vertical resolution (substitute your own height)',
                'source': 'Unreal Engine'
            },
            {
                'command': '-windowed',
                'description': 'Run the game in windowed mode',
                'source': 'Unreal Engine'
            },
            {
                'command': '-fullscreen',
                'description': 'Force fullscreen mode',
                'source': 'Unreal Engine'
            },
            {
                'command': '-dx12',
                'description': 'Force DirectX 12 renderer',
                'source': 'Unreal Engine'
            },
            {
                'command': '-dx11',
                'description': 'Force DirectX 11 renderer',
                'source': 'Unreal Engine'
            },
            # '-vulkan' was listed here. Unreal Engine 4 does have a Vulkan RHI,
            # but this block is keyed on title keywords ('mass effect',
            # 'batman arkham', 'borderlands') that overwhelmingly resolve to
            # UE3-era games with no Vulkan path at all — it was attached to 40
            # games, almost none of which could use it. There is no reliable
            # UE3-vs-UE4 signal here, so it is omitted rather than guessed;
            # PCGamingWiki and Steam Community still surface it per-game where
            # a source actually documents it.
            # '-sm4' was listed here, on 238 games. SM4 is a real Unreal
            # feature level — Epic's ERHIFeatureLevel enum defines it as "the
            # capabilities of DX10 Shader Model 4" — but Epic REMOVED it in
            # 4.23: "SM4 DirectX10 and GL 3.3+ have been removed for in 4.23".
            # The enum entry is literally named SM4_REMOVED.
            #
            # Blanket-emitting it to every Unreal-family game put it on 91
            # UE3-or-older titles (some UE1, from 1998) that predate the UE4
            # RHI entirely, 26 UE5+ titles, and 64 UE4 titles released after
            # 4.23 shipped. Around 78% of the attachments could not work.
            #
            # Scoping it by release year was rejected: that infers an engine
            # point-release from adjacent metadata, which is the guess that
            # produced the Frostbite-Peggle label. Left to the per-game
            # scrapers, which attach it only where a page documents it.
            # Same reasoning as '-vulkan' above.
            {
                'command': '-USEALLAVAILABLECORES',
                'description': 'Utilize all available CPU cores',
                'source': 'Unreal Engine'
            },
            # '-malloc=system' was listed here, on 237 games. It is not Unreal
            # syntax. Unreal selects an allocator with a bare switch —
            # -ansimalloc, -tbbmalloc, -binnedmalloc — and -ansimalloc is the
            # one that uses the system allocator this entry was reaching for.
            # There is no '-malloc=' switch to take a value; Epic's
            # command-line reference documents no malloc switch at all.
            #
            # So it was inert when pasted, exactly like the bare 'gamemode'
            # form, and the description promised "better performance" from a
            # string that does nothing. Removed rather than corrected to
            # -ansimalloc: nothing establishes that these 237 games want a
            # non-default allocator, and swapping one unsourced claim for
            # another is not a fix. Same reasoning as '-vulkan' above.
        ])
    
    # 4. ID TECH ENGINE
    elif engine_family == 'idtech':
        options.extend([
            {
                'command': '+set r_fullscreen',
                'description': 'Set fullscreen mode (0=windowed, 1=fullscreen)',
                'source': 'id Tech'
            },
            {
                'command': '+set r_customwidth',
                'description': 'Set custom screen width',
                'source': 'id Tech'
            },
            {
                'command': '+set r_customheight',
                'description': 'Set custom screen height',
                'source': 'id Tech'
            },
            {
                'command': '+set com_skipIntroVideo',
                'description': 'Skip intro videos (set to 1)',
                'source': 'id Tech'
            },
            {
                'command': '+set r_swapInterval',
                'description': 'Control V-Sync (0=off, 1=on)',
                'source': 'id Tech'
            }
        ])
    
    # GAME-SPECIFIC PATTERNS (Very targeted)
    
    # Minecraft (Java Edition)
    elif engine_family == 'minecraft':
        options.extend([
            {
                'command': '-Xmx4G',
                'description': 'Allocate 4GB of RAM to Minecraft',
                'source': 'Minecraft Java'
            },
            {
                'command': '-Xms2G',
                'description': 'Set initial memory allocation to 2GB',
                'source': 'Minecraft Java'
            },
            {
                'command': '-XX:+UnlockExperimentalVMOptions',
                'description': 'Enable experimental JVM optimizations',
                'source': 'Minecraft Java'
            },
            {
                'command': '-XX:+UseG1GC',
                'description': 'Use G1 garbage collector for better performance',
                'source': 'Minecraft Java'
            }
        ])
    
    # Bethesda Creation Engine games
    elif engine_family == 'creation':
        options.extend([
            {
                'command': '-windowed',
                'description': 'Run in windowed mode',
                'source': 'Creation Engine'
            },
            {
                'command': '-borderless',
                'description': 'Run in borderless windowed mode',
                'source': 'Creation Engine'
            },
            {
                'command': '-skipintro',
                'description': 'Skip intro videos and logos',
                'source': 'Creation Engine'
            }
        ])
    
    # Frostbite Engine (EA games)
    # Match the ENGINE, not the publisher. 'electronic arts' and 'ea games'
    # used to be triggers here, which classified every EA-published game as
    # Frostbite regardless of what it actually runs on — that is how UE3-era
    # titles like Mass Effect (2007) ended up carrying Frostbite options.
    elif engine_family == 'frostbite':
        options.extend([
            {
                'command': '-windowed',
                'description': 'Run in windowed mode',
                'source': 'Frostbite Engine'
            },
            # '-novid' was listed here and is NOT a Frostbite option — it is a
            # Source engine flag. It was attached to 164 Frostbite games, none
            # of which support it. Removed rather than replaced: no confirmed
            # Frostbite equivalent could be verified.
            {
                'command': '-dx12',
                'description': 'Force DirectX 12 if supported',
                'source': 'Frostbite Engine'
            }
        ])
    
    # Only add minimal universal options if:
    # 1. No engine-specific options were found, AND
    # 2. The game appears to be a PC game that might support windowing
    if not options:
        # Check if it's likely a PC game
        pc_indicators = ['windows', 'pc', 'steam', 'directx', 'opengl']
        if any(indicator in all_text for indicator in pc_indicators):
            # Add only the most universally supported options
            options.extend([
                {
                    'command': '-windowed',
                    'description': 'Attempt to run in windowed mode',
                    'source': 'Universal'
                }
            ])
    
    # Update test statistics if in test mode
    if test_mode and test_results and options:
        source_name = 'Game-Specific Knowledge'
        test_results.setdefault('options_by_source', {})
        test_results['options_by_source'].setdefault(source_name, 0)
        test_results['options_by_source'][source_name] += len(options)
    
    return options

def validate_game_specific_option(command: str, engine_hint: str = None, debug: bool = False) -> bool:
    """Engine-aware validation for game-specific options"""
    
    # Mapping lives in validation/options_validator.py so there is exactly one
    # of it. This function used to keep a private dict covering only the three
    # display names it knew about, which meant the newer engine values —
    # GoldSrc, Source 2, id Tech, Kex Engine — silently fell through to
    # UNIVERSAL with nothing to indicate a hint had been dropped.
    engine_type = engine_type_for(engine_hint)

    validator = LaunchOptionsValidator(ValidationLevel.STRICT)
    is_valid, reason = validator.validate_option(command, engine_type)
    
    if debug and not is_valid:
        print(f"🔍 Game-Specific: Rejected '{command}' for {engine_hint or 'Universal'} - {reason}")
    
    return is_valid