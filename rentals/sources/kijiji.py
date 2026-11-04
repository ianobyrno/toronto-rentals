"""Kijiji — long-term rentals within ~5.5 km of the middle of the search area, newest first.

Search pages embed structured data (Next.js __NEXT_DATA__ → Apollo state) with coordinates,
price and attributes. Descriptions there are truncated, so `enrich` fetches the full listing
page for candidates that already pass the cheap filters.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

from .. import http
from ..models import Listing

NAME = "kijiji"
CENTRE = (43.658, -79.377)     # middle of the Dufferin–Coxwell / lake–Dupont box
RADIUS_KM = 5.5                # reaches every corner of the area
MAX_PRICE = 2300
LOOKBACK = timedelta(hours=8)  # runs are 3 h apart; generous margin for late GitHub runs
MAX_PAGES = 6

_BEDS = {"0": "studio", "1": "1", "1.5": "1+den", "2": "2", "2.5": "2+den", "3": "3", "3.5": "3+den"}
_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _url(page: int) -> str:
    path = "/b-apartments-condos/city-of-toronto/" + (f"page-{page}/" if page > 1 else "") + "c37l1700273"
    q = {"sort": "dateDesc", "price": f"__{MAX_PRICE}", "ll": f"{CENTRE[0]},{CENTRE[1]}",
         "radius": f"{RADIUS_KM}", "address": "Toronto, ON"}
    return f"https://www.kijiji.ca{path}?{urlencode(q)}"


def _apollo(html: str) -> dict:
    m = _NEXT.search(html)
    if not m:
        raise RuntimeError("no __NEXT_DATA__ on page — Kijiji layout changed")
    return json.loads(m.group(1))["props"]["pageProps"]["__APOLLO_STATE__"]


def _attrs(raw: dict) -> dict[str, str]:
    out = {}
    for a in (raw.get("attributes") or {}).get("all") or []:
        v = a.get("canonicalValues") or []
        if v and v[0] != "Not Available":
            out[a["canonicalName"]] = v[0]
    return out


def to_listing(raw: dict) -> Listing | None:
    price = raw.get("price") or {}
    if price.get("type") != "FIXED" or not price.get("amount"):
        return None
    a = _attrs(raw)
    loc = raw.get("location") or {}
    coords = loc.get("coordinates") or {}
    extras = []
    if a.get("balcony") == "1":
        extras.append("balcony")
    if a.get("yard") == "1":
        extras.append("yard")
    if a.get("agreementtype") == "month-to-month":
        extras.append("month-to-month lease")
    avail = None
    if a.get("dateavailable"):
        try:
            avail = date.fromisoformat(a["dateavailable"][:10])
        except ValueError:
            pass
    desc = http.strip_html(raw.get("description") or "")
    if extras:
        desc += "\nKijiji features: " + ", ".join(extras)
    area = a.get("areainfeet", "")
    sqft = int(area) if area.isdigit() and int(area) > 0 else None
    baths = int(a["numberbathrooms"]) / 10 if a.get("numberbathrooms", "").isdigit() else None
    return Listing(
        source=NAME, source_id=str(raw["id"]), url=raw["url"], title=raw.get("title") or "",
        description=desc, price=price["amount"] // 100,
        bedrooms=_BEDS.get(a.get("numberbedrooms", "")),
        bathrooms=baths, unit_type=a.get("unittype"),
        address=loc.get("address"), lat=coords.get("latitude"), lon=coords.get("longitude"),
        available=avail, furnished={"1": True, "0": False}.get(a.get("furnished", "")),
        sqft=sqft, photo=(raw.get("imageUrls") or [None])[0], posted=raw.get("sortingDate"),
    )


def fetch() -> list[Listing]:
    cutoff = (datetime.now(timezone.utc) - LOOKBACK).isoformat()
    out: dict[str, Listing] = {}
    for page in range(1, MAX_PAGES + 1):
        ap = _apollo(http.get(_url(page)).text)
        raws = [v for k, v in ap.items() if k.startswith("RealEstateListing:")]
        if not raws:
            break
        organic = []
        for raw in raws:
            l = to_listing(raw)
            if l:
                out[l.source_id] = l
            if raw.get("adSource") == "ORGANIC":
                organic.append(raw.get("sortingDate") or "")
        # Pages are newest-first; stop once we're past the lookback window.
        if organic and min(organic).replace("Z", "+00:00") < cutoff:
            break
    return list(out.values())


def enrich(l: Listing) -> None:
    """Replace the truncated description with the full one from the listing page."""
    ap = _apollo(http.get(l.url).text)
    raw = next((v for k, v in ap.items() if k.startswith("RealEstateListing:") and str(v.get("id")) == l.source_id), None)
    if raw and raw.get("description"):
        full = to_listing(raw)
        if full:
            l.description = full.description
