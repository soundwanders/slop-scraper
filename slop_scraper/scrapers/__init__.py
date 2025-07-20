"""
Steam Game Launch Options Scrapers

This module contains various scrapers for finding launch options for Steam games
from different sources such as Steam Community guides, PCGamingWiki, and ProtonDB.
"""

import os
import sys

try:
    # Try relative imports first (when run as module)
    from .game_specific import fetch_game_specific_options
    from .steampowered import get_steam_game_list
    from .steamcommunity import fetch_steam_community_launch_options
    from .pcgamingwiki import fetch_pcgamingwiki_launch_options, format_game_title_for_api
    from .protondb import fetch_protondb_launch_options
except ImportError:
    # Fall back to absolute imports (when run directly)
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    
    from game_specific import fetch_game_specific_options
    from steampowered import get_steam_game_list
    from steamcommunity import fetch_steam_community_launch_options
    from pcgamingwiki import fetch_pcgamingwiki_launch_options, format_game_title_for_api
    from protondb import fetch_protondb_launch_options

__all__ = [
    'fetch_game_specific_options',
    'get_steam_game_list',
    'fetch_steam_community_launch_options',
    'fetch_pcgamingwiki_launch_options',
    'format_game_title_for_api', 
    'fetch_protondb_launch_options'
]