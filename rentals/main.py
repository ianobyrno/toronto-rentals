"""Entry point.

  python -m rentals.main             scrape, queue new matches into state/pending.json
  python -m rentals.main --digest    ...then email everything pending and clear the queue
  python -m rentals.main --digest --dry-run   write the email to digest.html instead of sending
"""
from __future__ import annotations

import argparse
import collections
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import digest, sources
from .dedupe import dedupe, same_unit
from .filters import Criteria
from .models import Listing
from .state import State, now

ROOT = Path(__file__).resolve().parent.parent
FAIL_ALERT_AFTER = timedelta(hours=24)


def seen_key(l: Listing) -> str:
    # Including the price means a price drop gets re-evaluated (and re-alerted if it now fits).
    return f"{l.key}@{l.price}"


def _reason(d) -> str:
    r = d.reason
    if r.startswith("price"):
        return "over budget"
    if r.startswith("available"):
        return "move-in too early" if "early" in r else "move-in too late"
    return r.split(":")[0].split(" (")[0]


def process(listings: list[Listing], state: State, crit: Criteria,
            enrichers: dict | None = None) -> tuple[list[Listing], collections.Counter]:
    reasons: collections.Counter = collections.Counter()
    enrichers = enrichers or {}
    fresh = []
    for l in listings:
        k = seen_key(l)
        if k in state.seen:
            continue
        d = crit.prefilter(l)
        if d.keep and l.source in enrichers:
            try:
                enrichers[l.source](l)
            except Exception as e:  # keep the search-page data; don't mark seen so it's retried
                print(f"enrich failed for {l.url}: {e}")
                reasons["enrich failed (will retry)"] += 1
                continue
        state.seen[k] = now()
        if d.keep:
            d = crit.evaluate(l)
        if d.keep:
            fresh.append(l)
        else:
            reasons[_reason(d)] += 1
    fresh = dedupe(fresh)
    # Drop units already queued (or already sent recently) under another site/listing id.
    out = []
    for l in fresh:
        dup = next((p for p in state.pending + state.recent if same_unit(p, l) or p.key == l.key), None)
        if dup is not None:
            if l.url not in dup.also_on and l.url != dup.url:
                dup.also_on.append(l.url)
            continue
        out.append(l)
    return out, reasons


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--digest", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    crit = Criteria(cfg)
    state = State()

    listings: list[Listing] = []
    enrichers = {}
    for mod in sources.load():
        if hasattr(mod, "enrich"):
            enrichers[mod.NAME] = mod.enrich
        h = state.health.setdefault(mod.NAME, {})
        try:
            got = mod.fetch()
            if not got:
                raise RuntimeError("returned 0 listings — probably blocked or the page layout changed")
            listings.extend(got)
            h.update(last_ok=now(), last_count=len(got), last_error=None)
            print(f"{mod.NAME}: {len(got)} listings")
        except Exception as e:  # one broken site shouldn't stop the others
            h.update(last_error=f"{now()} {type(e).__name__}: {e}"[:300], last_count=0)
            print(f"{mod.NAME}: FAILED\n{traceback.format_exc()}")

    new, reasons = process(listings, state, crit, enrichers)
    state.pending.extend(new)
    print(f"{len(new)} new matches queued; {len(state.pending)} pending. Rejected: {dict(reasons)}")

    if args.digest:
        cutoff = (datetime.now(timezone.utc) - FAIL_ALERT_AFTER).isoformat()
        failures = [f"{s} — last success {h.get('last_ok') or 'never'}; {h.get('last_error')}"
                    for s, h in state.health.items()
                    if h.get("last_error") and (h.get("last_ok") or "") < cutoff]
        subject, body = digest.build(state.pending, state.health, failures)
        if args.dry_run:
            (ROOT / "digest.html").write_text(body)
            print(f"[dry run] {subject} → digest.html")
        else:
            digest.send(subject, body)
            print(f"sent: {subject}")
            state.recent.extend(state.pending)
            state.pending = []
    state.save()


if __name__ == "__main__":
    main()
