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
* leaders: heads of state (P35) and government (P6) with their start and end
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
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, unquote

import duckdb
import httpx

from worldmodel_data.connectors.base import Connector, ConnectorError, sql_str

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
  VALUES (?p ?ps ?office) { (p:P35 ps:P35 "head of state") (p:P6 ps:P6 "head of government") }
  ?c wdt:P298 ?iso3 ; ?p ?st .
  ?st ?ps ?person ; pq:P580 ?start .
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
}


class Wikidata(Connector):
    source_id = "wikidata"
    fetch_every_days = FETCH_EVERY_DAYS
    fetch_version = 3  # 2: elections, leaders, sporting events and disasters as well as the facts; 3: leaders' parties

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
                events += EVENT_READERS[name](found)
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


EVENT_READERS = {"elections": election_events, "leaders": leader_events, "sport": sport_events,
                 "disasters": disaster_events}
