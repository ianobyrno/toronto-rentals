"""Polite HTTP: identifies itself honestly, waits between requests, never retries a block.

If a site answers 403/429 we stop and report it rather than trying to disguise the request.
"""
from __future__ import annotations

import html as _html
import random
import re
import time

import requests

USER_AGENT = "toronto-rentals-watch/0.1 (personal rental alert; +https://github.com/ianobyrno/toronto-rentals)"
MIN_DELAY, MAX_DELAY = 3.0, 6.0


class Blocked(RuntimeError):
    pass


_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-CA,en;q=0.8"})
_last = 0.0


def get(url: str, **kw) -> requests.Response:
    global _last
    wait = _last + random.uniform(MIN_DELAY, MAX_DELAY) - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    for attempt in range(2):
        try:
            r = _session.get(url, timeout=30, **kw)
        except requests.RequestException:
            if attempt:
                raise
            time.sleep(10)
            continue
        finally:
            _last = time.monotonic()
        if r.status_code in (403, 429):
            raise Blocked(f"{r.status_code} from {url.split('/')[2]} — the site is refusing automated requests")
        if r.status_code >= 500 and not attempt:
            time.sleep(10)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError("unreachable")


def strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>|</p>|</li>|</div>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = _html.unescape(s)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", s)).strip()
