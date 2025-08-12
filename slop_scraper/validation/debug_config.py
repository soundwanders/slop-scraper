"""Debug configuration for validation system"""

class ValidationDebugConfig:
    # Logging options
    LOG_ALL_VALIDATIONS = False      # Log every validation (very verbose)
    LOG_REJECTED_OPTIONS = True      # Log only rejected options
    LOG_STATISTICS = True            # Log validation statistics
    
    # Testing options
    VALIDATION_TEST_MODE = False     # Enable test mode for validation
    SAVE_REJECTED_OPTIONS = True     # Save rejected options to file for analysis
    
    # Performance monitoring
    TRACK_VALIDATION_TIME = True     # Track time spent on validation
    MAX_VALIDATION_TIME_WARNING = 50  # Warn if validation takes > 50ms

debug_config = ValidationDebugConfig()