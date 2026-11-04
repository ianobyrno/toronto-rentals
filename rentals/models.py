from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date


@dataclass
class Listing:
    """One rental listing, normalised across sources.

    Scrapers fill what they can; everything except source/source_id/url/title is optional.
    """
    source: str
    source_id: str
    url: str
    title: str
    description: str = ""
    price: int | None = None              # CAD per month
    bedrooms: str | None = None           # "studio" | "1" | "1+den" | "2" | "3" ...
    bathrooms: float | None = None
    unit_type: str | None = None          # site's own type field, e.g. "basement", "condo", "house"
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    available: date | None = None         # structured date from the site, if any
    available_text: str | None = None     # raw "available" text, if any
    furnished: bool | None = None         # site's own field, if any
    sqft: int | None = None
    photo: str | None = None
    posted: str | None = None

    # filled in by the pipeline
    tier: int | None = None
    score: float = 0.0
    flags: list[str] = field(default_factory=list)
    also_on: list[str] = field(default_factory=list)
    sent_at: str | None = None

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.description}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["available"] = self.available.isoformat() if self.available else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Listing":
        d = dict(d)
        if d.get("available"):
            d["available"] = date.fromisoformat(d["available"])
        return cls(**d)
