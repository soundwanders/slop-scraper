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

# Circuit breaker for PCGamingWiki outages. Observed 2026-07: the site's
# frontend responds instantly but api.php can go fully unresponsive (TLS
# handshake completes, zero bytes ever received) for extended periods. Without
# this, every game in a run pays the full ~15s+10s*variations timeout chain
# (~70s observed) for a source that's going to return nothing anyway. Two
# consecutive network-level failures (timeouts/connection errors — NOT
# legitimate "page not found" results) opens the circuit for a cooldown.
_CIRCUIT_FAILURE_THRESHOLD = 2
_CIRCUIT_COOLDOWN_SECONDS = 120
_circuit_state = {'consecutive_failures': 0, 'open_until': 0.0}


def _circuit_is_open():
    return time.time() < _circuit_state['open_until']


def _record_network_failure():
    _circuit_state['consecutive_failures'] += 1
    if _circuit_state['consecutive_failures'] >= _CIRCUIT_FAILURE_THRESHOLD:
        _circuit_state['open_until'] = time.time() + _CIRCUIT_COOLDOWN_SECONDS


def _record_network_success():
    _circuit_state['consecutive_failures'] = 0
    _circuit_state['open_until'] = 0.0


# Tracks whether the MOST RECENT fetch_pcgamingwiki_launch_options call could
# not reach a confident answer (site was down for all or part of the lookup),
# as opposed to a genuine "queried successfully, found nothing". Callers that
# save an empty result to the database should check this immediately after
# calling and record the game for a later recheck rather than treating the
# empty list as confirmed. Safe as module state because games are processed
# one at a time, sequentially, in the scraper's main loop.
_last_call_needs_recheck = False

# Engines recorded on the page that was VERIFIED to be the game just looked up.
#
# The page's wikitext is already in memory — it was downloaded to read launch
# options out of — and the infobox states the engine right there. Until now the
# engine came only from a bulk Cargo table cached for a week, through the same
# endpoint that has since closed, so a game's engine could not be learned at
# scrape time at all.
#
# Only ever set from a page that passed the App ID check, for the same reason
# the options are: an engine read off the wrong game's page is worse than no
# engine, because games.engine decides which block of engine-specific flags
# gets attached. Same module-state caveat as above — one game at a time.
_last_page_engines = []


def pcgamingwiki_needs_recheck():
    """True if the last call's empty/partial result may be an outage artifact."""
    return _last_call_needs_recheck


def pcgamingwiki_page_engines():
    """
    Engines the last verified page recorded, in order of appearance.

    Empty when the lookup failed, the page was never verified, or the wiki
    records no engine for it. More than one entry means the page genuinely
    lists several (Terraria records XNA and FNA) — the caller is expected to
    decline rather than pick, since nothing here establishes which applies.
    """
    return list(_last_page_engines)


def _record_page_engines(wikitext, debug=False):
    """Remember the engines named on a page already proven to be this game."""
    global _last_page_engines
    try:
        try:
            from ..utils.pcgw_wikitext import parse_page_engines
        except ImportError:
            from utils.pcgw_wikitext import parse_page_engines
        _last_page_engines = parse_page_engines(wikitext)
        if debug and _last_page_engines:
            print(f"🔍 PCGamingWiki API: Page records engine(s): {_last_page_engines}")
    except Exception:
        _last_page_engines = []


# Resolving a page by NAME used to be Cargo's job (method 2 below). Cargo now
# refuses every query, so the only path left was full-text search — which ranks
# by relevance to a title string and returns five hits. For a short or common
# title the game's own page is not among them:
#
#     Portal (app 400) -> Portal 2 Sixense Perceptual Pack, Portal of Evil,
#                         ZanZarah: The Hidden Portal, Portal Knights, Portal RTX
#
# App-ID verification then correctly declined all five and the lookup returned
# nothing, which is indistinguishable from "this game has no page". Measured
# across 284 games holding PCGamingWiki options, 102 of them (36%) resolved no
# page at all — including Portal, Half-Life, Quake, RAGE and HITMAN.
#
# MediaWiki can still resolve a title directly. This asks for the page by name,
# follows redirects, and verifies the App ID exactly as every other path does.
# Redirects do real work here, because Steam and PCGamingWiki name things
# differently: "Grand Theft Auto V Legacy" -> "Grand Theft Auto V",
# "SimCity 4 Deluxe Edition" -> "SimCity 4".
#
# Several title variants go in ONE request, so this costs a single call.
_TRADEMARKS = re.compile(r'[\u2122\u00ae\u00a9]')


def _title_variants(game_title):
    """Spellings of a Steam title worth asking MediaWiki for, most exact first."""
    seen, out = set(), []
    for candidate in (
            game_title,
            _TRADEMARKS.sub('', game_title),
            _TRADEMARKS.sub('', game_title).replace('\u2019', "'"),
            _TRADEMARKS.sub('', game_title).replace('&', 'and'),
    ):
        cleaned = re.sub(r'\s+', ' ', candidate).strip()
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            out.append(cleaned)
    return out[:4]


def _resolve_page_by_title(game_title, app_id, debug=False):
    """
    (page_id, wikitext) for the page named by this title, or (None, None).

    Verified against app_id like every other lookup path — a title that names
    the wrong game is exactly the failure this repo has removed twice.
    Returns the wikitext too, so the caller does not re-fetch what we just read.
    """
    variants = _title_variants(game_title)
    if not variants or not app_id:
        return None, None

    try:
        _pace()
        response = requests.get(
            "https://www.pcgamingwiki.com/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "prop": "revisions",
                "rvslots": "main",
                "rvprop": "content",
                "redirects": "1",
                "titles": "|".join(variants),
            },
            timeout=15,
        )
        if response.status_code != 200:
            return None, None
        data = response.json().get('query', {})
    except Exception as e:
        if debug:
            print(f"🔍 PCGamingWiki API: title lookup failed: {e}")
        return None, None

    # MediaWiki rewrites what we asked for twice over — once normalising the
    # string, once following redirects — so map our variant to what came back.
    covers_app = _page_verifier()
    normalised = {n['from']: n['to'] for n in data.get('normalized', [])}
    redirected = {r['from']: r['to'] for r in data.get('redirects', [])}
    by_title = {page['title']: page for page in data.get('pages', {}).values()}

    for variant in variants:
        resolved = normalised.get(variant, variant)
        resolved = redirected.get(resolved, resolved)
        page = by_title.get(resolved)
        revisions = (page or {}).get('revisions') or []
        if not revisions:
            continue
        wikitext = revisions[0].get('slots', {}).get('main', {}).get('*', '')
        if not wikitext:
            continue
        if covers_app(wikitext, app_id):
            if debug:
                print(f"🔍 PCGamingWiki API: title lookup resolved "
                      f"'{variant}' -> '{resolved}' for app {app_id}")
            return page.get('pageid'), wikitext
        if debug:
            print(f"🔍 PCGamingWiki API: '{resolved}' does not cover app {app_id}")

    return None, None


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

    global _last_call_needs_recheck, _last_page_engines
    _last_call_needs_recheck = False
    _last_page_engines = []

    # Security validation
    if not game_title or len(game_title) > 200:
        if debug:
            print("⚠️ Invalid game title for PCGamingWiki lookup")
        return []

    if _circuit_is_open():
        if debug:
            remaining = _circuit_state['open_until'] - time.time()
            print(f"🔍 PCGamingWiki API: Circuit open (site unresponsive), "
                  f"skipping for {remaining:.0f}s more")
        _last_call_needs_recheck = True
        return []

    _set_pace(rate_limit)

    if rate_limiter:
        rate_limiter.wait_if_needed("scraping", domain="pcgamingwiki.com")
    elif rate_limit:
        _pace()

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

        # Method 2b: resolve the page by its title through the ordinary
        # MediaWiki API. This is what replaces Cargo's page-name lookup, and it
        # runs before full-text search because a name is an answer while a
        # search is a guess. The wikitext comes back with it, so a hit costs one
        # request rather than two.
        title_wikitext = None
        if not page_id:
            page_id, title_wikitext = _resolve_page_by_title(
                game_title, app_id, debug=debug)

        if title_wikitext:
            _record_page_engines(title_wikitext, debug=debug)
            content_options = _options_from_wikitext(
                title_wikitext, page_id, debug=debug) or []
            validated_options = validate_pcgaming_options(content_options, debug=debug)
            options.extend(validated_options)
            if debug:
                print(f"🔍 PCGamingWiki API: Extracted {len(content_options)} raw, "
                      f"{len(validated_options)} validated options (title lookup)")
        elif page_id:
            content_options = get_launch_options_from_page_api(
                page_id, debug=debug, expect_app_id=app_id) or []
            # Apply strict validation to prevent false positives
            validated_options = validate_pcgaming_options(content_options, debug=debug)
            options.extend(validated_options)

            if debug:
                print(f"🔍 PCGamingWiki API: Extracted {len(content_options)} raw, {len(validated_options)} validated options")
        else:
            if debug:
                print(f"🔍 PCGamingWiki API: Game '{game_title}' not found via Cargo, trying full-text search...")

            # Method 3: full-text search over title variations
            alt_options = try_alternative_search(game_title, debug=debug, app_id=app_id)
            validated_alt_options = validate_pcgaming_options(alt_options, debug=debug)
            options.extend(validated_alt_options)
        
        # Update test statistics
        if test_mode and test_results:
            source = 'PCGamingWiki'
            if source not in test_results['options_by_source']:
                test_results['options_by_source'][source] = 0
            test_results['options_by_source'][source] += len(options)
        
        # An empty result while the circuit is now open (it may have tripped
        # partway through this very call) means we never got a confident
        # answer — don't let it look like a confirmed "no options on wiki".
        if not options and _circuit_is_open():
            _last_call_needs_recheck = True

        if debug:
            print(f"🔍 PCGamingWiki API: Final result: {len(options)} validated options found")
            for opt in options[:3]:
                print(f"🔍 PCGamingWiki API:   {opt['command']}: {opt['description'][:40]}...")

        return options

    except Exception as e:
        if session_monitor:
            session_monitor.record_error()

        _last_call_needs_recheck = True

        if debug:
            print(f"🔍 PCGamingWiki API: Error for '{game_title}': {e}")
        else:
            print(f"🔍 PCGamingWiki API: Error for '{game_title}': {e}")

        return []

# Minimum seconds between OUTBOUND requests, not between games.
#
# A single lookup now makes up to four requests — two Cargo attempts, a search,
# and one batched wikitext fetch — and the only sleep was at the top of the
# lookup. So a run at --rate 2.0 slept 2s and then sent four requests back to
# back. The scraper believed it was polite; the wiki saw bursts. That showed up
# as intermittent empty results under sustained load, which read exactly like
# "this game has no page" and quietly under-reported an audit.
_pace_interval = 0.0
_pace_last = 0.0


def _set_pace(rate_limit):
    """Adopt the caller's rate as a floor between individual requests."""
    global _pace_interval
    try:
        _pace_interval = max(0.0, float(rate_limit or 0.0))
    except (TypeError, ValueError):
        _pace_interval = 0.0


def _pace():
    """Wait until the configured interval has elapsed since the last request."""
    global _pace_last
    if _pace_interval > 0:
        wait = _pace_interval - (time.time() - _pace_last)
        if wait > 0:
            time.sleep(wait)
    _pace_last = time.time()


# Cargo answers "You don't have permission to run arbitrary Cargo queries".
# That is a policy decision, not a hiccup, so retrying it every game spends two
# requests per game to be told no twice. After a few consecutive refusals the
# lookup path is skipped for the rest of the process; it costs nothing to try
# again next run, and if PCGamingWiki reopens the endpoint the exact-by-App-ID
# path returns on its own.
_cargo_refusals = 0
_CARGO_REFUSAL_LIMIT = 3


def _cargo_disabled():
    return _cargo_refusals >= _CARGO_REFUSAL_LIMIT


def _page_verifier():
    """page_covers_app / parse_page_engines, under either import style."""
    try:
        from ..utils.pcgw_wikitext import page_covers_app
    except ImportError:
        from utils.pcgw_wikitext import page_covers_app
    return page_covers_app


def _cargo_find_page(where_clause, debug=False, session_monitor=None):
    """Run a Cargo query against Infobox_game and return the first PageID, or None."""
    global _cargo_refusals

    if _cargo_disabled():
        return None

    try:
        _pace()
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
        # A response was received at all — the network path works, whatever
        # the status code. Reset the circuit breaker.
        _record_network_success()

        if session_monitor:
            session_monitor.record_request()

        if response.status_code != 200:
            if debug:
                print(f"🔍 PCGamingWiki API: Cargo query failed with status {response.status_code}")
            return None

        payload = response.json()

        # Distinguish "no such game" from "you may not ask". Only the second
        # is worth giving up on.
        if isinstance(payload, dict) and 'error' in payload:
            info = str(payload['error'].get('info', ''))
            if 'permission' in info.lower() or 'denied' in info.lower():
                _cargo_refusals += 1
                if debug or _cargo_refusals == _CARGO_REFUSAL_LIMIT:
                    print(f"🔍 PCGamingWiki API: Cargo refused ({info.strip()})"
                          + (" — skipping Cargo for the rest of this run"
                             if _cargo_disabled() else ""))
            elif debug:
                print(f"🔍 PCGamingWiki API: Cargo error: {info}")
            return None

        results = payload.get("cargoquery") or []
        if not results:
            return None

        page_info = results[0]["title"]
        if debug:
            print(f"🔍 PCGamingWiki API: Found page '{page_info.get('Page')}' (ID: {page_info.get('PageID')})")
        return page_info.get("PageID")

    except requests.exceptions.RequestException as e:
        # Timeout / connection error — the site itself is unreachable, not
        # just this particular query. Feeds the circuit breaker.
        _record_network_failure()
        if debug:
            print(f"🔍 PCGamingWiki API: Cargo query network error: {e}")
        return None
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
            'source': 'PCGamingWiki',
            'source_url': option.get('source_url')
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

# HTML elements that actually appear in wikitext. Anything else inside angle
# brackets is left alone — see the note in clean_wiki_description.
_HTML_TAG = re.compile(
    r'</?\s*(?:br|ref|references|b|i|s|u|em|strong|small|big|sub|sup|code|pre|'
    r'tt|nowiki|noinclude|includeonly|span|div|p|hr|font|center|blockquote|'
    r'ul|ol|li|table|tr|td|th|thead|tbody|caption|abbr|kbd|samp|var|del|ins)'
    r'(?:\s[^>]*)?/?>',
    re.IGNORECASE
)


# Two inline templates carry words the sentence needs. Stripped along with
# every other template they left holes that still read as prose — "Press to
# bring up the editor", "Toggle profile with , and see", "Enables for taking
# screen shots" — four published rows, from {{key|F11}} and {{key|F10}}. A key
# template is the key's name (several keys are a chord); {{code|X}} is X.
_KEY_TEMPLATE = re.compile(r'\{\{\s*key\s*\|([^{}]*)\}\}', re.IGNORECASE)
_CODE_TEMPLATE = re.compile(r'\{\{\s*code\s*\|([^{}|]*)\}\}', re.IGNORECASE)
# {{file|.CFG}} names a file or extension, and stripping it left Far Cry 2's
# -exec documented as working on "files with a extension".
_FILE_TEMPLATE = re.compile(r'\{\{\s*file\s*\|([^{}|]*)\}\}', re.IGNORECASE)


def _render_inline_templates(text):
    text = _KEY_TEMPLATE.sub(
        lambda m: '+'.join(p.strip() for p in m.group(1).split('|') if p.strip()), text or '')
    text = _FILE_TEMPLATE.sub(lambda m: m.group(1).strip(), text)
    return _CODE_TEMPLATE.sub(lambda m: m.group(1).strip(), text)


_POINTER_SENTENCE = re.compile(
    r'(?:^|(?<=[.!?])\s+)[^.!?]*\b(?:here|this (?:article|page|guide|link|thread|post|video))\b'
    r'[^.!?]*[.!?]?\s*$',
    re.IGNORECASE)


def _drop_pointer_sentence(text):
    """Remove a trailing "see here" sentence; '' if pointing was all it did."""
    if not text:
        return text
    return _POINTER_SENTENCE.sub('', text).strip()


def _command_cell(text):
    """
    A table's command cell as plain text, for reading the VALUE after a flag.

    Unlike _plain(), <placeholder> tokens survive. Red Dead Redemption 2 writes
    "-processPriorityClass <class>_PRIORITY_CLASS"; stripped as though <class>
    were an HTML tag, what was left looked like a concrete value, and a genuine
    description of the flag was withheld.
    """
    text = re.sub(r'<ref[^>]*>.*?</ref>|<ref[^>]*/>', '', text or '', flags=re.DOTALL)
    text = _render_inline_templates(text)
    text = _HTML_TAG.sub('', text)
    text = re.sub(r"\{\{[^{}]*\}\}|'{2,}", '', text)
    return re.sub(r'\s+', ' ', text).strip()


def clean_wiki_description(description, debug=False):
    """
    Clean wiki description text to remove markup and artifacts
    """
    if not description:
        return ""

    # Strip wiki list markers (#, *, :) left over from numbered instructions
    description = re.sub(r'^[\s#*:;]+', '', description)
    description = _render_inline_templates(description)

    # Remove HTML/XML tags — but only ones that are actually tags.
    #
    # This used to be re.sub(r'<[^>]+>', ...), which treats anything in angle
    # brackets as markup. Documentation writes PLACEHOLDERS the same way, so it
    # quietly destroyed them:
    #
    #   "Write a Proton debug log to $HOME/steam-<appid>.log"
    #     -> "Write a Proton debug log to $HOME/steam-.log"
    #
    # The result still reads as a sentence, which is what makes it dangerous —
    # it looks repaired rather than damaged. Only recognised HTML element names
    # are stripped now; <appid>, <rate>, <width> and friends survive as the
    # placeholders they are.
    description = _HTML_TAG.sub('', description)
    
    # Links carry the words the sentence is made of, so they are RENDERED, not
    # removed. Deleting them wrote "Set quality (0–1)" where Grand Theft Auto V
    # says "Set [[FXAA]] quality (0–1)", and "Enable Nvidia (0–1)" for
    # [[TXAA]] — sentences that still read as sentences with the subject gone.
    # _plain() has always kept labels; this is the same rule, applied on the
    # path the table readers use.
    description = re.sub(r'\[\[(?:[^\]|]*\|)?([^\]]*)\]\]', r'\1', description)
    # An external link renders as its label too: "[https://… this article by
    # Microsoft]" is how a wiki cites one, and dropped whole it left the raw URL
    # behind, which the quality gate then refused as a cut-off link.
    description = re.sub(r'\[https?://\S+\s+([^\]]*)\]', r'\1', description)
    # Templates go last, so the ones that carry words have already rendered.
    description = re.sub(r'\{\{[^}]*\}\}', '', description)
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

    # A final sentence that only POINTS somewhere is dropped. Rendering a link
    # as its label is right for "Set [[FXAA]] quality", but a label that is a
    # pointer renders as a pointer to nothing — the site shows plain text, and
    # the link it pointed at is gone. Braid's -universe ended "... explanation
    # of the mod system is located here", Grand Theft Auto V's -keyboardLocal
    # "... see this article by Microsoft". The sentences before it stand.
    description = _drop_pointer_sentence(description)

    # A long description is cut at a SENTENCE, or not stored at all.
    #
    # This used to be `description[:200] + "..."`, which cut mid-word and then
    # lost the ellipsis to the trailing-punctuation trim, so Grand Theft Auto
    # V's -uilanguage was about to be published as "... korean, chinese,
    # chinesesimp, japanese, mexican (for Mexica". That is the same cut-off
    # shape the quality gate exists to refuse, manufactured by us.
    #
    # Nothing stored today is anywhere near this: the longest description in
    # the catalogue is 132 characters, so this only ever fires on a genuinely
    # long wiki cell.
    if len(description) > 300:
        cut = description.rfind('. ', 0, 300)
        description = description[:cut + 1] if cut > 60 else ""
    
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

def _options_from_wikitext(wikitext, page_id, debug=False, structured_only=True):
    """
    Parse one page's wikitext into options. No network.

    Only flags the page PRESENTS as flags are kept: a table row, a Fixbox, or a
    code span the flag opens (structured_flag_commands). A flag met only in
    running prose — "-any" was the tail of a config-file line in SimCity 4's
    page — is not documentation of a launch option, and the bulk backfill has
    refused those since it was written. The live scraper now holds the same
    line, so a rescan cannot add what the backfill would refuse.
    structured_only=False is for callers that count the refusals themselves.
    """
    parsed = parse_wikitext_for_launch_options_strict(wikitext, debug=debug) or []
    if structured_only:
        structured = structured_flag_commands(wikitext)
        kept = [o for o in parsed if str(o.get('command') or '').strip().lower() in structured]
        if debug and len(kept) < len(parsed):
            dropped = sorted({o['command'] for o in parsed} - {o['command'] for o in kept})
            print(f"🔍 PCGamingWiki: prose-only mentions not kept: {dropped}")
        parsed = kept
    page_url = f"https://www.pcgamingwiki.com/w/index.php?curid={page_id}"
    for opt in parsed:
        opt['source_url'] = page_url
    return parsed


def _fetch_wikitext_batch(page_ids, debug=False):
    """
    {page_id: wikitext} for several pages in ONE request.

    Verification means looking at more than one candidate page, and doing that
    with a request each would have tripled what this scraper asks of
    PCGamingWiki — the opposite of what the politeness rules require.
    MediaWiki will return many pages' content at once, so checking five
    candidates costs the same single round trip that fetching one used to.
    """
    if not page_ids:
        return {}
    try:
        _pace()
        response = requests.get(
            "https://www.pcgamingwiki.com/w/api.php",
            params={"action": "query", "format": "json", "prop": "revisions",
                    "rvprop": "content", "rvslots": "main",
                    "pageids": "|".join(str(p) for p in page_ids)},
            timeout=20
        )
        _record_network_success()
        if response.status_code != 200:
            return {}
        out = {}
        for pid, page in (response.json().get("query", {}).get("pages", {}) or {}).items():
            try:
                out[int(pid)] = page["revisions"][0]["slots"]["main"]["*"]
            except (KeyError, IndexError, TypeError, ValueError):
                continue
        return out
    except Exception as e:
        if debug:
            print(f"🔍 PCGamingWiki API: Batch wikitext fetch failed: {e}")
        return {}


def get_launch_options_from_page_api(page_id, debug=False, expect_app_id=None):
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

        _pace()
        response = requests.get(content_url, params=content_params, timeout=15)

        if response.status_code == 200:
            content_data = response.json()

            if "parse" in content_data and "wikitext" in content_data["parse"]:
                wikitext = content_data["parse"]["wikitext"]["*"]

                if debug:
                    print(f"🔍 PCGamingWiki API: Retrieved {len(wikitext)} characters of wikitext")

                # Is this page actually about the game we asked for?
                #
                # Cargo used to answer that by construction — it looked the
                # page up BY Steam App ID. That endpoint now refuses queries,
                # so resolution falls back to full-text title search, and a
                # title is not an identity. Audited against 284 catalogue
                # games, the first search hit is the wrong page 45% of the
                # time: "Max Payne" resolves to Max Payne 2, "HITMAN" to
                # Hitman 2, "DOOM" to Doom + Doom II.
                #
                # The page states its own App ID, so we check that instead of
                # trusting the search ranking. Returning None rather than []
                # lets the caller try the next candidate: [] would mean "this
                # game has no launch options", which is a different claim and
                # a wrong one.
                if expect_app_id is not None:
                    if not _page_verifier()(wikitext, expect_app_id):
                        if debug:
                            print(f"🔍 PCGamingWiki API: Page {page_id} does not cover "
                                  f"app {expect_app_id} — rejecting")
                        return None
                    _record_page_engines(wikitext, debug=debug)

                # The same parse, and the same structured-only rule, as every
                # other path that reads a page.
                options.extend(_options_from_wikitext(wikitext, page_id, debug=debug))

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

    # Reject URL slugs: 3 or more hyphens total in the command.
    # Real hyphenated flags exist though (--no-vr, -no-stereo-rendering,
    # -force-low-power-device, -force-d3d11-no-singlethreaded), and a plain
    # hyphen count rejects all of them. Options built from these known flag
    # prefixes are exempt — a URL slug never starts that way.
    _FLAG_PREFIXES = ('--', '-force-', '-no-', '-enable-', '-disable-', '-use-', '-set-')
    if cmd.count('-') >= 3 and not cmd.startswith(_FLAG_PREFIXES):
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
        # Added 2026-08-08 after a production cleanup found these extracted
        # from prose sentences on PCGamingWiki pages (e.g. "-based" from
        # "team-based", "-related" from "-related issues"). Verified against
        # a live snapshot of 55 junk rows before adding — see
        # cleanup_wikitext_junk.py for the full review.
        'based', 'related', 'friendly', 'developed', 'protected', 'saboteur',
        'sync', 'order', 'releases', 'bit', 'made', 'platform', 'seamless',
        'core', 'line', 'lit', 'end', 'run', 'print', 'screen', 'source',
        'party', 'processing', 'click', 'compliant', 'doubling', 'episode',
        'fixes', 'gfx', 'nexus', 'prelude', 'in', 'axis', 'aliasing',
        'localization',
    }
    if inner.lower() in _COMMON_WORDS:
        return False

    # Reject hash/GUID fragments (e.g. "-a214-f68e547dd54c"): a run of 8+
    # characters using only hex digits (0-9a-f). Real flags mixing letters
    # and digits are short structured technical terms (d3d12, glcore42,
    # r1600x900x32) that always include a letter outside a-f, so this can't
    # false-positive on them.
    if re.search(r'(?i)[0-9a-f]{8,}', inner):
        return False

    return True


# PCGamingWiki writes launch options two ways. Most pages put them in prose
# with <code>-flag</code> markup, which phases 1-3 below handle. A minority use
# a structured table instead:
#
#     ===Launch options===
#     {{Standard table|Parameter|Description|content=
#     {{Standard table/row|-width|Sets the horizontal resolution.}}
#     {{Standard table/row|-windowed|Forces windowed mode.}}
#     }}
#
# Those rows were invisible here. Phase 2 accepts a template only if its NAME
# looks like a launch-option template, and "Standard table/row" does not match;
# by the time phase 3 runs, clean_wikitext has stripped the braces. Measured on
# Grand Theft Auto IV: 42 documented flags, 4 extracted.
#
# It is worth reading properly because the second cell is a real description
# written by a wiki editor, which is exactly the text this project cannot
# otherwise obtain — see validation/description_quality.py.
#
# "Standard table/row" is a GENERIC template used for tables all over a page
# (save-game locations, API support, middleware). Reading it anywhere would
# pull in rows that are not launch options at all, so this is scoped to the
# launch-options section and nowhere else.
# PCGamingWiki usually writes this heading as a LINK to its glossary:
#
#     ===[[Glossary:Command line arguments|Command line arguments]]===
#
# Matching only the plain spelling found the section on 17 of 470 cached pages.
# Every page whose launch options are in a raw table — Counter-Strike: Global
# Offensive, Dota 2, both Command & Conquer entries, Tunnel Rats — writes the
# linked form, so the section they live in was invisible, and with it the
# editor-written descriptions beside each flag. The optional link prefix and
# the trailing wildcard also pick up "Command line arguments / Launch Options"
# and "Launch options (Linux)".
_LAUNCH_SECTION_HEADING = re.compile(
    r'^=+\s*(?:\[\[[^\]|]*\|)?\s*'
    r'(?:Launch options?|Command[ -]line arguments?|Command[ -]line parameters?)'
    r'[^=\n]*=+\s*$',
    re.IGNORECASE | re.MULTILINE)
_ANY_HEADING = re.compile(r'^=+[^=\n]+=+\s*$', re.MULTILINE)


def _launch_options_section(wikitext):
    """The wikitext between a launch-options heading and the next heading."""
    m = _LAUNCH_SECTION_HEADING.search(wikitext)
    if not m:
        return ''
    body = wikitext[m.end():]
    nxt = _ANY_HEADING.search(body)
    return body[:nxt.start()] if nxt else body


def _iter_template_bodies(text, name):
    """
    Yield the inside of each {{name...}} call, brace-balanced.

    A regex cannot do this: descriptions routinely contain nested templates
    ({{code|...}}, {{Refurl|...}}), so matching to the first '}}' truncates the
    row and can swallow the next one.
    """
    for _, body in _iter_template_spans(text, name):
        yield body


def _iter_template_spans(text, name):
    """(start offset, body) for each {{name...}} call, brace-balanced."""
    needle = '{{' + name
    i = 0
    while True:
        i = text.find(needle, i)
        if i < 0:
            return
        depth, j = 0, i
        while j < len(text):
            if text.startswith('{{', j):
                depth += 1
                j += 2
            elif text.startswith('}}', j):
                depth -= 1
                j += 2
                if depth == 0:
                    break
            else:
                j += 1
        else:
            return  # unbalanced tail; stop rather than guess
        yield i, text[i + 2:j - 2]
        i = j


def _split_template_params(body):
    """Split a template body on top-level '|' only, ignoring nested braces."""
    parts, depth, cur = [], 0, []
    k = 0
    while k < len(body):
        if body.startswith('{{', k) or body.startswith('[[', k):
            depth += 1
            cur.append(body[k:k + 2])
            k += 2
        elif body.startswith('}}', k) or body.startswith(']]', k):
            depth -= 1
            cur.append(body[k:k + 2])
            k += 2
        elif body[k] == '|' and depth == 0:
            parts.append(''.join(cur))
            cur = []
            k += 1
        else:
            cur.append(body[k])
            k += 1
    parts.append(''.join(cur))
    return parts


# A value written after a flag decides what its description is about.
#
# A PLACEHOLDER — "-fpsClamp N", "-xres [number]", "-exec filename" — stands
# for any value, so the row describes the flag. A CONCRETE value does not.
# Saints Row IV's table has one row per language ("-localize_language us |
# Set language to English", "... fr | Set language to French"), Planet Zoo
# documents "-watchdog 0" as "Disable loading watchdog", and Atari 50 lists
# "--display 1080p" and "--display 720p". The command column stores the bare
# flag, so with the value dropped each of those was about to publish one
# value's meaning as the flag's: -localize_language "sets the language to
# English".
#
# The description survives when the documented form was the flag alone, a
# placeholder, or 1 — the switched-on form of a boolean, which IS the flag's
# meaning ("-GameProfile_GodMode 1 | Enables god mode"). Anything else is
# stored without one, and the source link says the rest. Storing the valued
# form as its own row (so "-watchdog 0" is pasteable) is a separate decision.
_PLACEHOLDER_WORDS = {'x', 'y', 'n', 'flag', 'filename', 'file', 'number', 'num',
                      'value', 'path', 'name', 'id', 'level'}


def _is_placeholder(token):
    token = token.strip('\'"`')
    if not token or token in ('#', '$'):
        return True
    # "<class>_PRIORITY_CLASS", "<width>x<height>": a placeholder with text
    # around it is still a placeholder.
    if re.search(r'<\w+>', token):
        return True
    if re.fullmatch(r'[\[<(].*[\]>)]', token):
        return True
    if token.lower() in _PLACEHOLDER_WORDS:
        return True
    return bool(re.fullmatch(r'[A-Z]{1,5}', token)
                or re.fullmatch(r'X+(?:\.\d+)?', token, re.IGNORECASE))


def _value_is_specific(values):
    """True when the tokens after a flag name one particular value."""
    concrete = [v for v in values if not _is_placeholder(v)]
    if not concrete:
        return False
    return not (len(concrete) == 1 and concrete[0].lower() in ('1', 'true', 'on'))


def _options_from_standard_table(wikitext, debug=False):
    """(command, description) pairs from a launch-options section's table."""
    section = _launch_options_section(wikitext)
    if not section:
        return []

    found = []
    for body in _iter_template_bodies(section, 'Standard table/row'):
        params = _split_template_params(body)
        if len(params) < 2:
            continue
        # params[0] is the template name; the flag is the first real cell.
        command = re.sub(r"<[^>]+>|'{2,}", '', params[1]).strip()
        if not command.startswith(('-', '+')):
            continue
        command = command.split()[0] if command.split() else ''
        if not command:
            continue
        cell = params[2] if len(params) > 2 else ''
        # A cell documenting each VALUE on its own line —
        #   +showfps_enabled {{code|X}} | {{code|1}} Enables a simple FPS
        #   counter ... <br/>{{code|2}} Enables a large debug graph ...
        # describes no single meaning of the bare flag the command column
        # stores. Flattened, it was published as one run-on sentence.
        entries = re.split(r'<br\s*/?>', cell)
        if sum(1 for e in entries if re.match(r'\s*\{\{\s*code\s*\|', e)) >= 2:
            description = ''
        elif _value_is_specific(_command_cell(params[1]).split()[1:]):
            description = ''
        else:
            description = clean_wiki_description(cell, debug=debug) if cell else ''
        found.append((command, description))

    if debug and found:
        print(f"🔍 PCGamingWiki: Standard table yielded {len(found)} rows")
    return found


# The THIRD way PCGamingWiki writes launch options: a raw MediaWiki table.
#
#     ===[[Glossary:Command line arguments|Command line arguments]]===
#     {| class="wikitable"
#     ! Command !! Result
#     |-
#     | -nospeedtree || Disables SpeedTree.
#     |-
#     | -freq x OR -refresh x || Sets refresh rate / frequency.
#
# Same value as the {{Standard table}} form — the second cell is a description
# an editor wrote — and just as invisible to the rest of the parser, which
# reads the template in phase 0 and needs <code> markup or prose after that.
# Measured on the pages this repo has cached: Tunnel Rats documents 14 flags
# this way and we stored nine of them, undescribed, from prose.
#
# Scoped to the launch-options section like the template reader, and further
# required to LOOK like a launch-option table: at least two rows whose first
# cell opens with a flag. A page's other tables — save locations, API support,
# middleware, system requirements — cannot satisfy that.
_TABLE_ROW_SEPARATOR = re.compile(r'^\s*\|-.*$', re.MULTILINE)
# "-nod3d9ex or -disable_d3d9ex", "-freq x OR -refresh x", "-a, -b".
_CELL_ALTERNATIVES = re.compile(r'\s+or\s+|\s*,\s*', re.IGNORECASE)


def _iter_pipe_tables(text):
    """Each {| ... |} block, brace-balanced so a nested table cannot truncate one."""
    i = 0
    while True:
        i = text.find('{|', i)
        if i < 0:
            return
        depth, j = 0, i
        while j < len(text):
            if text.startswith('{|', j):
                depth += 1
                j += 2
            elif text.startswith('|}', j):
                depth -= 1
                j += 2
                if depth == 0:
                    break
            else:
                j += 1
        else:
            return  # unbalanced tail; stop rather than guess
        yield text[i:j]
        i = j


def _pipe_table_rows(body):
    """(first cell, second cell) for each data row, however the row is written."""
    rows = []
    for chunk in _TABLE_ROW_SEPARATOR.split(body):
        cells = []
        for line in chunk.split('\n'):
            line = line.strip()
            # '!' is a header row, '|+' a caption, '{|' and '|}' the table itself.
            if not line.startswith('|') or line.startswith(('|}', '|+')):
                continue
            cells.extend(line[1:].split('||'))
        if len(cells) >= 2:
            rows.append((cells[0], cells[1]))
    return rows


def _cell_flags(cell):
    """
    The flags a command cell documents, or [] when it documents none.

    Alternatives are separated ("-freq x OR -refresh x" is two flags, each
    doing what the row says). Flags written side by side are NOT: "-windowed
    -w # -h $ -noborder" says what that combination does together, which is not
    what any one of them does alone. Same judgement as _fixbox_flags.
    """
    text = _plain(cell).strip()
    if not text.startswith(('-', '+')):
        return []
    flags = []
    for part in _CELL_ALTERNATIVES.split(text):
        tokens = part.split()
        if not tokens or not tokens[0].startswith(('-', '+')):
            return []
        # A value placeholder may follow the flag ("-xres [number]", "-heapsize
        # #", "-resolution X Y"); another flag may not.
        if any(token.startswith(('-', '+')) for token in tokens[1:]):
            return []
        if not _is_plausible_launch_option(tokens[0]):
            return []
        flags.append(tokens[0])
    return flags


def _options_from_pipe_table(wikitext, debug=False):
    """(command, description) pairs from a raw table in the launch-options section."""
    section = _launch_options_section(wikitext)
    if not section:
        return []

    found = []
    for body in _iter_pipe_tables(section):
        rows = [(cell, description) for cell, description in _pipe_table_rows(body)
                if _cell_flags(cell)]
        if len(rows) < 2:
            continue
        for cell, description_cell in rows:
            description = clean_wiki_description(description_cell, debug=debug)
            if any(_value_is_specific(part.split()[1:])
                   for part in _CELL_ALTERNATIVES.split(_command_cell(cell))):
                description = ''
            for flag in _cell_flags(cell):
                found.append((flag, description))

    if debug and found:
        print(f"🔍 PCGamingWiki: Pipe table yielded {len(found)} rows")
    return found


# A {{Fixbox}} is how PCGamingWiki documents a workaround:
#
#     ===Remove the save limit===
#     {{Fixbox|description=Use an argument|ref=...|fix=
#     Use the <code>-unlimitedsaves</code> command line argument.
#     }}
#
# The sentence around the flag never says what it does — it is always some
# form of "use this argument". What it does is what the box is FOR, and the
# page says that twice: in description= (usually the method, sometimes the goal
# itself, "Enable Direct3D 11") and in the heading above (the goal, "Remove the
# save limit"). Both are written by an editor, about this fix, on this page,
# which is what makes them usable where text inferred from prose is not.
#
# Until this existed the parser took description= only from boxes containing no
# nested template, and with no judgement of what it said — which is how "Use an
# argument" was published as a definition, and why the same page could be read
# differently depending on whether a box happened to cite a {{Refurl}}.
#
# Two guards keep a box's text off the wrong flag:
#   - the box documents ONE flag, or alternatives for one written side by side
#     ("<code>-d3d11</code> or <code>-dx11</code>"). "-windowed -noborder" says
#     what the pair does together, which is not what either does alone.
#   - the heading is used only when the box's method IS the argument. When
#     description= names a tool ("Use the Widescreen Fix"), the flag is a step
#     in using that tool and the heading describes the tool's result.
#
# Those two were not enough. The first reheal run wrote six descriptions this
# way and four were wrong, each for a reason the page's own structure shows:
#   - +gl_overbright got a Mesa environment-variable fix, because the flag
#     appeared only in a Notes example of a whole Wine command line
#   - +fs_cachepath got "Preserve texture cache between sessions", a fix that
#     is creating folders under %LOCALAPPDATA%
#   - -any, which is not a flag at all but the tail of a config-file line
#     (<code>partialRule "Fast card" -any</code>), was created as an option
#   - -cfg got "Skip intro videos", true of -cfg "playOpeningLogo=false" and not
#     of the bare -cfg the command column stores
# So the box must also be a fix the flag carries on its own: the flag sits in
# the steps rather than the notes, it OPENS its code tag with at most a number
# or placeholder after it, and no step downloads, installs, copies or edits
# anything else.
#
# That was still a list of things a step may not do, and the next reheal found
# two more it did not name:
#   - -nohomedir got "Fixing the game shortcut" — a fix that REMOVES the flag
#   - -widescreen got "Manually patch 16:9 resolutions" — a hex edit whose last
#     step launches with the flag
# So every step is now held to what it MAY do instead: carry the flag, or be
# part of getting it into Steam's launch options or a shortcut (right-click,
# Properties, close and relaunch). Anything else makes the box a larger fix
# the flag is one ingredient of.
_FLAG_IN_CODE = re.compile(r'<(code|tt|kbd)>([^<]{1,80})</\1>')
_METHOD_VERB = re.compile(
    r'^(?:use|install|download|edit|apply|modify|delete|rename|replace|create|'
    r'copy|move|extract|open)\b', re.IGNORECASE)
_ALTERNATIVE_GAP = re.compile(r'^\s*(?:,|/|or|,\s*or)?\s*$', re.IGNORECASE)
# Where a box's steps stop and its caveats begin.
_FIX_NOTES = re.compile(r"'''\s*Notes?\s*'''", re.IGNORECASE)
# A step that does something other than pass an argument.
_OTHER_ACTION = re.compile(
    r'\b(?:download|install|copy|extract|delete|remove|rename|replace|edit|modify|'
    r'registry|environment variable|make a folder|create a folder)\b|\{\{\s*p\s*\|',
    re.IGNORECASE)
# The steps a box may have besides the one carrying the flag.
_LAUNCH_STEP = re.compile(
    r'\bright[\s-]?click|\bproperties\b|\blibrary\b|\bgeneral\s+tab\b'
    r'|\blaunch\s+options?\b|\bcommand[\s-]*line\s+(?:arguments?|parameters?)\b'
    r'|\b(?:press|click)\s+ok\b|\bclose\b|\brelaunch\b|\brestart\b'
    r'|\b(?:launch|run|start|play)\s+(?:the\s+)?game\b'
    r'|\bwhen\s+(?:the\s+)?game\s+(?:is\s+)?(?:launched|started|run)\b',
    re.IGNORECASE)
# A caveat line inside the steps ({{ii}}, {{--}}, {{++}}), not a step.
_NOTE_LINE = re.compile(r'^\s*\{\{\s*(?:ii|--|\+\+|mm)\s*\}\}', re.IGNORECASE)
# What may follow the flag in its code tag: a number, or a placeholder for one.
_PLAIN_VALUE = re.compile(r'^(?:\d+(?:\.\d+)?|#|X+(?:\.\d+)?|<[^>]+>)$', re.IGNORECASE)
# Feature subsections only. A level-2 heading ("==Video==") names a whole
# category, which is not a description of any one fix inside it.
_SUBSECTION_HEADING = re.compile(r'^===+[^=\n]+=+\s*$', re.MULTILINE)


def _plain(text):
    """Wikitext to readable text, keeping link labels ([[A|B]] -> B)."""
    text = re.sub(r'<ref[^>]*>.*?</ref>|<ref[^>]*/>', '', text or '', flags=re.DOTALL)
    text = _render_inline_templates(text)
    text = re.sub(r'\[\[(?:[^\]|]*\|)?([^\]]*)\]\]', r'\1', text)
    text = re.sub(r'\[https?://\S+\s+([^\]]*)\]', r'\1', text)
    text = re.sub(r"\{\{[^{}]*\}\}|<[^>]+>|'{2,}", '', text)
    return re.sub(r'\s+', ' ', text).strip()


def _fixbox_flags(fix_text):
    """
    The flags a box documents, or None when the box is not about them alone.

    Several flags qualify only as alternatives: one per code tag, separated by
    nothing but "or", a comma or a slash.
    """
    steps = _FIX_NOTES.split(fix_text, 1)[0]
    if _OTHER_ACTION.search(steps):
        return None
    for line in steps.splitlines():
        if _NOTE_LINE.match(line):
            continue
        if any(t.startswith(('-', '+')) for m in _FLAG_IN_CODE.finditer(line)
               for t in m.group(2).split()):
            continue
        text = _plain(re.sub(r'^[\s#*:;]+', '', line))
        if text and not _LAUNCH_STEP.search(text):
            return None

    spans = []
    for m in _FLAG_IN_CODE.finditer(steps):
        parts = m.group(2).split()
        tokens = [t for t in parts
                  if t.startswith(('-', '+')) and _is_plausible_launch_option(t)]
        if not tokens:
            continue
        if len(tokens) == 1 and (parts[0] != tokens[0] or len(parts) > 2
                                 or not all(_PLAIN_VALUE.match(p) for p in parts[1:])):
            return None
        # "-watchdog 0": the box's purpose is what THAT value does, and the
        # command column will hold the bare flag. See _value_is_specific.
        if _value_is_specific(parts[1:]):
            return None
        spans.append((m.start(), m.end(), tokens))

    flags, seen = [], set()
    for _, _, tokens in spans:
        for t in tokens:
            if t.lower() not in seen:
                seen.add(t.lower())
                flags.append(t)
    if len(flags) <= 1:
        return flags

    if any(len(tokens) != 1 for _, _, tokens in spans):
        return None
    for (_, end, _), (start, _, _) in zip(spans, spans[1:]):
        if not _ALTERNATIVE_GAP.match(steps[end:start]):
            return None
    return flags


def _options_from_fixboxes(wikitext, debug=False):
    """(command, description) for flags a {{Fixbox}} says the purpose of."""
    try:
        from ..validation import (acceptable_description, clean_option_description,
                                  is_generic_method)
    except ImportError:
        from validation import (acceptable_description, clean_option_description,
                                is_generic_method)

    headings = [(m.start(), m.group(0)) for m in _SUBSECTION_HEADING.finditer(wikitext)]
    found = []
    for start, body in _iter_template_spans(wikitext, 'Fixbox'):
        named = {}
        for param in _split_template_params(body)[1:]:
            if '=' in param:
                key, value = param.split('=', 1)
                named[key.strip().lower()] = value
        flags = _fixbox_flags(named.get('fix', ''))
        if not flags:
            continue

        if _OTHER_ACTION.search(named.get('description', '')):
            continue
        method = _plain(named.get('description', ''))
        if is_generic_method(method):
            heading = next((h for pos, h in reversed(headings) if pos < start), '')
            candidate = _plain(heading.strip().strip('='))
            if _LAUNCH_SECTION_HEADING.match(heading.strip()) or is_generic_method(candidate):
                continue
        elif _METHOD_VERB.match(method):
            continue
        else:
            candidate = method

        # Judged exactly as the write path will judge it, so a candidate that
        # would be stored as NULL leaves the flag to the later phases instead.
        for flag in flags:
            description = acceptable_description(flag, clean_option_description(candidate))
            if description:
                found.append((flag, description))

    if debug and found:
        print(f"🔍 PCGamingWiki: Fixboxes yielded {len(found)} described flags")
    return found


def structured_flag_commands(wikitext, debug=False):
    """
    The flags a page presents AS flags, lowercased.

    Phase 3 of the parser below reads prose near a "command line" heading, and
    that is the loosest thing it does: a config-file fragment on the SimCity 4
    page (`partialRule "Fast card" -any`) became a published option that way.
    For an ordinary scrape that risk is bounded — the game was already being
    read, and a human sees the diff. For a sweep over hundreds of games that
    were never scraped this way it is not, so the backfill links only what this
    returns:

      * a row of the page's launch-options table, in either syntax
      * a flag a {{Fixbox}} documents, under the guards in _fixbox_flags
      * a flag that OPENS a <code>/<tt>/<kbd> span or a {{code|...}} template

    The last one is the distinction that matters. `<code>-nomovies</code>` is
    the page calling `-nomovies` a flag; `<code>partialRule "Fast card"
    -any</code>` is the page quoting a line of a config file that happens to
    contain a dash.
    """
    found = set()

    for command, _ in _options_from_standard_table(wikitext, debug=debug):
        found.add(command.strip().lower())

    for command, _ in _options_from_pipe_table(wikitext, debug=debug):
        found.add(command.strip().lower())

    for command, _ in _options_from_fixboxes(wikitext, debug=debug):
        found.add(command.strip().lower())

    spans = [match.group(1) for tag in ('code', 'tt', 'kbd')
             for match in re.finditer(rf'<{tag}>([^<]{{1,80}})</{tag}>', wikitext)]
    # {{code|-console}} is the template spelling of the same thing, and pages
    # use it just as often — Half-Life documents -console and -nosierra that
    # way. The "opens the span" rule still applies, which is what keeps
    # +gl_overbright out: its span opens with MESA_EXTENSION_OVERRIDE=, because
    # the page is quoting a whole Wine command line, not naming a flag.
    spans += [match.group(1) for match in _CODE_TEMPLATE.finditer(wikitext)]

    for span in spans:
        span = span.strip()
        if not span.startswith(('-', '+')):
            continue
        for token in span.split():
            if token.startswith(('-', '+')) and _is_plausible_launch_option(token):
                found.add(token.lower())

    if debug:
        print(f"🔍 PCGamingWiki: {len(found)} flags in structured markup")
    return found


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
    #
    # Anchored at the end too, so a flag longer than the cap is skipped rather
    # than cut. Unanchored, Helheim Hassle's table flag
    # -merrychristmashohofatherchristmassayhello — refused by the save gate's
    # length limit in phase 0a — was picked up again here as
    # -merrychristmashohofatherchristm and published with the table's
    # description: a flag that does nothing, presented as documented.
    launch_option_patterns = [
        r'(?<![\w\-])(-[a-zA-Z][a-zA-Z0-9_\-]{1,30}(?![\w\-])(?:\s+[^\s<\|]{1,20})?)',
        r'(?<![\w\-])(\+[a-zA-Z][a-zA-Z0-9_\-]{1,30}(?![\w\-])(?:\s+[^\s<\|]{1,20})?)',
    ]

    # Phase 0: the structured launch-options table, read before anything
    # strips it. It runs first so its editor-written description wins over the
    # weaker text the later phases infer from surrounding prose.
    for cmd, desc in _options_from_standard_table(wikitext, debug=debug):
        if _is_plausible_launch_option(cmd):
            _add_option(cmd, desc)

    # Phase 0a: the same table written as raw wiki markup rather than as the
    # template. Read here, beside its sibling, and for the same reason: the
    # description in the second cell is an editor's, and the later phases would
    # claim the flag first with whatever prose surrounds it.
    for cmd, desc in _options_from_pipe_table(wikitext, debug=debug):
        if _is_plausible_launch_option(cmd):
            _add_option(cmd, desc)

    # Phase 0b: flags inside a {{Fixbox}}, described by what the box is for.
    # Before phase 1, which would otherwise claim the flag first with the
    # surrounding "use this argument" sentence — text the gate rightly refuses.
    for cmd, desc in _options_from_fixboxes(wikitext, debug=debug):
        if _is_plausible_launch_option(cmd):
            _add_option(cmd, desc)

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
            tokens = candidate.split()
            for index, token in enumerate(tokens):
                if token.startswith(('-', '+')) and _is_plausible_launch_option(token):
                    values = []
                    for following in tokens[index + 1:]:
                        if following.startswith(('-', '+')):
                            break
                        values.append(following)
                    # The prose around "<code>--display 1080p</code>" is about
                    # 1080p, not about --display. See _value_is_specific.
                    if _value_is_specific(values):
                        desc = 'Launch option from PCGamingWiki'
                    else:
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

    # Cap kept as a guard against a page that parses into nonsense, but raised:
    # a structured table legitimately documents more than 25 flags (Grand Theft
    # Auto IV has 42), and truncating those silently loses documented options.
    return options[:60]

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

def _strip_leading_command(text, command):
    """
    Remove the command from the front of a description without mangling it.

    The old approach (`text.replace(command, '')`) deleted the command from
    ANYWHERE in the sentence, which shredded descriptions where the command is
    grammatically load-bearing:
        "Use the -hz=x command line argument"  -> "Use the =x command line argument"
        "Use the -mod:X to launch modded ..."  -> "Use the to launch modded ..."
        "MESA_EXTENSION_OVERRIDE=-GL_ARB_..."  -> "MESA_EXTENSION_OVERRIDE="
    Only a leading occurrence is redundant with the command column; anywhere
    else it's part of the prose and must be preserved.
    """
    stripped = text.strip()
    if stripped.startswith(command):
        stripped = stripped[len(command):]
        # Drop the separator left behind ("-novid: skips intro" -> "skips intro")
        stripped = re.sub(r'^[\s:\-–—=,|]+', '', stripped)
    return stripped.strip()


def extract_description_from_context_safe(command, context):
    """
    Safely extract description for a command from its context.

    The `description=` template parameter is preferred when it genuinely
    belongs to THIS command, but it must be scoped to the command's own
    template block. Searching the whole context window for any `description=`
    attached the nearest neighbour's text to the wrong flag — that's how
    `-resx=1920` ended up documented as "Enable Direct3D 11" and
    `-localization=english` as "Disable SLI/Crossfire" in production. A
    confidently wrong description is worse than none, so scope strictly and
    fall through rather than guess.
    """
    # Only consider a description= that lives in the same {{...}} block as the
    # command itself.
    for block in re.finditer(r'\{\{([^{}]{0,600})\}\}', context):
        block_text = block.group(1)
        if command not in block_text:
            continue
        if block_text.split('|', 1)[0].strip().lower().startswith('fixbox'):
            # A Fixbox's description= is about the whole fix, not this flag.
            # _options_from_fixboxes reads it with the guards that make that
            # safe; read here without them, it published "Use an argument".
            break
        desc_match = re.search(r'description\s*=\s*([^|}]{5,150})', block_text)
        if desc_match:
            desc = clean_wiki_description(desc_match.group(1).strip())
            if desc and len(desc) > 5:
                return desc
        break

    for line in context.split('\n'):
        if command not in line:
            continue

        desc = clean_wiki_description(_strip_leading_command(line, command))

        # A description that still contains the command mid-sentence is an
        # instruction ABOUT using it, not a definition of it — and once the
        # command is left in place it duplicates the command column. Reject
        # rather than mangle; the fallback below is honest about not knowing.
        if desc and 5 < len(desc) < 150 and command not in desc:
            return desc

    return "Launch option from PCGamingWiki"

def try_alternative_search(game_title, debug=False, app_id=None):
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

        # Stop trying further variations the moment the circuit opens mid-loop
        # (e.g. this variation just timed out) — no point paying 10s each for
        # remaining variations when the site has gone unresponsive.
        if _circuit_is_open():
            if debug:
                print(f"🔍 PCGamingWiki API: Circuit open, abandoning remaining variations")
            break

        try:
            if debug:
                print(f"🔍 PCGamingWiki API: Searching variation: '{variation}'")

            search_params = {
                "action": "query",
                "format": "json",
                "list": "search",
                "srsearch": variation,
                # Five, not one. The right page is often not the top hit —
                # "Max Payne" ranks Max Payne 2 first — and with an App ID to
                # check against we can afford to look past the ranking.
                "srlimit": "5"
            }

            _pace()
            response = requests.get(search_url, params=search_params, timeout=10)
            _record_network_success()

            if response.status_code == 200:
                search_data = response.json()

                if "query" in search_data and "search" in search_data["query"]:
                    search_results = search_data["query"]["search"] or []

                    # Take the candidate that PROVES it is this game by
                    # stating our App ID. Audited over 284 catalogue games,
                    # this recovers the correct page for 11 of the 13 cases
                    # where taking the top hit picked a sequel, a remaster or
                    # a mod. All candidates come back in one request.
                    ordered = [h.get("pageid") for h in search_results if h.get("pageid")]
                    titles = {h.get("pageid"): h.get("title", "?") for h in search_results}
                    texts = _fetch_wikitext_batch(ordered, debug=debug)

                    verify = _page_verifier()
                    for page_id in ordered:
                        wikitext = texts.get(page_id)
                        if not wikitext:
                            continue
                        if app_id is not None and not verify(wikitext, app_id):
                            if debug:
                                print(f"🔍 PCGamingWiki API: '{titles.get(page_id)}' "
                                      f"({page_id}) does not cover app {app_id} — skipping")
                            continue

                        # Verified. Whatever the page holds is the answer, even
                        # if that is nothing: an empty verified page means this
                        # game has no documented options, which is a real
                        # finding. Reading on past it would only find another
                        # game's page.
                        _record_page_engines(wikitext, debug=debug)
                        alt_options = _options_from_wikitext(wikitext, page_id, debug=debug)
                        options.extend(alt_options)
                        if debug:
                            print(f"🔍 PCGamingWiki API: Verified '{titles.get(page_id)}' "
                                  f"for app {app_id} — {len(alt_options)} options")
                        return options

        except requests.exceptions.RequestException as e:
            _record_network_failure()
            if debug:
                print(f"🔍 PCGamingWiki API: Variation search network error for '{variation}': {e}")
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