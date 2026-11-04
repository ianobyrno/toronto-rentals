# Toronto rental watch

Checks Toronto rental sites (Kijiji, Condos.ca) every 3 hours on GitHub Actions and emails a morning digest
(~06:30–07:30 Toronto) of new listings matching `config.yaml`, ranked into:

1. **Available 1 February**
2. **Available in January**
3. **No date / available now / flexible**

Within each tier: units in houses or townhouses first, then listings with outdoor space, then 1+den or 2-bed, then cheaper.

## Setup

Repo → Settings → Secrets and variables → Actions → add:

| Secret | Example |
|---|---|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `465` |
| `SMTP_USER` | sending account |
| `SMTP_PASS` | Gmail **app password** (Google Account → Security → App passwords), not your login password |
| `EMAIL_TO` | where the digest goes |
| `EMAIL_FROM` | optional, defaults to `SMTP_USER` |

Test it: Actions → rental-watch → Run workflow → tick "Send the digest now".

## Tuning

- Criteria, keywords and map polygons all live in `config.yaml`.
- `python -m rentals.main --digest --dry-run` writes `digest.html` locally instead of emailing.
- `python -m pytest` runs the filter tests.
- If a source fails for more than 24 h, the digest says so at the top.

## Sources

| Site | Status |
|---|---|
| Kijiji | ✅ radius search, full description fetched only for candidates |
| Condos.ca | ✅ MLS condo leases; structured move-in date, furnished, outdoor space |
| Rentals.ca | ❌ refuses automated requests (403) — use its own saved-search alerts |
| PadMapper | ❌ listings only load from `/api`, which robots.txt disallows |
| Viewit | ⏸ parked: 5 results per page via ASP.NET postbacks (~60 requests/run), mostly whole-building ads without dates |

Scrapers identify themselves, wait 3–6 s between requests, stay within robots.txt, and stop
(reporting the failure in the digest) if a site blocks them.
