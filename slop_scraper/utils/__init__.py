import os
import sys

try:
    # Try relative imports first (when run as module)
    from .results_utils import (
        save_test_results,
        save_game_results
    )
    from .cache import (
        load_cache,
        save_cache
    )
    from .security_config import (
        SecurityConfig,
        RateLimiter,
        SecureRequestHandler,
        CredentialManager,
        SessionMonitor,
        validate_usage_pattern
    )
except ImportError:
    # Fall back to absolute imports (when run directly)
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    
    from results_utils import (
        save_test_results,
        save_game_results
    )
    from cache import (
        load_cache,
        save_cache
    )
    from security_config import (
        SecurityConfig,
        RateLimiter,
        SecureRequestHandler,
        CredentialManager,
        SessionMonitor,
        validate_usage_pattern
    )

# Define public API for the utils package
__all__ = [
    # Results utilities
    "save_test_results",
    "save_game_results",
    
    # Cache utilities
    "load_cache",
    "save_cache",
    
    # Security utilities
    "SecurityConfig",
    "RateLimiter", 
    "SecureRequestHandler",
    "CredentialManager",
    "SessionMonitor",
    "validate_usage_pattern"
]