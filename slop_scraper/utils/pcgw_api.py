"""
Batched, paced reads of PCGamingWiki's MediaWiki API.

WHY A SECOND CLIENT

scrapers/pcgamingwiki.py asks about ONE game at a time, because that is what a
scrape is: resolve this game's page, read it, move on. Re-reading the whole
catalogue that way costs a request per game no matter how little each page
holds — and most pages hold nothing, so almost every request buys nothing.

MediaWiki answers up to 50 pages in a single request, content included. Asked
that way, 3,000 games cost ~130 requests rather than ~9,000, and a page with no
launch options costs a fiftieth of one request instead of a whole one. That is
the difference between a sweep that is worth running and one that is not, and
it is also the politer of the two: bulk endpoints over page-by-page fetching is
this project's stated rule.

WHAT THIS GUARANTEES

  * One request at a time, never less than `min_interval` apart — the interval
    is between REQUESTS, not between games, because a batch is many games.
  * `maxlag=5`, the MediaWiki convention for "back off while replication is
    behind", honoured with the server's own Retry-After.
  * 429 and 5xx retried with Retry-After or exponential backoff, and a hard
    stop after repeated failures rather than hammering a struggling site.
  * A bot challenge or a permission refusal STOPS the run. This project does
    not work around those, and a refusal is not a transient error to retry.
  * An honest, identifying User-Agent, as MediaWiki's own policy asks for.
  * Titles are validated before they are sent: a Steam name containing '|'
    would otherwise split into two titles mid-request and silently mis-map the
    answers to the wrong game.

Nothing here parses launch options or touches the database. It fetches
wikitext; utils/pcgw_wikitext.py says whose page it is, and
scrapers/pcgamingwiki.py says what the page documents.
"""

import re
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import requests

API_URL = "https://www.pcgamingwiki.com/w/api.php"

# Identifies the project and gives a maintainer a way to find out what it is.
# MediaWiki's User-Agent policy asks for exactly this, and an anonymous default
# ("python-requests/2.x") is what gets a client blocked as a stranger.
USER_AGENT = (
    "slop-scraper/1.0 (+https://github.com/soundwanders/slop-scraper) "
    "batched MediaWiki reads for Steam launch-option metadata"
)

# MediaWiki's limit for an anonymous client asking for several pages at once.
TITLES_PER_REQUEST = 50

# A single response should be a few megabytes at most. Anything far past that
# means something other than what we asked for.
MAX_RESPONSE_BYTES = 24 * 1024 * 1024

# Characters MediaWiki forbids in a title. '|' matters most: it is the
# separator in the request itself, so a title carrying one would be read as two
# titles and every answer after it would map to the wrong game.
_ILLEGAL_TITLE = re.compile(r'[#<>\[\]|{}]|[\x00-\x1f\x7f]')

# How many times a redirect may be followed before we call it a loop.
_MAX_REDIRECT_HOPS = 4


class WikiError(RuntimeError):
    """The API could not be read this time."""


class WikiRefused(WikiError):
    """The site said no — a bot challenge, a block, or a permission refusal.

    Never retried and never worked around. The run stops and says so.
    """


class WikiUnavailable(WikiError):
    """Repeated transport failures. Stop now; the sweep resumes from its cache."""


def valid_title(title: str) -> bool:
    """Whether MediaWiki can be asked for this title at all."""
    if not title or not isinstance(title, str):
        return False
    stripped = title.strip()
    if not stripped or stripped.startswith(':'):
        return False
    if _ILLEGAL_TITLE.search(stripped):
        return False
    return len(stripped.encode('utf-8')) <= 255


def chunked(items: Sequence, size: int) -> Iterable[list]:
    for start in range(0, len(items), size):
        yield list(items[start:start + size])


class MediaWikiClient:
    """A paced, batching, fail-loudly reader for one MediaWiki install."""

    def __init__(self, min_interval: float = 2.0, timeout: Tuple[float, float] = (10, 60),
                 max_retries: int = 3, session=None, sleep=time.sleep,
                 monotonic=time.monotonic, user_agent: str = USER_AGENT,
                 api_url: str = API_URL, debug: bool = False,
                 max_consecutive_failures: int = 3):
        self.min_interval = max(0.0, float(min_interval))
        self.timeout = timeout
        self.max_retries = max_retries
        self.api_url = api_url
        self.debug = debug
        self.max_consecutive_failures = max_consecutive_failures
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request = 0.0
        self._consecutive_failures = 0
        self.session = session or requests.Session()
        self.session.headers.update({
            'User-Agent': user_agent,
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip',
        })
        self.stats = {'requests': 0, 'retries': 0, 'bytes': 0, 'slept': 0.0}

    # ---------------------------------------------------------------- transport

    def _pace(self) -> None:
        if self.min_interval <= 0:
            return
        elapsed = self._monotonic() - self._last_request
        wait = self.min_interval - elapsed
        if wait > 0:
            self.stats['slept'] += wait
            self._sleep(wait)

    def _backoff(self, response, attempt: int) -> float:
        """How long to wait, preferring the server's own answer."""
        header = (response.headers.get('Retry-After') if response is not None else None)
        try:
            if header is not None:
                return min(float(header), 300.0)
        except (TypeError, ValueError):
            pass
        return min(5.0 * (2 ** attempt), 120.0)

    def _get(self, params: dict) -> dict:
        """One API call, with pacing, retries and refusal handling."""
        query = {'format': 'json', 'formatversion': '2', 'maxlag': '5', **params}
        last_error = None

        for attempt in range(self.max_retries + 1):
            self._pace()
            response = None
            try:
                response = self.session.get(self.api_url, params=query, timeout=self.timeout)
                self._last_request = self._monotonic()
                self.stats['requests'] += 1
                self.stats['bytes'] += len(response.content or b'')

                if len(response.content or b'') > MAX_RESPONSE_BYTES:
                    raise WikiError(f"response larger than {MAX_RESPONSE_BYTES} bytes")

                # A challenge page, an error page, or anything else that is not
                # the API answering. Not retried: retrying a bot challenge is
                # how a scraper becomes the problem.
                content_type = (response.headers.get('Content-Type') or '').lower()
                if response.status_code in (401, 403) or (
                        'json' not in content_type and response.status_code == 200):
                    raise WikiRefused(
                        f"HTTP {response.status_code}, Content-Type {content_type!r} — "
                        f"not an API response (bot challenge or block). Stopping.")

                if response.status_code == 429 or response.status_code >= 500:
                    last_error = f"HTTP {response.status_code}"
                    if attempt < self.max_retries:
                        self.stats['retries'] += 1
                        self._sleep(self._backoff(response, attempt))
                        continue
                    raise WikiError(last_error)

                if response.status_code != 200:
                    raise WikiError(f"HTTP {response.status_code}")

                data = response.json()

            except WikiRefused:
                raise
            except (requests.exceptions.RequestException, ValueError) as e:
                last_error = str(e)
                if attempt < self.max_retries:
                    self.stats['retries'] += 1
                    self._sleep(self._backoff(response, attempt))
                    continue
                self._consecutive_failures += 1
                if self._consecutive_failures >= self.max_consecutive_failures:
                    raise WikiUnavailable(
                        f"{self._consecutive_failures} consecutive failures, last: {last_error}")
                raise WikiError(last_error)

            error = data.get('error') if isinstance(data, dict) else None
            if error:
                code = str(error.get('code', ''))
                info = str(error.get('info', ''))
                if code == 'maxlag':
                    last_error = f"maxlag: {info}"
                    if attempt < self.max_retries:
                        self.stats['retries'] += 1
                        self._sleep(self._backoff(response, attempt))
                        continue
                    raise WikiError(last_error)
                if code in ('permissiondenied', 'readapidenied', 'blocked', 'autoblocked') \
                        or 'permission' in info.lower() or 'denied' in info.lower():
                    raise WikiRefused(f"{code}: {info}")
                raise WikiError(f"{code}: {info}")

            self._consecutive_failures = 0
            return data if isinstance(data, dict) else {}

        raise WikiError(last_error or 'request failed')

    # ------------------------------------------------------------------- pages

    @staticmethod
    def _page_from(raw: dict) -> Optional[dict]:
        """A page with its wikitext, or None when the API returned no content."""
        if not isinstance(raw, dict) or raw.get('missing') or raw.get('invalid'):
            return None
        revisions = raw.get('revisions') or []
        if not revisions:
            return None
        slot = ((revisions[0].get('slots') or {}).get('main') or {})
        content = slot.get('content')
        if not content or slot.get('contentmodel') not in (None, 'wikitext'):
            return None
        try:
            page_id = int(raw.get('pageid'))
        except (TypeError, ValueError):
            return None
        return {
            'pageid': page_id,
            'title': raw.get('title') or '',
            'revid': revisions[0].get('revid'),
            'wikitext': content,
        }

    def _revision_params(self) -> dict:
        return {
            'action': 'query',
            'prop': 'revisions',
            'rvprop': 'ids|content',
            'rvslots': 'main',
        }

    def pages_by_titles(self, titles: Sequence[str]) -> Tuple[Dict[int, dict], Dict[str, Optional[int]]]:
        """
        Ask for several titles at once.

        -> ({page_id: page}, {requested title: page_id or None})

        Redirects are followed and normalisation applied, then mapped back to
        what we asked for — MediaWiki rewrites a title twice over, and without
        that mapping the caller cannot tell which answer belongs to which game.
        """
        wanted = [t for t in dict.fromkeys(titles) if valid_title(t)]
        pages: Dict[int, dict] = {}
        resolved: Dict[str, Optional[int]] = {t: None for t in titles}

        for batch in chunked(wanted, TITLES_PER_REQUEST):
            outstanding = list(batch)
            # A batch whose pages are large comes back partially filled, with a
            # `continue` token; the pages that carry no content are simply
            # asked for again rather than lost.
            for _ in range(3):
                if not outstanding:
                    break
                data = self._get({**self._revision_params(),
                                  'redirects': '1',
                                  'titles': '|'.join(outstanding)})
                query = data.get('query') or {}
                rewritten = {}
                for entry in (query.get('normalized') or []):
                    rewritten[entry.get('from')] = entry.get('to')
                redirects = {}
                for entry in (query.get('redirects') or []):
                    redirects[entry.get('from')] = entry.get('to')

                by_title: Dict[str, dict] = {}
                missing_titles = set()
                for raw in (query.get('pages') or []):
                    title = raw.get('title') or ''
                    if raw.get('missing') or raw.get('invalid'):
                        missing_titles.add(title)
                        continue
                    page = self._page_from(raw)
                    if page:
                        pages[page['pageid']] = page
                        by_title[title] = page

                still_outstanding = []
                for requested in outstanding:
                    final = rewritten.get(requested, requested)
                    for _hop in range(_MAX_REDIRECT_HOPS):
                        if final in redirects:
                            final = redirects[final]
                        else:
                            break
                    page = by_title.get(final)
                    if page:
                        resolved[requested] = page['pageid']
                    elif final in missing_titles:
                        resolved[requested] = None
                    else:
                        # Present but content not returned yet (result-size
                        # continuation). Ask again for this one.
                        still_outstanding.append(requested)

                if not data.get('continue'):
                    break
                outstanding = still_outstanding

        return pages, resolved

    def pages_by_ids(self, page_ids: Sequence[int]) -> Dict[int, dict]:
        """Wikitext for page ids already known, batched the same way."""
        ids = []
        for page_id in dict.fromkeys(page_ids):
            try:
                ids.append(int(page_id))
            except (TypeError, ValueError):
                continue

        pages: Dict[int, dict] = {}
        for batch in chunked(ids, TITLES_PER_REQUEST):
            outstanding = list(batch)
            for _ in range(3):
                if not outstanding:
                    break
                data = self._get({**self._revision_params(),
                                  'pageids': '|'.join(str(i) for i in outstanding)})
                query = data.get('query') or {}
                returned = set()
                for raw in (query.get('pages') or []):
                    page = self._page_from(raw)
                    if page:
                        pages[page['pageid']] = page
                        returned.add(page['pageid'])
                    elif raw.get('missing') or raw.get('invalid'):
                        try:
                            returned.add(int(raw.get('pageid')))
                        except (TypeError, ValueError):
                            pass
                if not data.get('continue'):
                    break
                outstanding = [i for i in outstanding if i not in returned]
        return pages

    def search(self, query_text: str, limit: int = 5) -> List[Tuple[int, str]]:
        """(page_id, title) for a full-text search — a guess, to be verified."""
        if not query_text or not query_text.strip():
            return []
        data = self._get({
            'action': 'query',
            'list': 'search',
            'srsearch': query_text.strip()[:300],
            'srlimit': str(max(1, min(int(limit), 20))),
        })
        results = ((data.get('query') or {}).get('search') or [])
        out = []
        for hit in results:
            try:
                out.append((int(hit['pageid']), str(hit.get('title') or '')))
            except (KeyError, TypeError, ValueError):
                continue
        return out
