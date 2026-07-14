import re
import time
import os
import requests
from urllib.parse import quote

try:
    # Try relative imports first (when run as module)
    from ..validation import LaunchOptionsValidator, ValidationLevel, EngineType
except ImportError:
    # Fall back to absolute imports (when run directly)
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from validation import LaunchOptionsValidator, ValidationLevel, EngineType

def fetch_pcgamingwiki_launch_options(game_title, app_id=None, rate_limit=None, debug=False,
                                    test_results=None, test_mode=False, rate_limiter=None,
                                    session_monitor=None):
    """
    Fetches launch options for a game from PCGamingWiki using the official API.

    Page lookup order (most to least reliable):
      1. Cargo query by Steam AppID — exact, immune to title formatting
      2. Cargo query by page name — Cargo stores names with SPACES, not underscores
      3. Full-text search over title variations (including the original title)
    """

    # Security validation
    if not game_title or len(game_title) > 200:
        if debug:
            print("⚠️ Invalid game title for PCGamingWiki lookup")
        return []

    if rate_limiter:
        rate_limiter.wait_if_needed("scraping", domain="pcgamingwiki.com")
    elif rate_limit:
        time.sleep(rate_limit)

    if debug:
        print(f"🔍 PCGamingWiki API: Looking up '{game_title}' (app_id={app_id})")

    options = []

    try:
        page_id = None

        # Method 1: Cargo lookup by Steam AppID (exact match, no title guessing)
        if app_id:
            page_id = _cargo_find_page(
                f'Infobox_game.Steam_AppID HOLDS "{int(app_id)}"',
                debug=debug, session_monitor=session_monitor
            )

        # Method 2: Cargo lookup by page name (with spaces — MediaWiki underscores
        # never match because Cargo stores _pageName with spaces)
        if not page_id:
            page_name = format_game_title_for_api(game_title)
            escaped = page_name.replace('\\', '').replace('"', '\\"')
            page_id = _cargo_find_page(
                f'Infobox_game._pageName="{escaped}"',
                debug=debug, session_monitor=session_monitor
            )

        if page_id:
            content_options = get_launch_options_from_page_api(page_id, debug=debug)
            # Apply strict validation to prevent false positives
            validated_options = validate_pcgaming_options(content_options, debug=debug)
            options.extend(validated_options)

            if debug:
                print(f"🔍 PCGamingWiki API: Extracted {len(content_options)} raw, {len(validated_options)} validated options")
        else:
            if debug:
                print(f"🔍 PCGamingWiki API: Game '{game_title}' not found via Cargo, trying full-text search...")

            # Method 3: full-text search over title variations
            alt_options = try_alternative_search(game_title, debug=debug)
            validated_alt_options = validate_pcgaming_options(alt_options, debug=debug)
            options.extend(validated_alt_options)
        
        # Update test statistics
        if test_mode and test_results:
            source = 'PCGamingWiki'
            if source not in test_results['options_by_source']:
                test_results['options_by_source'][source] = 0
            test_results['options_by_source'][source] += len(options)
        
        if debug:
            print(f"🔍 PCGamingWiki API: Final result: {len(options)} validated options found")
            for opt in options[:3]:
                print(f"🔍 PCGamingWiki API:   {opt['command']}: {opt['description'][:40]}...")
        
        return options
        
    except Exception as e:
        if session_monitor:
            session_monitor.record_error()
        
        if debug:
            print(f"🔍 PCGamingWiki API: Error for '{game_title}': {e}")
        else:
            print(f"🔍 PCGamingWiki API: Error for '{game_title}': {e}")
        
        return []

def _cargo_find_page(where_clause, debug=False, session_monitor=None):
    """Run a Cargo query against Infobox_game and return the first PageID, or None."""
    try:
        response = requests.get(
            "https://www.pcgamingwiki.com/w/api.php",
            params={
                "action": "cargoquery",
                "tables": "Infobox_game",
                "fields": "Infobox_game._pageName=Page,Infobox_game._pageID=PageID",
                "where": where_clause,
                "format": "json",
                "limit": "1"
            },
            timeout=15
        )

        if session_monitor:
            session_monitor.record_request()

        if response.status_code != 200:
            if debug:
                print(f"🔍 PCGamingWiki API: Cargo query failed with status {response.status_code}")
            return None

        results = response.json().get("cargoquery") or []
        if not results:
            return None

        page_info = results[0]["title"]
        if debug:
            print(f"🔍 PCGamingWiki API: Found page '{page_info.get('Page')}' (ID: {page_info.get('PageID')})")
        return page_info.get("PageID")

    except Exception as e:
        if debug:
            print(f"🔍 PCGamingWiki API: Cargo query error: {e}")
        return None

def validate_pcgaming_options(options, debug=False):
    """
    Strict validation for PCGamingWiki options to prevent HTML artifacts and false positives
    """
    validated_options = []
    
    for option in options:
        command = option.get('command', '').strip()
        description = option.get('description', '').strip()
        
        # STRICT validation for command
        if not validate_pcgw_option(command, debug=debug):
            if debug:
                print(f"🔍 PCGamingWiki: REJECTED command '{command}' - failed strict validation")
            continue
        
        # Clean and validate description 
        clean_description = clean_wiki_description(description, debug=debug)
        if not clean_description:
            clean_description = f"Launch option from PCGamingWiki"
        
        validated_options.append({
            'command': command,
            'description': clean_description,
            'source': 'PCGamingWiki'
        })
        
        if debug:
            print(f"🔍 PCGamingWiki: ACCEPTED '{command}' with clean description")
    
    return validated_options

def validate_pcgw_option(command: str, debug: bool = False) -> bool:
    """Production-ready validation for PCGamingWiki options"""
    
    validator = LaunchOptionsValidator(ValidationLevel.PERMISSIVE)
    is_valid, reason = validator.validate_option(command, EngineType.UNIVERSAL)
    
    if debug and not is_valid:
        print(f"🔍 PCGamingWiki: Rejected '{command}' - {reason}")
    
    return is_valid

def clean_wiki_description(description, debug=False):
    """
    Clean wiki description text to remove markup and artifacts
    """
    if not description:
        return ""

    # Strip wiki list markers (#, *, :) left over from numbered instructions
    description = re.sub(r'^[\s#*:;]+', '', description)

    # Remove HTML/XML tags
    description = re.sub(r'<[^>]+>', '', description)
    
    # Remove wiki markup
    description = re.sub(r'\{\{[^}]*\}\}', '', description)  # Templates
    description = re.sub(r'\[\[[^]]*\]\]', '', description)  # Links
    description = re.sub(r"'''?([^']*?)'''?", r'\1', description)  # Bold/italic
    description = re.sub(r'<ref[^>]*>.*?</ref>', '', description, flags=re.DOTALL)  # References
    description = re.sub(r'<ref[^>]*/?>', '', description)  # Self-closing refs
    
    # Remove wiki reference artifacts
    description = re.sub(r'\}\}.*?\{\{', ' ', description)
    description = re.sub(r'\|.*?\|', ' ', description)

    # The regexes above only strip CLOSED pairs. Truncated wikitext leaves
    # unclosed markup ("Use the -nomovies [[Glossary:Command line arguments")
    # that reached production. The shared cleaner cuts at the first markup
    # token, trims dangling function words, and rejects short fragments.
    try:
        from ..validation import clean_option_description
    except ImportError:
        from validation import clean_option_description
    description = clean_option_description(description) or ""

    # Reject template-parameter residue and path fragments that survive the
    # markup cut ("borderless windowed notes = ...", "fix=", "to \tf\custom")
    if description:
        if '\\' in description or re.search(r'\b(?:notes|fix|ref|description|comment)\s*=', description):
            return ""
        # A 1-2 letter lowercase first word means the context window sliced
        # the sentence mid-word ("e property ...", "n that playable ...")
        first_word = description.split(' ', 1)[0]
        if len(first_word) <= 2 and first_word.islower() and first_word not in ('a',):
            return ""

    # Clean up whitespace
    description = re.sub(r'\s+', ' ', description).strip()

    # If description is too long or contains artifacts, truncate/clean
    if len(description) > 200:
        description = description[:200] + "..."
    
    # Remove descriptions that are just artifacts
    artifact_patterns = [
        r'^and the .* are present',
        r'.*unavailable.*',
        r'^\d+$',  # Just numbers
        r'^[<>{}|]+$',  # Just markup characters
    ]
    
    for pattern in artifact_patterns:
        if re.match(pattern, description.lower()):
            return ""
    
    # If description is very short and not meaningful, provide default
    if len(description) < 10:
        return "Launch option from PCGamingWiki"
    
    return description

def format_game_title_for_api(title):
    """Format game title for PCGamingWiki API search"""
    formatted = title.strip()

    # Steam stores some titles in ALL CAPS (e.g. "FINAL FANTASY IX", "DAVE THE DIVER").
    # PCGamingWiki uses title case, so convert before building the page name.
    words = formatted.split()
    alpha_words = [w for w in words if w.isalpha()]
    if alpha_words and sum(1 for w in alpha_words if w.isupper()) / len(alpha_words) > 0.6:
        formatted = formatted.title()

    # Keep spaces — Cargo stores _pageName with spaces, not underscores.
    # Only strip characters that break the Cargo where-clause.
    formatted = formatted.replace('"', '')

    # Capitalize first letter (MediaWiki standard)
    if formatted:
        formatted = formatted[0].upper() + formatted[1:] if len(formatted) > 1 else formatted.upper()

    return formatted

def get_launch_options_from_page_api(page_id, debug=False):
    """Get launch options from a PCGamingWiki page using official API"""
    options = []

    try:
        # Get page content using official MediaWiki API
        content_url = "https://www.pcgamingwiki.com/w/api.php"
        content_params = {
            "action": "parse",
            "format": "json",
            "pageid": page_id,
            "prop": "wikitext"
        }

        response = requests.get(content_url, params=content_params, timeout=15)

        if response.status_code == 200:
            content_data = response.json()

            if "parse" in content_data and "wikitext" in content_data["parse"]:
                wikitext = content_data["parse"]["wikitext"]["*"]

                if debug:
                    print(f"🔍 PCGamingWiki API: Retrieved {len(wikitext)} characters of wikitext")

                # Parse wikitext for launch options with strict validation
                parsed_options = parse_wikitext_for_launch_options_strict(wikitext, debug=debug)
                options.extend(parsed_options)

    except Exception as e:
        if debug:
            print(f"🔍 PCGamingWiki API: Error getting page content: {e}")

    return options

def _is_plausible_launch_option(cmd: str) -> bool:
    """
    Reject strings that look like URL slugs, game title fragments, or template
    parameter names rather than real command-line options.

    Real launch options are compact tokens like -novid, -dx11, -threads, +fps_max.
    False positives from PCGamingWiki wikitext look like:
      -orchestra-ostfront-41-45  (URL slug with 3+ hyphens)
      -An-Accidental-Haunting    (Title-Case words = page title fragment)
      -time, -game, -person      (common English nouns = template params)
    """
    inner = cmd.lstrip('+-')

    # Reject URL slugs: 3 or more hyphens total in the command
    if cmd.count('-') >= 3:
        return False

    # Reject Title-Case hyphenated phrases (page title or category fragments)
    parts = inner.split('-')
    if len(parts) >= 2 and any(p and p[0].isupper() for p in parts[1:]):
        return False

    # Reject single capitalized English-looking words (-Games, -Menu, -Base).
    # Real options are lowercase (-novid), ALLCAPS (-USEALLAVAILABLECORES),
    # or mixed case with internal capitals (-ResX) — never simple Title Case.
    if re.match(r'^[A-Z][a-z]+$', inner):
        return False

    # Reject bare common English words that are never launch options
    _COMMON_WORDS = {
        'time', 'game', 'person', 'hosting', 'man', 'day', 'way', 'year',
        'work', 'life', 'world', 'hand', 'part', 'place', 'case', 'week',
        'company', 'system', 'program', 'question', 'government', 'number',
        'night', 'point', 'home', 'water', 'room', 'mother', 'area', 'money',
        'story', 'fact', 'month', 'lot', 'right', 'study', 'book', 'eye',
        'job', 'word', 'business', 'issue', 'side', 'kind', 'head', 'house',
        'service', 'friend', 'father', 'power', 'hour', 'move', 'city',
    }
    if inner.lower() in _COMMON_WORDS:
        return False

    return True


def parse_wikitext_for_launch_options_strict(wikitext, debug=False):
    """
    Parse MediaWiki wikitext for launch options.

    Three-phase approach so we don't destroy template data before parsing:
      Phase 1 - <code>-option</code> markup in raw wikitext (most common PCGamingWiki pattern)
      Phase 2 - template argument scanning ({{ ... -option ... }})
      Phase 3 - keyword-section search on cleaned text with proper forward lookahead
    """
    options = []
    seen_commands = set()

    def _add_option(command, description):
        cmd_lower = command.lower().strip()
        if cmd_lower not in seen_commands and validate_pcgw_option(command, debug=debug):
            seen_commands.add(cmd_lower)
            options.append({
                'command': command.strip(),
                'description': description,
                'source': 'PCGamingWiki'
            })
            if debug:
                print(f"🔍 PCGamingWiki: Found option: {command.strip()}")

    # Anchored so a match can't start mid-word: prose like "free-to-play" or
    # URL slugs like "team-fortress-2" produced junk matches (-to-play, -fortress-2)
    # when the leading '-' was preceded by a word character.
    launch_option_patterns = [
        r'(?<![\w\-])(-[a-zA-Z][a-zA-Z0-9_\-]{1,30}(?:\s+[^\s<\|]{1,20})?)',
        r'(?<![\w\-])(\+[a-zA-Z][a-zA-Z0-9_\-]{1,30}(?:\s+[^\s<\|]{1,20})?)',
    ]

    # Phase 1: <code>-option</code> and <tt>-option</tt> in raw wikitext
    # PCGamingWiki table cells frequently use <code> markup around options
    for tag in ('code', 'tt', 'kbd'):
        for match in re.finditer(rf'<{tag}>([^<]{{1,80}})</{tag}>', wikitext):
            candidate = match.group(1).strip()
            if not candidate.startswith(('-', '+')):
                continue
            context_start = max(0, match.start() - 200)
            context_end = min(len(wikitext), match.end() + 300)
            context = wikitext[context_start:context_end]
            # A single code tag can hold several options (e.g. "-window -noborder")
            for token in candidate.split():
                if token.startswith(('-', '+')) and _is_plausible_launch_option(token):
                    desc = extract_description_from_context_safe(token, context)
                    _add_option(token, desc)

    # Phase 2: scan inside template blocks before they are stripped
    # Only accept options from blocks that look like launch option templates.
    # Unrestricted scanning picks up URL slugs and template parameter names
    # (e.g. {{game|-time|...}} → "-time", {{Red Orchestra-...-sk|}} → "-sk").
    launch_template_names = re.compile(
        r'^(?:launch\s*option|cmd|command|startup\s*option|game\s*option)',
        re.IGNORECASE
    )
    for block in re.finditer(r'\{\{([^{}]{0,600})\}\}', wikitext):
        block_text = block.group(1)
        template_name = block_text.split('|')[0].strip()
        if not launch_template_names.match(template_name):
            continue
        for pat in launch_option_patterns:
            for m in re.finditer(pat, block_text):
                cmd = m.group(1).split()[0]
                if _is_plausible_launch_option(cmd):
                    _add_option(cmd, 'Launch option from PCGamingWiki')

    # Phase 3: keyword-section search on cleaned text with proper lookahead
    # The bug in the original: it searched only the keyword-containing line.
    # Headers like "== Command line arguments ==" match the keyword filter but
    # hold no options — the actual table rows follow on subsequent lines.
    cleaned_text = clean_wikitext(wikitext)
    lines = cleaned_text.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i]
        if any(kw in line.lower() for kw in
               ['command line', 'launch option', 'startup option', 'command-line',
                'parameter', 'argument', 'launch flag']):
            # Collect the next 25 lines as the section body
            section_end = min(len(lines), i + 25)
            section_text = '\n'.join(lines[i:section_end])
            for pat in launch_option_patterns:
                for m in re.finditer(pat, section_text):
                    cmd = m.group(1).split()[0]
                    if _is_plausible_launch_option(cmd):
                        desc = extract_description_from_context_safe(cmd, section_text)
                        _add_option(cmd, desc)
            i = section_end  # Skip ahead past the section we just consumed
        else:
            i += 1

    if debug:
        print(f"🔍 PCGamingWiki: Total unique options parsed: {len(options)}")

    return options[:25]

def clean_wikitext(wikitext):
    """
    Clean wikitext to remove markup that could cause false positives
    """
    # Remove reference tags completely
    cleaned = re.sub(r'<ref[^>]*>.*?</ref>', '', wikitext, flags=re.DOTALL)
    cleaned = re.sub(r'<ref[^>]*/?>', '', cleaned)
    
    # Remove other HTML tags
    cleaned = re.sub(r'<[^>]+>', '', cleaned)
    
    # Remove templates
    cleaned = re.sub(r'\{\{[^}]*\}\}', '', cleaned)
    
    # Remove links but keep link text
    cleaned = re.sub(r'\[\[([^]|]*\|)?([^]]*)\]\]', r'\2', cleaned)
    
    # Remove wiki markup
    cleaned = re.sub(r"'''([^']*?)'''", r'\1', cleaned)  # Bold
    cleaned = re.sub(r"''([^']*?)''", r'\1', cleaned)   # Italic

    # Collapse spaces/tabs but PRESERVE newlines — the keyword-section search
    # relies on line structure; flattening to one line made "the next 25 lines"
    # mean "the entire page", which let prose junk flood the results.
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

    return cleaned

def extract_description_from_context_safe(command, context):
    """
    Safely extract description for a command from its context
    """
    # Prefer a Fixbox/template description= parameter when present — it is a
    # human-written summary ("Use the -windowed property") rather than markup soup.
    desc_match = re.search(r'description\s*=\s*([^|}]{5,150})', context)
    if desc_match:
        desc = clean_wiki_description(desc_match.group(1).strip())
        if desc and len(desc) > 5:
            return desc

    lines = context.split('\n')
    
    for line in lines:
        if command in line:
            # Clean up the line
            desc = line.strip()
            
            # Remove the command itself from description
            desc = desc.replace(command, '').strip()
            
            # Clean up wiki markup from description
            desc = clean_wiki_description(desc)
            
            if desc and len(desc) > 5 and len(desc) < 150:
                return desc
    
    return f"Launch option from PCGamingWiki"

def try_alternative_search(game_title, debug=False):
    """
    Try alternative search methods when exact title match fails.

    Attempts multiple title variations so clean titles (no special chars)
    also get a fallback instead of silently returning nothing.
    """
    options = []

    # Build several candidate title variations to try
    title_variations = _build_title_variations(game_title)

    if debug:
        print(f"🔍 PCGamingWiki API: Trying {len(title_variations)} title variations for '{game_title}'")

    search_url = "https://www.pcgamingwiki.com/w/api.php"

    # The original title is a valid variation here: this full-text search is a
    # different mechanism than the Cargo lookups that already failed, so it must
    # NOT be skipped (skipping it left simple titles with zero search attempts).
    for variation in title_variations:
        if not variation:
            continue

        try:
            if debug:
                print(f"🔍 PCGamingWiki API: Searching variation: '{variation}'")

            search_params = {
                "action": "query",
                "format": "json",
                "list": "search",
                "srsearch": variation,
                "srlimit": "3"
            }

            response = requests.get(search_url, params=search_params, timeout=10)

            if response.status_code == 200:
                search_data = response.json()

                if "query" in search_data and "search" in search_data["query"]:
                    search_results = search_data["query"]["search"]

                    if search_results:
                        page_id = search_results[0].get("pageid")

                        if debug and page_id:
                            title_found = search_results[0].get("title", "?")
                            print(f"🔍 PCGamingWiki API: Found page '{title_found}' (ID: {page_id})")

                        if page_id:
                            alt_options = get_launch_options_from_page_api(page_id, debug=debug)
                            if alt_options:
                                options.extend(alt_options)
                                break  # Stop at first variation that yields results

        except Exception as e:
            if debug:
                print(f"🔍 PCGamingWiki API: Variation search error for '{variation}': {e}")

    return options


def _build_title_variations(game_title):
    """Build a list of title variations to try when exact match fails."""
    variations = []

    def _clean(s):
        """Strip special chars and collapse whitespace."""
        return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', '', s)).strip()

    def _rstrip_separator(s):
        """Remove trailing ' -', ' —', ' :', etc. left by edition stripping."""
        return re.sub(r'[\s\-—:]+$', '', s).strip()

    # 0. Title-case version for ALL CAPS Steam titles (e.g. "FINAL FANTASY IX")
    words = game_title.split()
    alpha_words = [w for w in words if w.isalpha()]
    if alpha_words and sum(1 for w in alpha_words if w.isupper()) / len(alpha_words) > 0.6:
        variations.append(game_title.title())

    # 1. Strip special characters
    simplified = _clean(game_title)
    if simplified:
        variations.append(simplified)

    # 2. Drop subtitle (everything after " - " or ": ")
    for sep in (' - ', ': ', ' — '):
        if sep in game_title:
            base = game_title.split(sep)[0].strip()
            if base:
                variations.append(base)
                variations.append(_clean(base))
            break

    # 3. Remove edition/version suffixes (common in Steam titles)
    edition_stripped = re.sub(
        r'\s*([-—]\s*)?(Complete|Definitive|Enhanced|Remastered|Gold|GOTY|'
        r'Game of the Year|Special|Deluxe|Ultimate|Anniversary|Director\'s Cut)\s*Edition.*$',
        '', game_title, flags=re.IGNORECASE
    )
    edition_stripped = _rstrip_separator(edition_stripped)
    if edition_stripped and edition_stripped != game_title:
        variations.append(edition_stripped)

    # 4. Remove "The " prefix if present
    if game_title.lower().startswith('the '):
        variations.append(game_title[4:])

    # 5. Plain title with no modifications (always attempt a general search)
    variations.append(game_title)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for v in variations:
        key = v.lower()
        if key not in seen and v:
            seen.add(key)
            unique.append(v)
    return unique