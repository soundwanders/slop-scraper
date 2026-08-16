"""
Keep the `source` label honest about where `source_url` actually points.

`source` names a PLACE — that was the whole reason `manual_curation` was
retired, since it named a process while every other value named somewhere a
reader could go and look. A label naming a vendor is therefore a claim about
the citation: "Valve Developer Community" says Valve documented this.

Eight published rows made that claim while linking somewhere else. The worst
read as an endorsement that was never given:

    -nohltv   source='Valve Developer Community'
              source_url=https://steamcommunity.com/sharedfiles/...

That is an individual's Steam guide presented under Valve's name. It is the
same defect as `manual_curation` rendering as a link to PCGamingWiki, and it
is worse than an unsourced row: an unsourced row admits it has nothing, while
this one borrows authority it was never given.

No scraper emits these labels any more — they are legacy rows from an older
static list. The rule lives here anyway, applied on the write path as well as
by the cleanup, because the one lesson this project keeps relearning is that a
rule enforced only by a cleanup script gets undone by the next scrape.

The rule is deliberately one-directional: a mismatched vendor label is
DEMOTED to whatever the URL really is. It never promotes — inventing a vendor
citation from a wiki link is the exact thing this module exists to stop. When
a flag genuinely has vendor documentation, that comes from
flag_dictionary.py's `authority`, which carries a URL that was fetched and
read.
"""

from typing import Optional
from urllib.parse import urlparse

# A source label that names a vendor, and the host its citation must be on for
# the label to be true. Substring match against the URL host, so
# 'docs.unity3d.com' satisfies 'unity3d.com'.
VENDOR_SOURCE_HOSTS = {
    'Epic Games Documentation': 'epicgames.com',
    'Unreal Engine': 'epicgames.com',
    'Unity Documentation': 'unity3d.com',
    'Unity Engine': 'unity3d.com',
    'Valve Developer Community': 'valvesoftware.com',
    'Source Engine': 'valvesoftware.com',
    'id Tech': 'github.com',
}

# What a citation on this host is honestly called. These are the three live
# scrapers' own labels, so a demoted row lands on a value the rest of the
# catalogue already uses rather than a new one the site would have to learn.
HOST_SOURCE_LABELS = (
    ('pcgamingwiki.com', 'PCGamingWiki'),
    ('steamcommunity.com', 'Steam Community'),
    ('protondb.com', 'ProtonDB'),
)


def honest_source(source: Optional[str], source_url: Optional[str]) -> Optional[str]:
    """
    The `source` value this row can actually stand behind.

    Returns `source` unchanged in every case except one: the label names a
    vendor, and `source_url` is a page on somebody else's site. Then the label
    becomes whatever that site is.

    A vendor label with NO url is left alone — it may be a curated entry whose
    provenance lives in verification_method, and silently rewriting it would
    assert something equally unfounded in the other direction. Those rows are
    reported by the cleanup for a human instead.
    """
    label = (source or '').strip()
    required = VENDOR_SOURCE_HOSTS.get(label)
    if not required:
        return source

    host = urlparse((source_url or '').strip()).netloc.lower()
    if not host or required in host:
        return source

    for fragment, honest_label in HOST_SOURCE_LABELS:
        if fragment in host:
            return honest_label
    return source


def misattributed(source: Optional[str], source_url: Optional[str]) -> bool:
    """True when the label claims a vendor the citation does not support."""
    return honest_source(source, source_url) != source


# Labels naming where a SCRAPER found something, as opposed to who documented
# it. Only these are eligible for promotion when the curated dictionary
# supplies a vendor citation.
COMMUNITY_SOURCES = {
    'PCGamingWiki',
    'Steam Community',
    'Steam Community Guides',
    'ProtonDB',
}


def promoted_source(source: Optional[str], authority_label: Optional[str]) -> Optional[str]:
    """
    The label to publish when the dictionary supplies a vendor citation.

    Deliberately narrow. Only a community label is replaced, because only a
    community label *understates* — "ProtonDB" on a row citing Feral's own
    README says less than the row can prove.

    Everything else is left exactly as it is, and the two cases that look like
    they want fixing are the reasons why:

      'Universal'      means the flag works across many games regardless of
                       engine. That is a statement about SCOPE, not about who
                       documented it. Overwriting it with 'Epic Games
                       Documentation' would trade real information for tidiness
                       — both facts are true and they are not the same fact.

      'Unity Engine',  are engine names rather than citation names. Redundant
      'Source Engine', beside 'Unity Documentation', but not false, and
      'Unreal Engine'  collapsing them removes values the site may filter on
                       for no correctness gain.

    So `source` is carrying two ideas at once — who says so, and how broadly it
    applies — and this function refuses to flatten the second into the first.
    """
    if not authority_label:
        return source
    return authority_label if (source or '').strip() in COMMUNITY_SOURCES else source
