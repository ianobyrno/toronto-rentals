"""Decide whether a listing fits, which move-in tier it's in, and how to rank it."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from . import geo
from .models import Listing

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_DAY_RE = r"(\d{1,2})(?:st|nd|rd|th)?"
_DATE_PATTERNS = [
    re.compile(rf"\b{_MONTH_RE}\s+{_DAY_RE}\b(?!\s*(?:sq|ft|m2|min|\$))", re.I),   # Feb 1, February 1st
    re.compile(rf"\b{_DAY_RE}\s+(?:of\s+)?{_MONTH_RE}\b", re.I),                   # 1st of February
]
_ISO_DATE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
_MONTH_ONLY = re.compile(rf"\bavail\w*\b[^.\n]{{0,25}}?\b(?:in |from |starting |as of |for )?{_MONTH_RE}\b(?!\s*\d)", re.I)
_AVAIL_ANCHOR = re.compile(r"\b(?:avail\w*|move[- ]?in|possession|occupancy|starting|start date|from)\b", re.I)
_NOW_RE = re.compile(r"\bavail\w*\s*(?:immediately|now|asap|right away|today)\b|\bimmediate (?:occupancy|move[- ]in|possession)\b|\bmove[- ]in ready\b", re.I)

_BED_PATTERNS = [
    (re.compile(r"\b(?:bachelor|studio|loft)\b", re.I), lambda m: "studio"),
    (re.compile(r"\b(\d)\s*(?:\+|plus|and a|and|with|w/)\s*den\b", re.I), lambda m: f"{m.group(1)}+den"),
    (re.compile(r"\b(\d)\s*(?:bed(?:room)?s?|br|bdrms?|bd)\s*(?:\+|plus|and a|and|with|w/)\s*den\b", re.I), lambda m: f"{m.group(1)}+den"),
    (re.compile(r"\b(\d)\s*(?:-\s*)?(?:bed(?:room)?s?|br|bdrms?|bd)\b", re.I), lambda m: m.group(1)),
    (re.compile(r"\b(one|two|three|four)[- ](?:bed(?:room)?s?|br)\b", re.I),
     lambda m: str(["one", "two", "three", "four"].index(m.group(1).lower()) + 1)),
]


@dataclass
class Decision:
    keep: bool
    reason: str = ""


class Criteria:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        kw = cfg["keywords"]
        c = lambda pats: [re.compile(p, re.I) for p in pats]
        self.exclude = {name: c(pats) for name, pats in kw["exclude"].items()}
        self.furnished = re.compile(kw["furnished"], re.I)
        self.furnished_ok = c(kw["furnished_ok"])
        self.flag = {name: c(pats) for name, pats in kw["flag"].items()}
        self.house = c(kw["boost"]["house_unit"])
        self.outdoor = c(kw["boost"]["outdoor"])
        area = cfg["area"]
        self.boundary = [tuple(p) for p in area["boundary"]["polygon"]]
        self.zones = [(z["name"], [tuple(p) for p in z["polygon"]], [a.lower() for a in z.get("aliases", [])])
                      for z in area["exclude"]]
        self.buffer = area["edge_buffer_m"]
        self.year = cfg["move_in"]["year"]
        self.max_rent = cfg["budget"]["max_rent"]
        self.scam_below = cfg["budget"]["scam_flag_below"]
        self.preferred = set(cfg["bedrooms"]["preferred"])

    # ---------------------------------------------------------------- pipeline
    def evaluate(self, l: Listing) -> Decision:
        """Returns keep/drop; on keep, sets l.tier, l.score, l.flags."""
        l.flags = []
        for step in (self._price, self._bedrooms, self._location, self._keywords, self._furnished, self._move_in):
            d = step(l)
            if d is not None and not d.keep:
                return d
        self._score(l)
        return Decision(True)

    def prefilter(self, l: Listing) -> Decision:
        """Cheap checks on search-page data, to decide whether the full listing is worth fetching."""
        flags = l.flags
        l.flags = []
        try:
            if l.unit_type and "basement" in l.unit_type.lower():
                return Decision(False, "basement (site field)")
            for step in (self._price, self._bedrooms, self._location):
                d = step(l)
                if d is not None and not d.keep:
                    return d
            return Decision(True)
        finally:
            l.flags = flags

    # ---------------------------------------------------------------- steps
    def _price(self, l: Listing) -> Decision | None:
        if l.price is None:
            l.flags.append("no price listed")
            return None
        if l.price > self.max_rent:
            return Decision(False, f"price ${l.price}")
        if l.price < self.scam_below:
            l.flags.append(f"⚠ ${l.price} is suspiciously cheap — likely scam")
        return None

    def _bedrooms(self, l: Listing) -> Decision | None:
        beds = l.bedrooms or parse_bedrooms(l.title) or parse_bedrooms(l.description)
        l.bedrooms = beds
        if beds is None:
            l.flags.append("bedrooms unknown")
            return None
        if beds == "studio":
            return None
        n = int(beds[0])
        if n == 0:
            l.bedrooms = "studio"
            return None
        if n > 2:
            return Decision(False, f"{beds} bedrooms")
        return None

    def _location(self, l: Listing) -> Decision | None:
        if l.lat is not None and l.lon is not None:
            p = (l.lat, l.lon)
            if not geo.contains(self.boundary, p):
                if geo.distance_to_edge_m(self.boundary, p) > self.buffer:
                    return Decision(False, "outside area")
                l.flags.append("just outside boundary — check location")
            elif geo.distance_to_edge_m(self.boundary, p) <= self.buffer:
                l.flags.append("near boundary — check location")
            for name, poly, _ in self.zones:
                if geo.contains(poly, p):
                    return Decision(False, f"in {name}")
                elif geo.distance_to_edge_m(poly, p) <= self.buffer:
                    l.flags.append(f"next to {name} — check location")
            return None
        # No coordinates: only the title/address can rule a listing out (descriptions mention
        # nearby neighbourhoods too often to trust).
        where = f"{l.title} {l.address or ''}".lower()
        for name, _, aliases in self.zones:
            if any(a in where for a in aliases):
                return Decision(False, f"in {name} (by name)")
        l.flags.append("no map location — check it's in the area")
        return None

    def _keywords(self, l: Listing) -> Decision | None:
        if l.unit_type and "basement" in l.unit_type.lower():
            return Decision(False, "basement (site field)")
        text = l.text
        for name, pats in self.exclude.items():
            for p in pats:
                if p.search(text):
                    return Decision(False, f"{name}: “{p.search(text).group(0)}”")
        for name, pats in self.flag.items():
            if any(p.search(text) for p in pats):
                l.flags.append(name.replace("_", " "))
        return None

    def _furnished(self, l: Listing) -> Decision | None:
        ok = [m.group(0).lower() for p in self.furnished_ok if (m := p.search(l.text))]
        if ok:
            # Text explicitly says unfurnished (or offers the choice) — trust it over the site field.
            if any(o != "unfurnished" for o in ok):
                l.flags.append("furnished/unfurnished option")
            return None
        if l.furnished is True:
            return Decision(False, "furnished (site field)")
        if self.furnished.search(l.text):
            # "semi-furnished", "partially furnished", "fully furnished" all land here
            return Decision(False, "furnished")
        return None

    def _move_in(self, l: Listing) -> Decision | None:
        today = date.today()
        site = l.available
        if site is not None and site < today - timedelta(days=60):
            # Long-stale default left in the site's field — ignore it.
            l.flags.append(f"site's move-in date ({site:%d %b %Y}) is stale — ignored")
            site = None
        text_d, approx, anchored = parse_available(l.available_text or "", self.year)
        if text_d is None:
            text_d, approx, anchored = parse_available(l.text, self.year)
        # Landlords often leave the site's date field at its default; a date written next to
        # "available"/"move-in" in the ad itself is more trustworthy.
        if text_d is not None and (anchored or site is None):
            d = text_d
            if site is not None and site != text_d:
                l.flags.append(f"ad says {text_d:%d %b}, site field says {site:%d %b}")
        else:
            d, approx = site, False
        if d is None:
            if _NOW_RE.search(l.text) or _NOW_RE.search(l.available_text or ""):
                return Decision(False, "available now (too early)")
            l.tier = 3
            return None
        jan1, feb1 = date(self.year, 1, 1), date(self.year, 2, 1)
        if (d.month, d.day) == (2, 1) or (approx and d.month == 2):
            l.tier = 1
        elif d < jan1:
            return Decision(False, f"available {d:%d %b} (too early)")
        elif d > feb1:
            return Decision(False, f"available {d:%d %b} (too late)")
        else:
            l.tier = 2
        l.available = d
        if approx:
            l.flags.append(f"available {d:%B} (day not stated)")
        return None

    def _score(self, l: Listing) -> None:
        s = 0.0
        ut = (l.unit_type or "").lower()
        house = any(w in ut for w in ("house", "town", "duplex", "triplex", "semi", "detached")) \
            or any(p.search(l.text) for p in self.house)
        if house:
            s += 3
            l.flags.insert(0, "🏠 house/townhouse unit")
        if any(p.search(l.text) for p in self.outdoor):
            s += 2
            l.flags.insert(0, "🌳 outdoor space")
        if l.bedrooms in self.preferred:
            s += 1
        if l.price:
            s += (self.max_rent - l.price) / 1000
        if any("scam" in f for f in l.flags):
            s -= 5
        l.score = round(s, 2)


# ---------------------------------------------------------------- parsers
def parse_bedrooms(text: str) -> str | None:
    if not text:
        return None
    for rx, fn in _BED_PATTERNS:
        m = rx.search(text)
        if m:
            return fn(m)
    return None


def parse_available(text: str, year: int) -> tuple[date | None, bool, bool]:
    """Find the move-in date in free text. Returns (date, approximate?, anchored?).

    Prefers a date that follows an 'available'/'move-in' anchor; falls back to the first date
    mentioned. Month-only mentions ("available in February") return the 1st with approx=True.
    """
    if not text:
        return None, False, False
    candidates: list[tuple[int, date]] = []
    for rx in _DATE_PATTERNS:
        for m in rx.finditer(text):
            g = m.groups()
            mon, day = (g[0], g[1]) if not g[0].isdigit() else (g[1], g[0])
            mnum, dnum = MONTHS[mon[:3].lower()], int(day)
            if not 1 <= dnum <= 31:
                continue
            y = year if mnum <= 6 else year - 1
            try:
                d = date(y, mnum, dnum)
            except ValueError:
                continue
            anchored = bool(_AVAIL_ANCHOR.search(text[max(0, m.start() - 40):m.start()]))
            candidates.append((0 if anchored else 1, m.start(), d))
    for m in _ISO_DATE.finditer(text):
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        anchored = bool(_AVAIL_ANCHOR.search(text[max(0, m.start() - 40):m.start()]))
        candidates.append((0 if anchored else 1, m.start(), d))
    if candidates:
        candidates.sort()
        return candidates[0][2], False, candidates[0][0] == 0
    m = _MONTH_ONLY.search(text)
    if m:
        mnum = MONTHS[m.group(1)[:3].lower()]
        y = year if mnum <= 6 else year - 1
        return date(y, mnum, 1), True, True
    return None, False, False
