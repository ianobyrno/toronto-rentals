"""Condos.ca — MLS condo leases in Toronto under budget, newest first.

The page embeds its search results as window.__INITIAL_STATE__ (JS object literal, mostly JSON),
with structured move-in date, furnished status and outdoor space. No description is included,
which is fine for MLS condo leases: the structured fields carry what we filter on.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone

from .. import http
from ..models import Listing

NAME = "condos.ca"
MAX_PRICE = 2300
LOOKBACK_DAYS = 2
MAX_PAGES = 4
_STATE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*(.*?)</script>", re.S)


def _url(page: int) -> str:
    return f"https://condos.ca/toronto/condos-for-rent?rent_price_range=0,{MAX_PRICE}" + (f"&page={page}" if page > 1 else "")


def _state(html: str) -> dict:
    m = _STATE.search(html)
    if not m:
        raise RuntimeError("no __INITIAL_STATE__ on page — Condos.ca layout changed")
    raw = re.sub(r"(?<=[:\[,])undefined(?=[,\]}])", "null", m.group(1).strip())
    raw = re.sub(r"function\s*\([^)]*\)\s*\{\s*\}", "null", raw)
    return json.JSONDecoder().raw_decode(raw)[0]


def to_listing(r: dict) -> Listing | None:
    if not r.get("asking_price") or r.get("offer") not in (None, "Rent"):
        return None
    beds = r.get("bedrooms")
    if beds is None:
        bedrooms = None
    elif int(beds) == 0:
        bedrooms = "studio"
    else:
        bedrooms = f"{int(beds)}+den" if r.get("bedrooms_plus") else str(int(beds))
    avail = None
    if r.get("date_available"):
        try:
            avail = date.fromisoformat(r["date_available"][:10])
        except ValueError:
            pass
    desc_bits = [r.get("sub_type") or r.get("home_type") or ""]
    if r.get("outdoor_space"):
        desc_bits.append(f"Outdoor space: {r['outdoor_space']}")
    elif r.get("has_balcony"):
        desc_bits.append("Balcony")
    if r.get("tags"):
        desc_bits.append(", ".join(r["tags"]))
    if r.get("pets_permitted"):
        desc_bits.append(f"Pets: {r['pets_permitted']}")
    photo = None
    if r.get("images") and r.get("photo_base_url"):
        photo = r["photo_base_url"] + r["images"][0]

    def f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    return Listing(
        source=NAME, source_id=str(r.get("mls_number") or r["id"]),
        url="https://condos.ca/" + (r.get("url") or "").lstrip("/"),
        title=r.get("title") or "", description=". ".join(b for b in desc_bits if b),
        price=int(r["asking_price"]), bedrooms=bedrooms, bathrooms=f(r.get("bathrooms")),
        unit_type=r.get("sub_type"), address=r.get("title"),
        lat=f(r.get("latitude")), lon=f(r.get("longitude")), available=avail,
        furnished={"Yes": True, "Part": True, "No": False}.get(r.get("furnished") or ""),
        sqft=int(r["sqft"]) if r.get("sqft") else None, photo=photo, posted=r.get("entry_date"),
    )


def fetch() -> list[Listing]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
    out: dict[str, Listing] = {}
    for page in range(1, MAX_PAGES + 1):
        st = _state(http.get(_url(page)).text)
        rows = (st.get("listings") or {}).get("searchAlogliaList") or []
        if not rows:
            break
        for r in rows:
            l = to_listing(r)
            if l:
                out[l.source_id] = l
        dates = sorted(r.get("entry_date") or "" for r in rows)
        # Mostly newest-first; stop when the median listing on the page is past the window.
        if dates[len(dates) // 2] < cutoff:
            break
    return list(out.values())
