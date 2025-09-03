"""Utility mapping for normalizing vehicle manufacturer names.

This module defines ``MAKE_ALIASES`` which maps common nicknames or
misspellings of vehicle makes to the canonical names used in the
application database.  Use this mapping when processing user queries or
importing data so that lookups are performed against consistent values.

Add new aliases here as additional edge cases appear in real data.
"""

from __future__ import annotations

# Maps lowercase alias -> canonical vehicle make
MAKE_ALIASES: dict[str, str] = {
    # Mercedes-Benz
    "benz": "Mercedes-Benz",
    "mercedes": "Mercedes-Benz",
    "mercedes benz": "Mercedes-Benz",
    "mercedez": "Mercedes-Benz",  # common misspelling
    "merc": "Mercedes-Benz",
    "mb": "Mercedes-Benz",

    # Volkswagen
    "vw": "Volkswagen",
    "volks": "Volkswagen",
    "volkswagon": "Volkswagen",  # common misspelling
    "volkswagen": "Volkswagen",

    # Chevrolet
    "chevy": "Chevrolet",
    "chev": "Chevrolet",
    "chevro": "Chevrolet",
    "chevrolet": "Chevrolet",

    # ALFA
    "alfa": "ALFA",
    "alfa romeo": "ALFA",

    # BMW
    "bmw": "BMW",
    "beemer": "BMW",
    "bimmer": "BMW",
}


def canonical_make(make: str | None) -> str | None:
    """Return the canonical vehicle make using ``MAKE_ALIASES``.

    ``make`` is matched case-insensitively; if it is not found in the
    mapping, the original value is returned unchanged.
    """
    if make is None:
        return None
    normalized = make.strip().lower()
    return MAKE_ALIASES.get(normalized, make)
