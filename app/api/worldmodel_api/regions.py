"""Regions inside a country (US states and counties, New Zealand's regions): their outlines for
the "Regions inside a country" maps, and one region's figures each set against the others at
the same level. Each function takes `q`, the API's rows(sql, params) helper.
"""

from __future__ import annotations

import json
from typing import Callable

Q = Callable[[str, list], list[dict]]


def _has(q: Q, table: str) -> bool:
    try:
        return bool(q("SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]))
    except Exception:  # noqa: BLE001
        return False


def place(q: Q, entity: str) -> dict | None:
    """Where a region sits: its level, its parent (state or country) and that parent's level."""
    if not _has(q, "subdivisions"):
        return None
    got = q("""SELECT d.level, d.parent_id, p.short_name AS parent_name, pd.level AS parent_level,
                      (SELECT count(*) FROM subdivisions c JOIN entities ce USING (entity_id)
                       WHERE c.parent_id = d.entity_id AND ce.valid_to IS NULL) AS children
               FROM subdivisions d JOIN entities p ON p.entity_id = d.parent_id
               LEFT JOIN subdivisions pd ON pd.entity_id = d.parent_id WHERE d.entity_id = ?""", [entity])
    return got[0] if got else None


def countries(q: Q) -> list[dict]:
    """Countries whose regions the app holds, with how many there are and their levels."""
    if not _has(q, "subdivisions"):
        return []
    return q("""SELECT d.parent_id AS entity_id, e.short_name AS name, count(*) AS regions, min(d.level) AS level,
                       (SELECT count(*) FROM subdivisions c JOIN subdivisions s ON c.parent_id = s.entity_id
                        WHERE s.parent_id = d.parent_id) AS below
                FROM subdivisions d JOIN entities e ON e.entity_id = d.parent_id WHERE e.type = 'country'
                GROUP BY 1, 2 ORDER BY 2""", [])


def shapes(q: Q, parent: str, level: str | None = None) -> dict:
    """The outlines of a country's or state's regions, as one FeatureCollection (id, name, level).
    level 'county' under a country gives every county of every state."""
    if not (_has(q, "geo_features") and _has(q, "subdivisions")):
        return {"type": "FeatureCollection", "features": []}
    if level and level != "state" and level != "region":
        ids = q("""SELECT c.entity_id FROM subdivisions s JOIN subdivisions c ON c.parent_id = s.entity_id
                   WHERE s.parent_id = ? AND c.level = ?""", [parent, level])
    else:
        ids = q("SELECT entity_id FROM subdivisions WHERE parent_id = ?", [parent])
    want = [r["entity_id"] for r in ids]
    feats = []
    for i in range(0, len(want), 500):
        part = want[i:i + 500]
        for r in q(f"""SELECT feature_id, name, props, geojson FROM geo_features WHERE layer_id = 'regions'
                       AND feature_id IN ({', '.join('?' * len(part))})""", part):
            props = json.loads(r["props"] or "{}")
            feats.append({"type": "Feature", "id": r["feature_id"], "geometry": json.loads(r["geojson"]),
                          "properties": {"id": r["feature_id"], "name": r["name"], "level": props.get("level")}})
    return {"type": "FeatureCollection", "features": feats}


def facts(q: Q, entity: str) -> dict:
    """Each figure held for a region: its latest value, its rank among the regions at the same level
    under the same parent (#1 the highest), their middle value and the parent's own value where held,
    and the last 15 years for a small line."""
    where = place(q, entity)
    out = {"entity_id": entity, "place": where, "facts": []}
    if not where:
        return out
    sibs = [r["entity_id"] for r in q("""SELECT d.entity_id FROM subdivisions d JOIN entities e USING (entity_id)
                                       WHERE d.parent_id = ? AND e.valid_to IS NULL""", [where["parent_id"]])]
    if entity not in sibs:
        sibs.append(entity)
    marks = ", ".join("?" * len(sibs))
    mine = q("""SELECT s.indicator_id, year(s.period_start) AS y, s.value FROM series s
                WHERE s.entity_id = ? AND s.breakdown = '' AND s.variant = 'central' AND s.freq = 'A' ORDER BY 1, 2""", [entity])
    if not mine:
        return out
    inds = sorted({r["indicator_id"] for r in mine})
    imarks = ", ".join("?" * len(inds))
    latest = {}
    for r in mine:
        latest[r["indicator_id"]] = (r["y"], r["value"])
    others = q(f"""SELECT s.indicator_id, s.entity_id, year(s.period_start) AS y, s.value FROM series s
                   WHERE s.entity_id IN ({marks}) AND s.indicator_id IN ({imarks}) AND s.breakdown = '' AND s.variant = 'central'
                   AND s.freq = 'A'""", sibs + inds)
    by: dict[tuple[str, int], list[float]] = {}
    for r in others:
        by.setdefault((r["indicator_id"], r["y"]), []).append(r["value"])
    parent_vals = {(r["indicator_id"], r["y"]): r["value"] for r in q(
        f"""SELECT indicator_id, year(period_start) AS y, value FROM series WHERE entity_id = ? AND indicator_id IN ({imarks})
            AND breakdown = '' AND variant = 'central' AND freq = 'A'""", [where["parent_id"]] + inds)}
    meta = {r["indicator_id"]: r for r in q(f"""SELECT i.indicator_id, i.name, i.unit, i.decimals, i.domain, i.description,
        x.source_id FROM indicators i LEFT JOIN indicator_sources x ON x.indicator_id = i.indicator_id AND x.rank = 1
        WHERE i.indicator_id IN ({imarks})""", inds)}
    for ind in inds:
        y, v = latest[ind]
        vals = sorted(by.get((ind, y), [v]))
        m = meta.get(ind, {})
        spark = [[r["y"], r["value"]] for r in mine if r["indicator_id"] == ind][-15:]
        out["facts"].append({
            "indicator_id": ind, "name": m.get("name", ind), "unit": m.get("unit"), "decimals": m.get("decimals"),
            "domain": m.get("domain"), "source_id": m.get("source_id"), "year": y, "value": v,
            "rank": 1 + sum(1 for x in vals if x > v), "of": len(vals), "lowest": vals[0], "highest": vals[-1],
            "middle": vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2,
            "parent_value": parent_vals.get((ind, y)), "spark": spark})
    return out
