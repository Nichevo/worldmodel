"""Grid now: the electricity system of four countries as it runs, read live only while the card
is open (Settings > Energy, "Grid now cards") and kept five minutes, never saved.

- New Zealand: Transpower's live data (em6 generation by fuel now, national demand every five
  minutes for the last day, HVDC transfer between the islands, renewable share). No key.
- Great Britain: Elexon's BMRS generation outturn by fuel (every five minutes, kept every half
  hour for the last two days; the interconnectors as imports) and the Carbon Intensity API. No key.
- United States (lower 48): EIA's hourly grid monitor, generation by fuel and demand (EIA_API_KEY).
- Australia (the NEM): Open Electricity, generation by fuel group every 30 minutes
  (OPENELECTRICITY_API_KEY, free).
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

KEEP = 300  # seconds an answer is kept
HOURS = 48
COUNTRIES = {
    "NZL": {"name": "New Zealand", "tz": "Pacific/Auckland", "source": "Transpower (em6 and system operator live data)"},
    "GBR": {"name": "Great Britain", "tz": "Europe/London", "source": "Elexon BMRS and National Energy System Operator Carbon Intensity API"},
    "USA": {"name": "United States (lower 48)", "tz": "America/New_York", "source": "EIA Hourly Electric Grid Monitor"},
    "AUS": {"name": "Australia (National Electricity Market)", "tz": "Australia/Sydney", "source": "Open Electricity"},
}
TRANSPOWER = "https://www.transpower.co.nz"
ELEXON = "https://data.elexon.co.uk/bmrs/api/v1/generation/outturn/summary"
CARBON = "https://api.carbonintensity.org.uk/intensity"
EIA = "https://api.eia.gov/v2/electricity/rto/{route}/data/"
OPEN_ELECTRICITY = "https://api.openelectricity.org.au/v4/data/network/NEM"

# Each source's fuel names, as the card's groups (the same colours as the energy flow chart's).
FUELS = {
    # Transpower em6
    "hydro": "Hydro", "geothermal": "Geothermal", "wind": "Wind", "solar": "Solar", "gas": "Natural gas", "coal": "Coal",
    "diesel/oil": "Oil", "co-gen": "Other", "battery": "Battery",
    # Elexon
    "ccgt": "Natural gas", "ocgt": "Natural gas", "nuclear": "Nuclear", "biomass": "Bioenergy", "npshyd": "Hydro",
    "ps": "Pumped storage", "oil": "Oil", "other": "Other",
    # EIA fuel codes
    "col": "Coal", "ng": "Natural gas", "nuc": "Nuclear", "wat": "Hydro", "sun": "Solar", "wnd": "Wind", "geo": "Geothermal",
    "bat": "Battery", "oth": "Other", "unk": "Other", "snb": "Battery", "wnb": "Wind",
    # Open Electricity fuel groups
    "bioenergy": "Bioenergy", "battery_discharging": "Battery", "pumps": "Pumped storage", "distillate": "Oil",
    "solar_utility": "Solar", "solar_rooftop": "Solar",
}
RENEWABLE = {"Hydro", "Geothermal", "Wind", "Solar", "Bioenergy"}
INTERCONNECTORS = {"INTFR": "France (IFA)", "INTIFA2": "France (IFA2)", "INTELEC": "France (ElecLink)", "INTNED": "Netherlands (BritNed)",
                   "INTNEM": "Belgium (Nemo)", "INTNSL": "Norway (North Sea Link)", "INTVKL": "Denmark (Viking)",
                   "INTIRL": "Northern Ireland (Moyle)", "INTEW": "Ireland (East-West)", "INTGRNL": "Ireland (Greenlink)"}

_lock = threading.Lock()
_kept: dict[str, tuple[float, dict]] = {}


def fuel(name: str) -> str:
    return FUELS.get(str(name).strip().lower(), str(name).strip().capitalize() or "Other")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stack(points: dict[str, dict[str, float]]) -> list[dict]:
    """{fuel: {time: MW}} as series, biggest first, each sorted by time."""
    out = [{"fuel": f, "points": sorted(v.items())} for f, v in points.items() if any(abs(x) > 0.5 for x in v.values())]
    out.sort(key=lambda s: -sum(v for _, v in s["points"]))
    return out


def _now_mix(series: list[dict]) -> list[dict]:
    last = max((p[0] for s in series for p in s["points"]), default=None)
    return [{"fuel": s["fuel"], "mw": dict(s["points"]).get(last, 0.0)} for s in series] if last else []


def _renewable(mix: list[dict]) -> float | None:
    total = sum(m["mw"] for m in mix if m["mw"] > 0 and m["fuel"] not in ("Battery", "Pumped storage", "Imports"))
    return round(100 * sum(m["mw"] for m in mix if m["fuel"] in RENEWABLE) / total, 1) if total else None


# ----------------------------------------------------------------------------- New Zealand
def _tp_time(t: dict, tz: ZoneInfo) -> str:
    """Transpower's {day, month (from 0), year, hour, minute} in New Zealand time, as UTC."""
    return _iso(datetime(int(t["year"]), int(t["month"]) + 1, int(t["day"]), int(t["hour"]), int(t["minute"]), tzinfo=tz))


def nz(client: httpx.Client) -> dict:
    tz = ZoneInfo(COUNTRIES["NZL"]["tz"])
    gen = client.get(f"{TRANSPOWER}/em6/data/current_generation").json()
    place = (gen.get("data") or {}).get("New Zealand") or {}
    mix = [{"fuel": fuel(k), "mw": float(v.get("generation") or 0), "capacity": v.get("capacity")}
           for k, v in place.items() if isinstance(v, dict)]
    merged: dict[str, dict] = {}
    for m in mix:  # Transpower's Co-Gen and the like can share a group
        g = merged.setdefault(m["fuel"], {"fuel": m["fuel"], "mw": 0.0, "capacity": 0.0})
        g["mw"] += m["mw"]
        g["capacity"] += float(m.get("capacity") or 0)
    mix = sorted(merged.values(), key=lambda m: -m["mw"])
    out: dict = {"mix": mix, "at": None, "lines": []}
    if gen.get("timestamp"):
        out["at"] = _iso(datetime.fromtimestamp(int(gen["timestamp"]), timezone.utc))
    try:
        load = client.get(f"{TRANSPOWER}/so/data/load_data_graph").json()
        pts = [(_tp_time(t, tz), float(v)) for t, v in (load.get("data") or {}).get("nzPoints") or []]
        out["lines"].append({"name": "Demand, whole country", "unit": "MW", "points": pts})
        out["demand_mw"] = pts[-1][1] if pts else None
    except Exception as exc:  # noqa: BLE001
        log.info("grid now NZ demand: %s", exc)
    try:
        hv = client.get(f"{TRANSPOWER}/em6/data/hvdc").json().get("data") or {}
        north = [(_tp_time(t, tz), float(v)) for t, v in hv.get("dcn_flow") or []]
        south = [(_tp_time(t, tz), float(v)) for t, v in hv.get("dcs_flow") or []]
        if north or south:
            flows = dict(north)
            for t, v in south:
                flows[t] = flows.get(t, 0.0) - v
            pts = sorted(flows.items())
            out["lines"].append({"name": "HVDC link, south to north (below 0: north to south)", "unit": "MW", "points": pts})
            out["links"] = [{"name": "HVDC link between the islands, south to north", "mw": pts[-1][1]}] if pts else []
    except Exception as exc:  # noqa: BLE001
        log.info("grid now NZ HVDC: %s", exc)
    try:
        share = client.get(f"{TRANSPOWER}/em6/data/renewables_generation").json().get("data") or []
        out["renewable_share"] = float(share[0]) if share else _renewable(mix)
    except Exception:  # noqa: BLE001
        out["renewable_share"] = _renewable(mix)
    out["note"] = "Generation by fuel is for the latest half hour; demand is every five minutes for the last day."
    return out


# ----------------------------------------------------------------------------- Great Britain
def gb(client: httpx.Client, now: datetime) -> dict:
    start = now - timedelta(hours=HOURS)
    body = client.get(ELEXON, params={"startTime": start.strftime("%Y-%m-%dT%H:%MZ"), "endTime": now.strftime("%Y-%m-%dT%H:%MZ")}).json()
    points: dict[str, dict[str, float]] = {}
    links: dict[str, float] = {}
    rows = body if isinstance(body, list) else body.get("data") or []
    last = None
    for r in rows:
        t = str(r.get("startTime") or "")
        if not t or t[14:16] not in ("00", "30"):  # every half hour of the five-minute figures
            continue
        t = t.replace("+00:00", "Z")
        for d in r.get("data") or []:
            code, v = str(d.get("fuelType") or ""), float(d.get("generation") or 0)
            g = "Imports" if code.startswith("INT") else fuel(code)
            p = points.setdefault(g, {})
            p[t] = p.get(t, 0.0) + v
            if code.startswith("INT") and (last is None or t >= last):
                if last != t:
                    links, last = {}, t
                links[INTERCONNECTORS.get(code, code)] = v
    series = _stack(points)
    mix = _now_mix(series)
    out = {"series": series, "mix": mix, "renewable_share": _renewable(mix),
           "demand_mw": round(sum(m["mw"] for m in mix), 0) if mix else None,
           "links": [{"name": k, "mw": v} for k, v in sorted(links.items(), key=lambda kv: -abs(kv[1]))],
           "at": last.replace(" ", "T") if last else None,
           "note": "Transmission-connected generation; rooftop and other small solar sit inside lower demand. "
                   "Interconnectors count as imports (below 0: exporting)."}
    try:
        ci = (client.get(CARBON).json().get("data") or [{}])[0].get("intensity") or {}
        out["carbon_g_kwh"] = ci.get("actual") or ci.get("forecast")
    except Exception as exc:  # noqa: BLE001
        log.info("grid now GB carbon: %s", exc)
    return out


# ----------------------------------------------------------------------------- United States
def _eia_time(p: str) -> str:
    return _iso(datetime.strptime(p[:13], "%Y-%m-%dT%H").replace(tzinfo=timezone.utc))


def us(client: httpx.Client, now: datetime) -> dict:
    key = os.environ.get("EIA_API_KEY")
    if not key:
        return {"error": "The US Grid now card needs your free EIA key: add EIA_API_KEY to .env (see Data status > Keys)."}
    start = (now - timedelta(hours=HOURS + 8)).strftime("%Y-%m-%dT%H")
    common = {"api_key": key, "frequency": "hourly", "data[0]": "value", "facets[respondent][]": "US48", "start": start,
              "sort[0][column]": "period", "sort[0][direction]": "asc", "length": 5000}
    body = client.get(EIA.format(route="fuel-type-data"), params=common).json()
    points: dict[str, dict[str, float]] = {}
    for r in (body.get("response") or {}).get("data") or []:
        v = r.get("value")
        if v is None or not r.get("period"):
            continue
        g = fuel(r.get("fueltype") or "")
        p = points.setdefault(g, {})
        t = _eia_time(str(r["period"]))
        p[t] = p.get(t, 0.0) + float(v)
    series = _stack(points)
    mix = _now_mix(series)
    out = {"series": series, "mix": mix, "renewable_share": _renewable(mix), "at": max((p[0] for s in series for p in s["points"]), default=None),
           "note": "Hourly, for the lower 48 states; the EIA's figures arrive an hour or two late."}
    try:
        d = client.get(EIA.format(route="region-data"), params={**common, "facets[type][]": "D"}).json()
        pts = sorted((_eia_time(str(r["period"])), float(r["value"])) for r in (d.get("response") or {}).get("data") or []
                     if r.get("value") is not None and r.get("period"))
        out["lines"] = [{"name": "Demand, lower 48 states", "unit": "MW", "points": pts}]
        out["demand_mw"] = pts[-1][1] if pts else None
    except Exception as exc:  # noqa: BLE001
        log.info("grid now US demand: %s", exc)
    return out


# ----------------------------------------------------------------------------- Australia
def au(client: httpx.Client, now: datetime) -> dict:
    key = os.environ.get("OPENELECTRICITY_API_KEY")
    if not key:
        return {"error": "The Australian Grid now card needs a free Open Electricity key: add OPENELECTRICITY_API_KEY "
                         "to .env (see Data status > Keys)."}
    start = (now - timedelta(hours=HOURS)).astimezone(ZoneInfo("Australia/Brisbane"))  # the NEM keeps Brisbane time
    body = client.get(OPEN_ELECTRICITY, headers={"Authorization": f"Bearer {key}"},
                      params={"metrics": "power", "interval": "30m", "date_start": start.strftime("%Y-%m-%dT%H:%M:%S"),
                              "secondary_grouping": "fueltech_group"}).json()
    points: dict[str, dict[str, float]] = {}
    for block in body.get("data") or []:
        for res in block.get("results") or []:
            name = (res.get("columns") or {}).get("fueltech_group") or re.sub(r"^power_", "", str(res.get("name") or ""))
            g = fuel(name)
            for t, v in res.get("data") or []:
                if v is None:
                    continue
                ts = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=ZoneInfo("Australia/Brisbane"))
                p = points.setdefault(g, {})
                p[_iso(ts)] = p.get(_iso(ts), 0.0) + float(v)
    series = _stack({g: v for g, v in points.items() if g not in ("Pumped storage",) or any(x > 0 for x in v.values())})
    mix = _now_mix(series)
    return {"series": series, "mix": mix, "renewable_share": _renewable(mix),
            "demand_mw": round(sum(m["mw"] for m in mix if m["mw"] > 0), 0) if mix else None,
            "at": max((p[0] for s in series for p in s["points"]), default=None),
            "note": "The National Electricity Market (Queensland to Tasmania), every 30 minutes; rooftop solar is estimated."}


def grid_now(country: str, on: bool = True, client: httpx.Client | None = None) -> dict:
    """The grid of one of the four countries now, kept five minutes."""
    if country not in COUNTRIES:
        return {"country": country, "error": "Grid now covers New Zealand, Australia, Great Britain and the US."}
    base = {"country": country, **COUNTRIES[country]}
    if not on:
        return {**base, "error": "Grid now cards are switched off in Settings > Energy."}
    with _lock:
        kept = _kept.get(country)
        if kept and time.time() - kept[0] < KEEP:
            return kept[1]
    own = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "worldmodel/0.1 (personal research tool)"})
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    try:
        got = {"NZL": lambda: nz(client), "GBR": lambda: gb(client, now), "USA": lambda: us(client, now),
               "AUS": lambda: au(client, now)}[country]()
    except Exception as exc:  # noqa: BLE001
        log.info("grid now %s: %s", country, exc)
        got = {"error": f"{COUNTRIES[country]['source']} did not answer just now ({type(exc).__name__}); try again in a few minutes."}
    finally:
        if own:
            client.close()
    out = {**base, "series": [], "mix": [], "lines": [], "links": [], **got, "read_at": _iso(now)}
    if "error" not in got:
        with _lock:
            _kept[country] = (time.time(), out)
    return out


# ----------------------------------------------------------------------------- power links (map layer)
# Capitals of the countries Eurostat lists as trading partners, for when the cities table is not loaded.
CAPITALS = {
    "ALB": (19.82, 41.33), "AND": (1.52, 42.51), "AUT": (16.37, 48.21), "BEL": (4.35, 50.85), "BGR": (23.32, 42.70),
    "BIH": (18.41, 43.86), "BLR": (27.56, 53.90), "CHE": (7.45, 46.95), "CYP": (33.38, 35.17), "CZE": (14.42, 50.09),
    "DEU": (13.40, 52.52), "DNK": (12.57, 55.68), "EST": (24.75, 59.44), "ESP": (-3.70, 40.42), "FIN": (24.94, 60.17),
    "FRA": (2.35, 48.86), "GBR": (-0.13, 51.51), "GEO": (44.79, 41.72), "GRC": (23.73, 37.98), "HRV": (15.98, 45.81),
    "HUN": (19.04, 47.50), "IRL": (-6.26, 53.35), "ISL": (-21.90, 64.15), "ITA": (12.50, 41.90), "LIE": (9.52, 47.14),
    "LTU": (25.28, 54.69), "LUX": (6.13, 49.61), "LVA": (24.11, 56.95), "MDA": (28.86, 47.01), "MKD": (21.43, 42.00),
    "MLT": (14.51, 35.90), "MNE": (19.26, 42.44), "MAR": (-6.84, 34.02), "NLD": (4.90, 52.37), "NOR": (10.75, 59.91),
    "POL": (21.01, 52.23), "PRT": (-9.14, 38.72), "ROU": (26.10, 44.43), "RUS": (37.62, 55.76), "SRB": (20.46, 44.79),
    "SVK": (17.11, 48.15), "SVN": (14.51, 46.06), "SWE": (18.07, 59.33), "TUR": (32.85, 39.93), "UKR": (30.52, 50.45),
    "XKX": (21.17, 42.66), "TUN": (10.18, 36.81), "DZA": (3.06, 36.75), "LBY": (13.19, 32.89), "EGY": (31.24, 30.04),
    "ISR": (35.21, 31.77), "JOR": (35.93, 31.95), "AZE": (49.87, 40.41), "ARM": (44.51, 40.18), "GIB": (-5.35, 36.14),
}

def power_links(q, year: int | None = None) -> dict:
    """Electricity traded between neighbouring countries in one year (Eurostat, by partner), as
    lines between their capitals drawn from the net exporter to the net importer. Each pair
    takes the larger of what one side says it sent and the other says it received."""
    base = """SELECT s.entity_id, substr(s.breakdown, 8) AS partner, s.indicator_id, year(s.period_start) AS y, s.value
        FROM series s WHERE s.indicator_id IN ('elec_imports_gwh', 'elec_exports_gwh') AND s.breakdown LIKE 'origin=%'
        AND s.variant = 'central'"""
    try:
        years = [r["y"] for r in q(f"SELECT DISTINCT y FROM ({base}) ORDER BY 1", [])]
    except Exception:  # noqa: BLE001 (an older warehouse without the table or figures)
        years = []
    if not years:
        return {"type": "FeatureCollection", "features": [], "years": []}
    year = year if year in years else years[-1]
    sent: dict[tuple[str, str], float] = {}
    for r in q(f"SELECT * FROM ({base}) WHERE y = ?", [year]):
        a, b = (r["partner"], r["entity_id"]) if r["indicator_id"] == "elec_imports_gwh" else (r["entity_id"], r["partner"])
        sent[(a, b)] = max(sent.get((a, b), 0.0), float(r["value"]))
    try:
        places = {r["entity_id"]: r for r in q("""SELECT e.entity_id, e.short_name AS name, c.lon, c.lat FROM entities e
            JOIN cities c ON c.country_id = e.entity_id AND c.capital = 'national'""", [])}
    except Exception:  # noqa: BLE001 (no cities table yet)
        places = {}
    names = {r["entity_id"]: r["name"] for r in q("SELECT entity_id, short_name AS name FROM entities", [])}
    for e, (lon, lat) in CAPITALS.items():
        if e not in places and e in names:
            places[e] = {"entity_id": e, "name": names[e], "lon": lon, "lat": lat}
    feats, done = [], set()
    for (a, b) in sent:
        pair = tuple(sorted((a, b)))
        if pair in done or a not in places or b not in places:
            continue
        done.add(pair)
        ab, ba = sent.get(pair, 0.0), sent.get(pair[::-1], 0.0)
        frm, to = (pair[0], pair[1]) if ab >= ba else (pair[1], pair[0])
        pa, pb = places[frm], places[to]
        feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[pa["lon"], pa["lat"]], [pb["lon"], pb["lat"]]]},
                      "properties": {"from": frm, "to": to, "from_name": pa["name"], "to_name": pb["name"], "year": year,
                                     "sent": round(max(ab, ba)), "back": round(min(ab, ba)), "net": round(abs(ab - ba)),
                                     "total": round(ab + ba)}})
    feats.sort(key=lambda f: -f["properties"]["total"])
    return {"type": "FeatureCollection", "features": feats, "years": years, "year": year}
