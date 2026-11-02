"""Places from Wikidata: metro and rail systems with their stations, universities, and
companies with their revenue and staff. Five queries, at most once a month.

    https://query.wikidata.org/sparql   (the Wikidata Query Service, Wikimedia's official API)

* transit: rapid transit (metro), light rail and commuter rail systems (classes found
  by their English name, as for the events), with country, city (P131), location
  (P625), length (P2043, in kilometres), official opening (P1619, else inception P571),
  yearly passengers (P3872, the latest dated figure) and English Wikipedia article;
* stations: every item whose transport network (P16) is one of those systems, with its
  location; counted per system and drawn as the "Metro and rail stations" map layer;
* universities: items that are a university (or a public, private, research or
  technical one) with a location and articles in three or more Wikipedias, with
  students (P2196, latest dated), founding year and article;
* companies: items with a revenue (P2139) in a currency, articles in five or more
  Wikipedias, a country (P17), staff (P1128), industry (P452) and head office (P159,
  with its location); the build turns revenue into US dollars with the World Bank's
  exchange rate for that currency and year;
* currencies: each country's currency code (P38 / ISO 4217 P498), to find the exchange
  rate for a currency.

A query that fails is logged and skipped, so one timing out leaves the others. What is
stored: places.parquet (one row per system, university or company) and the stations
map layer. Wikidata is CC0.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import duckdb
import httpx

from worldmodel_data.connectors.base import Connector, ConnectorError, sql_str
from worldmodel_data.connectors.wikidata import ENDPOINT, _day, _num, _qid, _val

log = logging.getLogger(__name__)

TRANSIT_TYPES = {"rapid transit": "metro", "light rail": "light rail", "commuter rail": "commuter rail"}
UNIVERSITY_TYPES = ("university", "public university", "private university", "research university", "technical university")
MIN_UNI_LINKS = 3
MIN_COMPANY_LINKS = 5


def _labels(names) -> str:
    return " ".join(f'"{n}"@en' for n in names)


ARTICLE = "OPTIONAL { ?article schema:about ?%s ; schema:isPartOf <https://en.wikipedia.org/> }"
QUERIES = {
    "transit": """
SELECT ?s ?sLabel ?kindName ?iso3 ?cityLabel ?coord ?length ?opened ?inception ?riders ?ridersAt ?article WHERE {
  VALUES ?kindName { %s }
  ?kind rdfs:label ?kindName .
  ?s wdt:P31 ?kind ; wdt:P17 ?c . ?c wdt:P298 ?iso3 .
  OPTIONAL { ?s wdt:P131 ?city }
  OPTIONAL { ?s wdt:P625 ?coord }
  OPTIONAL { ?s p:P2043/psn:P2043/wikibase:quantityAmount ?length }
  OPTIONAL { ?s wdt:P1619 ?opened }
  OPTIONAL { ?s wdt:P571 ?inception }
  OPTIONAL { ?s p:P3872 ?r . ?r ps:P3872 ?riders . OPTIONAL { ?r pq:P585 ?ridersAt } }
  %s
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}""" % (_labels(TRANSIT_TYPES), ARTICLE % "s"),
    "stations": """
SELECT ?st ?stLabel ?s ?coord WHERE {
  VALUES ?kindName { %s }
  ?kind rdfs:label ?kindName .
  ?s wdt:P31 ?kind .
  ?st wdt:P16 ?s .
  OPTIONAL { ?st wdt:P625 ?coord }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}""" % _labels(TRANSIT_TYPES),
    "universities": """
SELECT ?u ?uLabel ?kindName ?iso3 ?cityLabel ?coord ?students ?studentsAt ?founded ?links ?article WHERE {
  VALUES ?kindName { %s }
  ?kind rdfs:label ?kindName .
  ?u wdt:P31 ?kind ; wdt:P17 ?c ; wdt:P625 ?coord ; wikibase:sitelinks ?links .
  FILTER(?links >= %d)
  ?c wdt:P298 ?iso3 .
  OPTIONAL { ?u wdt:P131 ?city }
  OPTIONAL { ?u p:P2196 ?sx . ?sx ps:P2196 ?students . OPTIONAL { ?sx pq:P585 ?studentsAt } }
  OPTIONAL { ?u wdt:P571 ?founded }
  %s
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}""" % (_labels(UNIVERSITY_TYPES), MIN_UNI_LINKS, ARTICLE % "u"),
    "companies": """
SELECT ?co ?coLabel ?iso3 ?revenue ?currency ?revAt ?staff ?staffAt ?industryLabel ?hqLabel ?coord ?founded ?links ?article WHERE {
  ?co p:P2139 ?rs ; wikibase:sitelinks ?links .
  FILTER(?links >= %d)
  ?rs psv:P2139 ?rv . ?rv wikibase:quantityAmount ?revenue ; wikibase:quantityUnit ?unit .
  ?unit wdt:P498 ?currency .
  OPTIONAL { ?rs pq:P585 ?revAt }
  ?co wdt:P17 ?c . ?c wdt:P298 ?iso3 .
  OPTIONAL { ?co p:P1128 ?es . ?es ps:P1128 ?staff . OPTIONAL { ?es pq:P585 ?staffAt } }
  OPTIONAL { ?co wdt:P452 ?industry }
  OPTIONAL { ?co wdt:P159 ?hq . OPTIONAL { ?hq wdt:P625 ?coord } }
  OPTIONAL { ?co wdt:P571 ?founded }
  %s
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}""" % (MIN_COMPANY_LINKS, ARTICLE % "co"),
    "currencies": """
SELECT ?iso3 ?code WHERE {
  ?c wdt:P298 ?iso3 ; wdt:P38 ?cur . ?cur wdt:P498 ?code .
}""",
}


class WikidataPlaces(Connector):
    source_id = "wikidata_places"
    switch = "places_fetch"
    fetch_every_days = 28

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        got = 0
        for name, q in QUERIES.items():
            try:
                self.get(f"{ENDPOINT}?format=json&query={quote(q)}", raw_dir / f"places_{name}.json")
                got += 1
            except (ConnectorError, httpx.HTTPError) as exc:
                log.warning("wikidata_places: %s query skipped (%s)", name, exc)
        if not got:
            raise ConnectorError("wikidata_places: every query failed; the query service may be busy, try again later")
        return ENDPOINT

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        found = {name: _bindings(raw_dir / f"places_{name}.json") for name in QUERIES}
        stations = station_rows(found["stations"])
        rows = (transit_rows(found["transit"], stations) + university_rows(found["universities"])
                + company_rows(found["companies"], currency_countries(found["currencies"])))
        if not rows and not stations:
            raise ConnectorError(f"wikidata_places: nothing read from {raw_dir}")
        con.execute("CREATE TABLE wd_places (place_key VARCHAR, kind VARCHAR, subkind VARCHAR, name VARCHAR, country_id VARCHAR, "
                    "lat DOUBLE, lon DOUBLE, city_name VARCHAR, founded DATE, url VARCHAR, facts VARCHAR)")
        if rows:
            con.executemany("INSERT INTO wd_places VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        log.info("wikidata_places: %s places (%s), %s stations", len(rows),
                 ", ".join(f"{k} {sum(r[1] == k for r in rows)}" for k in ("transit", "university", "company")), len(stations))
        self.places_query = "SELECT * FROM wd_places"
        self.layers = []
        for kind, layer_id, title, about in (
                ("university", "universities", "Universities", "Universities with articles in three or more Wikipedias (Wikidata)."),
                ("company", "companies", "Big companies", "Head offices of companies with a stated revenue and articles in five or more Wikipedias (Wikidata).")):
            feats = []
            for r in rows:
                if r[1] != kind or r[5] is None:
                    continue
                f = json.loads(r[10])
                props = {"name": r[3], "id": r[0]}
                if kind == "university":
                    props |= {k: f[k] for k in ("students",) if k in f}
                else:
                    props |= {k: f[k] for k in ("revenue", "currency", "revenue_year", "industry") if k in f}
                feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(r[6], 4), round(r[5], 4)]},
                              "properties": props})
            if feats:
                self.layers.append({"layer_id": layer_id, "name": title, "description": about, "kind": "point",
                                    "feature_count": len(feats),
                                    "geojson": json.dumps({"type": "FeatureCollection", "features": feats},
                                                          separators=(",", ":"), ensure_ascii=False)})
        if stations:
            names = {r[0]: r[3] for r in rows if r[1] == "transit"}
            features = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 4), round(lat, 4)]},
                         "properties": {"name": name, "system": names.get(system, "")}}
                        for name, system, lat, lon in stations if lat is not None]
            self.layers.append({"layer_id": "transit_stations", "name": "Metro and rail stations",
                            "description": "Stations of metro, light rail and commuter rail systems (Wikidata).",
                            "kind": "point", "feature_count": len(features),
                            "geojson": json.dumps({"type": "FeatureCollection", "features": features},
                                                  separators=(",", ":"), ensure_ascii=False)})
        return (f"SELECT {sql_str(self.source_id)} AS source_id, {sql_str(vintage)} AS vintage, 'iso3' AS scheme, "
                "NULL AS source_code, NULL AS indicator_id, NULL AS period_start, 'A' AS freq, '' AS breakdown, "
                "'central' AS variant, NULL AS value, 'E' AS status WHERE false")


def _bindings(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))["results"]["bindings"]
    except (json.JSONDecodeError, KeyError):
        log.warning("wikidata_places: %s is not a query result; skipped", path.name)
        return []


def _point(v: str | None) -> tuple[float | None, float | None]:
    """(lat, lon) from a WKT "Point(lon lat)"."""
    if not v or not v.startswith("Point("):
        return None, None
    try:
        lon, lat = (float(x) for x in v[6:-1].split())
    except ValueError:
        return None, None
    return lat, lon


def _named(label: str | None, qid: str) -> str | None:
    """A label, unless Wikidata has no English one (it then gives the id)."""
    return None if not label or (label.startswith("Q") and label[1:].isdigit()) or label == qid else label


def _latest(bindings: list[dict], key: str, value: str, at: str) -> dict[str, tuple[float, int | None]]:
    """Per item, its latest dated figure (or an undated one if none is dated)."""
    out: dict[str, tuple[float, int | None]] = {}
    for b in bindings:
        q, v = _qid(_val(b, key)), _num(_val(b, value))
        if v is None:
            continue
        d, _ = _day(_val(b, at))
        y = d.year if d else None
        have = out.get(q)
        if have is None or (y or 0) > (have[1] or 0):
            out[q] = (v, y)
    return out


def _first(bindings: list[dict], key: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for b in bindings:
        out.setdefault(_qid(_val(b, key)), b)
    return out


def _year_date(v: str | None) -> date | None:
    d, _ = _day(v)
    return d


def station_rows(bindings: list[dict]) -> list[tuple]:
    """(station name, system id, lat, lon), one per station and system."""
    seen, out = set(), []
    for b in bindings:
        st, system = _qid(_val(b, "st")), _qid(_val(b, "s"))
        if (st, system) in seen:
            continue
        seen.add((st, system))
        lat, lon = _point(_val(b, "coord"))
        out.append((_named(_val(b, "stLabel"), st) or "", system, lat, lon))
    return out


def transit_rows(bindings: list[dict], stations: list[tuple]) -> list[tuple]:
    per_system = defaultdict(int)
    for _, system, _, _ in stations:
        per_system[system] += 1
    riders = _latest(bindings, "s", "riders", "ridersAt")
    out = []
    for q, b in _first(bindings, "s").items():
        name = _named(_val(b, "sLabel"), q)
        country = (_val(b, "iso3") or "").upper()
        if not name or not country:
            continue
        lat, lon = _point(_val(b, "coord"))
        length = _num(_val(b, "length"))  # normalised to metres
        r = riders.get(q)
        facts = {k: v for k, v in {
            "length_km": round(length / 1000, 1) if length else None, "stations": per_system.get(q) or None,
            "riders": r[0] if r else None, "riders_year": r[1] if r else None, "wikidata": q}.items() if v is not None}
        out.append((q, "transit", TRANSIT_TYPES.get(_val(b, "kindName") or "", "metro"), name, country, lat, lon,
                    _val(b, "cityLabel"), _year_date(_val(b, "opened") or _val(b, "inception")), _val(b, "article"),
                    json.dumps(facts)))
    return out


def university_rows(bindings: list[dict]) -> list[tuple]:
    students = _latest(bindings, "u", "students", "studentsAt")
    out = []
    for q, b in _first(bindings, "u").items():
        name = _named(_val(b, "uLabel"), q)
        country = (_val(b, "iso3") or "").upper()
        lat, lon = _point(_val(b, "coord"))
        if not name or not country or lat is None:
            continue
        s = students.get(q)
        kind = _val(b, "kindName") or "university"
        facts = {k: v for k, v in {
            "students": s[0] if s else None, "students_year": s[1] if s else None,
            "wikipedias": int(_num(_val(b, "links")) or 0), "wikidata": q}.items() if v is not None}
        out.append((q, "university", kind.replace(" university", "") if kind != "university" else None, name, country,
                    lat, lon, _val(b, "cityLabel"), _year_date(_val(b, "founded")), _val(b, "article"), json.dumps(facts)))
    return out


def currency_countries(bindings: list[dict]) -> dict[str, list[str]]:
    """Currency code -> countries using it, to find an exchange rate for it."""
    out: dict[str, list[str]] = defaultdict(list)
    for b in bindings:
        code, iso3 = _val(b, "code"), (_val(b, "iso3") or "").upper()
        if code and iso3 and iso3 not in out[code]:
            out[code].append(iso3)
    return out


def company_rows(bindings: list[dict], currencies: dict[str, list[str]]) -> list[tuple]:
    """A row per company: its latest dated revenue (with currency and year, and the country
    whose exchange rate converts it: its own if it uses that currency), staff, industries."""
    revenue: dict[str, tuple[float, str, int | None]] = {}
    industries: dict[str, list[str]] = defaultdict(list)
    for b in bindings:
        q, v, cur = _qid(_val(b, "co")), _num(_val(b, "revenue")), _val(b, "currency")
        d, _ = _day(_val(b, "revAt"))
        y = d.year if d else None
        if v and cur and (q not in revenue or (y or 0) > (revenue[q][2] or 0)):
            revenue[q] = (v, cur, y)
        ind = _val(b, "industryLabel")
        if ind and _named(ind, "") and ind not in industries[q]:
            industries[q].append(ind)
    staff = _latest(bindings, "co", "staff", "staffAt")
    out = []
    for q, b in _first(bindings, "co").items():
        name = _named(_val(b, "coLabel"), q)
        country = (_val(b, "iso3") or "").upper()
        if not name or not country or q not in revenue:
            continue
        v, cur, y = revenue[q]
        users = currencies.get(cur, [])
        rate_country = "USA" if cur == "USD" else country if country in users else (users[0] if users else None)
        lat, lon = _point(_val(b, "coord"))
        st = staff.get(q)
        facts = {k: v for k, v in {
            "revenue": v, "currency": cur, "revenue_year": y, "rate_country": rate_country,
            "staff": st[0] if st else None, "staff_year": st[1] if st else None,
            "industry": "; ".join(industries[q][:3]) or None, "wikipedias": int(_num(_val(b, "links")) or 0),
            "wikidata": q}.items() if v is not None}
        out.append((q, "company", None, name, country, lat, lon, _val(b, "hqLabel"), _year_date(_val(b, "founded")),
                    _val(b, "article"), json.dumps(facts)))
    return out
