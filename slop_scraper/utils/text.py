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
import unicodedata

# Characters that occupy no visual space. A human reading the rendered text
# cannot tell they are there, but every string comparison can.
#
# This was an enumerated list of six characters, which was the wrong shape:
# it caught the zero-width space and the HANGUL filler we had actually seen,
# and missed every other member of the class — SOFT HYPHEN, the direction
# marks, the invisible math operators. The read side found the gap while
# checking whether a padded title could move a canonical URL, and it can: an
# invisible character wedged inside a word separates it, so a title that looks
# identical slugs differently.
#
# The rule is now the Unicode category, so the class is closed rather than
# its known members patched.
#
# Two deliberate exceptions:
#
#   ZWNJ / ZWJ are Cf but carry meaning — they control ligature joining in
#   Persian, Arabic and Indic scripts, where removing one changes the word.
#   The previous enumerated list stripped both, which would have quietly
#   corrupted any such title. Nothing in the catalogue has one today; this
#   keeps it that way when one arrives.
#
#   HANGUL FILLER is category Lo, not Cf — a letter as far as Unicode is
#   concerned — so the category rule cannot see it and it stays explicit.
_KEEP = {'‌', '‍'}          # ZWNJ, ZWJ — meaningful, not padding
_EXPLICIT = {'ㅤ'}                # HANGUL FILLER — category Lo, so Cf misses it


def _is_invisible(ch):
    if ch in _KEEP:
        return False
    return ch in _EXPLICIT or unicodedata.category(ch) == 'Cf'


def clean_text(value):
    """Strip invisible characters, collapse whitespace runs, trim the ends."""
    if not value:
        return value
    cleaned = ''.join(ch for ch in str(value) if not _is_invisible(ch))
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip()
