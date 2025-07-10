def fetch_game_specific_options(app_id, title, cache, test_results=None, test_mode=False):
    """Fetch game-specific launch options based on patterns"""
    options = []
    
    # Derive title from cache or app_id
    title = cache.get(str(app_id), {}).get('title', 'Unknown Game Title')

    # Source engine games often share options
    source_engine_options = [
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
            'command': '-windowed',
            'description': 'Run the game in windowed mode',
            'source': 'Source Engine'
        },
        {
            'command': '-fullscreen',
            'description': 'Run the game in fullscreen mode',
            'source': 'Source Engine'
        },
        {
            'command': '-noborder',
            'description': 'Run the game in borderless windowed mode',
            'source': 'Source Engine'
        }
    ]
    
    # Unity engine games often share common options
    unity_engine_options = [
        {
            'command': '-screen-width',
            'description': 'Set screen width (e.g., -screen-width 1920)',
            'source': 'Unity Engine'
        },
        {
            'command': '-screen-height',
            'description': 'Set screen height (e.g., -screen-height 1080)',
            'source': 'Unity Engine'
        },
        {
            'command': '-popupwindow',
            'description': 'Run in borderless windowed mode',
            'source': 'Unity Engine'
        },
        {
            'command': '-window-mode',
            'description': 'Set window mode (values: exclusive, windowed, borderless)',
            'source': 'Unity Engine'
        }
    ]
    
    # Unreal Engine games often share common options
    unreal_engine_options = [
        {
            'command': '-windowed',
            'description': 'Run the game in windowed mode',
            'source': 'Unreal Engine'
        },
        {
            'command': '-fullscreen',
            'description': 'Run the game in fullscreen mode',
            'source': 'Unreal Engine'
        },
        {
            'command': '-presets=',
            'description': 'Specify graphics preset (e.g., -presets=high)',
            'source': 'Unreal Engine'
        },
        {
            'command': '-dx12',
            'description': 'Force DirectX 12 rendering',
            'source': 'Unreal Engine'
        },
        {
            'command': '-dx11',
            'description': 'Force DirectX 11 rendering',
            'source': 'Unreal Engine'
        }
    ]
    
    # Check for known games
    lower_title = title.lower()
    
    # Source engine games
    if any(game in lower_title for game in ['counter-strike', 'half-life', 'portal', 'team fortress', 'left 4 dead', 'garry', 'dota']):
        options.extend(source_engine_options)
    
    # Check for Unity games
    elif 'unity' in lower_title or app_id in cache and 'unity' in str(cache.get(str(app_id), {})).lower():
        options.extend(unity_engine_options)
    
    # Check for Unreal Engine games
    elif 'unreal' in lower_title or app_id in cache and 'unreal' in str(cache.get(str(app_id), {})).lower():
        options.extend(unreal_engine_options)
    
    # Common launch options
    general_options = [
        {
            'command': '-fps_max',
            'description': 'Limit maximum FPS (e.g., -fps_max 144)',
            'source': 'Launch Option'
        },
        {
            'command': '-nojoy',
            'description': 'Disable joystick/controller support',
            'source': 'Launch Option'
        },
        {
            'command': '-nosplash',
            'description': 'Skip splash/intro screens',
            'source': 'Launch Option'
        }
    ]
    
    options.extend(general_options)
    
    # Update test statistics
    if test_mode and options:
        source = 'Game-Specific Knowledge'
        if source not in test_results['options_by_source']:
            test_results['options_by_source'][source] = 0
        test_results['options_by_source'][source] += len(options)
    
    return options