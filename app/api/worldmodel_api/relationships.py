"""The relationship scan's results, as the app reads them.

The pipeline writes them after each refresh into <home>/warehouse/relationships/
(see worldmodel_contract.relations); this module reads the newest scan, joins
indicator names, filters and ranks. The scatter points for one pair come straight
from the warehouse, measured the same way the scan measured them.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import duckdb

from worldmodel_contract import catalogue, local
from worldmodel_contract import relations as rel

_lock = threading.Lock()
_cache: dict = {"key": None, "pairs": [], "events": [], "meta": None}


def _load(build_id: str | None) -> dict:
    meta = rel.latest(local.home(), build_id)
    if meta is None:
        return {"meta": None, "pairs": [], "events": []}
    paths = [Path(meta["pairs_path"]), Path(meta["events_path"])]
    key = (meta["build_id"], tuple(os.path.getmtime(p) if p.is_file() else 0 for p in paths))
    with _lock:
        if _cache["key"] != key:
            con = duckdb.connect()
            try:
                out = []
                for p in paths:
                    if not p.is_file():
                        out.append([])
                        continue
                    r = con.execute(f"SELECT * FROM read_parquet('{p.as_posix()}')")
                    cols = [d[0] for d in r.description]
                    out.append([dict(zip(cols, row)) for row in r.fetchall()])
            finally:
                con.close()
            names = meta.get("names", {})
            for row in out[0]:
                for side in ("x", "y"):
                    n = names.get(row[side], {})
                    row[f"{side}_name"], row[f"{side}_domain"] = n.get("name", row[side]), n.get("domain", "")
                    row[f"{side}_unit"] = rel.change_unit(n.get("unit"), n.get("kind", "diff"))
                row["groups"] = json.loads(row["groups"] or "{}")
            for row in out[1]:
                n = names.get(row["indicator_id"], {})
                row["name"], row["domain"] = n.get("name", row["indicator_id"]), n.get("domain", "")
            _cache.update(key=key, pairs=out[0], events=out[1], meta=meta)
        return {"meta": _cache["meta"], "pairs": _cache["pairs"], "events": _cache["events"]}


def summary(meta: dict | None, build_id: str | None) -> dict | None:
    if meta is None:
        return None
    out = {k: v for k, v in meta.items() if k not in ("names", "pairs_path", "events_path")}
    out["stale"] = bool(build_id) and meta["build_id"] != build_id
    out["domains"] = sorted({n.get("domain", "") for n in meta.get("names", {}).values()} - {""})
    out["labels"], out["groups"], out["event_kinds"] = rel.LABELS, rel.GROUPS, list(rel.EVENT_KINDS)
    return out


def pairs(build_id: str | None, label: str | None = None, domain: str | None = None, group: str | None = None,
          q: str | None = None, indicator: str | None = None, drivers_only: bool = False, hide_same: bool = True,
          first_only: bool = False, hide_same_source: bool = False, limit: int = 100, offset: int = 0) -> dict:
    data = _load(build_id)
    found = data["pairs"]
    words = [w for w in (q or "").lower().split() if w]
    out = []
    for r in found:
        if label and label not in r["labels"]:
            continue
        if domain and domain not in (r["x_domain"], r["y_domain"]):
            continue
        if indicator and indicator not in (r["x"], r["y"]):
            continue
        if drivers_only and not r["in_drivers"]:
            continue
        if hide_same and r["near_same"]:
            continue
        if hide_same_source and r.get("same_source"):
            continue
        if first_only and not r["first"]:
            continue
        if words:
            hay = f"{r['x']} {r['y']} {r['x_name']} {r['y_name']}".lower()
            if not all(w in hay for w in words):
                continue
        if group:
            g = r["groups"].get(group)
            if not g or abs(g[0]) < 0.1 or g[2] >= 0.05:
                continue
        out.append(r)
    if group:
        out.sort(key=lambda r: -abs(r["groups"][group][0]))
    else:
        out.sort(key=lambda r: -r["score"])
    return {"scan": summary(data["meta"], build_id), "total": len(out), "rows": out[offset:offset + limit]}


def one(build_id: str | None, x: str, y: str) -> dict | None:
    data = _load(build_id)
    for r in data["pairs"]:
        if (r["x"], r["y"]) == (x, y):
            return {**r, "flipped": False}
        if (r["x"], r["y"]) == (y, x):
            return {**r, "flipped": True}
    return None


def kind_of(build_id: str | None, indicator: str) -> str | None:
    meta = _load(build_id)["meta"]
    n = (meta or {}).get("names", {}).get(indicator)
    return n.get("kind") if n else None


def events(build_id: str | None, kind: str | None = None, indicator: str | None = None, significant: bool = True,
           hide_built_in: bool = True, hide_diverging: bool = True) -> dict:
    data = _load(build_id)
    out = [e for e in data["events"]
           if (not kind or e["kind"] == kind) and (not indicator or e["indicator_id"] == indicator)
           and (not significant or e["significant"]) and (not hide_built_in or not e["built_in"])
           and (not hide_diverging or not e.get("diverging_before"))]
    out.sort(key=lambda e: e["p"])
    return {"scan": summary(data["meta"], build_id), "total": len(out), "rows": out[:500]}


def scatter_sql(kind_x: str, kind_y: str) -> str:
    """Each country's yearly changes of two indicators, side by side, measured as the scan does."""
    def change(kind: str, t: str) -> str:
        if kind == "pct":
            return f"CASE WHEN {t}.value > 0 AND {t}.prev > 0 THEN 100 * (ln({t}.value) - ln({t}.prev)) END"
        return f"{t}.value - {t}.prev"
    return f"""
        WITH s AS (
            SELECT s.indicator_id, s.entity_id, year(s.period_start) AS y, s.value,
                   lag(s.value) OVER (PARTITION BY s.indicator_id, s.entity_id ORDER BY s.period_start) AS prev,
                   lag(year(s.period_start)) OVER (PARTITION BY s.indicator_id, s.entity_id ORDER BY s.period_start) AS py
            FROM series s
            JOIN indicator_sources r ON r.indicator_id = s.indicator_id AND r.source_id = s.source_id AND r.rank = 1
            JOIN entities e ON e.entity_id = s.entity_id
            WHERE s.indicator_id IN (?, ?) AND s.status = 'E' AND s.breakdown = '' AND s.variant = 'central'
              AND s.freq = 'A' AND e.type = 'country'),
        c AS (SELECT indicator_id, entity_id, y, value, prev FROM s WHERE py = y - 1)
        SELECT a.entity_id, a.y, {change(kind_x, 'a')} AS dx,
               {change(kind_y, 'b')} AS dy
        FROM c a JOIN c b ON a.entity_id = b.entity_id AND a.y = b.y
        WHERE a.indicator_id = ? AND b.indicator_id = ?
        ORDER BY a.entity_id, a.y"""


def keys() -> list[dict]:
    """The keys the app can use, whether each is set (never the key itself), and what it unlocks."""
    out = []
    for e in catalogue.api_keys():
        if not e.get("needs_key"):
            continue
        env = e.get("env") or []
        out.append({"source": e["source"], "name": e["name"], "signup": e.get("signup"), "how": e.get("how"),
                    "unlocks": e.get("unlocks"), "limits": e.get("limits"), "status": e.get("status", ""),
                    "active": str(e.get("status", "")).startswith("active"),
                    "env": [{"name": v, "set": bool(os.environ.get(v))} for v in env]})
    return out
