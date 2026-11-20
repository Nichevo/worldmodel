"""War trackers: equipment lost (seen and claimed), ground held, and aid given, for the wars
listed in contract wars.yaml (Russia's war on Ukraine to start with).

oryx
    Oryx's lists of each side's lost equipment, counted only with photo or video proof:
    one page per side, read politely (two pages a refresh, at most once a day). Each read
    keeps the totals by category and by what happened (destroyed, damaged, abandoned,
    captured) as a small file per side and day, so the history grows with each refresh.
    Earlier history is filled in from the Internet Archive's monthly copies of the same
    pages, a few months a refresh (Settings: oryx_backfill). Pages saved by hand (Ctrl+S)
    in var\\manual\\oryx load too; put the date in the file name (oryx_RUS_2025-03-01.html)
    or it counts as today's.
ua_claimed_losses
    The Ukrainian General Staff's daily claimed Russian losses (tanks, artillery, drones,
    personnel ...), as collected on GitHub by Petro Ivaniuk (Kaggle "2022 Ukraine Russia
    War" dataset). These are one side's claims about the other and are not checked; the app
    shows them beside Oryx's seen losses, never merged.
deepstate
    DeepStateMap's daily map of the Ukrainian land Russia holds, saved each day as GeoJSON by
    the deepstate-map-data project on GitHub (one compressed file with every day since July
    2024). The area in km² is worked out for every day; the shape is kept for every Monday,
    every day of the last 90 days, and the latest, simplified to about 500 m (map layer
    front_line).
kiel_ukraine
    The Kiel Institute's Ukraine Support Tracker: aid promised to Ukraine by each donor,
    military, financial and humanitarian, in euro. Saved by hand (get.bat opens the page);
    the "Country Summary (€)" sheet is read.
"""

from __future__ import annotations

import gzip
import json
import logging
import math
import re
from datetime import date, datetime, timedelta
from html import unescape
from pathlib import Path

import duckdb

from worldmodel_contract import osint
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.cities import country_by_name
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS
from worldmodel_data.connectors.tabular import Rows, indicator, num, xlsx_rows, xlsx_sheet_names
from worldmodel_data.connectors.transport import stage_geo

log = logging.getLogger(__name__)

WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
WAYBACK = "https://web.archive.org/web/{ts}id_/{url}"
SNAPSHOT = re.compile(r"oryx_([A-Z]{3})_(\d{4}-\d{2}-\d{2})\.json$")


def _settings() -> dict:
    try:
        from worldmodel_contract.local import load_settings
        from worldmodel_data.config import paths
        return load_settings(paths().home)
    except Exception:  # noqa: BLE001 - settings unreadable: defaults
        return {}


def _losses_table(con: duckdb.DuckDBPyConnection, rows: list[tuple], table: str = "wl") -> str:
    con.execute(f"CREATE TABLE {table} (war_id VARCHAR, side VARCHAR, day DATE, category VARCHAR, status VARCHAR, "
                "count DOUBLE, basis VARCHAR)")
    if rows:
        con.executemany(f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    return f"SELECT DISTINCT ON (war_id, side, day, category, status, basis) * FROM {table}"


# ----------------------------------------------------------------------------- Oryx
def page_text(html: str) -> str:
    """An HTML page as plain lines of text."""
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|h\d|li|tr)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = unescape(t).replace("\xa0", " ")
    return "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in t.splitlines() if ln.strip())


_STATUS = re.compile(r"(destroyed|damaged|abandoned|captured)\s*:?\s*([\d,]+)", re.I)
_HEAD = re.compile(r"^(?P<head>[A-Z][^()\n]{2,90}?)\s*\(\s*(?P<n>[\d,]+)\s*,\s*of which:?\s*(?P<rest>[^)]*)\)", re.M)
_TOTAL = re.compile(r"^(?P<side>Russia|Ukraine)\s*-\s*(?P<n>[\d,]+)\s*,\s*of which:?\s*(?P<rest>.*)$", re.M | re.I)


def _n(s: str) -> float:
    return float(s.replace(",", ""))


def oryx_totals(html: str) -> dict[str, dict[str, float]]:
    """category id -> {total, destroyed, damaged, abandoned, captured} from an Oryx page."""
    text = page_text(html)
    out: dict[str, dict[str, float]] = {}
    m = _TOTAL.search(text)
    if m:
        out["total"] = {"total": _n(m["n"]), **{k.lower(): _n(v) for k, v in _STATUS.findall(m["rest"])}}
    for m in _HEAD.finditer(text):
        cid = osint.loss_category(m["head"])
        if cid and cid not in out:
            out[cid] = {"total": _n(m["n"]), **{k.lower(): _n(v) for k, v in _STATUS.findall(m["rest"])}}
    return out


def oryx_rows(war_id: str, side: str, day: date, totals: dict[str, dict[str, float]]) -> list[tuple]:
    return [(war_id, side, day, cid, status, v, "seen") for cid, d in totals.items() for status, v in d.items()]


class Oryx(Connector):
    source_id = "oryx"
    switch = "wars_fetch"
    fetch_every_days = 1
    keeps_files = True  # each day's totals are kept as a small file
    backfill_per_run = 6

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        from worldmodel_data.scrape import PageReader

        pages = [(w["id"], side, url) for w in osint.wars() for side, url in (w.get("oryx") or {}).items()]
        today = date.today().isoformat()
        last = self.last_vintage_dir(raw_dir)
        have = {p.name for p in last.iterdir()} if last else set()
        backfill = self._backfill_plan(pages, have) if _settings().get("oryx_backfill", True) else []
        with PageReader(self, planned=len(pages) + len(backfill)) as reader:
            for war_id, side, url in pages:
                tmp = raw_dir / f"oryx_{side}.html.part"
                html = reader.read(url, tmp, expect=r"of which", what=f"Oryx, {side} losses")
                self._keep(raw_dir, war_id, side, today, html)
                tmp.unlink(missing_ok=True)
            for war_id, side, url, ts in backfill:
                tmp = raw_dir / f"oryx_{side}_{ts}.html.part"
                try:
                    html = reader.read(WAYBACK.format(ts=ts, url=url), tmp, expect=r"of which",
                                       what=f"Oryx {side}, archived {ts[:8]}", missing_ok=True)
                except ConnectorError as exc:  # the archive turned us away: today's figures are already kept
                    log.info("oryx: archive copies left for another day (%s)", exc)
                    break
                if html:
                    self._keep(raw_dir, war_id, side, f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", html)
                tmp.unlink(missing_ok=True)
        return ", ".join(url for _, _, url in pages)

    @staticmethod
    def _keep(raw_dir: Path, war_id: str, side: str, day: str, html: str) -> None:
        totals = oryx_totals(html)
        if not totals:
            raise ConnectorError(f"oryx: no totals found on the {side} page; its layout may have changed")
        (raw_dir / f"oryx_{side}_{day}.json").write_text(json.dumps({"war": war_id, "side": side, "day": day,
                                                                       "totals": totals}), encoding="utf-8")

    def _backfill_plan(self, pages: list[tuple], have: set[str]) -> list[tuple]:
        """Archived copies to read this run: one a month back to the war's start, for months
        with no day kept yet, newest first, a few a run."""
        held = {(m.group(1), m.group(2)[:7]) for n in have if (m := SNAPSHOT.search(n))}
        plan = []
        for war_id, side, url in pages:
            try:
                r = self.client.get(WAYBACK_CDX, params={"url": url, "output": "json", "fl": "timestamp",
                                                         "filter": "statuscode:200", "collapse": "timestamp:6"})
                stamps = [row[0] for row in (r.json() or [])[1:]] if r.status_code == 200 else []
            except Exception:  # noqa: BLE001 - the archive is a nicety
                stamps = []
            for ts in sorted(stamps, reverse=True):
                if (side, f"{ts[:4]}-{ts[4:6]}") not in held:
                    plan.append((war_id, side, url, ts))
        plan.sort(key=lambda p: p[3], reverse=True)
        return plan[: self.backfill_per_run]

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = []
        for f in sorted(raw_dir.iterdir()):
            if f.suffix.lower() == ".json":
                d = json.loads(f.read_text(encoding="utf-8"))
                rows += oryx_rows(d["war"], d["side"], date.fromisoformat(d["day"]), d["totals"])
            elif f.suffix.lower() in (".html", ".htm"):  # saved by hand
                html = f.read_text(encoding="utf-8", errors="replace")
                side = "UKR" if re.search(r"ukrain", f.name, re.I) or re.search(r"^Ukraine\s*-\s*[\d,]+", page_text(html), re.M) else "RUS"
                m = re.search(r"(\d{4}-\d{2}-\d{2})", f.name)
                day = date.fromisoformat(m.group(1)) if m else datetime.fromtimestamp(f.stat().st_mtime).date()
                war_id = next((w["id"] for w in osint.wars() if side in (w.get("oryx") or {})), "russia_ukraine")
                rows += oryx_rows(war_id, side, day, oryx_totals(html))
        if not rows:
            raise ConnectorError(f"oryx: no loss totals read from {raw_dir}")
        self.history_queries = {"war_losses": _losses_table(con, rows)}
        log.info("oryx: %s days of totals", len({(r[1], r[2]) for r in rows}))
        return EMPTY_OBSERVATIONS


# ----------------------------------------------------------------------------- claimed losses
CLAIMED_BASE = "https://raw.githubusercontent.com/PetroIvaniuk/2022-Ukraine-Russia-War-Dataset/main/data/"
CLAIMED_FILES = ("russia_losses_equipment.json", "russia_losses_personnel.json")


def claimed_rows(war_id: str, side: str, records: list[dict]) -> list[tuple]:
    out = []
    for r in records:
        try:
            day = date.fromisoformat(str(r.get("date"))[:10])
        except ValueError:
            continue
        for key, cid in osint.CLAIMED_CATEGORIES.items():
            v = num(r.get(key))
            if v is not None:
                out.append((war_id, side, day, cid, "total", v, "claimed"))
    return out


class UAClaimedLosses(Connector):
    source_id = "ua_claimed_losses"
    switch = "wars_fetch"
    fetch_every_days = 1

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        for f in CLAIMED_FILES:
            self.get(CLAIMED_BASE + f, raw_dir / f)
        return CLAIMED_BASE

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        w = next((w for w in osint.wars() if (w.get("claimed") or {}).get("source") == self.source_id), None)
        if not w:
            raise ConnectorError("ua_claimed_losses: no war in wars.yaml uses this source")
        rows = []
        for f in sorted(raw_dir.glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            rows += claimed_rows(w["id"], w["claimed"]["side"], data if isinstance(data, list) else [])
        if not rows:
            raise ConnectorError(f"ua_claimed_losses: no figures read from {raw_dir}")
        self.history_queries = {"war_losses": _losses_table(con, rows)}
        return EMPTY_OBSERVATIONS


# ----------------------------------------------------------------------------- DeepState
DEEPSTATE = "https://raw.githubusercontent.com/cyterat/deepstate-map-data/main/deepstate-map-data.geojson.gz"
R_KM = 6371.0072  # the authalic Earth radius
FRONT_TOL = 0.005  # degrees, about 500 m
KEEP_DAILY_DAYS = 90


def area_km2(geom) -> float:
    """Area of a lon/lat shapely geometry in km², on a Lambert equal-area projection centred on it."""
    import numpy as np
    import shapely

    c = geom.centroid
    lam0, ph1 = math.radians(c.x), math.radians(c.y)

    def laea(xy):
        lam, ph = np.radians(xy[:, 0]), np.radians(xy[:, 1])
        k = np.sqrt(2 / (1 + math.sin(ph1) * np.sin(ph) + math.cos(ph1) * np.cos(ph) * np.cos(lam - lam0)))
        return np.column_stack((R_KM * k * np.cos(ph) * np.sin(lam - lam0),
                                R_KM * k * (math.cos(ph1) * np.sin(ph) - math.sin(ph1) * np.cos(ph) * np.cos(lam - lam0))))

    return shapely.transform(geom, laea).area


def front_days(features: list[dict]) -> dict[date, object]:
    from shapely.geometry import shape

    out = {}
    for ft in features:
        p = ft.get("properties") or {}
        raw = p.get("date") or p.get("update_date") or p.get("id")
        try:
            day = date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
        try:
            g = shape(ft.get("geometry"))
        except Exception:  # noqa: BLE001 - a broken shape is skipped
            continue
        if not g.is_valid:
            g = g.buffer(0)
        if not g.is_empty:
            out[day] = g
    return out


def _poly_json(geom) -> dict | None:
    from shapely.geometry import mapping

    g = geom.simplify(FRONT_TOL, preserve_topology=True)
    if g.is_empty:
        return None
    m = mapping(g)
    def rnd(c):
        return [rnd(x) for x in c] if c and isinstance(c[0], (list, tuple)) else [round(c[0], 4), round(c[1], 4)]
    return {"type": m["type"], "coordinates": rnd(m["coordinates"])}


class DeepState(Connector):
    source_id = "deepstate"
    switch = "wars_fetch"
    fetch_every_days = 1

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(DEEPSTATE, raw_dir / "deepstate-map-data.geojson.gz")
        return DEEPSTATE

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        w = next((w for w in osint.wars() if (w.get("front") or {}).get("source") == self.source_id), None)
        if not w:
            raise ConnectorError("deepstate: no war in wars.yaml uses this source")
        feats = []
        for f in sorted(raw_dir.iterdir()):
            if f.name.endswith(".gz"):
                feats += json.loads(gzip.decompress(f.read_bytes())).get("features") or []
            elif f.suffix.lower() in (".geojson", ".json"):
                d = json.loads(f.read_text(encoding="utf-8"))
                for ft in d.get("features") or []:  # a single day's file: its date from the name
                    m = re.search(r"(\d{4})-?(\d{2})-?(\d{2})", f.name)
                    if m and not (ft.get("properties") or {}).get("date"):
                        ft.setdefault("properties", {})["date"] = f"{m[1]}-{m[2]}-{m[3]}"
                    feats.append(ft)
        days = front_days(feats)
        if not days:
            raise ConnectorError(f"deepstate: no dated shapes read from {raw_dir}")
        holder, land_of = w["front"]["holder"], w["front"]["land_of"]
        latest = max(days)
        areas, geo = [], []
        for day, g in sorted(days.items()):
            km2 = area_km2(g)
            areas.append((w["id"], day, holder, land_of, round(km2, 1)))
            if day == latest or day.weekday() == 0 or day >= latest - timedelta(days=KEEP_DAILY_DAYS):
                gj = _poly_json(g)
                if gj:
                    geo.append(("front_line", f"{w['id']}:{day.isoformat()}", f"{w['short']}: held by {holder}, {day.isoformat()}",
                                2 if day != latest else 1, {"war": w["id"], "day": day.isoformat(), "area_km2": round(km2),
                                                            "holder": holder, "land_of": land_of}, [holder, land_of], gj))
        con.execute("CREATE TABLE wa (war_id VARCHAR, day DATE, holder VARCHAR, land_of VARCHAR, area_km2 DOUBLE)")
        con.executemany("INSERT INTO wa VALUES (?, ?, ?, ?, ?)", areas)
        self.history_queries = {"war_areas": "SELECT * FROM wa", "geo_features": stage_geo(con, geo)}
        log.info("deepstate: %s days, %s shapes kept, latest %s (%s km²)", len(areas), len(geo), latest, f"{areas[-1][4]:,.0f}")
        return EMPTY_OBSERVATIONS


# ----------------------------------------------------------------------------- Kiel Ukraine Support Tracker
KIEL_COLUMNS = {"military": "ukraine_aid_military_eur", "financial": "ukraine_aid_financial_eur",
                "humanitarian": "ukraine_aid_humanitarian_eur", "total": "ukraine_aid_total_eur"}


def kiel_rows(table: list[list]) -> dict[str, dict[str, float]]:
    """entity id -> {indicator: € billion} from a country summary sheet (a header row naming
    the country column and military/financial/humanitarian/total columns)."""
    head_at, cols = None, {}
    for i, row in enumerate(table[:40]):
        cells = [str(c or "").strip().lower() for c in row]
        if any("countr" in c or "donor" in c for c in cells) and any("military" in c for c in cells):
            head_at = i
            for j, c in enumerate(cells):
                if "countr" in c or "donor" in c:
                    cols.setdefault("country", j)
                for word, ind in KIEL_COLUMNS.items():
                    if c.startswith(word) or c == word or (word in c and "%" not in c and "gdp" not in c):
                        cols.setdefault(ind, j)
            break
    if head_at is None or "country" not in cols:
        return {}
    out: dict[str, dict[str, float]] = {}
    for row in table[head_at + 1:]:
        if len(row) <= cols["country"]:
            continue
        ent = country_by_name(str(row[cols["country"]] or "").strip())
        if not ent:
            continue
        vals = {ind: num(row[j]) for ind, j in cols.items() if ind != "country" and j < len(row) and num(row[j]) is not None}
        if vals:
            out[ent] = vals
    return out


class KielUkraine(Connector):
    source_id = "kiel_ukraine"
    manual = True

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("kiel_ukraine: saved by hand (get.bat opens the Kiel Institute's page)")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(f for f in raw_dir.iterdir() if f.suffix.lower() in (".xlsx", ".xlsm"))
        if not files:
            raise ConnectorError(f"kiel_ukraine: no Excel file in {raw_dir}")
        f = files[-1]
        found = {}
        names = xlsx_sheet_names(f)
        for name in sorted(names, key=lambda n: ("summary" not in n.lower(), "€" not in n and "eur" not in n.lower())):
            found = kiel_rows(xlsx_rows(f, name))
            if found:
                break
        if not found:
            raise ConnectorError(f"kiel_ukraine: no country summary sheet found in {f.name} (sheets: {', '.join(names[:12])})")
        m = re.search(r"(20\d\d)", f.name)
        year = int(m.group(1)) if m else int(release[:4])
        obs = Rows()
        for ent, vals in found.items():
            for ind, v in vals.items():
                obs.add("iso3", ent, ind, year, v)
        label = {"ukraine_aid_military_eur": "military", "ukraine_aid_financial_eur": "financial",
                 "ukraine_aid_humanitarian_eur": "humanitarian", "ukraine_aid_total_eur": "all"}
        self.listed_indicators = [indicator(
            ind, f"Aid to Ukraine promised, {label[ind]}",
            f"Aid promised to Ukraine since January 2022, {label[ind]}, € billion, as tracked by the Kiel Institute "
            "(the year is the tracker's release).", "€ bn", "conflict", self.source_id, f"kiel:{ind}", decimals=2,
            aggregation={"method": "sum"}) for ind in KIEL_COLUMNS.values()]
        return obs.stage(con, self.source_id, vintage)
