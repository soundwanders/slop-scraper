"""
Curated launch-option documentation.

Scraped sources rarely explain a flag well enough to act on. This table is the
authoritative override: where an entry exists it wins over whatever a scraper
produced, because a hand-verified description from primary documentation beats
a sentence lifted out of a forum post.

Every entry carries the source it was verified against. That field is for
maintainers, not the website — it exists so a future reader can re-check a
claim instead of trusting it. Entries whose behaviour could not be confirmed
against primary documentation are deliberately absent rather than guessed:
a flag nobody can explain accurately is worse than no flag at all.

`scope` is set when a flag only works on particular engines. It is folded into
the description shown to users, so nobody pastes an Unreal flag into a Source
game and wonders why nothing happened.
"""

from typing import Optional

# command -> curated documentation
FLAG_DICTIONARY = {
    # ---- id Tech ----------------------------------------------------------
    '+set r_customwidth': {
        'description': 'Set a custom horizontal resolution',
        'effect': 'Overrides the width used when r_mode is -1. Without r_mode -1 the '
                  'engine uses a preset mode and this value is ignored.',
        'usage_example': '+set r_mode -1 +set r_customwidth 1920 +set r_customheight 1080',
        'authority': 'id Tech 4 console variable reference (Doom 3 / Quake 4 lineage)',
    },
    '+set r_customheight': {
        'description': 'Set a custom vertical resolution',
        'effect': 'Overrides the height used when r_mode is -1. Without r_mode -1 the '
                  'engine uses a preset mode and this value is ignored.',
        'usage_example': '+set r_mode -1 +set r_customwidth 1920 +set r_customheight 1080',
        'authority': 'id Tech 4 console variable reference (Doom 3 / Quake 4 lineage)',
    },

    # ---- Source engine ----------------------------------------------------
    '-console': {
        'description': 'Enable the developer console',
        'effect': 'Makes the in-game developer console available, opened with the ~ key.',
        'usage_example': '-console',
        'authority': 'Valve Developer Community — Command line options',
    },
    '-w': {
        'description': 'Set the window width in pixels',
        'effect': 'Forces the game to start at the given horizontal resolution instead '
                  'of the saved or auto-detected one. Pass -h as well to set height '
                  'explicitly; on its own, height is derived from the aspect ratio.',
        'usage_example': '-w 1920 -h 1080',
        'authority': 'Valve Developer Community — Command line options',
    },
    '-h': {
        'description': 'Set the window height in pixels',
        'effect': 'Forces the game to start at the given vertical resolution instead of '
                  'the saved or auto-detected one.',
        'usage_example': '-w 1920 -h 1080',
        'authority': 'Valve Developer Community — Command line options',
    },
    '-window': {
        'description': 'Run the game in a window instead of fullscreen',
        'effect': 'Starts windowed rather than exclusive fullscreen. -window, -windowed '
                  'and -sw are synonyms in Source.',
        'usage_example': '-window',
        'authority': 'Valve Developer Community — Command line options',
    },
    '-language': {
        'description': "Set the game's language",
        'effect': 'Loads localisation files for the named language instead of following '
                  'the Steam client language.',
        'usage_example': '-language english',
        'authority': 'Valve Developer Community — Command line options',
    },
    '-refresh': {
        'description': 'Set the monitor refresh rate in Hz',
        'effect': 'Requests the given refresh rate on the display the game opens on.',
        'usage_example': '-refresh 144',
        'authority': 'Valve Developer Community — Command line options',
    },

    # ---- Engine-specific: scope is part of the answer ---------------------
    '-vulkan': {
        'description': 'Use the Vulkan renderer where the game supports it',
        'effect': 'Forces the Vulkan rendering backend instead of DirectX or OpenGL. '
                  'Only has an effect in engines with a Vulkan path; ignored elsewhere.',
        'usage_example': '-vulkan',
        'authority': 'Valve — Source 2 Vulkan support (Dota 2, CS2, Half-Life: Alyx)',
        'scope': 'Source 2 and id Tech 6/7 only',
    },
    '-nostartupmovies': {
        'description': 'Skip the startup movies',
        'effect': 'Prevents intro and logo movies from playing at launch.',
        'usage_example': '-nostartupmovies',
        'authority': 'Unreal Engine command-line arguments (UE3/UE4)',
        'scope': 'Unreal Engine games',
    },
    '-nomovies': {
        'description': 'Skip intro movies',
        'effect': 'Prevents pre-game cinematic and logo movies from playing. Source '
                  'games use -novid instead.',
        'usage_example': '-nomovies',
        'authority': 'PCGamingWiki per-game pages (Relic Essence-engine titles)',
        'scope': 'game-specific, not an engine-wide standard',
    },
    '-nolauncher': {
        'description': "Skip the game's external launcher",
        'effect': 'Starts the game directly instead of opening its separate launcher or '
                  'configuration window first. The exact spelling varies per title.',
        'usage_example': '-nolauncher',
        'authority': 'PCGamingWiki per-game pages',
        'scope': 'only games that ship a launcher',
    },
    '-height': {
        'description': 'Set the window height in pixels',
        'effect': 'Forces the given vertical resolution. This is a per-game convention '
                  'rather than an engine standard — Source uses -h, Unity uses '
                  '-screen-height.',
        'usage_example': '-height 1080',
        'authority': 'per-game conventions; not a Source or Unity standard',
        'scope': 'game-specific spelling',
    },
}


def _dictionary_key(command: str) -> Optional[str]:
    """
    Match a stored command to a dictionary entry.

    Commands are stored with their values ("-w 1920", "+set r_customwidth"), so
    an exact match is tried first and then the flag without its trailing value.
    """
    if not command:
        return None
    command = command.strip()
    if command in FLAG_DICTIONARY:
        return command

    # "-w 1920" -> "-w";  "+set r_customwidth 1920" -> "+set r_customwidth"
    parts = command.split(' ')
    for take in range(len(parts) - 1, 0, -1):
        candidate = ' '.join(parts[:take])
        if candidate in FLAG_DICTIONARY:
            return candidate
    return None


def lookup_flag(command: str) -> Optional[dict]:
    """Curated entry for a command, or None. Never raises."""
    key = _dictionary_key(command)
    return FLAG_DICTIONARY.get(key) if key else None


def curated_description(command: str) -> Optional[str]:
    """
    The description to publish, with scope folded in where one applies.

    A scoped flag reads "Skip the startup movies (Unreal Engine games)" so the
    limitation travels with the text instead of living only in our notes.
    """
    entry = lookup_flag(command)
    if not entry:
        return None
    description = entry['description']
    scope = entry.get('scope')
    return f"{description} ({scope})" if scope else description
