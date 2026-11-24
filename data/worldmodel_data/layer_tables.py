"""Map layer details: the layer_items table and the map_layers indicators.

prepare() runs while the build loads its sources, before dbt: it reads every dot layer in
src.raw_layers that worldmodel_contract.layer_details lists, gives each item a country (the
one its source names, else the one it sits in, from Natural Earth's countries on a 0.1 degree
grid that reaches about 20 km out to sea), and writes src.raw_layer_items. From those it adds
the map_layers indicators to src.raw_observations (count, count per million people and the
size total, for the build's year), so dbt treats them like any source's figures and works out
blocs and regions too.

compute() runs after dbt and creates layer_items from src.raw_layer_items, with companies'
revenue in US dollars from the places table."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import duckdb

from worldmodel_contract import layer_details as spec
from worldmodel_contract.schema import TABLES

log = logging.getLogger(__name__)

COUNTRIES_FILE = "ne_50m_admin_0_countries.geojson"
COLUMNS = TABLES["layer_items"].columns
DDL = ", ".join(f"{c} {t}" for c, t in COLUMNS.items())


def countries_file(raw: Path) -> Path | None:
    """The newest copy of Natural Earth's countries among the raw downloads (several sources fetch it)."""
    if not raw.exists():
        return None
    found = [p for pattern in (f"*/*/*/{COUNTRIES_FILE}", f"*/*/{COUNTRIES_FILE}") for p in raw.glob(pattern)]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").strip()
    digits = "".join(ch for ch in s.split(" ")[0] if ch.isdigit() or ch in ".-")
    try:
        return float(digits) if digits not in ("", ".", "-") else None
    except ValueError:
        return None


class Placer:
    """Entity ids for what a source calls a country, and for a point on the map."""

    def __init__(self, con: duckdb.DuckDBPyConnection, countries: Path | None):
        self.known = {r[0] for r in con.execute("SELECT entity_id FROM src.entities").fetchall()}
        self.codes: dict[tuple[str, str], str] = {}
        for scheme, code, ent in con.execute(
                "SELECT scheme, code, entity_id FROM src.entity_codes WHERE scheme IN ('iso3', 'iso2') "
                "ORDER BY valid_to NULLS FIRST").fetchall():
            self.codes.setdefault((scheme, code), ent)
        self.grid = None
        if countries is not None:
            try:
                from worldmodel_data.connectors.networks import Grids
                self.grid = Grids(countries)
            except Exception as exc:  # noqa: BLE001 - no grid: items without a named country stay unplaced
                log.warning("map layer details: could not read %s (%s); items without a country stay unplaced", countries, exc)
        self._names: dict[str, str | None] = {}

    def named(self, v) -> str | None:
        if v in (None, ""):
            return None
        s = str(v).strip()
        if s in self.known:
            return s
        if len(s) == 3 and s.isalpha() and s.isupper():
            return self.codes.get(("iso3", s))
        if len(s) == 2 and s.isalpha() and s.isupper():
            return self.codes.get(("iso2", s))
        if s not in self._names:
            from worldmodel_contract import catalogue
            try:
                self._names[s] = catalogue.country_by_name(s, None)
            except Exception:  # noqa: BLE001
                self._names[s] = None
        return self._names[s]

    def named_all(self, v) -> list[str]:
        """Countries a source names in one text: "Chile-Argentina" is two (the volcano list's way)."""
        one = self.named(v)
        if one or v in (None, ""):
            return [one] if one else []
        parts = [x.strip() for x in str(v).split("-")]
        return list(dict.fromkeys(e for e in (self.named(x) for x in parts if x and not x.startswith("administered")) if e))

    def at(self, lon: float, lat: float) -> str | None:
        if self.grid is None:
            return None
        return self.named(self.grid.at(lon, lat))


def insert_many(con: duckdb.DuckDBPyConnection, table: str, cols: list[str], rows: list, per: int = 500) -> None:
    """Insert rows a few hundred at a time in one statement each: executemany runs one statement per
    row, which for the 100,000 dots of a full download takes minutes and grows the write-ahead log."""
    one = f"({', '.join('?' * len(cols))})"
    for i in range(0, len(rows), per):
        chunk = rows[i:i + per]
        con.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES {', '.join([one] * len(chunk))}",
                    [v for r in chunk for v in r])


def _point(f: dict) -> tuple[float, float] | None:
    g = f.get("geometry") or {}
    if g.get("type") != "Point":
        return None
    c = g.get("coordinates") or []
    try:
        return float(c[0]), float(c[1])
    except (IndexError, TypeError, ValueError):
        return None


def items(layer: spec.LayerDetail, features: list[dict], placer: Placer) -> list[tuple]:
    """(item_id, name, entity_id, lat, lon, size, category, url, props json, placed) for each item
    and country: one row per country an item names (a shared World Heritage site has several)."""
    out = []
    for n, f in enumerate(features):
        pt = _point(f)
        if pt is None:
            continue
        p = dict(f.get("properties") or {})
        item_id = str(p.get("id") or p.get("city") or p.get("locode") or n)
        name = p.get("name") or layer.one
        named = [e for e in (placer.named(c) for c in str(p.get("countries") or "").split(",")) if e] \
            or placer.named_all(p.get("country"))
        placed = not named
        ents = named or [placer.at(*pt)]
        size = _num(p.get(layer.size.prop)) if layer.size else None
        cat = p.get(layer.category[0]) if layer.category else None
        if layer.category and layer.category[0] == "capital":
            cat = "Capital" if cat else "Other"
        url = p.get("url") or p.get("wiki")
        if not url and str(p.get("id") or "").startswith("Q"):
            url = f"https://www.wikidata.org/wiki/{p['id']}"
        keep = {k: v for k, v in p.items() if k not in ("name", "country", "countries", "url", "wiki", "id") and v not in (None, "")}
        for e in dict.fromkeys(ents):
            out.append((item_id, str(name), e, round(pt[1], 5), round(pt[0], 5), size,
                        None if cat in (None, "") else str(cat), url, json.dumps(keep, ensure_ascii=False), placed))
    return out


def prepare(con: duckdb.DuckDBPyConnection, raw: Path, today: date | None = None) -> dict[str, int]:
    """Create src.raw_layer_items and add the map_layers indicators and figures. Returns items per layer."""
    con.execute(f"CREATE TABLE src.raw_layer_items ({DDL})")
    stored = {d.id: d for d in spec.LAYERS if d.kind == "stored"}
    layers = con.execute("SELECT layer_id, geojson, source_id, vintage FROM src.raw_layers WHERE layer_id IN "
                         f"({', '.join('?' * len(stored))}) QUALIFY row_number() OVER (PARTITION BY layer_id ORDER BY vintage DESC) = 1",
                         list(stored)).fetchall() if stored else []
    if not layers:
        return {}
    placer = Placer(con, countries_file(raw))
    counts: dict[str, int] = {}
    cols = list(COLUMNS)
    for layer_id, geojson, source_id, vintage in layers:
        try:
            feats = json.loads(geojson or "{}").get("features") or []
        except json.JSONDecodeError:
            log.warning("map layer details: %s is not GeoJSON; skipped", layer_id)
            continue
        rows = items(stored[layer_id], feats, placer)
        if not rows:
            continue
        insert_many(con, "src.raw_layer_items", cols, [(layer_id, *r, source_id, vintage) for r in rows])
        counts[layer_id] = len({r[0] for r in rows})
    # Universities and companies: the country Wikidata gives (their dots leave it out).
    con.execute("""UPDATE src.raw_layer_items l SET entity_id = p.country_id, placed = false
                   FROM (SELECT place_key, kind, any_value(country_id) AS country_id FROM src.raw_places
                         WHERE country_id IS NOT NULL GROUP BY ALL) p
                   WHERE p.place_key = l.item_id AND p.kind = CASE l.layer_id WHEN 'companies' THEN 'company'
                                                                 WHEN 'universities' THEN 'university' END""")
    _indicators(con, set(counts), today or date.today())
    return counts


def _indicators(con: duckdb.DuckDBPyConnection, found: set[str], today: date) -> None:
    """The layers' indicators into src.indicators, their figures into src.raw_observations."""
    inds = spec.indicators(found)
    if not inds:
        return
    have = {r[0] for r in con.execute("SELECT indicator_id FROM src.indicators").fetchall()}
    inds = [i for i in inds if i["id"] not in have]
    if not inds:
        return
    n = len(TABLES["indicators"].columns)
    con.executemany(f"INSERT INTO src.indicators VALUES ({', '.join('?' * n)})", [
        (i["id"], i["name"], i["description"], "|".join(i["synonyms"]), i["domain"], i["unit"], i["decimals"], i["frequency"],
         "", i["aggregation"]["method"], None, i["aggregation"].get("numerator"), i["aggregation"].get("denominator"),
         i["aggregation"].get("multiplier", 1.0), i["bounds"][0], i["bounds"][1], i["default_on"]) for i in inds])
    con.executemany("INSERT INTO src.indicator_sources VALUES (?, ?, ?, ?, ?, ?)",
                    [(i["id"], spec.SOURCE_ID, i["id"], 1.0, 1, "") for i in inds])
    vintage = today.isoformat()
    con.execute("INSERT INTO src.vintages VALUES (?, ?, ?, now(), NULL, NULL, 'build', true)", [spec.SOURCE_ID, vintage, vintage])
    year = f"{today.year}-01-01"
    pop = _population(con, today.year)
    obs = []
    for layer_id in sorted(found):
        d = spec.BY_ID[layer_id]
        ids = spec.indicator_ids(d)
        if not ids:  # a layer with no figures of its own (chokepoints): details page only
            continue
        for ent, n_items, total in con.execute(
                "SELECT entity_id, count(DISTINCT item_id), sum(size) FROM src.raw_layer_items "
                "WHERE layer_id = ? AND entity_id IS NOT NULL GROUP BY 1", [layer_id]).fetchall():
            obs.append((ids["count"], ent, n_items))
            if pop.get(ent):
                obs.append((ids["per_m"], ent, n_items / pop[ent] * 1e6))
            if "size" in ids and total is not None:
                obs.append((ids["size"], ent, total))
    names = [c[0] for c in con.execute("SELECT * FROM src.raw_observations LIMIT 0").description]
    vals = {"source_id": spec.SOURCE_ID, "vintage": vintage, "scheme": "iso3", "period_start": year, "freq": "A",
            "breakdown": "", "variant": "central", "status": "E"}
    order = [c for c in names if c in vals or c in ("indicator_id", "source_code", "value")]
    if not obs:
        return
    insert_many(con, "src.raw_observations", order,
                [[{"indicator_id": i, "source_code": e, "value": float(v)}.get(c, vals.get(c)) for c in order] for i, e, v in obs])


def _population(con: duckdb.DuckDBPyConnection, year: int) -> dict[str, float]:
    """Each country's population in the year nearest `year` (the UN's estimate or central projection
    first, else the World Bank's)."""
    try:
        got = con.execute("""
            SELECT c.entity_id, arg_min(r.value, abs(year(r.period_start) - ?) * 10 + CASE r.source_id WHEN 'un_wpp' THEN 0 ELSE 1 END)
            FROM src.raw_observations r JOIN src.entity_codes c ON c.scheme = r.scheme AND c.code = r.source_code
            WHERE r.indicator_id = 'pop_total' AND coalesce(r.variant, 'central') = 'central' AND coalesce(r.breakdown, '') = ''
              AND r.source_id IN ('un_wpp', 'world_bank_wdi') AND r.value > 0 AND r.freq = 'A'
            GROUP BY 1""", [year]).fetchall()
    except duckdb.Error:
        return {}
    return {e: v for e, v in got}


def compute(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Create layer_items (empty when no layer has items). Returns items per layer."""
    con.execute(f"CREATE TABLE layer_items ({DDL})")
    have = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'src'").fetchall()}
    if "raw_layer_items" not in have:
        return {}
    con.execute("INSERT INTO layer_items SELECT * FROM src.raw_layer_items")
    places = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()}
    if "places" in places:  # companies' revenue in US dollars, worked out with the places
        con.execute("""UPDATE layer_items l SET size = p.size FROM places p
                       WHERE l.layer_id = 'companies' AND p.kind = 'company' AND p.place_id = p.source_id || ':company:' || l.item_id""")
    return dict(con.execute("SELECT layer_id, count(DISTINCT item_id) FROM layer_items GROUP BY 1").fetchall())
