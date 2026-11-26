"""The way a ship goes by sea, not the straight line: through the shipping lanes, round capes and
coasts and through Suez, Panama, Malacca and the other straits. Uses the searoute package (Apache
2.0, Eurostat's SeaRoute marine network); without it, None is returned and callers keep the
great-circle line. The Northwest Passage is left out (as searoute does by default)."""

from __future__ import annotations

import logging
import threading
from functools import lru_cache

log = logging.getLogger(__name__)
_lock = threading.Lock()  # searoute builds its network once; one route at a time is quick enough


def available() -> bool:
    try:
        import searoute  # noqa: F401
    except ImportError:
        return False
    return True


@lru_cache(maxsize=2048)
def _route(lon1: float, lat1: float, lon2: float, lat2: float) -> tuple[tuple[tuple[float, float], ...], float, tuple[str, ...]] | None:
    try:
        import searoute as sr
    except ImportError:
        return None
    try:
        with _lock:
            f = sr.searoute([lon1, lat1], [lon2, lat2], units="naut", append_orig_dest=True, return_passages=True)
    except Exception as exc:  # noqa: BLE001  (no path, bad point: keep the straight line)
        log.info("sea path %s,%s -> %s,%s: %s", lon1, lat1, lon2, lat2, exc)
        return None
    coords = tuple((round(c[0], 4), round(c[1], 4)) for c in (f.get("geometry") or {}).get("coordinates") or [])
    if len(coords) < 2:
        return None
    props = f.get("properties") or {}
    return coords, float(props.get("length") or 0), tuple(props.get("traversed_passages") or ())


def sea_path(lon1: float, lat1: float, lon2: float, lat2: float, exact: bool = True) -> dict | None:
    """{coords, nm, passages} from a point to a port by sea, or None. `exact` False rounds the start
    to 0.25 degrees so many nearby asks share one answer (for distances, not drawing)."""
    if exact:
        r = _route(round(lon1, 3), round(lat1, 3), round(lon2, 3), round(lat2, 3))
    else:
        r = _route(round(lon1 * 4) / 4, round(lat1 * 4) / 4, round(lon2, 2), round(lat2, 2))
    if not r:
        return None
    return {"coords": [list(c) for c in r[0]], "nm": round(r[1]), "passages": list(r[2])}
