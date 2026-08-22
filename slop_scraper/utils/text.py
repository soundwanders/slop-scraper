"""
Text normalization for stored game metadata.

Steam names arrive with padding that renders as nothing but breaks every
exact-match lookup: trailing spaces, doubled internal spaces, and invisible
characters lifted from store pages and community guides. A title differing
from the store's by an unseeable character fails any join on title, and the
mismatch is invisible in every UI that would let someone spot it.

This rule was previously written only inside
maintenance/cleanups/cleanup_text_sanitation.py, so a cleanup pass fixed the
stored rows and the next scrape reintroduced them. It lives here now, and the
cleanup script imports it, so the two cannot disagree.

Deliberately NOT normalized here: trademark marks in official Steam names, and
non-Latin scripts. Both are part of the real title.
"""

import re

# Characters that occupy no visual space. A human reading the rendered text
# cannot tell they are there, but every string comparison can.
_INVISIBLE = {
    'ㅤ',  # HANGUL FILLER — the Steam-guide table-alignment trick
    '​',  # ZERO WIDTH SPACE
    '‌',  # ZERO WIDTH NON-JOINER
    '‍',  # ZERO WIDTH JOINER
    '⁠',  # WORD JOINER
    '﻿',  # ZERO WIDTH NO-BREAK SPACE / BOM
}
_INVISIBLE_RE = re.compile('[' + ''.join(_INVISIBLE) + ']')


def clean_text(value):
    """Strip invisible characters, collapse whitespace runs, trim the ends."""
    if not value:
        return value
    cleaned = _INVISIBLE_RE.sub('', str(value))
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip()
