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

# Where one flag's description runs into the next flag's entry.
#
# Community guides list flags one per line as "-flag - what it does", and when
# that survives as a single blob of text the scraper takes the whole run. A
# real case: -forcenovsync came back described as "Disables VSyns, vertical
# sync (If you need it) -high - Makes TF2 a higher priority on the computer,
# using more memory, very unstable" — the first clause belongs to it, the rest
# belongs to -high.
#
# The signal is a flag token followed by a definition separator, which is what
# starts the NEXT entry. A description that merely mentions a flag in passing
# ("use alongside -novid for a faster start") has no separator after it and is
# left alone. The existing >=2-other-flags rule does not catch this, because a
# run-on into a single neighbour names only one.
_RUN_ON_DEFINITION = re.compile(
    r'(?:^|\s)(?<![\w\-])[+\-][a-zA-Z][a-zA-Z0-9_\-]{2,}\s+[-–—:]\s+'
)


def truncate_at_next_definition(description: Optional[str]) -> Optional[str]:
    """
    Cut a description where the next flag's entry begins.

    Returns the leading clause, or None if nothing precedes the cut (the text
    was entirely someone else's entry). Text with no run-on is returned as-is.
    """
    raw = (description or '').strip()
    if not raw:
        return None

    match = _RUN_ON_DEFINITION.search(raw)
    if not match:
        return raw

    head = raw[:match.start()].strip(' \t-–—:,;')
    return head or None

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
#
# The second alternative covers the same split without the bracket: a Garry's
# Mod guide documents "-particles 512 Lowers the amount of particles", and
# severing the value left -particles described as "512 Lowers the amount of
# particles to 512 (minimum)". A leading bare number followed by a word is the
# value that belongs on the command, not the start of a definition.
# "1080p" and "16:9" are unaffected — both need whitespace after the digits.
_LEADS_WITH_VALUE = re.compile(r'^\d+(?:\s*[\(\[]|\s+(?=[A-Za-z]))')

# The text says the option does not do anything. Whatever that is, it is not a
# description of what the flag does, and an option documented as broken has no
# business being published as advice.
_SELF_NEGATING = re.compile(
    r'\b(?:does\s*n[o\']t\s*work|doesn.?t\s*work|does\s*nothing|'
    r'no\s*longer\s*works|not\s*working|broken|has\s*no\s*effect)\b',
    re.IGNORECASE
)


# A Fixbox's description= names the METHOD of a fix, and on PCGamingWiki the
# commonest method is "use a command-line argument". Stored against a flag it
# says nothing: every row in a launch-options catalogue is an argument. Five
# were published this way — "Use an argument", "Add parameters", "Use
# command-line parameter", "Set launch options", "Use command line parameter
# set" — each where the page's section heading said what the flag was for.
_GENERIC_METHOD = re.compile(
    r'^(?:use|add|set|try|apply|enter|type|edit)\s+(?:an?\s+|the\s+)?'
    r'(?:following\s+)?(?:steam\s+|custom\s+)?'
    r'(?:command[\s-]*line\s+|launch\s+|startup\s+)?'
    r'(?:argument|parameter|option|flag)s?(?:\s+set)?\.?$',
    re.IGNORECASE
)


def is_generic_method(text: Optional[str]) -> bool:
    """True when the text names only the method "use a launch argument"."""
    return bool(_GENERIC_METHOD.match((text or '').strip()))


# The hole the retired `desc.replace(command, '')` bug left in a sentence. The
# parser stopped doing this, but rows written before the fix never get
# re-judged, and this gate is the only thing the cleanup can judge them by:
#
#   "Use # -yres # for custom window resolution."   (-xres cut out)
#   "Add or -dx11 to the launch options"            (-d3d11 cut out)
#   "Use the =x command line argument"              (-hz cut out)
#   "Use the to launch modded version ..."          (-mod:X cut out)
_DELETED_COMMAND_TRACE = re.compile(
    r'^(?:use|add|type|enter|put|append)\s+(?:the\s+)?(?:or|and|to|for|with|[#=])(?=\s|$)'
    r'|\bthe\s+(?:to|for|with|or|and)\b'
    r'|\bthe\s+='
    r'|\s#\s+-'
    r'|#\s+#',        # "Use -xres # # for ..." — -yres cut from between its two placeholders
    re.IGNORECASE
)

# A step lifted out of a numbered procedure with the number written out —
# "4. Use the command line argument ...", "Method №1. Launch parameters
# through Steam". The wiki's own '#' list marker is handled separately below.
# "3.5 GB" is unaffected: the number must be followed by a dot AND a space.
_NUMBERED_STEP = re.compile(
    r'^(?:\d{1,2}\.\s|(?:method|step)\s*(?:№|no\.?|#)?\s*\d)', re.IGNORECASE)

# A table of values rather than a definition: "1 = TRUE 0 = FALSE ...".
_VALUE_LEGEND = re.compile(r'^\d+\s*=\s*\S')

# Where to type the flag rather than what it does: "Editing launch options",
# "Type in in the launch options", "set the 'Target' field of the shortcut",
# "pass it through a shortcut". Every stored description matching this was an
# instruction step, and none of the curated entries match it.
_WHERE_TO_ENTER = re.compile(
    r"\blaunch\s+options?\b|\bsteam\s+properties\b|\bproperties\s+window\b"
    r"|\btarget'?\s*field\b|\b(?:the|a)\s+shortcut\b",
    re.IGNORECASE
)

# A raw external link, "[https://...", survives only when wikitext was cut
# mid-link: "Download and install [https://www.nexusmods.com/... this mo".
_RAW_LINK = re.compile(r'\[https?://')

# The platforms an option works on, taken from a table's platform column:
# -nosteam documented as "Windows, OS X, Linux".
_PLATFORM = r'(?:windows|os\s*x|mac\s*os|macos|mac|linux|steamos|steam\s*deck)'
_PLATFORM_LIST = re.compile(
    r'^' + _PLATFORM + r'(?:\s*(?:,|/|&|and)\s*(?:and\s+)?' + _PLATFORM + r')*\.?$',
    re.IGNORECASE
)

# Text before a mention that makes it an illustration rather than an
# instruction — "(e.g. DXVK_HUD=fps)".
_EXAMPLE_LEAD = re.compile(r'(?:\(|e\.g\.?,?|i\.e\.?,?|for example,?)\s*$', re.IGNORECASE)


def _names_itself_mid_sentence(command: str, description: str) -> bool:
    """
    The description uses the command inside the sentence: "Use -availablevidmem
    XXXX.0", "Run the game with the -forcehighpoly". That instructs the reader
    to use the flag instead of saying what it does, and the command column
    already carries the flag. The PCGamingWiki extractor refuses these as it
    scrapes; this is the same judgement, somewhere the cleanup can apply it.

    A bracketed example is the exception. "Show the DXVK performance HUD
    overlay (e.g. DXVK_HUD=fps)" is a definition illustrating itself.
    """
    if not command:
        return False
    pattern = r'(?<![\w\-+])' + re.escape(command) + r'(?![\w\-])'
    for m in re.finditer(pattern, description):
        if m.start() == 0:
            continue
        if _EXAMPLE_LEAD.search(description[:m.start()]):
            continue
        return True
    return False


def _alnum(text: str) -> str:
    return re.sub(r'[\W_]+', '', text.lower())


def _is_circular(command: str, description: str) -> bool:
    """
    "Use the -nomovie" restates the command and adds nothing. Only circular if
    removing the boilerplate and the command leaves essentially nothing, so
    genuinely informative text starting with "Use" survives.
    """
    # A heading that is only the flag's own name — "Windowed" above +windowed —
    # restates it as surely as "Use the +windowed" does, just without the
    # punctuation and in a different case.
    if _alnum(description) and _alnum(description) == _alnum(command):
        return True

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

    if is_generic_method(raw):
        return True, 'names the method (a launch argument), not what the flag does'

    if _DELETED_COMMAND_TRACE.search(raw):
        return True, 'the command was cut out of the sentence'

    if _NUMBERED_STEP.match(raw):
        return True, 'numbered instruction step, not a description'

    if _VALUE_LEGEND.match(raw):
        return True, 'value legend, not a definition'

    if _names_itself_mid_sentence(command, raw):
        return True, 'instruction to use the flag, not a definition'

    if _WHERE_TO_ENTER.search(raw):
        return True, 'says where to enter the flag, not what it does'

    if _RAW_LINK.search(raw):
        return True, 'cut off inside a wiki link'

    if _PLATFORM_LIST.match(raw):
        return True, 'a platform list, not a description'

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

    # Trim a run-on into the next flag's entry BEFORE judging the text, so the
    # remaining clause is assessed on its own merits rather than on wording
    # that was never about this command.
    raw = truncate_at_next_definition(raw)
    if not raw or is_placeholder_description(raw):
        return None

    junk, _ = is_junk_description(command, raw)
    if junk:
        return None

    # A real definition that lost its leading command reads lowercase.
    if raw[:1].islower() and _DESCRIPTIVE_VERB.match(raw):
        raw = raw[0].upper() + raw[1:]

    return raw
