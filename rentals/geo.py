"""Point-in-polygon and distance-to-edge on small areas (equirectangular projection is fine at city scale)."""
from __future__ import annotations

import math

Point = tuple[float, float]  # (lat, lon)

_M_PER_DEG_LAT = 111_320.0


def _project(p: Point, lat0: float) -> tuple[float, float]:
    lat, lon = p
    return (lon * _M_PER_DEG_LAT * math.cos(math.radians(lat0)), lat * _M_PER_DEG_LAT)


def contains(polygon: list[Point], p: Point) -> bool:
    """Ray casting. Polygon given as [(lat, lon), ...], implicitly closed."""
    lat, lon = p
    inside = False
    n = len(polygon)
    for i in range(n):
        lat1, lon1 = polygon[i]
        lat2, lon2 = polygon[(i + 1) % n]
        if (lat1 > lat) != (lat2 > lat):
            x = lon1 + (lat - lat1) * (lon2 - lon1) / (lat2 - lat1)
            if lon < x:
                inside = not inside
    return inside


def distance_to_edge_m(polygon: list[Point], p: Point) -> float:
    lat0 = p[0]
    px, py = _project(p, lat0)
    best = math.inf
    n = len(polygon)
    for i in range(n):
        ax, ay = _project(polygon[i], lat0)
        bx, by = _project(polygon[(i + 1) % n], lat0)
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
        cx, cy = ax + t * dx, ay + t * dy
        best = min(best, math.hypot(px - cx, py - cy))
    return best


def haversine_m(a: Point, b: Point) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))
