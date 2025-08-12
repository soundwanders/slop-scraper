"""
Validation Configuration
Centralized configuration for validation settings
"""

from .options_validator import ValidationLevel, EngineType

class ValidationConfig:
    """Centralized validation configuration"""
    
    # Default validation levels by scraper
    SCRAPER_VALIDATION_LEVELS = {
        'pcgamingwiki': ValidationLevel.PERMISSIVE,
        'steamcommunity': ValidationLevel.PERMISSIVE,
        'protondb': ValidationLevel.RELAXED, 
        'game_specific': ValidationLevel.STRICT
    }
    
    # Engine detection mapping
    ENGINE_KEYWORDS = {
        'source': EngineType.SOURCE,
        'unity': EngineType.UNITY,
        'unreal': EngineType.UNREAL
    }
    
    # Performance settings
    ENABLE_CACHING = True
    MAX_VALIDATION_TIME_MS = 100  # Maximum time per validation
    
    # Debug settings
    LOG_REJECTED_OPTIONS = True
    LOG_VALIDATION_STATS = True

# Global configuration instance
config = ValidationConfig()