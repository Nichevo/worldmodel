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
                "bloc", "alliance", "group", "custom")
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
