from datetime import date
from pathlib import Path

import pytest
import yaml

from rentals.dedupe import dedupe
from rentals.filters import Criteria, parse_available, parse_bedrooms
from rentals.models import Listing

CFG = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text())
C = Criteria(CFG)

# Known points (approximate)
LESLIEVILLE = (43.6625, -79.3330)        # Queen E & Jones
TRINITY_BELLWOODS = (43.6480, -79.4140)
ANNEX = (43.6700, -79.4050)              # Bloor & Spadina-ish, north of Bloor
QUEENS_QUAY = (43.6395, -79.3810)
BATHURST_QUAY = (43.6345, -79.3985)
LIBERTY_VILLAGE = (43.6385, -79.4200)
FIN_DISTRICT = (43.6485, -79.3815)       # King & Bay
ST_JAMES_TOWN = (43.6690, -79.3735)
CHURCH_WELLESLEY = (43.6655, -79.3810)
HIGH_PARK = (43.6465, -79.4630)          # west of Dufferin
ROSEDALE = (43.6800, -79.3800)           # north of Bloor east of Yonge
EAST_YORK = (43.6950, -79.3350)          # north of Danforth
BEACHES = (43.6700, -79.3000)            # east of Coxwell
CABBAGETOWN = (43.6650, -79.3630)        # east of Parliament


def L(**kw):
    base = dict(source="test", source_id=kw.pop("id", "1"), url="https://example.com/1",
                title=kw.pop("title", "Bright 1 bedroom apartment"), price=2100,
                description=kw.pop("description", "Available February 1. Unfurnished."))
    if "at" in kw:
        kw["lat"], kw["lon"] = kw.pop("at")
    base.update(kw)
    return Listing(**base)


def keep(**kw):
    l = L(**kw)
    return C.evaluate(l).keep, l


@pytest.mark.parametrize("pt", [LESLIEVILLE, TRINITY_BELLWOODS, ANNEX, QUEENS_QUAY, BATHURST_QUAY, CABBAGETOWN])
def test_in_area(pt):
    ok, _ = keep(at=pt)
    assert ok


@pytest.mark.parametrize("pt", [LIBERTY_VILLAGE, FIN_DISTRICT, ST_JAMES_TOWN, CHURCH_WELLESLEY,
                                HIGH_PARK, ROSEDALE, EAST_YORK, BEACHES])
def test_out_of_area(pt):
    ok, _ = keep(at=pt)
    assert not ok


def test_no_coords_excluded_by_name_in_title_only():
    assert not keep(title="1 bed condo in Liberty Village")[0]
    ok, l = keep(description="Available Feb 1. 5 min walk to Liberty Village.")
    assert ok and any("no map location" in f for f in l.flags)


@pytest.mark.parametrize("text", [
    "Basement apartment, separate entrance", "Bright lower level unit", "Walk-out basement",
    "Room for rent in shared house", "Looking for a roommate", "Female only please",
    "Students only", "Short-term rental", "6 month lease", "Fully furnished 1 bed",
    "Partially furnished", "Shared kitchen and bathroom"])
def test_excluded_text(text):
    assert not keep(description=f"{text}. Available Feb 1.")[0], text


@pytest.mark.parametrize("text", [
    "Unfurnished. Walk out to balcony.", "Shared laundry in building", "No students please",
    "Shared backyard", "Furnished or unfurnished available", "Lower Bay St views",
    "Ideal for students and professionals", "Suited for shared living arrangements"])
def test_not_excluded_text(text):
    assert keep(description=f"{text}. Available Feb 1.")[0], text


def test_over_budget_and_bedrooms():
    assert not keep(price=2400)[0]
    assert not keep(title="3 bedroom house")[0]
    assert keep(title="Huge loft")[0]
    assert keep(title="1+den condo")[0]


def test_lower_title_is_basement():
    assert not keep(title="Lower - 147 Niagara Street")[0]


def test_dedupe_unit_prefix_formats():
    a = L(id="a", address="- 20 EDWARD STREET, Toronto (Bay St Corridor)", source="kijiji", url="https://kijiji.ca/a")
    b = L(id="b", address="1901 - 20 Edward Street", source="condos.ca", url="https://condos.ca/b")
    assert len(dedupe([a, b])) == 1
    c = L(id="c", address="1706 - 55 Cooper Street", source="condos.ca", url="https://condos.ca/c", price=2250)
    d = L(id="d", address="Unit 5207, 55 Cooper St", source="kijiji", url="https://kijiji.ca/d", price=2300)
    assert len(dedupe([c, d])) == 2


def test_site_basement_field():
    assert not keep(unit_type="Basement")[0]


@pytest.mark.parametrize("text,tier", [
    ("Available Feb 1st", 1), ("Available February 1, 2027", 1), ("Move in 1st of February", 1),
    ("Available in February", 1), ("Available Jan 15", 2), ("Available January 1st", 2),
    ("Lovely place", 3)])
def test_tiers(text, tier):
    ok, l = keep(description=text)
    assert ok and l.tier == tier, (text, l.tier)


@pytest.mark.parametrize("text", ["Available Dec 1", "Available March 1", "Available Feb 15",
                                  "Available immediately"])
def test_bad_dates_dropped(text):
    assert not keep(description=text)[0]


def test_anchor_preferred_over_other_dates():
    d, _, anchored = parse_available("Built Dec 2019. Open house Nov 9. Available Feb 1.", 2027)
    assert anchored
    assert d == date(2027, 2, 1)


def test_structured_date_used_when_ad_has_no_anchored_date():
    ok, l = keep(available=date(2027, 2, 1), description="Unfurnished, lease ends Jan 5")
    assert ok and l.tier == 1


def test_anchored_ad_date_beats_default_site_date():
    ok, l = keep(available=date(2026, 12, 1), description="Available Feb 1st.")
    assert ok and l.tier == 1


def test_stale_site_date_ignored():
    ok, l = keep(available=date(2024, 2, 1), description="Nice unit.")
    assert ok and l.tier == 3 and any("stale" in f for f in l.flags)


def test_recent_past_site_date_means_available_now():
    from datetime import timedelta
    assert not keep(available=date.today() - timedelta(days=2), description="Nice unit.")[0]


def test_iso_date_in_text():
    ok, l = keep(description="- available 2027-01-15 for $2000")
    assert ok and l.tier == 2


def test_excluded_zones_are_strict():
    assert not keep(at=(43.6715, -79.3830))[0]       # 85 Bloor St E, right on the zone edge
    assert not keep(at=(43.6390, -79.4150))[0]       # Western Battery Rd


def test_ranking():
    _, house = keep(description="Upper floor of a Victorian with a deck. Available Feb 1.")
    _, condo = keep(description="Condo unit. Available Feb 1.")
    assert house.score > condo.score
    _, scam = keep(price=1100)
    assert scam.score < condo.score and any("scam" in f for f in scam.flags)


def test_parse_bedrooms():
    assert parse_bedrooms("Spacious 1 Bedroom + Den") == "1+den"
    assert parse_bedrooms("2BR apartment") == "2"
    assert parse_bedrooms("Bachelor unit") == "studio"
    assert parse_bedrooms("two-bedroom upper") == "2"


def test_dedupe_across_sites():
    a = L(id="a", address="123 Queen St E, Toronto", source="kijiji", url="https://kijiji.ca/a")
    b = L(id="b", address="123 Queen Street East unit 2", source="rentals.ca", url="https://rentals.ca/b", price=2125)
    c = L(id="c", address="125 Queen St E", source="viewit", url="https://viewit.ca/c")
    out = dedupe([a, b, c])
    assert len(out) == 2 and out[0].also_on == ["https://rentals.ca/b"]
