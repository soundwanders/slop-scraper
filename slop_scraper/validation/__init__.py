"""
Launch Options Validation System
Production-ready validation for Steam launch options
"""

from .options_validator import (
    LaunchOptionsValidator,
    ValidationLevel,
    EngineType,
    engine_type_for,
    validate_launch_option,
    get_recommended_options,
    is_valid_launch_option,
    clean_option_description
)
from .metadata_tagging import (
    classify_risk_level,
    classify_categories,
    classify_engine_compatibility,
    classify_option_metadata,
    describe_env_var,
    PROTON_WINE_DESCRIPTIONS,
    ENV_VAR_BLOCKLIST
)
from .flag_dictionary import (
    FLAG_DICTIONARY,
    lookup_flag,
    curated_description,
    curated_usage_example,
    authority_url
)
from .source_attribution import honest_source, misattributed
from .description_quality import (
    is_junk_description,
    is_placeholder_description,
    acceptable_description,
    PLACEHOLDER_DESCRIPTIONS
)

__all__ = [
    'LaunchOptionsValidator',
    'ValidationLevel',
    'EngineType',
    'engine_type_for',
    'validate_launch_option',
    'get_recommended_options',
    'is_valid_launch_option',
    'clean_option_description',
    'classify_risk_level',
    'classify_categories',
    'classify_engine_compatibility',
    'classify_option_metadata',
    'describe_env_var',
    'PROTON_WINE_DESCRIPTIONS',
    'ENV_VAR_BLOCKLIST',
    'is_junk_description',
    'is_placeholder_description',
    'acceptable_description',
    'PLACEHOLDER_DESCRIPTIONS',
    'FLAG_DICTIONARY',
    'lookup_flag',
    'curated_description',
    'curated_usage_example',
    'honest_source',
    'misattributed',
    'authority_url'
]