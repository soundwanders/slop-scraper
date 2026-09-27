"""
Links the write path refuses to create, whatever source proposes them.

A cleanup that removes a link is undone by the next scrape that finds the same
flag again, unless the write path refuses it too. These rules used to live only
in the cleanup and backfill scripts, so a rescan could re-attach what they had
removed — a Source flag found in a guide attached to a Unity game, which is how
-nojoy reached Oxygen Not Included.

Two rules, both narrow:

  ENGINE FAMILY  an option stamped by an engine block ('Unity Engine', 'Source
                 Engine', ...) is never linked to a game whose known engine is
                 a different family. A game with no known engine is not judged.
  REFUSED PAIRS  a (command, app_id) pair checked by hand and found wrong,
                 where the family rule cannot reach because the option's source
                 names a vendor rather than an engine block.
"""

from typing import Optional

# launch_options.source values that game_specific.py stamps on its engine
# blocks, mapped to the family keys scrapers.game_specific._option_family
# returns for a game's engine.
SOURCE_FAMILY = {
    'Source Engine': 'source',
    'Unity Engine': 'unity',
    'Unreal Engine': 'unreal',
    'id Tech': 'idtech',
    'Creation Engine': 'creation',
    'Frostbite Engine': 'frostbite',
    'Minecraft Java': 'minecraft',
}

# Keyed on the lowercased command and the game's app_id, never a pattern. Each
# was probed before being listed: no current scraper produces it for that game.
REFUSED_LINKS = {
    # -sm4 is scoped by its curated entry to Unreal Engine 4 before 4.23. Rainbow
    # Six Siege runs AnvilNext, its App-ID-verified wiki page never mentions
    # -sm4, and PCGamingWiki, Steam Community and ProtonDB all returned nothing
    # of the kind for it (2026-09-13). ARK: Survival Evolved's link is NOT here:
    # its page documents -sm4 twice.
    ('-sm4', 359550): 'AnvilNext game; its wiki page never mentions -sm4',
}


def link_refusal(command: str, option_source: Optional[str],
                 game_family: Optional[str], app_id) -> Optional[str]:
    """Why this link must not be created, or None when it may be."""
    try:
        key = (str(command or '').strip().lower(), int(app_id))
    except (TypeError, ValueError):
        key = None
    if key in REFUSED_LINKS:
        return f'hand-verified wrong for this game: {REFUSED_LINKS[key]}'
    option_family = SOURCE_FAMILY.get(option_source or '')
    if option_family and game_family and option_family != game_family:
        return f'engine family: option is {option_family}, game is {game_family}'
    return None
