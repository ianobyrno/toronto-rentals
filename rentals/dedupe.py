"""Collapse the same unit listed on several sites into one entry."""
from __future__ import annotations

import re

from . import geo
from .models import Listing

_ABBR = {"street": "st", "avenue": "ave", "road": "rd", "boulevard": "blvd", "drive": "dr",
         "crescent": "cres", "place": "pl", "court": "crt", "east": "e", "west": "w", "e.": "e", "w.": "w"}


def norm_address(a: str | None) -> str | None:
    if not a:
        return None
    a = a.lower().split(",")[0]
    a = re.sub(r"^\s*(?:[a-z0-9]+\s+)?-\s+", "", a)   # "1901 - 20 Edward St", "- 20 EDWARD STREET"
    a = re.sub(r"\b(?:unit|apt|suite|#)\s*\w+\b", " ", a)
    a = re.sub(r"[^\w\s]", " ", a)
    words = [_ABBR.get(w, w) for w in a.split()]
    # Needs a street number to be useful
    return " ".join(words) if words and words[0].isdigit() else None


_UNIT = re.compile(r"^\s*([a-z]?\d+[a-z]?)\s+-\s+\d|\b(?:unit|apt|suite|#)\s*([a-z]?\d+[a-z]?)\b", re.I)


def unit_of(l: Listing) -> str | None:
    for s in (l.address, l.title):
        m = _UNIT.search(s or "")
        if m:
            return (m.group(1) or m.group(2)).lower()
    return None


def same_unit(a: Listing, b: Listing) -> bool:
    if a.source == b.source:
        return False
    ua, ub = unit_of(a), unit_of(b)
    if ua and ub and ua != ub:
        return False
    if a.price and b.price and abs(a.price - b.price) > 50:
        return False
    if a.bedrooms and b.bedrooms and a.bedrooms != b.bedrooms:
        return False
    na, nb = norm_address(a.address), norm_address(b.address)
    if na and nb:
        return na == nb
    if None not in (a.lat, a.lon, b.lat, b.lon):
        return geo.haversine_m((a.lat, a.lon), (b.lat, b.lon)) < 30
    return False


def dedupe(listings: list[Listing]) -> list[Listing]:
    out: list[Listing] = []
    for l in listings:
        for kept in out:
            if same_unit(kept, l):
                kept.also_on.append(l.url)
                # keep the richer description
                if len(l.description) > len(kept.description):
                    kept.description = l.description
                break
        else:
            out.append(l)
    return out
