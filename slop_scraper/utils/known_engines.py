"""
Curated title -> engine table.

Engine detection previously matched FRANCHISE names against the game title:
'counter-strike' -> Source Engine, 'fallout' -> Creation Engine, 'unity' ->
Unity Engine. Measured against the live catalogue that was wrong for roughly
30% of the titles it fired on, because a franchise changes engine between
entries and unrelated games reuse the words:

    Counter-Strike / Condition Zero   GoldSrc, not Source
    Half-Life, Team Fortress Classic  GoldSrc, not Source
    Dota Underlords                   Unity, not Source
    Morrowind / Oblivion / Fallout 3  Gamebryo, not Creation
    Fallout 1, 2, Tactics             pre-3D custom engine
    Fallout Shelter                   Unity, not Creation
    Need for Speed: Shift / Hot Pursuit   not Frostbite
    Assassin's Creed Unity            AnvilNext — 'unity' is in the TITLE
    Doom Rails                        an unrelated indie game

A substring cannot make that distinction, so the fuzzy patterns are gone and
the specific games are named here instead. Every entry is a game whose engine
is publicly documented and stable. Anything not listed resolves to 'Unknown',
which is the honest answer — this table is meant to grow by verification, not
by pattern-guessing.

Keys are normalized titles (see normalize_title): lowercased, trademark
symbols and edition suffixes removed.
"""

import re

# Edition/rerelease suffixes that do not change the engine. Stripped only as a
# FALLBACK, after the full title has been tried, so a rerelease that genuinely
# switched engines (Oblivion Remastered -> Unreal Engine 5) can be listed
# separately and still win.
_EDITION_SUFFIXES = (
    'game of the year edition', 'game of the year', 'goty edition',
    'definitive edition', 'special edition', 'complete edition',
    'ultimate edition', 'enhanced edition', 'deluxe edition',
    'anniversary edition', 'legendary edition', 'collection',
    'remastered', 'redux',
)

_TRADEMARKS = str.maketrans('', '', '™®©')


def normalize_title(title: str) -> str:
    """Lowercase, strip trademark marks, collapse whitespace and punctuation noise."""
    if not title:
        return ''
    text = str(title).translate(_TRADEMARKS).lower()
    text = re.sub(r'\s+', ' ', text).strip()
    return text.strip(' -–—:')


def _strip_edition(title: str) -> str:
    """Remove a trailing edition suffix, if present."""
    for suffix in _EDITION_SUFFIXES:
        if title.endswith(' ' + suffix):
            return title[: -(len(suffix) + 1)].strip(' -–—:,')
        if title.endswith(': ' + suffix):
            return title[: -(len(suffix) + 2)].strip(' -–—:,')
    return title


KNOWN_TITLE_ENGINES = {
    # --- Valve: GoldSrc ---------------------------------------------------
    # The whole pre-2004 line. These are the games the 'half-life' and
    # 'counter-strike' patterns mislabelled as Source.
    'half-life': 'GoldSrc',
    'half-life: opposing force': 'GoldSrc',
    'half-life: blue shift': 'GoldSrc',
    'team fortress classic': 'GoldSrc',
    'counter-strike': 'GoldSrc',
    'counter-strike: condition zero': 'GoldSrc',
    'counter-strike nexon': 'GoldSrc',
    'counter-strike nexon: studio': 'GoldSrc',
    'day of defeat': 'GoldSrc',
    'deathmatch classic': 'GoldSrc',
    'ricochet': 'GoldSrc',

    # --- Valve: Source ----------------------------------------------------
    'half-life: source': 'Source Engine',
    'half-life deathmatch: source': 'Source Engine',
    'half-life 2': 'Source Engine',
    'half-life 2: deathmatch': 'Source Engine',
    'half-life 2: lost coast': 'Source Engine',
    'half-life 2: episode one': 'Source Engine',
    'half-life 2: episode two': 'Source Engine',
    'counter-strike: source': 'Source Engine',
    'day of defeat: source': 'Source Engine',
    'portal': 'Source Engine',
    'portal 2': 'Source Engine',
    'team fortress 2': 'Source Engine',
    'left 4 dead': 'Source Engine',
    'left 4 dead 2': 'Source Engine',
    "garry's mod": 'Source Engine',
    'black mesa': 'Source Engine',

    # --- Valve: Source 2 --------------------------------------------------
    'dota 2': 'Source 2',
    'counter-strike 2': 'Source 2',
    'half-life: alyx': 'Source 2',

    # Valve-adjacent but NOT Source: Underlords is a Unity title.
    'dota underlords': 'Unity Engine',

    # --- Bethesda: Gamebryo vs Creation -----------------------------------
    # The split is Skyrim. Everything before it is Gamebryo/NetImmerse; the
    # 'elder scrolls'/'fallout' patterns called all of them Creation Engine.
    'the elder scrolls iii: morrowind': 'Gamebryo',
    'the elder scrolls iv: oblivion': 'Gamebryo',
    'fallout 3': 'Gamebryo',
    'fallout: new vegas': 'Gamebryo',

    'the elder scrolls v: skyrim': 'Creation Engine',
    'fallout 4': 'Creation Engine',
    'fallout 76': 'Creation Engine',
    'starfield': 'Creation Engine',

    # Listed explicitly so the edition-suffix fallback cannot reduce it to
    # plain "Oblivion" and inherit Gamebryo — the 2025 rerelease is UE5.
    'the elder scrolls iv: oblivion remastered': 'Unreal Engine',

    # Not Creation Engine despite the franchise name.
    'fallout': 'Unknown',            # 1997, isometric custom engine
    'fallout 2': 'Unknown',
    'fallout tactics: brotherhood of steel': 'Unknown',
    'fallout: a post nuclear role playing game': 'Unknown',
    'fallout 2: a post nuclear role playing game': 'Unknown',
    'fallout shelter': 'Unity Engine',
    # ESO runs a HeroEngine derivative, not Creation.
    'the elder scrolls online': 'Unknown',

    # --- id Software ------------------------------------------------------
    'doom': 'id Tech',
    'doom ii': 'id Tech',
    'doom 3': 'id Tech',
    'doom eternal': 'id Tech',
    'quake': 'id Tech',
    'quake ii': 'id Tech',
    'quake iii arena': 'id Tech',
    'quake 4': 'id Tech',
    'quake live': 'id Tech',
    'wolfenstein 3d': 'id Tech',
    'return to castle wolfenstein': 'id Tech',
    'wolfenstein: youngblood': 'id Tech',
    'rage': 'id Tech',
    'hexen: beyond heretic': 'id Tech',
    'hexen ii': 'id Tech',
    'hexen: deathkings of the dark citadel': 'id Tech',
    'heretic: shadow of the serpent riders': 'id Tech',
    'commander keen': 'id Tech',

    # --- EA: Frostbite, and the ones that are not -------------------------
    'battlefield: bad company 2': 'Frostbite Engine',
    'battlefield: bad company 2 vietnam': 'Frostbite Engine',
    'battlefield 1': 'Frostbite Engine',
    'battlefield v': 'Frostbite Engine',
    'battlefield 2042': 'Frostbite Engine',
    'fifa 22': 'Frostbite Engine',
    'ea sports fifa 23': 'Frostbite Engine',
    'need for speed: heat': 'Frostbite Engine',
    'need for speed heat': 'Frostbite Engine',
    'need for speed: payback': 'Frostbite Engine',
    'need for speed payback': 'Frostbite Engine',
    # Pre-Frostbite Need for Speed entries.
    'need for speed: shift': 'Unknown',
    'need for speed: hot pursuit': 'Unknown',

    # --- Crytek -----------------------------------------------------------
    'far cry': 'CryEngine',
    'crysis': 'CryEngine',
    'crysis warhead': 'CryEngine',
    'crysis 2': 'CryEngine',
    'crysis 3': 'CryEngine',
    'ryse: son of rome': 'CryEngine',
    'hunt: showdown': 'CryEngine',
    'hunt: showdown 1896': 'CryEngine',

    # --- Unreal Engine ----------------------------------------------------
    'unreal': 'Unreal Engine',
    'unreal 2: the awakening': 'Unreal Engine',
    'unreal tournament': 'Unreal Engine',
    'borderlands': 'Unreal Engine',
    'borderlands 2': 'Unreal Engine',
    'borderlands 3': 'Unreal Engine',
    "tiny tina's wonderlands": 'Unreal Engine',
    'batman: arkham asylum': 'Unreal Engine',
    'batman: arkham city': 'Unreal Engine',
    'batman: arkham knight': 'Unreal Engine',
    'mass effect': 'Unreal Engine',
    'mass effect (2007)': 'Unreal Engine',
    'mass effect 2': 'Unreal Engine',
    'mass effect 3': 'Unreal Engine',
    'brothers in arms: road to hill 30': 'Unreal Engine',
    "brothers in arms: earned in blood": 'Unreal Engine',
    "brothers in arms: hell's highway": 'Unreal Engine',
    'aliens: colonial marines': 'Unreal Engine',

    # BioWare pre-Mass Effect: in-house engines, not Unreal. These are the
    # titles the 'bioware' studio pattern got wrong.
    'star wars: knights of the old republic': 'Unknown',
    'jade empire': 'Unknown',
    'dragon age: origins': 'Unknown',
    'mdk 2': 'Unknown',

    # --- Unity ------------------------------------------------------------
    'among us': 'Unity Engine',
    'hollow knight': 'Unity Engine',
    'cuphead': 'Unity Engine',
    'ori and the blind forest': 'Unity Engine',
    'ori and the will of the wisps': 'Unity Engine',
    'cities: skylines': 'Unity Engine',

    # --- GameMaker --------------------------------------------------------
    'undertale': 'GameMaker Studio',
    'hyper light drifter': 'GameMaker Studio',

    # --- Other ------------------------------------------------------------
    'minecraft': 'Java (Minecraft)',
    # Telltale Tool, despite the Minecraft name.
    'minecraft: story mode': 'Unknown',
    'minecraft: story mode - a telltale games series': 'Unknown',
}


def lookup_title_engine(title: str):
    """
    Curated engine for a game title, or None when the title is not listed.

    Returns the string 'Unknown' for titles that ARE listed but whose engine we
    deliberately decline to state (a franchise entry that does not share its
    siblings' engine). That is a real answer — it stops a later fuzzy method
    from filling in the wrong one — and is distinct from None, which means the
    table simply has nothing to say.
    """
    normalized = normalize_title(title)
    if not normalized:
        return None

    if normalized in KNOWN_TITLE_ENGINES:
        return KNOWN_TITLE_ENGINES[normalized]

    stripped = _strip_edition(normalized)
    if stripped != normalized and stripped in KNOWN_TITLE_ENGINES:
        return KNOWN_TITLE_ENGINES[stripped]

    return None
