"""
Quality gate for launch-option descriptions.

Scraped descriptions are frequently not descriptions at all: they are wiki
instruction steps, pasted blocks of unrelated flags, or restatements of the
command itself. A wrong or content-free description is worse than none —
the site renders the source link when a description is missing, which is
honest about what we actually know.

This module is the single source of truth for that judgement. It is used at
two points, and both matter:

  - database/supabase.py, so junk is never written in the first place
  - the one-off cleanup script, so existing rows can be audited with exactly
    the same rules

Keeping one implementation is the point. When these rules lived only in the
cleanup script, a later re-scrape silently reinstated every description the
cleanup had removed.
"""

import re
from typing import Optional, Tuple

# Placeholders a scraper emits when it found a command but no explanation of
# it. Honest, but carrying no more information than an empty column — so they
# must never be written over a NULL description.
PLACEHOLDER_DESCRIPTIONS = {
    'launch option from pcgamingwiki',
    'launch option from steam community guide',
    'launch option reported by protondb users',
    'proton/wine compatibility option',
}

# A description naming other command-line flags is an instruction ("Add -foo
# -bar to the launch options"), not a definition of the flag it belongs to.
_FLAG_TOKEN = re.compile(r'(?<![\w\-])[+\-][a-zA-Z][a-zA-Z0-9_\-]{2,}')

# Third-person present verbs: the sentence states what the flag DOES rather
# than instructing the reader. The trailing -s is the whole signal — "forces
# higher quality audio" is a definition, "Force ..." / "Add ..." is an
# instruction, and in this data usually a mangled one.
_DESCRIPTIVE_VERB = re.compile(
    r'^(?:forces|disables|enables|sets|changes|removes|skips|opens|plays|'
    r'runs|starts|overrides|allows|prevents|reduces|increases|limits|caps|'
    r'toggles|specifies|selects|shows|hides|makes|bypasses|launches|loads|'
    r'uses|adds|turns)\b',
    re.IGNORECASE
)

# Non-answers that look like content but assert nothing.
_NON_ANSWERS = {
    'not tested yet', 'unknown', 'n/a', 'na', 'tbd', 'none', 'todo', 'test', '?',
    'use the following set',
}


def is_placeholder_description(text: Optional[str]) -> bool:
    """True for a scraper's own generic filler (never overwrite NULL with it)."""
    return (text or '').strip().rstrip('.').lower() in PLACEHOLDER_DESCRIPTIONS


# Boilerplate wrapped around a bare restatement of the command. "Use the -X"
# was the only form handled; the guide scrapers also produce "Run the game with
# the -X" and "Launch game with -X", which carry exactly as little.
_CIRCULAR_PREFIX = re.compile(
    r'^(?:use|using|try|add|put|set|type|enter|write|include|append)\s+'
    r'(?:the\s+)?(?:following\s+)?'
    r'|^(?:run|launch|start|open|boot)\s+(?:the\s+)?(?:game|it|this)?\s*'
    r'(?:with|using|via)?\s*(?:the\s+)?',
    re.IGNORECASE
)

# A stray trailing integer is the NEXT item's number in a numbered list, caught
# by a context window that ran past the end of the entry:
#
#     "-tickrate"        -> "128 (Max tickrate) 3"
#     "+cl_updaterate"   -> "128 (Highest update rate possible) 11"
#
# Anchored to a closing bracket or sentence end so a description that
# legitimately ends in a number ("Set the window height in pixels, e.g. 1080")
# is untouched.
_TRAILING_LIST_INDEX = re.compile(r'[)\].]\s+\d{1,3}\s*$')

# The description opens with the VALUE rather than a definition — the parser
# split "-tickrate 128 (Max tickrate)" at the wrong place and kept the tail.
_LEADS_WITH_VALUE = re.compile(r'^\d+\s*[\(\[]')

# The text says the option does not do anything. Whatever that is, it is not a
# description of what the flag does, and an option documented as broken has no
# business being published as advice.
_SELF_NEGATING = re.compile(
    r'\b(?:does\s*n[o\']t\s*work|doesn.?t\s*work|does\s*nothing|'
    r'no\s*longer\s*works|not\s*working|broken|has\s*no\s*effect)\b',
    re.IGNORECASE
)


def _is_circular(command: str, description: str) -> bool:
    """
    "Use the -nomovie" restates the command and adds nothing. Only circular if
    removing the boilerplate and the command leaves essentially nothing, so
    genuinely informative text starting with "Use" survives.
    """
    residue = _CIRCULAR_PREFIX.sub('', description.strip(), count=1)
    residue = residue.replace(command, '')
    residue = re.sub(r'[\s\.\-–—:,"\']+', '', residue)
    return len(residue) <= 3


def is_junk_description(command: str, description: Optional[str]) -> Tuple[bool, str]:
    """
    -> (is_junk, reason). Empty and placeholder descriptions are NOT junk —
    they are simply absent, and the caller decides what to do about that.
    """
    raw = (description or '').strip()
    if not raw or is_placeholder_description(raw):
        return False, ''

    if raw.lower().rstrip('.') in _NON_ANSWERS:
        return True, 'non-answer'

    if _is_circular(command, raw):
        return True, 'circular — restates the command'

    # Wiki list markers introduce instruction steps, except when the marker
    # precedes a real definition whose command was stripped off the front.
    if raw[:1] in '#*':
        body = re.sub(r'^[\s#*:;\-]+', '', raw)
        if not (_DESCRIPTIVE_VERB.match(body) and not _FLAG_TOKEN.search(body)):
            return True, 'instruction step, not a description'

    if len(set(_FLAG_TOKEN.findall(raw)) - {command}) >= 2:
        return True, 'instruction text listing other flags'

    if raw[:1] in ')]}>':
        return True, 'leading markup fragment'

    if _SELF_NEGATING.search(raw):
        return True, 'says the option does not work'

    if _TRAILING_LIST_INDEX.search(raw):
        return True, "trailing list index — the next entry's number"

    if _LEADS_WITH_VALUE.match(raw):
        return True, 'starts with the value, not a definition'

    # Starts mid-sentence/lowercase: the context window sliced into it. A real
    # definition whose command was stripped reads as a third-person verb.
    if raw[:1].islower() and not _DESCRIPTIVE_VERB.match(raw):
        return True, 'sentence fragment'

    if re.search(r'\b(?:notes|fix|ref|description|comment)\s*=', raw):
        return True, 'template parameter residue'

    return False, ''


def acceptable_description(command: str, description: Optional[str]) -> Optional[str]:
    """
    The description to store for this command, or None to store nothing.

    None means "we do not have a usable description" — which the site renders
    as the source link. That is deliberately preferred over text that looks
    like an answer without being one.
    """
    raw = (description or '').strip()
    if not raw or is_placeholder_description(raw):
        return None

    junk, _ = is_junk_description(command, raw)
    if junk:
        return None

    # A real definition that lost its leading command reads lowercase.
    if raw[:1].islower() and _DESCRIPTIVE_VERB.match(raw):
        raw = raw[0].upper() + raw[1:]

    return raw
