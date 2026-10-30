"""Load and check the catalogues shipped in worldmodel_contract/catalogues/."""

from __future__ import annotations

import csv
from datetime import date
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

CATALOGUE_DIR = Path(str(resources.files("worldmodel_contract") / "catalogues"))

ENTITY_TYPES = ("country", "historical_country", "world", "continent", "subregion", "intermediate_region",
                "bloc", "alliance", "group", "income_group", "custom")
GROUP_TYPES = tuple(t for t in ENTITY_TYPES if t not in ("country", "historical_country"))


class Aggregation(BaseModel):
    method: Literal["sum", "weighted_mean", "ratio", "none"]
    weight: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    multiplier: float = 1.0

    @model_validator(mode="after")
    def _check(self) -> "Aggregation":
        if self.method == "weighted_mean" and not self.weight:
            raise ValueError("weighted_mean needs a weight")
        if self.method == "ratio" and not (self.numerator and self.denominator):
            raise ValueError("ratio needs a numerator and a denominator")
        return self


class IndicatorSource(BaseModel):
    source_id: str
    series: str
    scale: float = 1.0
    notes: str = ""


class Indicator(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    description: str
    synonyms: list[str] = []
    domain: str
    unit: str
    decimals: int = 1
    frequency: Literal["A", "Q", "M", "D"] = "A"
    breakdowns: list[str] = []
    aggregation: Aggregation
    bounds: tuple[float, float]
    sources: list[IndicatorSource]
    default_on: bool = True  # shown in the map page's menus until switched off on the Indicators page


class Source(BaseModel):
    id: str
    name: str
    short_name: str
    publisher: str
    url: str
    licence: str
    licence_url: str
    commercial_use: bool
    cadence: str
    attribution: str
    status: Literal["active", "planned"]
    default_rank: int


class Entity(BaseModel):
    entity_id: str
    name: str
    short_name: str
    type: str
    iso3: str = ""
    iso2: str = ""
    m49: str = ""
    valid_from: date | None = None
    valid_to: date | None = None
    synonyms: str = ""
    description: str = ""

    @property
    def is_group(self) -> bool:
        return self.type in GROUP_TYPES


def _csv(name: str) -> list[dict[str, str]]:
    with (CATALOGUE_DIR / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _yaml(name: str):
    with (CATALOGUE_DIR / name).open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _none_if_blank(row: dict[str, str]) -> dict[str, str | None]:
    return {k: (v if v != "" else None) for k, v in row.items()}


@lru_cache
def indicators() -> dict[str, Indicator]:
    return {d["id"]: Indicator(**d) for d in _yaml("indicators.yaml")}


def source_indicators(path: Path) -> list[Indicator]:
    """Indicators a source lists itself, saved by its connector beside a vintage
    (indicators.json): for example every World Bank WDI series. Each comes from
    that one source and starts switched off unless the file says otherwise."""
    import json

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    return [Indicator(**{"default_on": False, **d}) for d in data]


@lru_cache
def sources() -> dict[str, Source]:
    return {d["id"]: Source(**d) for d in _yaml("sources.yaml")}


@lru_cache
def entities() -> dict[str, Entity]:
    out = {}
    for r in _csv("entities.csv"):
        e = Entity(**{k: v for k, v in r.items() if v != "" or k in ("entity_id", "name", "short_name", "type")})
        out[e.entity_id] = e
    return out


def entity_codes() -> list[dict[str, str | None]]:
    return [_none_if_blank(r) for r in _csv("entity_codes.csv")]


def memberships() -> list[dict[str, str | None]]:
    return [_none_if_blank(r) for r in _csv("memberships.csv")]


def successions() -> list[dict[str, str | None]]:
    return [_none_if_blank(r) for r in _csv("successions.csv")]


def notable_episodes() -> list[dict[str, str | None]]:
    """Curated episodes (capital-spending booms, bubbles), each with the source it was typed from."""
    return [_none_if_blank(r) for r in _csv("notable_episodes.csv")]


def streams() -> list[dict]:
    return _yaml("streams.yaml")


def driver_graph() -> dict:
    return _yaml("driver_graph.yaml")


def validate() -> list[str]:
    """Cross-check the catalogues. Returns a list of problems; empty means fine."""
    problems: list[str] = []
    try:
        inds, srcs, ents = indicators(), sources(), entities()
    except Exception as exc:  # pydantic or YAML error
        return [f"catalogue failed to load: {exc}"]

    if len(ents) != len(_csv("entities.csv")):
        problems.append("duplicate entity_id in entities.csv")
    for e in ents.values():
        if e.type not in ENTITY_TYPES:
            problems.append(f"entity {e.entity_id}: unknown type {e.type}")

    for i in inds.values():
        if i.bounds[0] > i.bounds[1]:
            problems.append(f"indicator {i.id}: bounds reversed")
        for s in i.sources:
            if s.source_id not in srcs:
                problems.append(f"indicator {i.id}: unknown source {s.source_id}")
        a = i.aggregation
        for ref in (a.weight, a.numerator, a.denominator):
            if ref and ref not in inds:
                problems.append(f"indicator {i.id}: aggregation refers to unknown indicator {ref}")

    seen = set()
    for c in entity_codes():
        if c["entity_id"] not in ents:
            problems.append(f"entity_codes: unknown entity {c['entity_id']}")
        key = (c["scheme"], c["code"], c["valid_from"])
        if key in seen:
            problems.append(f"entity_codes: duplicate {key}")
        seen.add(key)

    for m in memberships():
        g, mem = ents.get(m["group_id"]), ents.get(m["member_id"])
        if g is None or not g.is_group:
            problems.append(f"memberships: {m['group_id']} is not a group entity")
        if mem is None:
            problems.append(f"memberships: unknown member {m['member_id']}")
        if m["valid_from"] and m["valid_to"] and m["valid_from"] > m["valid_to"]:
            problems.append(f"memberships: {m['group_id']}/{m['member_id']} ends before it starts")

    for s in successions():
        for k in ("predecessor_id", "successor_id"):
            if s[k] not in ents:
                problems.append(f"successions: unknown entity {s[k]}")

    keys = set()
    for n in notable_episodes():
        if n["entity_id"] not in ents:
            problems.append(f"notable_episodes: unknown entity {n['entity_id']}")
        if n["event_key"] in keys:
            problems.append(f"notable_episodes: duplicate {n['event_key']}")
        keys.add(n["event_key"])
        if n["precision"] not in ("day", "month", "year"):
            problems.append(f"notable_episodes: {n['event_key']} precision must be day, month or year")
        if n["end_date"] and n["end_date"] < n["start_date"]:
            problems.append(f"notable_episodes: {n['event_key']} ends before it starts")

    for st in streams():
        if st["indicator"] not in inds:
            problems.append(f"stream {st['name']}: unknown indicator {st['indicator']}")
        for eid in st.get("entities", []):
            if eid not in ents:
                problems.append(f"stream {st['name']}: unknown entity {eid}")
        if st.get("members_of") and st["members_of"] not in ents:
            problems.append(f"stream {st['name']}: unknown group {st['members_of']}")

    graph = driver_graph()
    node_ids = {n["id"] for n in graph["nodes"]}
    for n in node_ids:
        if not n.startswith("assumption:") and n not in inds:
            problems.append(f"driver graph: node {n} is not an indicator")
    for link in graph["links"]:
        for k in ("from", "to"):
            if link[k] not in node_ids:
                problems.append(f"driver graph: link refers to unknown node {link[k]}")
    return problems


# ----------------------------------------------------------------------------- country names
# Spellings event sources use that the entity names and synonyms do not cover.
# A name that meant different states at different times maps by date in country_by_name.
NAME_ALIASES = {
    "usa": "USA", "us": "USA", "united states of america": "USA", "uk": "GBR", "great britain": "GBR",
    "england": "GBR", "south korea": "KOR", "korea south": "KOR", "republic of korea": "KOR", "korea": "KOR",
    "north korea": "PRK", "korea north": "PRK", "democratic people s republic of korea": "PRK",
    "burma": "MMR", "myanmar burma": "MMR", "ivory coast": "CIV", "cote d ivoire": "CIV",
    "congo kinshasa": "COD", "democratic republic of congo": "COD", "dr congo": "COD", "drc": "COD", "zaire": "COD",
    "congo brazzaville": "COG", "republic of congo": "COG", "congo": "COG", "east timor": "TLS", "timor leste": "TLS",
    "cape verde": "CPV", "swaziland": "SWZ", "eswatini": "SWZ", "macedonia": "MKD", "north macedonia": "MKD",
    "fyr macedonia": "MKD", "czech republic": "CZE", "czechia": "CZE", "the gambia": "GMB", "gambia": "GMB",
    "laos": "LAO", "vietnam": "VNM", "viet nam": "VNM", "russia": "RUS", "iran": "IRN", "syria": "SYR",
    "bolivia": "BOL", "venezuela": "VEN", "tanzania": "TZA", "moldova": "MDA", "turkey": "TUR", "turkiye": "TUR",
    "brunei": "BRN", "taiwan": "TWN", "palestine": "PSE", "west bank and gaza": "PSE", "gaza": "PSE",
    "vatican": "VAT", "holy see": "VAT", "micronesia": "FSM", "saint lucia": "LCA",
    "saint kitts and nevis": "KNA", "saint vincent and the grenadines": "VCT", "bosnia": "BIH",
    "bosnia herzegovina": "BIH", "bosnia and herzegovina": "BIH", "kyrgyzstan": "KGZ", "slovakia": "SVK",
    "hong kong": "HKG", "macau": "MAC", "macao": "MAC", "reunion": "REU", "curacao": "CUW",
    "west germany": "DEU", "federal republic of germany": "DEU", "germany west": "DEU",
    "east germany": "DDR", "germany east": "DDR", "german democratic republic": "DDR",
    "ussr": "SUN", "soviet union": "SUN", "north yemen": "YAR", "yemen arab republic": "YAR",
    "south yemen": "YMD", "yemen people s republic": "YMD", "czechoslovakia": "CSK",
    "serbia and montenegro": "SCG", "netherlands antilles": "ANT", "kosovo": "XKX",
    "kyrgyz republic": "KGZ", "slovak republic": "SVK", "micronesia fed sts": "FSM", "egypt arab republic": "EGY",
    "yemen republic": "YEM", "iran islamic republic": "IRN", "venezuela rb": "VEN", "lao pdr": "LAO",
}
# name -> [(until, entity)]: the first whose `until` is on or after the date wins.
NAMES_BY_DATE = {
    "yugoslavia": [(date(1992, 4, 26), "YUG"), (date(2006, 6, 3), "SCG"), (date(9999, 12, 31), "SRB")],
    "serbia": [(date(2006, 6, 3), "SCG"), (date(9999, 12, 31), "SRB")],
    "russia": [(date(1991, 12, 25), "SUN"), (date(9999, 12, 31), "RUS")],
    "yemen": [(date(1990, 5, 21), "YAR"), (date(9999, 12, 31), "YEM")],
    "germany": [(date(9999, 12, 31), "DEU")],
}


def name_key(name: str, keep_brackets: bool = False) -> str:
    """A spelling-insensitive form of a country name: lower case, no accents, punctuation or 'the'."""
    import re
    import unicodedata

    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"['`]", "", s)
    s = re.sub(r",\s*the$", "", s.strip())
    s = (s if keep_brackets else re.sub(r"\(.*?\)", " ", s)).replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(the|of|and)\b", " ", s)
    s = re.sub(r"\b(rep|repub)\b", "republic", s)
    s = re.sub(r"\bdem\b", "democratic", s)
    s = re.sub(r"\b(st|ste)\b", "saint", s)
    return re.sub(r"\s+", " ", s).strip()


@lru_cache
def _names() -> dict[str, str]:
    out: dict[str, str] = {}
    seen: dict[str, set[str]] = {}
    for e in entities().values():
        if e.type not in ("country", "historical_country"):
            continue
        for n in (e.name, e.short_name, *e.synonyms.split("|")):
            if n:
                out.setdefault(name_key(n, keep_brackets=True), e.entity_id)
                seen.setdefault(name_key(n), set()).add(e.entity_id)
    for k, ids in seen.items():  # "Virgin Islands" alone is either; keep only names that are not
        if len(ids) == 1:
            out.setdefault(k, next(iter(ids)))
        # "Congo, Democratic Republic of the" -> "democratic republic of the congo"
        if "," in e.name:
            head, tail = e.name.split(",", 1)
            out.setdefault(name_key(f"{tail} {head}"), e.entity_id)
    out.update({name_key(k): v for k, v in NAME_ALIASES.items()})
    return out


def country_by_name(name: str, on: date | None = None) -> str | None:
    """The entity id for a country name as an event source spells it, on a date
    (for names that meant different states at different times), or None."""
    keys = [name_key(name or "", keep_brackets=True), name_key(name or "")]
    if "," in (name or ""):  # "Korea, South", "Congo, Dem. Rep."
        head, tail = name.split(",", 1)
        keys.append(name_key(f"{tail} {head}"))
    for key in filter(None, keys):
        if on and key in NAMES_BY_DATE:
            return next(e for until, e in NAMES_BY_DATE[key] if on <= until)
        if key in _names():
            return _names()[key]
    return None
