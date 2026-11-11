"""The Solar system page's downloads, kept under <data folder>/space/ and read again every 90 days.

    asteroids   JPL Small-Body Database query API: the ~15,000 biggest main-belt asteroids
                (H < 13), near-Earth asteroids (H < 20) and Jupiter Trojans (H < 14), with their
                orbits, spectral type where measured, size and brightness (albedo).
    missions    JPL Horizons: where each spacecraft in MISSIONS was, every 15 days from launch
                to the end of its mission (or 2030), seen from above the Sun (ecliptic, AU).
    values      Asterank's guessed dollar values for asteroids (only with Settings > Maps >
                "Asteroid values"; they are rough guesses, kept apart from the rest).

One request at a time, two seconds apart; a mission Horizons cannot answer is listed and skipped.
Planet positions need no download: the page works them out from JPL's orbital elements.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from worldmodel_contract import local

log = logging.getLogger(__name__)

SBDB = "https://ssd-api.jpl.nasa.gov/sbdb_query.api"
HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api"
ASTERANK = "https://www.asterank.com/api/asterank"
USER_AGENT = "worldmodel/0.1 (personal local tool) httpx"
GAP = 2.0
KEEP_DAYS = 90
FIELDS = "full_name,a,e,i,om,w,ma,epoch,spec_B,spec_T,neo,class,diameter,albedo,H"
GROUPS = [  # (label, extra query parameters)
    ("main belt", {"sb-kind": "a", "sb-cdata": json.dumps({"AND": ["H|LT|13"]}), "limit": "20000"}),
    ("near Earth", {"sb-kind": "a", "sb-group": "neo", "sb-cdata": json.dumps({"AND": ["H|LT|20"]}), "limit": "8000"}),
    ("Jupiter Trojans", {"sb-kind": "a", "sb-class": "TJN", "sb-cdata": json.dumps({"AND": ["H|LT|14"]}), "limit": "8000"}),
]

# Spacecraft that left Earth's neighbourhood. id = NAIF code used by Horizons; dates bound the path asked for.
MISSIONS: list[dict] = [
    {"id": "-23", "name": "Pioneer 10", "start": "1972-03-04", "stop": "2030-01-01", "country": "USA", "agency": "NASA",
     "what": "First to cross the asteroid belt and fly past Jupiter (1973)."},
    {"id": "-24", "name": "Pioneer 11", "start": "1973-04-07", "stop": "2030-01-01", "country": "USA", "agency": "NASA",
     "what": "First to Saturn (1979), after Jupiter."},
    {"id": "-31", "name": "Voyager 1", "start": "1977-09-06", "stop": "2030-01-01", "country": "USA", "agency": "NASA",
     "what": "Jupiter and Saturn; left the Sun's bubble (heliopause) in 2012, the farthest human-made object."},
    {"id": "-32", "name": "Voyager 2", "start": "1977-08-21", "stop": "2030-01-01", "country": "USA", "agency": "NASA",
     "what": "The only visit to Uranus (1986) and Neptune (1989)."},
    {"id": "-77", "name": "Galileo", "start": "1989-10-19", "stop": "2003-09-20", "country": "USA", "agency": "NASA",
     "what": "Orbited Jupiter 1995-2003; found signs of an ocean under Europa's ice."},
    {"id": "-82", "name": "Cassini", "start": "1997-10-16", "stop": "2017-09-14", "country": "USA", "agency": "NASA, ESA, ASI",
     "what": "Orbited Saturn 2004-2017; landed Huygens on Titan."},
    {"id": "-236", "name": "MESSENGER", "start": "2004-08-04", "stop": "2015-04-29", "country": "USA", "agency": "NASA",
     "what": "First to orbit Mercury (2011-2015); found ice in its polar craters."},
    {"id": "-226", "name": "Rosetta", "start": "2004-03-03", "stop": "2016-09-29", "country": None, "agency": "ESA",
     "what": "Orbited comet 67P and put the Philae lander on it (2014)."},
    {"id": "-98", "name": "New Horizons", "start": "2006-01-20", "stop": "2030-01-01", "country": "USA", "agency": "NASA",
     "what": "Pluto (2015) and Arrokoth (2019) in the Kuiper belt."},
    {"id": "-203", "name": "Dawn", "start": "2007-09-28", "stop": "2018-10-30", "country": "USA", "agency": "NASA",
     "what": "Orbited Vesta and Ceres, the two biggest bodies in the asteroid belt."},
    {"id": "-61", "name": "Juno", "start": "2011-08-06", "stop": "2025-09-01", "country": "USA", "agency": "NASA",
     "what": "Orbiting Jupiter since 2016, over its poles."},
    {"id": "-3", "name": "Mangalyaan", "start": "2013-11-06", "stop": "2014-09-23", "country": "IND", "agency": "ISRO",
     "what": "India's Mars Orbiter Mission, Mars at the first try."},
    {"id": "-37", "name": "Hayabusa2", "start": "2014-12-04", "stop": "2030-01-01", "country": "JPN", "agency": "JAXA",
     "what": "Brought samples of asteroid Ryugu back to Earth (2020)."},
    {"id": "-64", "name": "OSIRIS-REx", "start": "2016-09-09", "stop": "2030-01-01", "country": "USA", "agency": "NASA",
     "what": "Brought samples of asteroid Bennu back (2023); now OSIRIS-APEX, on its way to Apophis."},
    {"id": "-96", "name": "Parker Solar Probe", "start": "2018-08-13", "stop": "2025-08-01", "country": "USA", "agency": "NASA",
     "what": "Closest to the Sun of any spacecraft, through its outer atmosphere."},
    {"id": "-121", "name": "BepiColombo", "start": "2018-10-21", "stop": "2026-11-01", "country": None, "agency": "ESA, JAXA",
     "what": "On its way to orbit Mercury."},
    {"id": "-168", "name": "Perseverance", "start": "2020-07-31", "stop": "2021-02-17", "country": "USA", "agency": "NASA",
     "what": "Mars rover collecting rock samples in Jezero crater."},
    {"id": "-49", "name": "Lucy", "start": "2021-10-17", "stop": "2033-01-01", "country": "USA", "agency": "NASA",
     "what": "On its way to Jupiter's Trojan asteroids."},
    {"id": "-28", "name": "JUICE", "start": "2023-04-15", "stop": "2031-07-01", "country": None, "agency": "ESA",
     "what": "On its way to Jupiter's icy moons Ganymede, Callisto and Europa."},
    {"id": "-255", "name": "Psyche", "start": "2023-10-14", "stop": "2029-08-01", "country": "USA", "agency": "NASA",
     "what": "On its way to the metal-rich asteroid Psyche."},
    {"id": "-159", "name": "Europa Clipper", "start": "2024-10-15", "stop": "2030-04-01", "country": "USA", "agency": "NASA",
     "what": "On its way to Jupiter's moon Europa and its ocean."},
]

_lock = threading.Lock()
_job: dict = {"state": "idle"}


def root() -> Path:
    return local.home() / "space"


def _read(name: str):
    try:
        return json.loads((root() / name).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _write(name: str, data) -> None:
    root().mkdir(parents=True, exist_ok=True)
    tmp = root() / f"{name}.tmp"
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    tmp.replace(root() / name)


def _age_days(data) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(data["fetched"])).days
    except (TypeError, KeyError, ValueError):
        return 1e9


def status() -> dict:
    s = local.load_settings()
    with _lock:
        job = dict(_job)
    out = {"job": job, "on": s["space_fetch"], "values_on": s["space_values"], "missions": MISSIONS}
    for name in ("asteroids", "missions", "values"):
        d = _read(f"{name}.json")
        out[name + "_have"] = {"fetched": d.get("fetched"), "count": len(d.get("rows", [])),
                               "bytes": (root() / f"{name}.json").stat().st_size} if d else None
    out["due"] = s["space_fetch"] and any(_age_days(_read(f"{n}.json")) > KEEP_DAYS for n in ("asteroids", "missions"))
    return out


def data(name: str):
    return _read(f"{name}.json")


# ----------------------------------------------------------------------------- reading the answers
def asteroid_rows(answer: dict, group: str) -> list[list]:
    """SBDB's {"fields": [...], "data": [[...]]} into compact rows:
    [name, a, e, i, om, w, ma, epoch, type, measured, neo, class, diameter, group]."""
    f = {k: i for i, k in enumerate(answer.get("fields", []))}
    out = []

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    for r in answer.get("data", []):
        a, e = num(r[f["a"]]), num(r[f["e"]])
        if a is None or e is None or e >= 1:
            continue
        spec = (r[f["spec_B"]] or r[f["spec_T"]] or "").strip() if "spec_B" in f else ""
        kind, measured = spec_kind(spec), bool(spec)
        if not measured:  # guess from how much light it reflects: dark ones are mostly carbon-rich, bright ones stony
            alb = num(r[f["albedo"]]) if "albedo" in f else None
            kind = None if alb is None else ("C" if alb < 0.1 else "S" if alb < 0.3 else "X")
        out.append([str(r[f["full_name"]]).strip(), round(a, 5), round(e, 5), round(num(r[f["i"]]) or 0, 3),
                    round(num(r[f["om"]]) or 0, 3), round(num(r[f["w"]]) or 0, 3), round(num(r[f["ma"]]) or 0, 3),
                    num(r[f["epoch"]]), kind, measured, r[f["neo"]] == "Y", r[f["class"]], num(r[f["diameter"]]), group])
    return out


def spec_kind(spec: str) -> str | None:
    """A spectral type (SMASSII or Tholen) into its broad group: C (carbon, water-bearing), S (stony,
    silicates and some metal), M/X (metal-rich or unclear), V (basalt, like Vesta), or other."""
    s = spec.strip().upper()
    if not s:
        return None
    if s[0] in "CBGFD" or s.startswith("P"):
        return "C"
    if s[0] in "SQAKLR" or s.startswith("O"):
        return "S"
    if s[0] in "MXE":
        return "X"
    if s[0] == "V":
        return "V"
    return "C" if s[0] == "T" else None


def horizons_rows(answer: dict) -> list[list[float]]:
    """Horizons CSV vectors between $$SOE and $$EOE into [julian day, x, y, z] (AU, ecliptic, Sun at 0)."""
    text = answer.get("result", "")
    if "$$SOE" not in text:
        raise ValueError(text.strip().splitlines()[-1][:200] if text.strip() else "no answer")
    body = text.split("$$SOE", 1)[1].split("$$EOE", 1)[0]
    out = []
    for line in body.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        try:
            out.append([round(float(parts[0]), 1), round(float(parts[2]), 4), round(float(parts[3]), 4), round(float(parts[4]), 4)])
        except (IndexError, ValueError):
            continue
    return out


def value_rows(answer: list) -> list[list]:
    out = []
    for r in answer or []:
        try:
            out.append([str(r.get("full_name") or r.get("prov_des") or "").strip(), float(r["price"]), r.get("spec") or None])
        except (KeyError, TypeError, ValueError):
            continue
    return out


# ----------------------------------------------------------------------------- fetching
def start(force: bool = False) -> dict:
    with _lock:
        if _job.get("state") == "running":
            return dict(_job)
        _job.clear()
        _job.update(state="running", step="Getting ready", started=datetime.now(timezone.utc).isoformat(timespec="seconds"), skipped=[])
    threading.Thread(target=_fetch, args=(force,), daemon=True, name="space").start()
    with _lock:
        return dict(_job)


def _step(text: str) -> None:
    with _lock:
        _job["step"] = text


def _fetch(force: bool) -> None:
    s = local.load_settings()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            if force or _age_days(_read("asteroids.json")) > KEEP_DAYS:
                rows = []
                for label, params in GROUPS:
                    _step(f"Asteroids: {label}")
                    r = client.get(SBDB, params={"fields": FIELDS, **params})
                    r.raise_for_status()
                    rows += asteroid_rows(r.json(), label)
                    time.sleep(GAP)
                seen, unique = set(), []
                for row in rows:  # a near-Earth asteroid can also match the main-belt query
                    if row[0] not in seen:
                        seen.add(row[0])
                        unique.append(row)
                _write("asteroids.json", {"fetched": now, "source": "JPL Small-Body Database", "rows": unique})
            if force or _age_days(_read("missions.json")) > KEEP_DAYS:
                kept = (_read("missions.json") or {}).get("rows", {})
                skipped = []
                for m in MISSIONS:
                    _step(f"Mission paths: {m['name']}")
                    stop = min(m["stop"], date.today().isoformat())  # where it has been, not where it is planned to go
                    try:
                        r = client.get(HORIZONS, params={
                            "format": "json", "COMMAND": f"'{m['id']}'", "EPHEM_TYPE": "VECTORS", "CENTER": "'500@10'",
                            "START_TIME": f"'{m['start']}'", "STOP_TIME": f"'{stop}'", "STEP_SIZE": "'15 d'",
                            "VEC_TABLE": "'1'", "OUT_UNITS": "'AU-D'", "REF_PLANE": "'ECLIPTIC'", "CSV_FORMAT": "'YES'",
                            "OBJ_DATA": "'NO'"})
                        r.raise_for_status()
                        kept[m["id"]] = horizons_rows(r.json())
                    except (httpx.HTTPError, ValueError) as exc:
                        skipped.append(f"{m['name']}: {exc}"[:200])
                    time.sleep(GAP)
                with _lock:
                    _job["skipped"] = skipped
                _write("missions.json", {"fetched": now, "source": "JPL Horizons", "rows": kept, "skipped": skipped})
            if s["space_values"] and (force or _age_days(_read("values.json")) > KEEP_DAYS):
                _step("Asteroid values (Asterank)")
                r = client.get(ASTERANK, params={"query": json.dumps({"price": {"$gt": 1}}), "limit": "1000"})
                r.raise_for_status()
                _write("values.json", {"fetched": now, "source": "Asterank", "rows": value_rows(r.json())})
        with _lock:
            _job.update(state="done", step="Ready", finished=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    except Exception as exc:  # noqa: BLE001 - shown on the page
        log.warning("space: %s", exc)
        with _lock:
            _job.update(state="failed", error=f"{_job.get('step', '')}: {exc}"[:300])
