"""Wikidata: a facts box for every country, from one query a month.

    https://query.wikidata.org/sparql   (the Wikidata Query Service, Wikimedia's official API)

One SPARQL query fetches, for every item with an ISO 3166-1 alpha-3 code (P298),
the properties in FACTS below (capital, head of state and government, currency,
languages, calling code and so on), the English Wikipedia article, and the
Commons file names of its flag, coat of arms, locator map and main picture. Where
several items share a code (the Netherlands and the Kingdom of the Netherlands),
the one with the most Wikipedia editions is kept.

What is stored: text only (texts.parquet beside the vintage; section "Facts",
field_key the property id, values joined with "; "). The app shows it as a facts
box on country pages and uses the article name to fetch the Wikipedia introduction.
Wikidata is CC0. The query runs at most once every FETCH_EVERY_DAYS days (a refresh
skips it in between); `worldmodel-data fetch wikidata` runs it at once.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote

import duckdb

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


class Wikidata(Connector):
    source_id = "wikidata"
    fetch_every_days = FETCH_EVERY_DAYS

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        url = f"{ENDPOINT}?format=json&query={quote(query())}"
        self.get(url, raw_dir / FILE)
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
