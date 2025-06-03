import os
import sys

try:
    # Try relative imports first (when run as module)
    from .supabase import (
        setup_supabase_connection, 
        get_supabase_credentials, 
        test_database_connection, 
        fetch_steam_launch_options_from_db, 
        save_to_database
    )
except ImportError:
    # Fall back to absolute imports (when run directly)
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    
    from supabase import (
        setup_supabase_connection, 
        get_supabase_credentials, 
        test_database_connection, 
        fetch_steam_launch_options_from_db, 
        save_to_database
    )

__all__ = [
    "setup_supabase_connection",
    "get_supabase_credentials", 
    "test_database_connection", 
    "fetch_steam_launch_options_from_db", 
    "save_to_database"
]