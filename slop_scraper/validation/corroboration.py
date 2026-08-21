"""
Corroboration gate for community-sourced launch options.

A community guide is a real source — it has a URL and an author — but it is a
source with no editorial process. Guides carry typos, stale advice and flags
the author never actually ran. The catalogue's rule is that every published
claim answers "what confirmed this is real?", and for a single forum post the
honest answer is "one stranger wrote it down".

The case that produced this module: a Team Fortress 2 guide lists
`-nod3d9ex1` in a copy-paste block. There is no such flag — the author typed
a stray 1 onto `-nod3d9ex`, and the same guide goes on to say the correctly
spelled version "does absolutely nothing" on modern builds. Nothing about the
text marks it as wrong. It is well-formed, it sits among genuine flags, and
every syntactic gate we have passes it. The only thing that distinguishes it
from the real flags around it is that no other source repeats it.

So that is the test. Not "does it look like a flag" — it does — but "did
anyone else say the same thing".

WHAT COUNTS AS CORROBORATION

  1. A curated dictionary entry. That means the flag was checked against
     primary vendor documentation, which outranks any number of guides.
  2. Independent sightings: the same command appearing in two or more distinct
     guides. Two authors making the identical typo is far less likely than one.

WHY THIS IS NOT A BLOCKLIST

Naming `-nod3d9ex1` and deleting it would fix exactly one row and leave the
next typo to be discovered by a human reading a diff. The failure is not that
this particular string is bad, it is that a single unreviewed sighting was
ever enough to publish. Fixing the threshold fixes the whole class, including
the instances nobody has looked at yet.

WHERE IT APPLIES

At the scraper, before options reach the database layer — deliberately, so an
uncorroborated command cannot be inserted AND cannot heal an existing hidden
row into visibility. Provenance stamping treats any re-encounter as
confirmation, so a gate placed later would still have published the typo.

Nothing here re-judges rows already in the catalogue. It governs what the
scrape hands over, not what the view shows.
"""

from typing import Dict, Iterable, List, Set, Tuple

# Two authors, independently, writing the same flag. One is an anecdote.
MIN_INDEPENDENT_SIGHTINGS = 2


def _curated(command: str) -> bool:
    try:
        from .flag_dictionary import lookup_flag
    except ImportError:
        from flag_dictionary import lookup_flag
    return lookup_flag(command) is not None


def is_corroborated(command: str, sighting_count: int,
                    min_sightings: int = MIN_INDEPENDENT_SIGHTINGS) -> Tuple[bool, str]:
    """
    -> (ok, reason). Reason is filled in either direction, for debug output.
    """
    if _curated(command):
        return True, 'curated: verified against primary documentation'
    if sighting_count >= min_sightings:
        return True, f'{sighting_count} independent guides'
    return False, f'single unconfirmed sighting ({sighting_count})'


def filter_corroborated(options: List[dict], sightings: Dict[str, Set[str]],
                        min_sightings: int = MIN_INDEPENDENT_SIGHTINGS,
                        debug: bool = False) -> List[dict]:
    """
    Keep only options that clear the gate.

    `sightings` maps a lowercased command to the set of distinct source URLs it
    was seen at. A set, not a count: the same guide re-parsed, or one guide
    listing a flag three times, is still one sighting.
    """
    kept = []
    for option in options:
        command = (option.get('command') or '').strip()
        seen = sightings.get(command.lower(), set())
        ok, reason = is_corroborated(command, len(seen), min_sightings)
        if ok:
            kept.append(option)
            if debug:
                print(f"🔍 Corroboration: ✅ {command} — {reason}")
        elif debug:
            print(f"🔍 Corroboration: ❌ {command} — {reason}")
    return kept
