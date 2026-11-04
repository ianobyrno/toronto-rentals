"""Site scrapers. Each module exposes `NAME` and `fetch() -> list[Listing]`.

A scraper should return every listing on the site's newest-first results for the wider
downtown area under budget; the pipeline does all the real filtering, so scrapers stay dumb.
It should raise on failure (blocked, layout changed) rather than return [] — the digest
reports failing sources so silent breakage gets noticed.
"""
from __future__ import annotations

import importlib

# Filled in as each scraper is written against the live site.
ENABLED: list[str] = ["kijiji", "condos_ca"]


def load():
    return [importlib.import_module(f"{__name__}.{n}") for n in ENABLED]
