import os

try:
    # Try relative imports first (when run as module)
    from ..validation import LaunchOptionsValidator, ValidationLevel, EngineType
except ImportError:
    # Fall back to absolute imports (when run directly)
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from validation import LaunchOptionsValidator, ValidationLevel, EngineType

"""
Game-Specific Launch Options Scraper
"""
def fetch_game_specific_options(app_id, title, cache, test_results=None, test_mode=False):
    """
    Fetch game-specific launch options based on engine detection and game patterns
    launch options for various game engines and specific games.
    :param app_id: The Steam application ID of the game
    :param title: The title of the game
    :param cache: Cache object to retrieve game metadata
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
    
    # Combined text for pattern matching
    all_text = f"{lower_title} {developer_text} {publisher_text} {category_text} {genre_text}"
    
    # ENGINE-SPECIFIC DETECTION AND OPTIONS
    
    # 1. SOURCE ENGINE GAMES (Valve games and Source-based)
    source_engine_indicators = [
        # Game titles
        'counter-strike', 'half-life', 'portal', 'team fortress', 'left 4 dead', 
        'garry', 'dota', 'day of defeat', 'alien swarm', 'black mesa',
        # Developer/publisher indicators
        'valve corporation', 'valve software',
        # Engine indicators
        'source engine', 'source 2'
    ]
    
    if any(indicator in all_text for indicator in source_engine_indicators):
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
    elif any(indicator in all_text for indicator in [
        'unity', 'unity technologies', 'made with unity',
        # Known Unity games
        'cuphead', 'ori and the', 'hollow knight', 'cities skylines', 'kerbal space',
        'subnautica', 'hearthstone', 'pillars of eternity'
    ]):
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
    elif any(indicator in all_text for indicator in [
        'unreal engine', 'epic games', 'epic games launcher',
        # Known Unreal games
        'fortnite', 'rocket league', 'borderlands', 'bioshock infinite', 
        'gears of war', 'mass effect', 'batman arkham', 'mortal kombat'
    ]):
        options.extend([
            {
                'command': '-ResX=',
                'description': 'Set horizontal resolution (e.g., -ResX=1920)',
                'source': 'Unreal Engine'
            },
            {
                'command': '-ResY=',
                'description': 'Set vertical resolution (e.g., -ResY=1080)',
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
            {
                'command': '-vulkan',
                'description': 'Force Vulkan renderer',
                'source': 'Unreal Engine'
            },
            {
                'command': '-sm4',
                'description': 'Force Shader Model 4.0',
                'source': 'Unreal Engine'
            },
            {
                'command': '-USEALLAVAILABLECORES',
                'description': 'Utilize all available CPU cores',
                'source': 'Unreal Engine'
            },
            {
                'command': '-malloc=system',
                'description': 'Use system memory allocator for better performance',
                'source': 'Unreal Engine'
            }
        ])
    
    # 4. ID TECH ENGINE (id Software games)
    elif any(indicator in all_text for indicator in [
        'id software', 'id tech',
        'doom', 'quake', 'wolfenstein', 'rage'
    ]):
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
    elif 'minecraft' in lower_title and 'java' in all_text:
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
    elif any(game in lower_title for game in ['skyrim', 'fallout', 'elder scrolls', 'starfield']):
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
    elif any(indicator in all_text for indicator in [
        'electronic arts', 'ea games', 'frostbite',
        'battlefield', 'fifa', 'need for speed', 'mass effect andromeda'
    ]):
        options.extend([
            {
                'command': '-windowed',
                'description': 'Run in windowed mode',
                'source': 'Frostbite Engine'
            },
            {
                'command': '-novid',
                'description': 'Skip intro videos',
                'source': 'Frostbite Engine'
            },
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
    
    # Map engine strings to enum
    engine_map = {
        'source engine': EngineType.SOURCE,
        'unity engine': EngineType.UNITY, 
        'unreal engine': EngineType.UNREAL
    }
    
    engine_type = engine_map.get(engine_hint.lower() if engine_hint else None, EngineType.UNIVERSAL)
    
    validator = LaunchOptionsValidator(ValidationLevel.STRICT)
    is_valid, reason = validator.validate_option(command, engine_type)
    
    if debug and not is_valid:
        print(f"🔍 Game-Specific: Rejected '{command}' for {engine_hint or 'Universal'} - {reason}")
    
    return is_valid