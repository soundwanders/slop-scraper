# SlopScraper


**SlopScraper** is a Python CLI tool for scraping Steam launch options from various sources and aggregating the data into a Supabase database. 
The Slop Scraper was built to support the [Vanilla Slops](https://github.com/soundwanders/vanilla-slops) project. 

While I have built security measures into this program to prevent abuse due to the general nature of repeated API calls and web scraping, I'm no Alan Turing and it's up to you to do the right thing.

So, if you find yourself alone, riding in green fields with the sun on your face, with access to the Slop Scraper, do not be troubled. 
Use your power wisely. 😊


## 📦 Features

- **Multi-source scraping**: Fetches launch options from PCGamingWiki, Steam Community guides, and game engine documentation
- **Steam API integration**: Retrieves comprehensive game data from Steam's public API
- **Rate limiting**: Respectful scraping with configurable delays
- **Progress tracking**: Real-time progress bars with [tqdm](https://tqdm.github.io/)
- **Graceful shutdown**: Clean exit handling with data preservation
- **Modular architecture**: Well-organized codebase for easy maintenance and extension

## 🔧 Installation & Setup

### Prerequisites

- Python 3.8 or higher
- A Supabase account and project (for production mode)

### Get the Code

```bash
git clone https://github.com/soundwanders/slop-scraper.git
cd slop-scraper
```

### Choose Your Setup Method

You have two options for running SlopScraper:

#### **Option A: Package Installation (Recommended)**
*Install once, run from anywhere*

```bash
# Install the package
pip install -e .

# Or with development dependencies
pip install -e ".[dev]"

# Now you can use the slop-scraper command from anywhere
slop-scraper --test --limit 5
```

#### **Option B: Direct Script Execution**
*Run without installation*

```bash
# Navigate to the source directory
cd slop_scraper

# Run directly
python3 main.py --test --limit 5
```

### Environment Setup (For Production Mode)

Create a `.env` file in the project root:
```env
SUPABASE_URL=your_supabase_project_url
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
```

Alternatively, set these as environment variables or create a credentials file at `~/.supabase_creds`:
```json
{
  "url": "your_supabase_project_url",
  "key": "your_service_role_key"
}
```

## 🗄️ Database Setup

The tool requires specific Supabase tables. Create these tables in your Supabase project:

```sql
-- Games table
CREATE TABLE games (
    app_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    developer TEXT,
    publisher TEXT,
    release_date TEXT,
    engine TEXT DEFAULT 'Unknown',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Sources table
CREATE TABLE sources (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    reliability_score DECIMAL(3,2) DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Launch options table
CREATE TABLE launch_options (
    id SERIAL PRIMARY KEY,
    command TEXT UNIQUE NOT NULL,
    description TEXT,
    source TEXT NOT NULL,
    verified BOOLEAN DEFAULT FALSE,
    upvotes INTEGER DEFAULT 0,
    downvotes INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Junction table for many-to-many relationship
CREATE TABLE game_launch_options (
    id SERIAL PRIMARY KEY,
    game_app_id INTEGER REFERENCES games(app_id) ON DELETE CASCADE,
    launch_option_id INTEGER REFERENCES launch_options(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(game_app_id, launch_option_id)
);
```

## 🚀 Usage

### Available Options

| Option | Description | Default |
|-------------------|----------------------------------------------------------|---------------------|
| `--test` | Run in test mode (save results locally) | False |
| `--limit LIMIT` | Maximum number of games to process | 10 |
| `--rate RATE` | Delay in seconds between requests | 2.0 |
| `--output PATH` | Output directory for test results | `./test-output` |
| `--absolute-path` | Use absolute path for output directory | False |
| `--force-refresh` | Force refresh of cached game data | False |
| `--test-db` | Test database connection and exit | False |

### 🔍 Usage Examples

Choose the command format based on your installation method:

#### **If you installed the package (Option A):**

```bash
# Test the database connection
slop-scraper --test-db

# Run in test mode with 10 games
slop-scraper --test --limit 10

# Production run with 50 games
slop-scraper --limit 50 --rate 1.5

# Save test results to a custom directory
slop-scraper --test --output ./my-results --limit 20

# Force refresh cached data and run with absolute output path
slop-scraper --test --force-refresh --output /home/user/slop-data --absolute-path

# High-volume production run with conservative rate limiting
slop-scraper --limit 200 --rate 3.0
```

#### **If you're running the script directly (Option B):**

*Make sure you're in the `slop_scraper` directory first*

```bash
# Test the database connection
python3 main.py --test-db

# Run in test mode with 10 games
python3 main.py --test --limit 10

# Production run with 50 games
python3 main.py --limit 50 --rate 1.5

# Save test results to a custom directory
python3 main.py --test --output ./my-results --limit 20

# Force refresh cached data and run with absolute output path
python3 main.py --test --force-refresh --output /home/user/slop-data --absolute-path

# High-volume production run with conservative rate limiting
python3 main.py --limit 200 --rate 3.0
```

### **🛠️ Quick Start Guide**

1. **First-time setup:**
   ```bash
   # Clone the repository
   git clone https://github.com/soundwanders/slop-scraper.git
   cd slop-scraper
   
   # Choose Option A (install) OR Option B (direct run)
   # Option A:
   pip install -e .
   slop-scraper --test-db
   
   # Option B:
   cd slop_scraper
   python3 main.py --test-db
   ```

2. **Development workflow:**
   ```bash
   # Test with small dataset (adjust command based on your setup)
   slop-scraper --test --limit 5        # If installed
   python3 main.py --test --limit 5     # If running directly
   
   # Check results
   ls test-output/
   cat test-output/test_results.json
   ```

3. **Production usage:**
   ```bash
   # Set up environment variables
   export SUPABASE_URL="your_url_here"
   export SUPABASE_SERVICE_ROLE_KEY="your_key_here"
   
   # Run scraper (adjust command based on your setup)
   slop-scraper --limit 100 --rate 2.0        # If installed
   python3 main.py --limit 100 --rate 2.0     # If running directly
   ```

## 🧪 Test Mode Output

When using `--test`, the tool creates these files in your output directory:

- **`test_results.json`** — Summary statistics and all processed games
- **`game_[appid].json`** — Individual game data with found launch options
- **`appdetails_cache.json`** — Steam API response cache

### Example test_results.json structure:
```json
{
  "games_processed": 10,
  "games_with_options": 8,
  "total_options_found": 42,
  "options_by_source": {
    "PCGamingWiki": 15,
    "Steam Community": 12,
    "Game-Specific Knowledge": 15
  },
  "games": [...]
}
```

## 🏗️ Project Architecture

```
slop_scraper/
├── __init__.py
├── main.py                 # CLI entry point
├── core/
│   ├── __init__.py
│   └── scraper.py         # Main SlopScraper class
├── database/
│   ├── __init__.py
│   └── supabase.py        # Database operations
├── scrapers/              # Source-specific scrapers
│   ├── __init__.py
│   ├── steampowered.py    # Steam API integration
│   ├── pcgamingwiki.py    # PCGamingWiki scraper
│   ├── steamcommunity.py  # Steam Community guides
│   └── game_specific.py   # Built-in game knowledge
└── utils/                 # Utility functions
    ├── __init__.py
    ├── cache.py          # Cache management
    ├── results_utils.py  # Test output handling
    └── security_config.py # Security controls
```

## 🧰 Troubleshooting

### Installation and Command Issues

**Command not found error?**
- If using Option A: Make sure you ran `pip install -e .` from the project root
- If using Option B: Make sure you're in the `slop_scraper` directory and using `python3 main.py`

**Import errors?**
- For Option A: Try reinstalling with `pip install -e . --force-reinstall`
- For Option B: Ensure you have all dependencies installed with `pip install requests beautifulsoup4 tqdm supabase python-dotenv`

### Database Connection Issues

1. **Missing credentials**: The tool automatically falls back to test mode if Supabase credentials are missing
2. **Invalid credentials**: Check your `.env` file or environment variables
3. **Database schema**: Ensure all required tables exist (see Database Setup section)
4. **Network issues**: Verify your Supabase project is accessible

### Rate Limiting and API Errors

**Getting 429 (Too Many Requests) errors?**
```bash
# Increase delay between requests (adjust command for your setup)
slop-scraper --rate 5.0           # If installed
python3 main.py --rate 5.0        # If running directly
```

**Steam API timeouts?**
The tool automatically retries failed requests and caches successful ones.

### Permission and Output Issues

**Can't write to output directory?**
```bash
# Use absolute path (adjust command for your setup)
slop-scraper --test --output /tmp/slop-results --absolute-path
python3 main.py --test --output /tmp/slop-results --absolute-path
```

**Cache file issues?**
Delete the cache file to start fresh:
```bash
rm appdetails_cache.json
```

### Performance Optimization

**For large-scale scraping:**
- Use production mode (database storage is more efficient)
- Increase the limit gradually: `--limit 100`, then `--limit 500`, etc.
- Monitor your Supabase usage to avoid hitting limits
- Use `--force-refresh` sparingly as it bypasses cache

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Install development dependencies: `pip install -e ".[dev]"`
4. Make your changes and add tests
5. Run the test suite: `pytest`
6. Submit a pull request

## 📜 License

MIT License - see [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [PCGamingWiki](https://www.pcgamingwiki.com/) for comprehensive game information
- [Steam Community](https://steamcommunity.com/) for user-generated guides
- [Supabase](https://supabase.com/) for database infrastructure