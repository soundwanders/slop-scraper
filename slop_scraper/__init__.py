"""
SlopScraper - A Python tool for gathering a list of Steam games and scraping the web to find their launch options.

This package allows users to collect various launch options for Steam games from
various sources including PCGamingWiki, Steam Community, and custom game-specific
configurations and save them into a Supabase database.
"""

# Version information
__version__ = "0.10"
__author__ = "soundwanders"

# Define exports
__all__ = [
    "SlopScraper",  # Main class
    "main",         # Main function
    "__version__",  # Version info
    "run_scraper",  # CLI runner function
]


def __getattr__(name):
    """
    Lazy attribute access (PEP 562).

    Importing .main or .core.scraper eagerly at package-init time caused
    `python3 -m slop_scraper.main` to import the main module twice (once via
    this __init__, once as __main__), triggering a RuntimeWarning about
    'slop_scraper.main' already being in sys.modules. Resolving the imports
    only when the attribute is actually requested avoids the double import
    while keeping `from slop_scraper import SlopScraper` and
    `from slop_scraper import main` working.
    """
    if name == "SlopScraper":
        from .core.scraper import SlopScraper
        return SlopScraper
    if name == "main":
        from .main import main
        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def run_scraper():
    """Run SlopScraper from the command line."""
    from .main import main
    main()
