"""How big a ship is, how many containers it carries, and where it is too big to go.

- TEU (twenty-foot containers): no free list gives every ship's capacity, so it is estimated
  from the length and beam the ship sends over AIS (a fit to well-known container ships, about
  20% either way), and replaced by an exact figure where one is known: Wikidata ('maximum
  capacity' that applies to TEU, asked with the ship's owner details), or a CSV of IMO and TEU
  saved in var\\manual\\ship_teu\\.
- Canals and straits: the largest ship each takes (length, beam, draught, air draught), from
  the canal authorities' notices (Panama Canal Authority notice N-1-2025) and Wikipedia's
  Suezmax, Seawaymax, Malaccamax and Kiel Canal pages; typed in here.
- Ports: the largest ship each port takes and its channel depth, from NGA's World Port Index
  (not every port has them; NGA's figures can be old).

A ship's draught over AIS is how deep it sits now, as the crew last set it; a ship that is not
fully loaded sits higher, so 'fits now' can differ from 'fits when full'.
"""

from __future__ import annotations

import csv
import math
import time
from pathlib import Path

# name, id, length, beam, draught, air draught (m), what the figures are, where from
CANALS = [
    {"id": "panama_new", "name": "Panama Canal (new locks)", "length": 370.33, "beam": 51.25, "draught": 15.24, "air": 57.91,
     "note": "Neopanamax: the 2016 locks", "source": "Panama Canal Authority notice N-1-2025"},
    {"id": "panama_old", "name": "Panama Canal (old locks)", "length": 294.43, "beam": 32.31, "draught": 12.04, "air": 57.91,
     "note": "Panamax: 294.4 m is the limit for container and passenger ships (289.6 m for others)",
     "source": "Panama Canal Authority notice N-1-2025"},
    {"id": "suez", "name": "Suez Canal", "length": 400.0, "beam": 77.5, "draught": 20.1, "air": 68.0,
     "note": "Suezmax: 20.1 m draught for ships up to 50 m wide, less for wider ships (12.2 m at 77.5 m)",
     "source": "Wikipedia, Suezmax"},
    {"id": "malacca", "name": "Strait of Malacca", "length": None, "beam": None, "draught": 20.5, "air": None,
     "note": "Malaccamax: only draught limits ships (the strait is about 25 m deep at its shallowest; 20.5 m is the usual largest)",
     "source": "Wikipedia, Malaccamax"},
    {"id": "kiel", "name": "Kiel Canal", "length": 235.5, "beam": 32.5, "draught": 7.0, "air": 40.0,
     "note": "7 m draught at the longest; ships up to 160 m long may draw 9.5 m", "source": "Wikipedia, Kiel Canal"},
    {"id": "seaway", "name": "St Lawrence Seaway", "length": 225.55, "beam": 23.8, "draught": 8.08, "air": 35.5,
     "note": "Seawaymax: the size of the Seaway's locks", "source": "Wikipedia, Seawaymax"},
]
CANAL_BY_ID = {c["id"]: c for c in CANALS}

# TEU ~ exp(A) * length^B * beam^C, fitted to well-known container ships from 1,000 to 24,000 TEU
TEU_A, TEU_B, TEU_C = -4.897, 1.090, 2.019
CONTAINER_WORDS = ("CONTAINER", "CONT.")


def estimate_teu(length_m, beam_m) -> int | None:
    """About how many TEU a container ship of this length and beam carries (rounded to 100,
    or 10 under 1,000); None for sizes no container ship has."""
    if not isinstance(length_m, (int, float)) or not isinstance(beam_m, (int, float)):
        return None
    if not (80 <= length_m <= 420 and 12 <= beam_m <= 66) or length_m / beam_m < 4:
        return None
    t = math.exp(TEU_A) * length_m ** TEU_B * beam_m ** TEU_C
    return int(round(t, -1 if t < 1000 else -2))


def _beam_draught_suez(beam: float) -> float:
    """Suez's allowed draught falls for ships wider than 50 m (straight line to 12.2 m at 77.5 m)."""
    if beam <= 50:
        return 20.1
    return round(20.1 - (beam - 50) * (20.1 - 12.2) / 27.5, 1)


def check(ship: dict, limit: dict) -> dict:
    """Whether a ship fits a canal or port's limits: ok True (fits), False (too big) or None
    (can't tell: a size or a limit is missing); why lists each size over its limit, now
    (draught as it sits now) and the checks that could be made."""
    length, beam, draught = ship.get("length_m"), ship.get("width_m"), ship.get("draught_m")
    max_draught = limit.get("draught")
    if limit.get("id") == "suez" and isinstance(beam, (int, float)):
        max_draught = _beam_draught_suez(beam)
    if limit.get("id") == "kiel" and isinstance(length, (int, float)) and length <= 160:
        max_draught = 9.5
    why, checked = [], 0
    for label, have, most in (("long", length, limit.get("length")), ("wide", beam, limit.get("beam")),
                              ("deep in the water now", draught, max_draught)):
        if isinstance(have, (int, float)) and have > 0 and isinstance(most, (int, float)) and most > 0:
            checked += 1
            if have > most + 0.05:
                why.append(f"{have:g} m {label}; the limit is {most:g} m")
    ok = False if why else (True if checked else None)
    return {"ok": ok, "why": why, "checked": checked}


def port_limit(port: dict) -> dict | None:
    """A World Port Index port's limits as check() takes them, or None when NGA lists none: its
    largest ship (length, beam, draught), else its channel depth as the draught limit."""
    if not port:
        return None
    draught = port.get("max_draft") or port.get("depth")
    if not (port.get("max_len") or port.get("max_beam") or draught):
        return None
    return {"id": f"port:{port.get('locode') or port.get('name')}", "name": port.get("name"), "length": port.get("max_len"),
            "beam": port.get("max_beam"), "draught": draught,
            "note": "largest ship listed" if port.get("max_draft") else "channel depth (no largest ship listed)",
            "source": "NGA World Port Index"}


def fits(ship: dict, next_port: dict | None = None) -> dict:
    """The canals and straits a ship fits through, and its next port if that port's limits are known."""
    canals = [{"id": c["id"], "name": c["name"], "note": c["note"], "source": c["source"],
               "limits": {k: c[k] for k in ("length", "beam", "draught", "air")}, **check(ship, c)} for c in CANALS]
    port = None
    pl = port_limit(next_port) if next_port else None
    if pl:
        port = {"name": pl["name"], "note": pl["note"], "source": pl["source"],
                "limits": {k: pl[k] for k in ("length", "beam", "draught")}, **check(ship, pl)}
    return {"canals": canals, "port": port}


def too_big(ship: dict, limit_id: str, ports_by_code: dict | None = None) -> bool:
    """True when the ship is over a canal's limits ('panama_new' ...) or a port's ('port:NZAKL')."""
    if limit_id.startswith("port:"):
        code = limit_id[5:].replace(" ", "").upper()
        limit = port_limit((ports_by_code or {}).get(code) or {})
    else:
        limit = CANAL_BY_ID.get(limit_id)
    return bool(limit) and check(ship, limit)["ok"] is False


# ----------------------------------------------------------------------------- exact TEU
class KnownTeu:
    """Exact TEU by IMO from CSVs saved in var\\manual\\ship_teu (columns imo and teu, any other
    columns ignored), read again when a file changes."""

    def __init__(self, folder: Path | None) -> None:
        self.folder = folder
        self._at, self._seen, self.teu = 0.0, None, {}

    def get(self, imo) -> int | None:
        if not imo or self.folder is None:
            return None
        if time.time() - self._at > 60:
            self._at = time.time()
            files = sorted(self.folder.glob("*.csv")) if self.folder.is_dir() else []
            stamp = tuple((f.name, f.stat().st_mtime) for f in files)
            if stamp != self._seen:
                self._seen, self.teu = stamp, _read_teu(files)
        return self.teu.get(str(imo))


def _read_teu(files: list[Path]) -> dict[str, int]:
    out = {}
    for f in files:
        with f.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
            for row in csv.DictReader(fh):
                low = {str(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                imo, teu = "".join(ch for ch in low.get("imo", "") if ch.isdigit()), low.get("teu", "").replace(",", "")
                if len(imo) == 7 and teu.replace(".", "", 1).isdigit():
                    out[imo] = int(float(teu))
    return out


def teu_of(ship: dict, known: int | None = None, wikidata: int | None = None, is_container: bool | None = None) -> dict | None:
    """A ship's TEU: exact (your list, then Wikidata) or estimated from its size, with where the
    figure came from; container says whether the ship is known to carry containers (an estimate
    for a ship not known to is 'if it carries containers')."""
    if known:
        return {"teu": known, "estimated": False, "source": "your list (var\\manual\\ship_teu)", "container": True}
    if wikidata:
        return {"teu": wikidata, "estimated": False, "source": "Wikidata", "container": True}
    est = estimate_teu(ship.get("length_m"), ship.get("width_m"))
    if est is None:
        return None
    return {"teu": est, "estimated": True, "source": "estimated from its length and beam (about 20% either way)",
            "container": bool(is_container)}


def looks_container(name: str | None, cargo_words: list[str] | None = None) -> bool:
    """True when a ship's line (by name) or a port list's cargo says it carries containers."""
    from worldmodel_api.schedules import line_of

    if any(w and any(c in str(w).upper() for c in CONTAINER_WORDS) for w in cargo_words or []):
        return True
    return line_of(name) is not None
