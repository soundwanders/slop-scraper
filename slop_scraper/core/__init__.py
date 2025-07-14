import os
import sys

try:
    # Try relative imports first (when run as module)
    from .scraper import SlopScraper
except ImportError:
    # Fall back to importing scraper.py directly
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, current_dir)
    
    import scraper
    SlopScraper = scraper.SlopScraper

# For utils imports, let's try both ways too
try:
    from ..utils import load_cache, save_cache
except ImportError:
    # Fall back for utils
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    
    from utils import load_cache, save_cache

__all__ = [
    "SlopScraper", 
    "load_cache", 
    "save_cache"
]