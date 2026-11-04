"""Persistent state, committed back to the repo by the workflow.

state/seen.json     {listing key: first-seen ISO timestamp}  — never alert twice
state/pending.json  [listing dicts]                          — matches waiting for the next digest
state/recent.json   [listing dicts]                          — sent in the last 30 days (cross-day de-dupe)
state/health.json   {source: {last_ok, last_error, last_count}}
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Listing

ROOT = Path(__file__).resolve().parent.parent / "state"
KEEP_SEEN_DAYS = 90
KEEP_RECENT_DAYS = 30


def _load(name: str, default):
    p = ROOT / name
    return json.loads(p.read_text()) if p.exists() else default


def _save(name: str, data) -> None:
    ROOT.mkdir(exist_ok=True)
    (ROOT / name).write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class State:
    def __init__(self):
        self.seen: dict[str, str] = _load("seen.json", {})
        self.pending: list[Listing] = [Listing.from_dict(d) for d in _load("pending.json", [])]
        self.recent: list[Listing] = [Listing.from_dict(d) for d in _load("recent.json", [])]
        self.health: dict[str, dict] = _load("health.json", {})

    def save(self) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_SEEN_DAYS)).isoformat()
        self.seen = {k: v for k, v in self.seen.items() if v >= cutoff}
        _save("seen.json", self.seen)
        _save("pending.json", [l.to_dict() for l in self.pending])
        rcut = (datetime.now(timezone.utc) - timedelta(days=KEEP_RECENT_DAYS)).isoformat()
        for l in self.recent:
            l.sent_at = l.sent_at or now()
        self.recent = [l for l in self.recent if l.sent_at >= rcut]
        _save("recent.json", [l.to_dict() for l in self.recent])
        _save("health.json", self.health)
