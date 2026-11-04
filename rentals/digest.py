"""Build and send the daily email."""
from __future__ import annotations

import html
import os
import smtplib
from email.message import EmailMessage

from .models import Listing

TIER_TITLES = {
    1: "⭐ Available 1 February",
    2: "Available in January",
    3: "No date stated / available now / flexible",
}


def _card(l: Listing) -> str:
    e = html.escape
    bits = [f"<b>${l.price:,}</b>" if l.price else "<b>price ?</b>",
            e(l.bedrooms + (" bed" if l.bedrooms not in ("studio", None) else "")) if l.bedrooms else "beds ?"]
    if l.bathrooms:
        bits.append(f"{l.bathrooms:g} bath")
    if l.sqft:
        bits.append(f"{l.sqft} sq ft (~{round(l.sqft * 0.0929)} m²)")
    if l.available:
        bits.append(f"from {l.available:%a %d %b}")
    meta = " · ".join(bits)
    flags = "".join(f'<span style="display:inline-block;background:#eef;border-radius:4px;padding:1px 6px;margin:2px 4px 0 0;font-size:12px">{e(f)}</span>'
                    for f in l.flags)
    photo = (f'<img src="{e(l.photo)}" width="120" style="float:right;margin-left:10px;border-radius:4px">'
             if l.photo else "")
    also = ""
    if l.also_on:
        also = "<br><small>Also listed: " + " · ".join(f'<a href="{e(u)}">{e(u.split("/")[2])}</a>' for u in l.also_on) + "</small>"
    desc = e(l.description[:280] + ("…" if len(l.description) > 280 else ""))
    return f"""
<div style="border:1px solid #ddd;border-radius:6px;padding:10px;margin:8px 0;overflow:hidden">
 {photo}<a href="{e(l.url)}" style="font-size:15px;font-weight:600">{e(l.title)}</a>
 <div style="color:#555;font-size:12px">{e(l.source)}{(' · ' + e(l.address)) if l.address else ''}</div>
 <div style="margin:4px 0">{meta}</div>
 <div>{flags}</div>
 <div style="color:#444;font-size:13px;margin-top:6px">{desc}</div>{also}
</div>"""


def build(listings: list[Listing], health: dict, failures: list[str]) -> tuple[str, str]:
    by_tier: dict[int, list[Listing]] = {}
    for l in listings:
        by_tier.setdefault(l.tier or 3, []).append(l)
    parts = ['<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:680px">']
    if failures:
        parts.append('<div style="background:#fee;border:1px solid #c33;padding:8px;border-radius:6px">'
                     '<b>Sources failing:</b><br>' + "<br>".join(html.escape(f) for f in failures) + "</div>")
    if not listings:
        parts.append("<p>No new matches since the last digest.</p>")
    for tier in sorted(by_tier):
        items = sorted(by_tier[tier], key=lambda l: -l.score)
        parts.append(f"<h2 style='margin-bottom:0'>{TIER_TITLES[tier]} ({len(items)})</h2>")
        parts.extend(_card(l) for l in items)
    counts = ", ".join(f"{s}: {h.get('last_count', '?')}" for s, h in sorted(health.items()))
    parts.append(f"<p style='color:#888;font-size:12px'>Listings checked on last run — {html.escape(counts)}</p></div>")
    t1 = len(by_tier.get(1, []))
    subject = f"Toronto rentals — {len(listings)} new" + (f" ({t1} for Feb 1)" if t1 else "")
    if failures:
        subject += " — ⚠ source failing"
    return subject, "\n".join(parts)


def send(subject: str, body_html: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("EMAIL_FROM") or os.environ["SMTP_USER"]
    msg["To"] = os.environ["EMAIL_TO"]
    msg.set_content("This digest is HTML — open it in an HTML-capable mail client.")
    msg.add_alternative(body_html, subtype="html")
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    if port == 465:
        with smtplib.SMTP_SSL(host, port) as s:
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port) as s:
            s.starttls()
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
            s.send_message(msg)
