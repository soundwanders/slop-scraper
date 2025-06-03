"""
SlopScraper - A Python tool for gathering a list of Steam games and scraping the web to find their launch options.

This package allows users to collect various launch options for Steam games from
various sources including PCGamingWiki, Steam Community, and custom game-specific
configurations and save them into a Supabase database. 
"""

# Version information
__version__ = "0.10"
__author__ = "soundwanders"

# Import and expose the main class for ease of use
from .core.scraper import SlopScraper

# Import main function for CLI usage
try:
    from .main import main
except ImportError:
    # Fallback if main module has import issues
    def main():
        """Fallback main function"""
        print("Main function not available. Try running the script directly.")

# Define exports
__all__ = [
    "SlopScraper",  # Main class
    "main",         # Main function
    "__version__",  # Version info
    "run_scraper",  # CLI runner function
]

def run_scraper():
    """Run SlopScraper from the command line."""
    main()

# Only run main if this module is executed directly
if __name__ == "__main__":
    main()