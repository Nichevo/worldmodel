"""Wikidata: a facts box for every country, from one query a month.

    https://query.wikidata.org/sparql   (the Wikidata Query Service, Wikimedia's official API)

One SPARQL query fetches, for every item with an ISO 3166-1 alpha-3 code (P298),
the properties in FACTS below (capital, head of state and government, currency,
languages, calling code and so on), the English Wikipedia article, and the
Commons file names of its flag, coat of arms, locator map and main picture. Where
several items share a code (the Netherlands and the Kingdom of the Netherlands),
the one with the most Wikipedia editions is kept.

What is stored: text (texts.parquet beside the vintage; section "Facts",
field_key the property id, values joined with "; "). The app shows it as a facts
box on country pages and uses the article name to fetch the Wikipedia introduction.

Four more queries fetch dated events for the milestones (events.parquet):

* elections: national presidential, general, legislative and parliamentary
  elections and referendums since 1945, past and scheduled (date P585);
* leaders: heads of state (P35) and government (P6), and everyone who held the
  country's head-of-state (P1906) or head-of-government (P1313) office (P39), with their start and end
  dates, as periods, and the party (P102) each belonged to when the term began
  with the party's colour (P465), for charts coloured by governing party;
* sport: editions of the major championships in SPORT_COMPETITIONS, with host
  country (P17, or the country of the venue P276) and start and end dates;
  an event with several hosts has a row for each;
* disasters: earthquakes, cyclones, floods, wildfires, eruptions, heat waves,
  droughts, epidemics and the like (classes in DISASTER_TYPES and their direct
  subclasses), with deaths (P1120) and damage in US dollars (P2630).

Classes are found by their English name, so a renamed class drops out quietly
rather than breaking the fetch. An event query that fails (the query service
times out, say) is logged and skipped; the facts still load. The founding date
in the facts (P571) also becomes an "independence" event. Wikidata stores a
year-only date as 1 January; such dates are marked precision "year".

Wikidata is CC0. The queries run at most once every FETCH_EVERY_DAYS days (a
refresh skips them in between); `worldmodel-data fetch wikidata` runs them at once.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, unquote

import duckdb
import httpx

from worldmodel_data.connectors import leaders_curated
from worldmodel_data.connectors.base import Connector, ConnectorError, sql_str
from worldmodel_data.connectors.layers import collection

log = logging.getLogger(__name__)

ENDPOINT = "https://query.wikidata.org/sparql"
FILE = "wikidata.json"
FETCH_EVERY_DAYS = 28

# (property, label shown), in the order shown.
FACTS = (
    ("P1448", "Official name"), ("P36", "Capital"), ("P35", "Head of state"), ("P6", "Head of government"),
    ("P122", "Form of government"), ("P194", "Legislature"), ("P37", "Official languages"), ("P38", "Currency"),
    ("P1549", "Demonym"), ("P571", "Founded"), ("P463", "Member of"), ("P85", "Anthem"), ("P610", "Highest point"),
    ("P474", "Calling code"), ("P78", "Internet domain"), ("P1622", "Drives on the"), ("P421", "Time zones"),
    ("P856", "Official website"),
)
IMAGES = (("P41", "Flag"), ("P94", "Coat of arms"), ("P242", "Locator map"), ("P18", "Picture"))
MULTI_LIMIT = 12  # values kept for one property (Member of lists dozens of bodies)

QUERY = """
SELECT ?item ?iso3 ?links ?article ?p ?value ?valueLabel WHERE {
  ?item wdt:P298 ?iso3 ; wikibase:sitelinks ?links .
  OPTIONAL { ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }
  VALUES ?p { %s }
  OPTIONAL {
    ?p wikibase:directClaim ?wdt .
    ?item ?wdt ?value .
    FILTER(!isLiteral(?value) || lang(?value) = "" || lang(?value) = "en")
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""


def query() -> str:
    props = " ".join(f"wd:{p}" for p, _ in (*FACTS, *IMAGES))
    return QUERY % props


ELECTION_TYPES = ("presidential election", "general election", "legislative election", "parliamentary election",
                  "referendum")
SPORT_COMPETITIONS = (
    "Summer Olympic Games", "Winter Olympic Games", "Summer Paralympic Games", "Winter Paralympic Games",
    "FIFA World Cup", "FIFA Women's World Cup", "Rugby World Cup", "Cricket World Cup", "Commonwealth Games",
    "Asian Games", "Pan American Games", "African Games", "UEFA European Championship", "Copa América",
    "Africa Cup of Nations", "AFC Asian Cup", "World Athletics Championships", "Formula One Grand Prix",
)
DISASTER_TYPES = {  # English class name -> (kind, subkind)
    "earthquake": ("disaster", "earthquake"), "tsunami": ("disaster", "tsunami"),
    "volcanic eruption": ("disaster", "volcano"), "tropical cyclone": ("disaster", "storm"),
    "hurricane": ("disaster", "storm"), "typhoon": ("disaster", "storm"), "tornado": ("disaster", "storm"),
    "blizzard": ("disaster", "storm"), "flood": ("disaster", "flood"), "landslide": ("disaster", "landslide"),
    "avalanche": ("disaster", "landslide"), "wildfire": ("disaster", "wildfire"),
    "heat wave": ("disaster", "heatwave"), "cold wave": ("disaster", "cold wave"), "drought": ("disaster", "drought"),
    "famine": ("disaster", "famine"), "epidemic": ("epidemic", "epidemic"), "pandemic": ("epidemic", "pandemic"),
}


ACCIDENT_TYPES = {  # English class name -> subkind (event kind "transport")
    "aviation accident": "air", "airliner accident": "air", "aviation incident": "air", "mid-air collision": "air",
    "shipwreck": "sea", "maritime incident": "sea", "maritime disaster": "sea", "ferry disaster": "sea",
    "ship collision": "sea", "railway accident": "rail", "train wreck": "rail", "train collision": "rail",
    "derailment": "rail", "level crossing accident": "rail",
}
ACCIDENT_MIN_DEATHS = 5  # fetched from 5 deaths; Settings > Transport picks what shows (10 by default)
SITE_MIN_VISITORS = 1_000_000


SUMMIT_SERIES = ("G7 summit", "G8 summit", "G20 summit", "NATO summit", "APEC summit", "BRICS summit",
                 "East Asia Summit", "ASEAN Summit", "Commonwealth Heads of Government Meeting", "European Council meeting",
                 "Summit of the Americas", "African Union summit", "Pacific Islands Forum", "Shanghai Cooperation Organisation summit",
                 "United Nations Climate Change Conference")


def _names(names) -> str:
    return " ".join(f'"{n}"@en' for n in names)


EVENT_QUERIES = {
    "elections": """
SELECT ?e ?eLabel ?iso3 ?date ?kindName WHERE {
  VALUES ?kindName { %s }
  ?kind rdfs:label ?kindName .
  ?e wdt:P31/wdt:P279? ?kind ; wdt:P17 ?c ; wdt:P585 ?date .
  ?c wdt:P298 ?iso3 .
  FILTER NOT EXISTS { ?e wdt:P131 ?within }
  FILTER(YEAR(?date) >= 1945)
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}""" % _names(ELECTION_TYPES),
    "leaders": """
SELECT ?iso3 ?office ?person ?personLabel ?start ?end ?party ?partyLabel ?partyStart ?partyEnd ?colour WHERE {
  VALUES (?p ?ps ?held ?office) { (p:P35 ps:P35 wdt:P1906 "head of state") (p:P6 ps:P6 wdt:P1313 "head of government") }
  ?c wdt:P298 ?iso3 .
  # Many countries list only the current leader on the country item, so the full
  # history comes from everyone whose "position held" is the country's office.
  { ?c ?p ?st . ?st ?ps ?person ; pq:P580 ?start . }
  UNION
  { ?c ?held ?post . ?person p:P39 ?st . ?st ps:P39 ?post ; pq:P580 ?start . }
  OPTIONAL { ?st pq:P582 ?end }
  OPTIONAL {
    ?person p:P102 ?ms . ?ms ps:P102 ?party .
    OPTIONAL { ?ms pq:P580 ?partyStart }
    OPTIONAL { ?ms pq:P582 ?partyEnd }
    OPTIONAL { ?party wdt:P465 ?colour }
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}""",
    "sport": """
SELECT ?e ?eLabel ?compName ?iso3 ?start ?end ?date ?placeLabel WHERE {
  VALUES ?compName { %s }
  ?comp rdfs:label ?compName .
  { ?e wdt:P31 ?comp } UNION { ?e wdt:P3450 ?comp }
  { ?e wdt:P17 ?c } UNION { ?e wdt:P276/wdt:P17 ?c }
  ?c wdt:P298 ?iso3 .
  OPTIONAL { ?e wdt:P580 ?start }
  OPTIONAL { ?e wdt:P582 ?end }
  OPTIONAL { ?e wdt:P585 ?date }
  OPTIONAL { ?e wdt:P276 ?place }
  FILTER(BOUND(?start) || BOUND(?date))
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}""" % _names(SPORT_COMPETITIONS),
    "disasters": """
SELECT ?e ?eLabel ?typeName ?iso3 ?start ?end ?date ?deaths ?damage WHERE {
  VALUES ?typeName { %s }
  ?type rdfs:label ?typeName .
  ?e wdt:P31/wdt:P279? ?type ; wdt:P17 ?c .
  ?c wdt:P298 ?iso3 .
  OPTIONAL { ?e wdt:P580 ?start }
  OPTIONAL { ?e wdt:P582 ?end }
  OPTIONAL { ?e wdt:P585 ?date }
  OPTIONAL { ?e wdt:P1120 ?deaths }
  OPTIONAL { ?e p:P2630/psv:P2630 [ wikibase:quantityAmount ?damage ; wikibase:quantityUnit wd:Q4917 ] }
  FILTER(BOUND(?start) || BOUND(?date))
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}""" % _names(DISASTER_TYPES),
    "summits": """
SELECT ?e ?eLabel ?seriesName ?iso3 ?start ?end ?date ?placeLabel WHERE {
  VALUES ?seriesName { %s }
  ?series rdfs:label ?seriesName .
  { ?e wdt:P31 ?series } UNION { ?e wdt:P179 ?series }
  { ?e wdt:P17 ?c } UNION { ?e wdt:P276/wdt:P17 ?c }
  ?c wdt:P298 ?iso3 .
  OPTIONAL { ?e wdt:P580 ?start }
  OPTIONAL { ?e wdt:P582 ?end }
  OPTIONAL { ?e wdt:P585 ?date }
  OPTIONAL { ?e wdt:P276 ?place }
  FILTER(BOUND(?start) || BOUND(?date))
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}""" % _names(SUMMIT_SERIES),
    "courts": """
SELECT ?case ?caseLabel ?courtName ?role ?iso3 ?start ?date ?end WHERE {
  VALUES ?courtName { "International Court of Justice"@en "International Criminal Court"@en
                      "Permanent Court of Arbitration"@en "International Tribunal for the Law of the Sea"@en }
  ?court rdfs:label ?courtName .
  ?case wdt:P4884 ?court .
  { ?case wdt:P1620 ?c . BIND("plaintiff" AS ?role) } UNION { ?case wdt:P1591 ?c . BIND("defendant" AS ?role) }
  ?c wdt:P298 ?iso3 .
  OPTIONAL { ?case wdt:P580 ?start }
  OPTIONAL { ?case wdt:P585 ?date }
  OPTIONAL { ?case wdt:P577 ?date }
  OPTIONAL { ?case wdt:P582 ?end }
  FILTER(BOUND(?start) || BOUND(?date))
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}""",
    "resolutions": """
SELECT ?r ?rLabel ?iso3 ?date WHERE {
  ?type rdfs:label "United Nations Security Council resolution"@en .
  ?r wdt:P31 ?type ; wdt:P921 ?c .
  ?c wdt:P298 ?iso3 .
  { ?r wdt:P585 ?date } UNION { ?r wdt:P577 ?date }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}""",
    "accidents": """
SELECT ?e ?eLabel ?typeName ?iso3 ?date ?start ?deaths ?placeLabel WHERE {
  VALUES ?typeName { %s }
  ?type rdfs:label ?typeName .
  ?e wdt:P31/wdt:P279? ?type ; wdt:P1120 ?deaths .
  FILTER(?deaths >= %d)
  { ?e wdt:P17 ?c } UNION { ?e wdt:P276/wdt:P17 ?c }
  ?c wdt:P298 ?iso3 .
  OPTIONAL { ?e wdt:P585 ?date }
  OPTIONAL { ?e wdt:P580 ?start }
  OPTIONAL { ?e wdt:P276 ?place }
  FILTER(BOUND(?start) || BOUND(?date))
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}""" % (_names(ACCIDENT_TYPES), ACCIDENT_MIN_DEATHS),
    "sites": """
SELECT ?s ?sLabel ?coord ?iso3 ?visitors ?year ?article WHERE {
  ?s p:P1174 ?st . ?st ps:P1174 ?visitors .
  FILTER(?visitors >= %d)
  OPTIONAL { ?st pq:P585 ?year }
  ?s wdt:P625 ?coord ; wdt:P17 ?c .
  ?c wdt:P298 ?iso3 .
  OPTIONAL { ?article schema:about ?s ; schema:isPartOf <https://en.wikipedia.org/> }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}""" % SITE_MIN_VISITORS,
    "stations": """
SELECT ?s ?sLabel ?coord ?iso3 ?opLabel ?start WHERE {
  ?s wdt:P30 wd:Q51 ; wdt:P625 ?coord ; wdt:P31/wdt:P279* ?t .
  ?t rdfs:label "research station"@en .
  OPTIONAL { ?s wdt:P137 ?op . OPTIONAL { ?op wdt:P298 ?opIso } OPTIONAL { ?op wdt:P17/wdt:P298 ?opCountry } }
  OPTIONAL { ?s wdt:P17/wdt:P298 ?ownIso }
  BIND(COALESCE(?opIso, ?opCountry, ?ownIso) AS ?iso3)
  OPTIONAL { ?s wdt:P571 ?start }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}""",
}


class Wikidata(Connector):
    source_id = "wikidata"
    fetch_every_days = FETCH_EVERY_DAYS
    stage_version = 2  # 2: hand-checked leaders for NZ, Australia, the UK and the US (leaders_curated)
    fetch_version = 6  # 6: air, sea and rail accidents, most visited places; 2: elections, leaders, sporting events and disasters as well as the facts; 3: leaders' parties; 4: every holder of the office; 5: summits, court cases, Security Council resolutions, Antarctic stations

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        url = f"{ENDPOINT}?format=json&query={quote(query())}"
        self.get(url, raw_dir / FILE)
        for name, q in EVENT_QUERIES.items():
            try:
                self.get(f"{ENDPOINT}?format=json&query={quote(q)}", raw_dir / f"wikidata_{name}.json")
            except (ConnectorError, httpx.HTTPError) as exc:  # the facts are what matters; events come next month
                log.warning("wikidata: %s query skipped (%s)", name, exc)
        return ENDPOINT

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        path = raw_dir / FILE
        if not path.exists():
            raise ConnectorError(f"wikidata: no {FILE} in {raw_dir}")
        try:
            bindings = json.loads(path.read_text(encoding="utf-8"))["results"]["bindings"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise ConnectorError(f"wikidata: {FILE} is not a query result ({exc})") from None
        rows = facts(bindings)
        con.execute("CREATE TABLE wd (source_code VARCHAR, section VARCHAR, field VARCHAR, field_key VARCHAR, "
                    "content VARCHAR, position BIGINT)")
        con.executemany("INSERT INTO wd VALUES (?, ?, ?, ?, ?, ?)", rows)
        log.info("wikidata: %s facts for %s countries", len(rows), len({r[0] for r in rows}))
        self.texts_query = (f"SELECT 'wikidata' AS source_id, {sql_str(vintage)} AS vintage, 'iso3' AS scheme, source_code, "
                            "NULL AS edition, section, field, field_key, content, position FROM wd")
        events = founding_events(rows)
        for name in EVENT_QUERIES:
            f = raw_dir / f"wikidata_{name}.json"
            if f.exists():
                try:
                    found = json.loads(f.read_text(encoding="utf-8"))["results"]["bindings"]
                except (json.JSONDecodeError, KeyError):
                    log.warning("wikidata: %s is not a query result; skipped", f.name)
                    continue
                if name == "sites":
                    sites = site_features(found)
                    if sites:
                        self.layers.append({"layer_id": "visited_sites", "name": "Most visited places",
                                            "description": "Museums, parks, monuments and other places with a million or more "
                                                           "visitors a year (Wikidata, latest year given).",
                                            "kind": "point", "feature_count": len(sites), "geojson": collection(sites)})
                    continue
                if name == "stations":
                    stations = station_features(found)
                    if stations:
                        self.layers.append({"layer_id": "antarctic_stations", "name": "Antarctic research stations",
                                            "description": "Research stations in Antarctica and the country that runs each (Wikidata).",
                                            "kind": "point", "feature_count": len(stations), "geojson": collection(stations)})
                    continue
                events += EVENT_READERS[name](found)
        self.layers.append(antarctic_claims())
        events = leaders_curated.merge(events)
        log.info("wikidata: %s events", len(events))
        con.execute("CREATE TABLE wd_events (source_code VARCHAR, event_key VARCHAR, kind VARCHAR, subkind VARCHAR, "
                    "title VARCHAR, start_date DATE, end_date DATE, precision VARCHAR, deaths DOUBLE, damage_usd DOUBLE, "
                    "place VARCHAR, url VARCHAR, detail VARCHAR, color VARCHAR)")
        if events:  # rows from the readers that give no party or colour end at url
            con.executemany("INSERT INTO wd_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            [(*e, *(None,) * (14 - len(e))) for e in events])
        self.events_query = (f"SELECT 'wikidata' AS source_id, {sql_str(vintage)} AS vintage, 'iso3' AS scheme, "
                             "source_code, event_key, kind, subkind, title, start_date, end_date, precision, "
                             "deaths AS size, CASE WHEN deaths IS NOT NULL THEN 'deaths' END AS size_unit, deaths, "
                             "NULL AS affected, damage_usd, place, url, detail, color FROM wd_events")
        # No numbers: an empty observation set with the staged columns.
        return (f"SELECT 'wikidata' AS source_id, {sql_str(vintage)} AS vintage, 'iso3' AS scheme, NULL AS source_code, "
                "NULL AS indicator_id, NULL AS period_start, 'A' AS freq, '' AS breakdown, 'central' AS variant, "
                "NULL AS value, 'E' AS status WHERE false")


def facts(bindings: list[dict]) -> list[tuple]:
    """(iso3, section, field, property, text, position) rows from the query's result rows."""
    labels = dict((*FACTS, *IMAGES))
    order = {p: i for i, (p, _) in enumerate((*FACTS, *IMAGES))}
    items: dict[str, dict] = {}  # item -> {iso3, links, article, values: {prop: [..]}}
    for b in bindings:
        item = b["item"]["value"]
        it = items.setdefault(item, {"iso3": b["iso3"]["value"].upper(), "links": int(b.get("links", {}).get("value", 0)),
                                     "article": b.get("article", {}).get("value"), "values": {}})
        if "value" not in b:
            continue
        prop = b["p"]["value"].rsplit("/", 1)[-1]
        text = _text(prop, b["value"], b.get("valueLabel"))
        vals = it["values"].setdefault(prop, [])
        if text and text not in vals:
            vals.append(text)
    best: dict[str, dict] = {}
    for item, it in items.items():  # one item per code: the one in the most Wikipedia editions
        have = best.get(it["iso3"])
        if have is None or it["links"] > have["links"]:
            best[it["iso3"]] = {**it, "item": item}
    rows = []
    for iso3, it in sorted(best.items()):
        rows.append((iso3, "Links", "Wikidata item", "item", it["item"].rsplit("/", 1)[-1], 900))
        if it["article"]:
            rows.append((iso3, "Links", "Wikipedia article", "article",
                         unquote(it["article"].rsplit("/wiki/", 1)[-1]).replace("_", " "), 901))
        for prop, vals in it["values"].items():
            section = "Pictures" if prop in dict(IMAGES) else "Facts"
            shown = vals[:MULTI_LIMIT] + ([f"and {len(vals) - MULTI_LIMIT} more"] if len(vals) > MULTI_LIMIT else [])
            rows.append((iso3, section, labels[prop], prop, "; ".join(shown), order[prop]))
    return rows


def _text(prop: str, value: dict, label: dict | None) -> str:
    v = value.get("value", "")
    if value.get("type") == "uri":
        if "Special:FilePath/" in v:  # a Commons file: keep its name
            return unquote(v.rsplit("Special:FilePath/", 1)[-1])
        if v.startswith("http://www.wikidata.org/entity/"):
            return (label or {}).get("value", "") if label and not label.get("value", "").startswith("Q") else ""
        return v  # a website
    if value.get("datatype", "").endswith("#dateTime"):
        v = v.lstrip("+")
        return v[:4] if v[4:].startswith("-01-01T") else v[:10]  # a bare year is stored as 1 January
    return v


# ----------------------------------------------------------------------------- events
# Rows: (iso3, event_key, kind, subkind, title, start, end, precision, deaths, damage_usd, place, url)

def _val(b: dict, k: str) -> str | None:
    return b.get(k, {}).get("value") or None


def _day(v: str | None) -> tuple[date | None, str]:
    """A Wikidata time value as a date, with its likely precision (1 January means a bare year)."""
    if not v:
        return None, "day"
    v = v.lstrip("+")
    try:
        d = date.fromisoformat(v[:10])
    except ValueError:
        return None, "day"
    return d, "year" if (d.month, d.day) == (1, 1) else "day"


def _qid(uri: str | None) -> str:
    return (uri or "").rsplit("/", 1)[-1]


def _num(v: str | None) -> float | None:
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def founding_events(rows: list[tuple]) -> list[tuple]:
    """The founding date in the facts (P571), as an independence event."""
    out = []
    for iso3, section, _, prop, text, _ in rows:
        if prop != "P571" or section != "Facts":
            continue
        first = text.split("; ")[0]
        d, prec = _day(first if len(first) > 4 else f"{first}-01-01")
        if d:
            out.append((iso3, f"founded:{iso3}", "independence", "founded", "Founded (Wikidata inception)", d, None,
                        prec, None, None, None, None))
    return out


def election_events(bindings: list[dict]) -> list[tuple]:
    out = {}
    for b in bindings:
        d, prec = _day(_val(b, "date"))
        iso3, q = (_val(b, "iso3") or "").upper(), _qid(_val(b, "e"))
        if not d or not iso3 or not q:
            continue
        kind_name = _val(b, "kindName") or "election"
        sub = "referendum" if "referendum" in kind_name else kind_name.replace(" election", "")
        out[(iso3, q)] = (iso3, f"election:{q}", "election", sub, _val(b, "eLabel") or kind_name.capitalize(), d, None,
                          prec, None, None, None, f"https://www.wikidata.org/wiki/{q}")
    return list(out.values())


def leader_events(bindings: list[dict]) -> list[tuple]:
    """A row per term, with the party the leader belonged to when the term began
    (a membership whose dates cover the start, else one with no dates, else any)
    and that party's colour."""
    out: dict[tuple, tuple] = {}
    fit: dict[tuple, int] = {}
    for b in bindings:
        start, prec = _day(_val(b, "start"))
        end, _ = _day(_val(b, "end"))
        iso3, person = (_val(b, "iso3") or "").upper(), _qid(_val(b, "person"))
        if not start or not iso3:
            continue
        office = _val(b, "office") or "leader"
        name = _val(b, "personLabel") or person
        if name.startswith("Q") and name[1:].isdigit():  # no English label
            continue
        party = _val(b, "partyLabel")
        if party and party.startswith("Q") and party[1:].isdigit():
            party = None
        p_start, _ = _day(_val(b, "partyStart"))
        p_end, _ = _day(_val(b, "partyEnd"))
        score = 0 if not party else 3 if ((p_start or p_end) and (not p_start or p_start <= start)
                                         and (not p_end or start <= p_end)) else 2 if not (p_start or p_end) else 1
        key = (iso3, office, person, start)
        if key in out and fit[key] >= score:
            continue
        colour = (_val(b, "colour") or "").strip().lstrip("#")
        colour = f"#{colour.upper()}" if len(colour) == 6 and all(c in "0123456789abcdefABCDEF" for c in colour) else None
        fit[key] = score
        out[key] = (
            iso3, f"leader:{iso3}:{'hos' if 'state' in office else 'hog'}:{person}:{start}", "leader",
            office, f"{name} ({office})", start, end, prec, None, None, None, f"https://www.wikidata.org/wiki/{person}",
            party if score else None, colour if score else None)
    return list(out.values())


def sport_events(bindings: list[dict]) -> list[tuple]:
    out = {}
    for b in bindings:
        start, prec = _day(_val(b, "start") or _val(b, "date"))
        end, _ = _day(_val(b, "end"))
        iso3, q = (_val(b, "iso3") or "").upper(), _qid(_val(b, "e"))
        if not start or not iso3:
            continue
        key = (iso3, q)
        have = out.get(key)
        place = _val(b, "placeLabel")
        if have and have[10] and place and place not in have[10].split("; "):
            place = f"{have[10]}; {place}"
        elif have:
            place = have[10] or place
        out[key] = (iso3, f"sport:{q}", "sport", _val(b, "compName"), _val(b, "eLabel") or _val(b, "compName"),
                    start, end, prec, None, None, place, f"https://www.wikidata.org/wiki/{q}")
    return list(out.values())


def disaster_events(bindings: list[dict]) -> list[tuple]:
    out = {}
    for b in bindings:
        start, prec = _day(_val(b, "start") or _val(b, "date"))
        end, _ = _day(_val(b, "end"))
        iso3, q = (_val(b, "iso3") or "").upper(), _qid(_val(b, "e"))
        if not start or not iso3:
            continue
        kind, sub = DISASTER_TYPES.get(_val(b, "typeName") or "", ("disaster", None))
        deaths, damage = _num(_val(b, "deaths")), _num(_val(b, "damage"))
        have = out.get((iso3, q))
        if have:  # several values for deaths or damage: keep the largest
            deaths = max(filter(None, (deaths, have[8])), default=None)
            damage = max(filter(None, (damage, have[9])), default=None)
        out[(iso3, q)] = (iso3, f"disaster:{q}", kind, sub, _val(b, "eLabel") or sub, start, end, prec, deaths, damage,
                          None, f"https://www.wikidata.org/wiki/{q}")
    return list(out.values())


def accident_events(bindings: list[dict]) -> list[tuple]:
    """Air, sea and rail accidents with their deaths (kind transport)."""
    out = {}
    for b in bindings:
        start, prec = _day(_val(b, "date") or _val(b, "start"))
        iso3, q = (_val(b, "iso3") or "").upper(), _qid(_val(b, "e"))
        if not start or not iso3 or not q:
            continue
        sub = ACCIDENT_TYPES.get(_val(b, "typeName") or "")
        deaths = _num(_val(b, "deaths"))
        have = out.get((iso3, q))
        if have:
            deaths = max(filter(None, (deaths, have[8])), default=None)
            sub = have[3] or sub
        out[(iso3, q)] = (iso3, f"accident:{q}", "transport", sub, _val(b, "eLabel") or "Accident", start, None, prec,
                          deaths, None, _val(b, "placeLabel"), f"https://www.wikidata.org/wiki/{q}")
    return list(out.values())


def site_features(bindings: list[dict]) -> list[dict]:
    """Places with their latest visitors a year."""
    best: dict[str, tuple] = {}
    for b in bindings:
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", _val(b, "coord") or "")
        q, v = _qid(_val(b, "s")), _num(_val(b, "visitors"))
        if not m or not q or v is None:
            continue
        year = (_val(b, "year") or "")[:4]
        y = int(year) if year.isdigit() else 0
        if q in best and best[q][0] >= y:
            continue
        best[q] = (y, v, float(m.group(1)), float(m.group(2)), b)
    out = []
    for q, (y, v, lon, lat, b) in best.items():
        props = {"name": _val(b, "sLabel") or q, "country": (_val(b, "iso3") or "").upper(), "visitors": round(v),
                 "id": q, "url": _val(b, "article") or f"https://www.wikidata.org/wiki/{q}"}
        if y:
            props["year"] = y
        out.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 4), round(lat, 4)]},
                    "properties": props})
    return out


def summit_events(bindings: list[dict]) -> list[tuple]:
    out = {}
    for b in bindings:
        start, prec = _day(_val(b, "start") or _val(b, "date"))
        end, _ = _day(_val(b, "end"))
        iso3, q = (_val(b, "iso3") or "").upper(), _qid(_val(b, "e"))
        if not start or not iso3 or not q:
            continue
        series = _val(b, "seriesName") or "summit"
        sub = re.sub(r"\s+(summit|meeting)$", "", series, flags=re.I) or series
        out[(iso3, q)] = (iso3, f"summit:{q}", "summit", sub, _val(b, "eLabel") or series, start, end, prec, None, None,
                          _val(b, "placeLabel"), f"https://www.wikidata.org/wiki/{q}", f"Host of the {series}")
    return list(out.values())


COURTS = {"International Court of Justice": "ICJ", "International Criminal Court": "ICC",
          "Permanent Court of Arbitration": "PCA", "International Tribunal for the Law of the Sea": "ITLOS"}


def court_events(bindings: list[dict]) -> list[tuple]:
    """A case before an international court, on each country that brought it or answers it."""
    out = {}
    for b in bindings:
        start, prec = _day(_val(b, "start") or _val(b, "date"))
        end, _ = _day(_val(b, "end"))
        iso3, q = (_val(b, "iso3") or "").upper(), _qid(_val(b, "case"))
        if not start or not iso3 or not q:
            continue
        court = COURTS.get(_val(b, "courtName") or "", "court")
        role = _val(b, "role") or ""
        have = out.get((iso3, q))
        if have and have[5] <= start:
            continue
        out[(iso3, q)] = (iso3, f"court:{q}:{iso3}", "court", court, _val(b, "caseLabel") or f"{court} case", start, end,
                          prec, None, None, None, f"https://www.wikidata.org/wiki/{q}",
                          f"{_val(b, 'courtName')}: the country is the {role}" if role else _val(b, "courtName"))
    return list(out.values())


def resolution_events(bindings: list[dict]) -> list[tuple]:
    """UN Security Council resolutions whose main subject is a country."""
    out = {}
    for b in bindings:
        d, _ = _day(_val(b, "date"))
        iso3, q = (_val(b, "iso3") or "").upper(), _qid(_val(b, "r"))
        if not d or not iso3 or not q:
            continue
        out[(iso3, q)] = (iso3, f"unsc:{q}:{iso3}", "un", "resolution", _val(b, "rLabel") or "Security Council resolution",
                          d, None, "day", None, None, None, f"https://www.wikidata.org/wiki/{q}")
    return list(out.values())


def station_features(bindings: list[dict]) -> list[dict]:
    feats = {}
    for b in bindings:
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", _val(b, "coord") or "")
        q = _qid(_val(b, "s"))
        if not m or not q or q in feats:
            continue
        lon, lat = float(m.group(1)), float(m.group(2))
        if lat > -55:
            continue
        start, _ = _day(_val(b, "start"))
        props = {"name": _val(b, "sLabel") or q, "country": (_val(b, "iso3") or "").upper(),
                 "operator": _val(b, "opLabel") or "", "id": q}
        if start:
            props["opened"] = start.year
        feats[q] = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 4), round(lat, 4)]},
                    "properties": props}
    return list(feats.values())


# Territorial claims in Antarctica (frozen by the Antarctic Treaty, 1959): sectors from 60°S
# to the pole between two meridians. Hand-entered; the Norwegian claim has no stated
# northern and southern limits, and Marie Byrd Land is unclaimed.
CLAIMS = (
    ("NZL", "Ross Dependency (New Zealand)", 160.0, -150.0),
    ("AUS", "Australian Antarctic Territory", 44.633, 136.183),
    ("AUS", "Australian Antarctic Territory", 142.033, 160.0),
    ("FRA", "Adélie Land (France)", 136.183, 142.033),
    ("NOR", "Queen Maud Land (Norway)", -20.0, 44.633),
    ("GBR", "British Antarctic Territory", -80.0, -20.0),
    ("ARG", "Argentine Antarctica", -74.0, -25.0),
    ("CHL", "Chilean Antarctic Territory", -90.0, -53.0),
    (None, "Marie Byrd Land (unclaimed)", -150.0, -90.0),
)


def antarctic_claims() -> dict:
    feats = []
    for iso3, name, west, east in CLAIMS:
        span = (east - west) % 360
        # longitudes past 180 are kept as they are, so the Ross Dependency is drawn in one piece
        arc = [[round(west + span * i / 24, 3), -60.0] for i in range(25)]
        ring = arc + [[arc[-1][0], -85.0], [arc[0][0], -85.0], arc[0]]
        feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": ring},
                      "properties": {"name": name, "country": iso3 or "", "overlap": iso3 in ("ARG", "CHL", "GBR")}})
    return {"layer_id": "antarctic_claims", "name": "Antarctic territorial claims",
            "description": "The seven claims to parts of Antarctica, frozen by the Antarctic Treaty of 1959. The "
                           "Argentine, British and Chilean claims overlap; Marie Byrd Land is unclaimed.",
            "kind": "line", "feature_count": len(feats), "geojson": collection(feats)}


EVENT_READERS = {"elections": election_events, "accidents": accident_events, "leaders": leader_events, "sport": sport_events,
                 "disasters": disaster_events, "summits": summit_events, "courts": court_events,
                 "resolutions": resolution_events}
