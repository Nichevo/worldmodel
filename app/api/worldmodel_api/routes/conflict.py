"""OSINT detail and the world beyond borders (seas, airspace, sanctions)."""

from __future__ import annotations

from fastapi import HTTPException, Query

from worldmodel_api import osint, userdata
from worldmodel_api.core import api, rows, split
from worldmodel_api.routes.disease import events


# ----------------------------------------------------------------------------- OSINT detail
@api.get("/osint/events")
def osint_events(west: float = -180, south: float = -90, east: float = 180, north: float = 90,
                 days: int = Query(30, ge=1, le=3650), end: str | None = None, kinds: str | None = None,
                 sources: str | None = None, limit: int = Query(4000, ge=1, le=20000)):
    """Located fighting and unrest in a map window (UCDP and ACLED), the biggest first, as GeoJSON points.
    `days` back from `end` (a date; default the newest event held)."""
    return osint.map_events(rows, west, south, east, north, days=days, end=end, kinds=split(kinds) or None,
                            sources=split(sources) or None, limit=limit)


@api.get("/osint/country/{entity_id}")
def osint_country(entity_id: str, months: int = Query(24, ge=3, le=240)):
    """A country month by month: deaths in fighting (UCDP and ACLED, apart), protests and riots, internet outages,
    sanctions newly listed, and the CrisisWatch rating, with months where the rating and events disagree."""
    return osint.country_months(rows, entity_id, months)


@api.get("/osint/crisiswatch-month")
def osint_crisiswatch_month(month: str = Query(..., pattern=r"^\d{4}-\d{2}$")):
    """For the CrisisWatch map's month: each country's deaths, events, outages and new sanctions."""
    return osint.crisiswatch_month(rows, month)


@api.get("/osint/wars")
def osint_wars():
    """The wars followed (contract wars.yaml) with their latest loss totals and ground held."""
    return osint.wars(rows)


@api.get("/osint/wars/{war_id}")
def osint_war(war_id: str):
    """One war: losses by side, category and what happened, seen (Oryx) and claimed; ground held by day;
    aid by donor; deaths in fighting by month."""
    w = osint.war(rows, war_id)
    if w is None:
        raise HTTPException(404, f"no war {war_id}")
    return w


@api.get("/osint/front/{war_id}")
def osint_front(war_id: str, day: str | None = None):
    """The land held on a day (the nearest kept day on or before it), as GeoJSON, with the days kept."""
    return osint.front_line(rows, war_id, day)


@api.get("/osint/sanctions")
def osint_sanctions(schema: str | None = None):
    """Sanctions in force (OpenSanctions): listings by target country and sanctioning authority, and the newest."""
    return osint.sanctions(rows, schema)


@api.get("/osint/sanctions/search")
def osint_sanctions_search(q: str = Query(..., min_length=2, max_length=80)):
    return {"items": osint.sanctions_search(rows, q)}


@api.get("/osint/military")
def osint_military(entities: str = "NZL,AUS,GBR,USA"):
    """Global Firepower's counts for the countries asked for, with ranks, the change since the edition before,
    and a second source where the app has one."""
    return osint.military(rows, split(entities)[:12])


@api.get("/osint/military/map")
def osint_military_map(measure: str = "gfp_personnel_active"):
    return osint.military_map(rows, measure)


@api.get("/osint/arms/{entity_id}")
def osint_arms(entity_id: str, since: int = Query(2000, ge=1950, le=2100)):
    """Who a country buys major weapons from and sells them to (SIPRI trade register)."""
    return osint.arms(rows, entity_id, since)


@api.get("/layers")
def layers():
    """The map overlays the warehouse holds (plate boundaries, faults, volcanoes, earthquakes), without their features."""
    return rows("""SELECT l.layer_id, l.name, l.description, l.kind, l.feature_count, l.source_id, s.short_name AS source_name
        FROM layers l LEFT JOIN sources s USING (source_id) ORDER BY l.layer_id""")


# ----------------------------------------------------------------------------- the world beyond borders
CW_SCORE = {"deteriorated": -2, "risk_alert": -1, "unchanged": 0, "improved": 1, "resolution_opportunity": 2}


@api.get("/entities/{entity_id}/voting")
def voting(entity_id: str,
           compare: str | None = Query(None, description="Partners, comma-separated; 'eu' is the average over the "
                                                         "EU's members of the year. Default: Settings voting_compare")):
    """How often a country voted with others in the UN General Assembly (percent, by year), its voting
    position (ideal point), and its Security Council seats and vetoes."""
    partners = [p for p in (split(compare) or split(userdata.settings().get("voting_compare") or "USA,CHN,RUS,eu"))
                if p != entity_id][:8]
    names = {r["entity_id"]: r["short_name"] for r in rows(
        "SELECT entity_id, short_name FROM entities WHERE entity_id IN (SELECT unnest(?))", [partners + [entity_id]])}
    lines = []
    for p in partners:
        if p in ("eu", "nato", "oecd", "g7", "g20", "asean", "au") or p.islower():
            # a group: the average of the agreement with its members of each year
            data = rows("""SELECT year(s.period_start) AS year, round(avg(s.value), 2) AS value, count(*) AS n
                FROM series s JOIN memberships m ON m.member_id = s.breakdown AND m.group_id = ?
                  AND (m.valid_from IS NULL OR m.valid_from <= s.period_start)
                  AND (m.valid_to IS NULL OR m.valid_to >= s.period_start)
                WHERE s.indicator_id = 'unga_agreement' AND s.entity_id = ? AND s.variant = 'central' AND s.breakdown <> ?
                GROUP BY 1 ORDER BY 1""", [p, entity_id, entity_id])
            label = f"{names.get(p, p)} members (average)"
        else:
            data = rows("""SELECT year(period_start) AS year, value FROM series WHERE indicator_id = 'unga_agreement'
                AND entity_id = ? AND breakdown = ? AND variant = 'central' ORDER BY 1""", [entity_id, p])
            label = names.get(p, p)
        lines.append({"id": p, "name": label, "points": [[r["year"], r["value"]] for r in data]})
    ideal = rows("""SELECT year(period_start) AS year, value FROM series WHERE indicator_id = 'unga_ideal_point'
        AND entity_id = ? AND breakdown = '' AND variant = 'central' ORDER BY 1""", [entity_id])
    closest = rows("""SELECT s.breakdown AS entity_id, coalesce(e.short_name, s.breakdown) AS name, s.value
        FROM series s LEFT JOIN entities e ON e.entity_id = s.breakdown
        WHERE s.indicator_id = 'unga_agreement' AND s.entity_id = ? AND s.variant = 'central'
          AND s.period_start = (SELECT max(period_start) FROM series WHERE indicator_id = 'unga_agreement' AND entity_id = ?)
        ORDER BY s.value DESC""", [entity_id, entity_id])
    council = events(entities=entity_id, members=False, kinds="un", sources=None, start=None, end=None, min_size=None,
                     q=None, limit=2000)
    return {"entity": entity_id, "name": names.get(entity_id, entity_id), "lines": lines,
            "ideal": [[r["year"], r["value"]] for r in ideal],
            "closest": closest[:8], "furthest": closest[-8:][::-1] if len(closest) > 8 else [],
            "closest_year": rows("""SELECT max(year(period_start)) AS y FROM series WHERE indicator_id = 'unga_agreement'
                AND entity_id = ?""", [entity_id])[0]["y"],
            "council": council}


@api.get("/crisiswatch")
def crisiswatch(month: str | None = Query(None, description="YYYY-MM; default the latest month stored")):
    """CrisisWatch ratings for one month, for a map: each country's rating as a score
    (-2 deteriorated, -1 conflict risk alert, 0 unchanged, 1 improved, 2 resolution opportunity)."""
    months = [r["m"] for r in rows("""SELECT DISTINCT strftime(start_date, '%Y-%m') AS m FROM events
        WHERE kind = 'crisiswatch' ORDER BY 1""")]
    if not months:
        return {"months": [], "month": None, "rows": []}
    if month not in months:
        month = max((m for m in months if m <= (month or months[-1])), default=months[-1])
    data = rows("""SELECT e.entity_id, coalesce(n.short_name, e.entity_id) AS name, e.subkind, e.title, e.detail, e.place, e.url
        FROM events e LEFT JOIN entities n USING (entity_id)
        WHERE e.kind = 'crisiswatch' AND strftime(e.start_date, '%Y-%m') = ? ORDER BY e.subkind, name""", [month])
    for r in data:
        r["score"] = CW_SCORE.get(r["subkind"] or "", 0)
    return {"months": months, "month": month, "rows": data}


ZONES = {
    "ATA": {"indicators": ["sea_ice_extent_min", "sea_ice_extent_max", "sea_ice_extent_mean", "sea_ice_extent"],
            "layers": ["antarctic_claims", "antarctic_stations"], "treaties": []},
    "arctic": {"indicators": ["sea_ice_extent_min", "sea_ice_extent_max", "sea_ice_extent_mean", "sea_ice_extent"],
               "layers": [], "treaties": []},
    "space": {"indicators": ["objects_in_orbit_payload", "objects_in_orbit_rocket_body", "objects_in_orbit_debris"],
              "layers": [], "treaties": [], "by_country": ["sats_in_orbit", "sats_launched", "space_launches", "debris_in_orbit"]},
    "high_seas": {"indicators": [], "layers": [], "treaties": ["unclos", "bbnj"]},
}


@api.get("/zones")
def zones():
    """Places beyond any one country: Antarctica, the Arctic, space and the high seas, with what is
    stored for each (indicators, map layers, the treaties that govern them)."""
    have_inds = {r["indicator_id"] for r in rows("SELECT DISTINCT indicator_id FROM series WHERE indicator_id IN (SELECT unnest(?))",
                                                 [[i for z in ZONES.values() for i in z["indicators"] + z.get("by_country", [])]])}
    have_layers = {r["layer_id"] for r in rows("SELECT layer_id FROM layers")}
    ents = {r["entity_id"]: r for r in rows("SELECT entity_id, short_name, name, description FROM entities WHERE entity_id IN (SELECT unnest(?))",
                                             [list(ZONES)])}
    out = []
    for zid, z in ZONES.items():
        e = ents.get(zid, {"entity_id": zid, "short_name": zid, "name": zid, "description": None})
        treaties = []
        for t in z["treaties"]:
            n = rows("""SELECT count(DISTINCT entity_id) FILTER (WHERE title LIKE 'Joined%') AS joined,
                count(DISTINCT entity_id) FILTER (WHERE title LIKE 'Signed%') AS signed_only, min(title) AS title
                FROM events WHERE kind = 'treaty' AND subkind = ?""", [t])[0]
            treaties.append({"treaty": t, **n})
        out.append({**e, "indicators": [i for i in z["indicators"] if i in have_inds],
                    "by_country": [i for i in z.get("by_country", []) if i in have_inds],
                    "layers": [l for l in z["layers"] if l in have_layers], "treaties": treaties})
    return out


@api.get("/beyond/others")
def beyond_others():
    """International organisations (the UN, Comecon, the Arab League, and the blocs and alliances
    such as the EU and NATO) and armed groups (Al-Qaeda, ISIL), with how many sanctions are on
    each and the most each imposed in one year."""
    return rows("""
        SELECT e.entity_id, e.short_name, e.name, e.type, e.description, e.valid_from, e.valid_to,
               (SELECT count(*) FROM events v WHERE v.entity_id = e.entity_id AND v.kind = 'sanction') AS sanctions_on,
               (SELECT min(year(v.start_date)) FROM events v WHERE v.entity_id = e.entity_id) AS first_year,
               (SELECT max(s.value) FROM series s WHERE s.entity_id = e.entity_id AND s.indicator_id = 'sanctions_imposed'
                  AND s.status = 'E') AS most_imposed,
               (SELECT count(*) FROM events v WHERE v.entity_id = e.entity_id) AS events
        FROM entities e WHERE e.type IN ('organisation', 'bloc', 'alliance', 'armed_group')
        ORDER BY e.type = 'armed_group', sanctions_on DESC, most_imposed DESC NULLS LAST, e.short_name""")
