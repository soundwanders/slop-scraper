"""
Release date normalization for Steam store data.

Steam returns human-formatted date strings that vary by region and era:
"8 Feb, 2018", "Mar 14, 2006", "February 8, 2018", sometimes just
"Feb 2018" or "2018" for older/unreleased titles. The database should
hold ISO dates (YYYY-MM-DD) so the web app can sort on them.
"""

import re
from datetime import datetime

_ISO_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# Full-date formats seen in Steam store data
_FULL_FORMATS = ('%b %d, %Y', '%d %b, %Y', '%B %d, %Y', '%d %B, %Y')
# Partial dates (month/year or year only) — mapped to the first of the period
_PARTIAL_FORMATS = ('%b %Y', '%B %Y', '%Y')


def normalize_release_date(date_str):
    """
    Convert a Steam release date string to ISO format (YYYY-MM-DD).

    Already-ISO strings pass through untouched. Partial dates ("Feb 2018",
    "2018") map to the first day of the period so they remain sortable.
    Unparseable strings ("Coming soon", "TBA") are returned as-is rather
    than lost — the UI can decide how to render them.
    """
    if not date_str:
        return date_str

    cleaned = str(date_str).strip()
    if not cleaned or _ISO_DATE.match(cleaned):
        return cleaned

    for fmt in _FULL_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue

    for fmt in _PARTIAL_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue

    return cleaned  # unparseable → store as-is rather than lose it
