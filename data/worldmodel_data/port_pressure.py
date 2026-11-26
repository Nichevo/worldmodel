"""Port pressure: ports and chokepoints each week against normal, and what events did to them.

Made by the build from port_daily, chokepoint_traffic, port_disruptions and events (see
network_tables.py, which loads the first three):

* traffic_weekly: ship calls (ports) or transits (chokepoints) each full week, Monday to
  Sunday, with tonnes for ports and what is normal for that week. Normal is the same week
  (with the weeks either side) of up to three years before, scaled by how busy the place was
  in the eight weeks before against those same weeks; before there is a year to compare
  with, it is the average of the eight weeks before.
* traffic_impacts: for each event that reached a port or chokepoint, the ships against
  what was expected from the eight weeks before it (the normal of each week, scaled once at
  the start, so a long disruption does not become its own normal): the worst week, calls
  and tonnes lost until recovered, days to recover (two weeks back within 10%), the
  busiest week after, and the curve of weeks -4 to +16. Events are PortWatch's disruptions
  with the ports they reached, and the app's own disasters, epidemics, conflicts and
  shipping blockages matched to the country's three busiest ports (or to a chokepoint by
  name).

Everything is a description of the data, not proof that the event caused the change.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import tempfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np

from worldmodel_data.stepcache import OFF, StepCache, key, rows_hash

log = logging.getLogger(__name__)

WEEKLY_DDL = """CREATE TABLE traffic_weekly (place_kind VARCHAR, place_id VARCHAR, entity_id VARCHAR, week DATE,
    value DOUBLE, tonnes DOUBLE, normal DOUBLE, ratio DOUBLE)"""
IMPACTS_DDL = """CREATE TABLE traffic_impacts (impact_id VARCHAR, event_key VARCHAR, origin VARCHAR, title VARCHAR,
    hazard VARCHAR, entity_id VARCHAR, start_date DATE, end_date DATE, place_kind VARCHAR, place_id VARCHAR,
    place_name VARCHAR, base_weekly DOUBLE, worst_pct DOUBLE, worst_week DATE, lost_calls DOUBLE, lost_tonnes DOUBLE,
    recover_days INTEGER, catchup_pct DOUBLE, clear BOOLEAN, curve VARCHAR)"""

PRE = 8            # weeks before an event that set its expected level
BEFORE, AFTER = 4, 16  # the curve kept for each impact, in weeks around the start
RECOVER_WITHIN = 26
BACK = 0.9         # within 10% of expected counts as back to normal
MIN_WEEKLY = 20.0  # ports and chokepoints with fewer ships a week are too noisy to call
CLEAR_FALL = -20.0
EVENT_KINDS = ("disaster", "epidemic", "conflict", "infrastructure", "pollution", "coup", "outage")
PORTS_PER_COUNTRY = 3


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def normal_series(v: np.ndarray) -> np.ndarray:
    """What is normal for each week of a weekly series (NaN where it cannot be told)."""
    n = len(v)
    season = np.full(n, np.nan)
    for i in range(n):
        got = []
        for k in (1, 2, 3):
            j = i - 52 * k
            if j - 1 >= 0 and j + 1 < n:
                got.append(v[j - 1:j + 2].mean())
        if got:
            season[i] = float(np.mean(got))
    out = np.full(n, np.nan)
    for i in range(PRE, n):
        prev, sprev = v[i - PRE:i], season[i - PRE:i]
        ok = ~np.isnan(sprev)
        if not np.isnan(season[i]) and ok.sum() >= 6 and sprev[ok].sum() > 0:
            level = float(np.clip(prev[ok].sum() / sprev[ok].sum(), 0.5, 2.0))
            out[i] = season[i] * level
        else:
            out[i] = prev.mean()
    return out


def expected_from(v: np.ndarray, s: int) -> np.ndarray | None:
    """Expected ships for every week from s on, with the level frozen at the eight weeks
    before s: the seasonal shape of the years before where there is one, else flat."""
    if s < PRE:
        return None
    prev = v[s - PRE:s]
    if prev.mean() <= 0:
        return None
    n = len(v)
    season = np.full(n, np.nan)
    for i in range(s - PRE, n):
        got = [v[i - 52 * k - 1:i - 52 * k + 2].mean() for k in (1, 2, 3) if i - 52 * k - 1 >= 0]
        if got:
            season[i] = float(np.mean(got))
    sp = season[s - PRE:s]
    if not np.isnan(sp).any() and sp.sum() > 0 and not np.isnan(season[s:]).any():
        level = float(np.clip(prev.sum() / sp.sum(), 0.5, 2.0))
        return np.concatenate([np.full(s, np.nan), season[s:] * level])
    return np.concatenate([np.full(s, np.nan), np.full(n - s, prev.mean())])


def impact(v: np.ndarray, t: np.ndarray | None, s: int, e: int) -> dict | None:
    """What happened from week s (the event's first week) to the event's last week e and
    after. None when there is too little before or after to tell."""
    n = len(v)
    if s < PRE or s + 2 >= n:
        return None
    exp = expected_from(v, s)
    if exp is None:
        return None
    base = float(v[s - PRE:s].mean())
    r = np.where(exp > 0, v / np.where(exp > 0, exp, 1), np.nan)
    last_look = min(max(e, s) + 4, n - 1)
    seg = r[s:last_look + 1]
    if np.isnan(seg).all():
        return None  # nothing expected in those weeks (a seasonal port in its off season): nothing to compare
    w = int(np.nanargmin(seg)) + s
    worst = float(r[w])
    rec = None
    for i in range(w, min(s + RECOVER_WITHIN, n - 1)):
        if r[i] >= BACK and r[i + 1] >= BACK:
            rec = i
            break
    stop = rec if rec is not None else min(s + RECOVER_WITHIN, n)
    lost = float(np.nansum(exp[s:stop] - v[s:stop]))
    lost_t = None
    if t is not None:
        tp = t[s - PRE:s].sum() / max(v[s - PRE:s].sum(), 1e-9)  # tonnes a call before
        lost_t = float(np.nansum(exp[s:stop] * tp - t[s:stop]))
    catch = None
    if rec is not None:
        after = r[rec:min(rec + 9, n)]
        if len(after):
            catch = round(100 * (float(np.nanmax(after)) - 1), 1)
    curve = [None if (i < 0 or i >= n or np.isnan(r[i])) else round(float(r[i]), 3)
             for i in range(s - BEFORE, s + AFTER + 1)]
    return {"base": base, "worst_pct": round(100 * (worst - 1), 1), "worst_i": w, "lost": round(lost, 1),
            "lost_t": None if lost_t is None else round(lost_t), "rec": rec, "catchup": catch, "curve": curve}


def shore_key(name: str) -> str:
    words = re.findall(r"[a-z]+", str(name or "").lower().replace("ø", "o"))
    return " ".join(w for w in words if w not in {"strait", "straits", "of", "the", "canal", "channel", "passage", "el"})


def _has(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ? AND table_schema = 'main'",
                            [table]).fetchone()[0])


def _insert(con: duckdb.DuckDBPyConnection, table: str, rows: list[tuple]) -> None:
    """Many rows through a temporary CSV (much faster than executemany)."""
    if not rows:
        return
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "rows.csv"
        with p.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            for r in rows:
                w.writerow(["" if x is None else x for x in r])
        cols = [c[0] for c in con.execute(f"DESCRIBE {table}").fetchall()]
        types = {c[0]: c[1] for c in con.execute(f"DESCRIBE {table}").fetchall()}
        con.execute(f"INSERT INTO {table} SELECT * FROM read_csv(?, header = false, columns = ?, nullstr = '', "
                    "quote = '\"', escape = '\"')", [p.as_posix(), {c: types[c] for c in cols}])


def _series(con, sql: str, last_week: date) -> dict[str, dict]:
    """Weekly series by place: {id: {entity, weeks (list of dates), v, t}} with missing weeks as 0."""
    raw: dict[str, dict] = {}
    for pid, ent, w, val, ton in con.execute(sql).fetchall():
        if w > last_week:
            continue
        s = raw.setdefault(pid, {"entity": ent, "vals": {}, "tons": {}})
        s["vals"][w] = float(val or 0)
        if ton is not None:
            s["tons"][w] = float(ton)
    out = {}
    for pid, s in raw.items():
        first = min(s["vals"])
        weeks = []
        w = first
        while w <= last_week:
            weeks.append(w)
            w += timedelta(days=7)
        out[pid] = {"entity": s["entity"], "weeks": weeks,
                    "v": np.array([s["vals"].get(x, 0.0) for x in weeks]),
                    "t": np.array([s["tons"].get(x, 0.0) for x in weeks]) if s["tons"] else None}
    return out


PORT_WEEKS = """SELECT port_id, any_value(entity_id), date_trunc('week', day)::DATE, sum(calls),
                       sum(coalesce(import_t, 0) + coalesce(export_t, 0))
                FROM port_daily GROUP BY 1, 3"""
CHOKE_WEEKS = """SELECT chokepoint_id, NULL, date_trunc('week', day)::DATE, sum(transits), NULL
                 FROM chokepoint_traffic GROUP BY 1, 3"""
EVENTS_SQL = f"""SELECT event_id, title, kind, subkind, entity_id, start_date, end_date, place FROM events
                 WHERE start_date >= DATE '2019-03-01' AND kind IN ({', '.join(repr(k) for k in EVENT_KINDS)})
                   AND coalesce(precision, 'day') IN ('day', 'month') AND source_id <> 'portwatch'"""
DISRUPTIONS_SQL = ("SELECT event_id, port_id, name, hazard, entity_id, start_date, end_date FROM port_disruptions "
                   "WHERE port_id <> '' AND start_date IS NOT NULL")
NAMES_SQL = "SELECT layer_id, geojson FROM layers WHERE layer_id IN ('ports', 'chokepoints')"


def _weeks_last(con, table: str) -> date | None:
    last = con.execute(f"SELECT max(day) FROM {table}").fetchone()[0] if _has(con, table) else None
    return (monday(last) - timedelta(days=7 if last.weekday() < 6 else 0)) if last else None


def compute(con: duckdb.DuckDBPyConnection, cache: StepCache = OFF) -> dict[str, int]:
    """Create traffic_weekly and traffic_impacts (empty when there is no traffic). Row counts.

    Saved in two parts: the weeks (redone only when port or chokepoint traffic changed) and
    the impacts (redone when the weeks, the events or the disruptions changed)."""
    con.execute(WEEKLY_DDL)
    con.execute(IMPACTS_DDL)
    last_p, last_c = _weeks_last(con, "port_daily"), _weeks_last(con, "chokepoint_traffic")
    k_weeks = key("port_pressure_weeks", last_p, last_c,
                  rows_hash(con, PORT_WEEKS) if last_p else None, rows_hash(con, CHOKE_WEEKS) if last_c else None)
    k_impacts = key("port_pressure_impacts", k_weeks,
                    rows_hash(con, EVENTS_SQL) if _has(con, "events") else None,
                    rows_hash(con, DISRUPTIONS_SQL) if _has(con, "port_disruptions") else None,
                    rows_hash(con, NAMES_SQL), rows_hash(con, "SELECT chokepoint_id, name FROM chokepoint_traffic")
                    if last_c else None)
    have_weeks = cache.load(con, "port_pressure_weeks", k_weeks, {"weekly": "traffic_weekly"})
    if have_weeks and cache.load(con, "port_pressure_impacts", k_impacts, {"impacts": "traffic_impacts"}):
        out = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("traffic_weekly", "traffic_impacts")}
        log.info("port pressure: traffic and events unchanged since the last build; reused %s impacts", out["traffic_impacts"])
        return out
    places: dict[tuple[str, str], dict] = {}
    if last_p:
        for pid, s in _series(con, PORT_WEEKS, last_p).items():
            places[("port", pid)] = s
    if last_c:
        for cid, s in _series(con, CHOKE_WEEKS, last_c).items():
            s["t"] = None
            places[("chokepoint", cid)] = s
    if not places:
        return {"traffic_weekly": 0, "traffic_impacts": 0}
    if have_weeks:
        n_weeks = con.execute("SELECT count(*) FROM traffic_weekly").fetchone()[0]
        log.info("port pressure: traffic unchanged since the last build; reused its weeks, working out event impacts again")
    else:
        rows = []
        for (kind, pid), s in places.items():
            norm = normal_series(s["v"])
            for i, w in enumerate(s["weeks"]):
                nv = None if np.isnan(norm[i]) else round(float(norm[i]), 2)
                ratio = round(float(s["v"][i] / norm[i]), 4) if nv else None
                rows.append((kind, pid, s["entity"], w.isoformat(), s["v"][i],
                             None if s["t"] is None else round(float(s["t"][i])), nv, ratio))
        _insert(con, "traffic_weekly", rows)
        n_weeks = len(rows)
        cache.save(con, "port_pressure_weeks", k_weeks, {"weekly": "SELECT * FROM traffic_weekly"})
    impacts = _impacts(con, places)
    _insert(con, "traffic_impacts", impacts)
    cache.save(con, "port_pressure_impacts", k_impacts, {"impacts": "SELECT * FROM traffic_impacts"})
    cache.note_worked("port_pressure")
    return {"traffic_weekly": n_weeks, "traffic_impacts": len(impacts)}


def _names(con) -> tuple[dict[str, str], dict[str, str]]:
    ports, chokes = {}, {}
    try:
        got = con.execute(NAMES_SQL).fetchall()
    except duckdb.Error:
        got = []
    for layer, gj in got:
        for f in json.loads(gj).get("features") or []:
            p = f.get("properties") or {}
            (ports if layer == "ports" else chokes)[p.get("id")] = p.get("name")
    if _has(con, "chokepoint_traffic"):
        for cid, name in con.execute("SELECT chokepoint_id, any_value(name) FROM chokepoint_traffic GROUP BY 1").fetchall():
            chokes.setdefault(cid, name)
    return ports, chokes


def _impacts(con, places: dict) -> list[tuple]:
    port_names, choke_names = _names(con)
    choke_by_key = {shore_key(n): cid for cid, n in choke_names.items() if n}
    # Each country's busiest ports in the year before a date are worked out once per country and year.
    yearly: dict[tuple[str, int], list[tuple[float, str]]] = defaultdict(list)  # (country, year) -> (calls a week, port)
    for (kind, pid), s in places.items():
        if kind == "port" and s["entity"]:
            sums: dict[int, list[float]] = defaultdict(list)
            for w, v in zip(s["weeks"], s["v"]):
                sums[w.year].append(v)
            for y, vals in sums.items():
                yearly[(s["entity"], y)].append((float(np.mean(vals)), pid))
    first_year = min((y for _, y in yearly), default=2019)

    def busiest(ent: str, d: date) -> list[str]:
        """The country's busiest ports in the year before (or the first year there is)."""
        scored = yearly.get((ent, max(d.year - 1, first_year))) or []
        return [p for m, p in sorted(scored, reverse=True) if m >= MIN_WEEKLY][:PORTS_PER_COUNTRY]

    jobs: list[tuple] = []  # (event_key, origin, title, hazard, entity, start, end, kind, place)
    if _has(con, "port_disruptions"):
        for eid, pid, name, hazard, ent, start, end in con.execute(DISRUPTIONS_SQL).fetchall():
            jobs.append((f"portwatch:{eid}", "portwatch", name, hazard, ent, start, end or start, "port", pid))
    if _has(con, "events"):
        got = con.execute(EVENTS_SQL).fetchall()
        seen = set()
        for eid, title, kind, sub, ent, start, end, place in got:
            hazard = (sub or kind).replace("_", " ")
            ck = choke_by_key.get(shore_key(place)) if place else None
            if ck is None and kind == "infrastructure" and title:
                ck = next((cid for k, cid in choke_by_key.items() if k and k in shore_key(title)), None)
            if ck:
                key = (title, start, "chokepoint", ck)
                if key not in seen:
                    seen.add(key)
                    jobs.append((f"event:{eid}", "events", title, hazard, ent, start, end or start, "chokepoint", ck))
                continue
            if not ent:
                continue
            for pid in busiest(ent, start):
                key = (title, start, "port", pid)
                if key not in seen:
                    seen.add(key)
                    jobs.append((f"event:{eid}", "events", title, hazard, ent, start, end or start, "port", pid))
    out = []
    for event_key, origin, title, hazard, ent, start, end, kind, pid in jobs:
        s = places.get((kind, pid))
        if not s or start < s["weeks"][0] + timedelta(days=7 * PRE):
            continue
        idx = {w: i for i, w in enumerate(s["weeks"])}
        si = idx.get(monday(start))
        if si is None:
            continue
        ei = idx.get(monday(min(end, s["weeks"][-1])), si)
        got = impact(s["v"], s["t"], si, min(ei, si + 12))
        if not got:
            continue
        rec_days = None if got["rec"] is None else (got["rec"] - si) * 7
        clear = got["base"] >= MIN_WEEKLY and got["worst_pct"] <= CLEAR_FALL
        name = (port_names if kind == "port" else choke_names).get(pid) or pid
        out.append((f"{event_key}|{kind}:{pid}", event_key, origin, title, hazard, ent, start.isoformat(),
                    max(end, start).isoformat(), kind, pid, name, round(got["base"], 1), got["worst_pct"],
                    s["weeks"][got["worst_i"]].isoformat(), got["lost"], got["lost_t"], rec_days, got["catchup"], clear,
                    json.dumps(got["curve"], separators=(",", ":"))))
    log.info("port pressure: %s impacts from %s events and places", len(out), len(jobs))
    return out
