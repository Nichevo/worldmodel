"""Stats NZ Aotearoa Data Explorer: figures for New Zealand's 16 regions.

statsnz
    The Data Explorer's SDMX API (api.data.stats.govt.nz), with the free key
    STATSNZ_API_KEY (header Ocp-Apim-Subscription-Key). Each refresh lists the tables
    (dataflows), picks one per measure in the contract's statsnz.yaml by the words in
    its name, and downloads it as SDMX-CSV with labels. Rows are kept for the regional
    council areas, with every other dimension at its total unless statsnz.yaml asks for
    a value (Māori in an ethnic group table, say). The list of tables is kept beside the
    data as statsnz_dataflows.csv, so a renamed table is easy to find again.
    Files saved by hand from the Data Explorer into var/manual/statsnz are read the same
    way, matched to a measure by their file name or the table name inside them.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import duckdb

from worldmodel_contract import catalogue
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.tabular import Rows, indicator, num

log = logging.getLogger(__name__)

STATSNZ_API = "https://api.data.stats.govt.nz/rest"
FLOWS_URL = STATSNZ_API + "/dataflow/all/all/latest"
DATA_URL = STATSNZ_API + "/data/{agency},{id},{version}/all?dimensionAtObservation=AllDimensions"
TOTAL_CODES = {"99", "999", "9999", "T", "_T", "TOTAL", "TOT", "ALL", "_Z"}


def plain(s) -> str:
    """Lower case, no macrons or punctuation, single spaces."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s.lower()).split())


def measures() -> list[dict]:
    with (catalogue.CATALOGUE_DIR / "statsnz.yaml").open(encoding="utf-8") as f:
        import yaml
        return yaml.safe_load(f)["measures"]


@lru_cache
def region_names() -> dict[str, str]:
    """Plain region name (and synonyms, with or without "region") -> entity id."""
    subs = {r["entity_id"] for r in catalogue.subdivisions() if r["parent_id"] == "NZL"}
    out = {}
    for e in catalogue.entities().values():
        if e.entity_id not in subs:
            continue
        for n in [e.name, e.short_name, *e.synonyms.split("|")]:
            p = plain(n)
            if p:
                out[p] = e.entity_id
                out[re.sub(r"\s*region$", "", p)] = e.entity_id
    return out


def region_of(label: str) -> str | None:
    """The region an SDMX value ('01: Northland Region', 'Northland') names, if any."""
    code, _, text = str(label or "").partition(":")
    text = text if text else code
    p = plain(text)
    names = region_names()
    return names.get(p) or names.get(re.sub(r"\s*region$", "", p))


def is_total(label: str) -> bool:
    code, _, text = str(label or "").partition(":")
    return code.strip().upper() in TOTAL_CODES or plain(text or code).startswith("total") or plain(text) in ("all", "all ages")


def pick_flow(flows: list[dict], m: dict) -> dict | None:
    """The table for a measure: all `find` words in its name; most `prefer` words; newest id."""
    want = [plain(w) for w in m.get("find", [])]
    prefer = [plain(w) for w in m.get("prefer", [])]
    hits = [f for f in flows if all(w in plain(f["name"]) for w in want)]
    if not hits:
        return None
    return max(hits, key=lambda f: (sum(1 for w in prefer if w in plain(f["name"])), f["id"]))


def parse_flows(xml: str) -> list[dict]:
    out = []
    root = ET.fromstring(xml)
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "Dataflow" or not el.get("id"):
            continue
        name = ""
        for c in el:
            if c.tag.rsplit("}", 1)[-1] == "Name" and (not name or c.get("{http://www.w3.org/XML/1998/namespace}lang") == "en"):
                name = (c.text or "").strip()
        out.append({"agency": el.get("agencyID") or "STATSNZ", "id": el.get("id"), "version": el.get("version") or "1.0",
                    "name": name})
    return out


def read_table(text: str, m: dict) -> dict[tuple[str, int], float]:
    """(region entity, year) -> value from an SDMX-CSV table, for one measure."""
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        return {}
    head = rows[0]
    ids = [h.split(":", 1)[0].strip().upper() for h in head]
    names = [plain(h.split(":", 1)[1] if ":" in h else h) for h in head]
    if "OBS_VALUE" not in ids:
        raise ConnectorError("statsnz: the table has no OBS_VALUE column (not SDMX-CSV)")
    vi = ids.index("OBS_VALUE")
    ti = next((i for i, x in enumerate(ids) if x in ("TIME_PERIOD", "TIME", "YEAR")), None)
    if ti is None:
        raise ConnectorError("statsnz: the table has no TIME_PERIOD column")
    dims = [i for i in range(vi) if i != ti and ids[i] not in ("DATAFLOW", "STRUCTURE", "STRUCTURE_ID", "ACTION")]
    body = [r for r in rows[1:] if len(r) > vi]
    # The area dimension: the one naming the most regions.
    area = max(dims, key=lambda i: len({region_of(r[i]) for r in body} - {None}), default=None)
    if area is None or len({region_of(r[area]) for r in body} - {None}) < 8:
        return {}
    chosen: dict[int, str] = {}
    keep = {plain(k): plain(v) for k, v in (m.get("keep") or {}).items()}
    for i in dims:
        if i == area:
            continue
        values = Counter(r[i] for r in body)
        want = next((v for k, v in keep.items() if k and (k in names[i] or k in plain(ids[i]))), None)
        pick = None
        if want:
            pick = next((v for v in values if want in plain(v.partition(":")[2] or v)), None)
        if pick is None and len(values) == 1:
            pick = next(iter(values))
        if pick is None:
            pick = next((v for v in values if is_total(v)), None)
        if pick is None:
            pick = values.most_common(1)[0][0]
            log.info("statsnz: %s: no total in %s; using %s", m["id"], head[i], pick)
        chosen[i] = pick
    out: dict[tuple[str, int], float] = {}
    for r in body:
        if any(r[i] != v for i, v in chosen.items()):
            continue
        ent = region_of(r[area])
        y = re.match(r"\s*(\d{4})", r[ti])
        v = num(r[vi])
        if ent and y and v is not None:
            out[(ent, int(y.group(1)))] = v
    return out


class StatsNZ(Connector):
    source_id = "statsnz"
    pack = "nz"
    needs_env = ("STATSNZ_API_KEY",)
    fetch_every_days = 30

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        key = self.env("STATSNZ_API_KEY")
        hdr = {"Ocp-Apim-Subscription-Key": key}
        try:
            self.get(FLOWS_URL, raw_dir / "dataflows.xml",
                     headers={**hdr, "Accept": "application/vnd.sdmx.structure+xml;version=2.1"})
        except ConnectorError as exc:
            if "HTTP 401" in str(exc) or "HTTP 403" in str(exc):
                raise ConnectorError("statsnz: the Data Explorer refused the key (check STATSNZ_API_KEY in .env: the "
                                     "primary key of your Aotearoa Data Explorer subscription)") from exc
            raise
        flows = parse_flows((raw_dir / "dataflows.xml").read_text(encoding="utf-8", errors="replace"))
        with (raw_dir / "statsnz_dataflows.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["agency", "id", "version", "name"])
            w.writerows([[x["agency"], x["id"], x["version"], x["name"]] for x in flows])
        picks, done = {}, set()
        for m in measures():
            f = pick_flow(flows, m)
            picks[m["id"]] = f["id"] if f else None
            if not f:
                log.warning("statsnz: no table found for %s (words: %s)", m["id"], ", ".join(m.get("find", [])))
                continue
            if f["id"] in done:
                continue
            try:
                self.get(DATA_URL.format(**f), raw_dir / f"{f['id']}.csv",
                         headers={**hdr, "Accept": "application/vnd.sdmx.data+csv;labels=both"})
                done.add(f["id"])
            except ConnectorError as exc:
                log.warning("statsnz: %s (%s) not downloaded: %s", f["id"], f["name"], exc)
                picks[m["id"]] = None
            time.sleep(1)
        (raw_dir / "statsnz_picks.json").write_text(json.dumps(picks, indent=1), encoding="utf-8")
        if not done:
            raise ConnectorError("statsnz: no region table could be found or downloaded; the table list is in "
                                 "statsnz_dataflows.csv beside the raw files")
        return f"Stats NZ Data Explorer, {len(done)} tables"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        picks_file = raw_dir / "statsnz_picks.json"
        picks = json.loads(picks_file.read_text(encoding="utf-8")) if picks_file.exists() else {}
        files = {f.stem.upper(): f for f in raw_dir.glob("*.csv") if f.name != "statsnz_dataflows.csv"}
        rows, found = Rows(), []
        for m in measures():
            texts = []
            if picks.get(m["id"]) and picks[m["id"]].upper() in files:
                texts.append(files[picks[m["id"]].upper()].read_text(encoding="utf-8-sig", errors="replace"))
            elif not picks:  # files saved by hand: match by file name or the table named inside
                want = [plain(w) for w in m.get("find", [])]
                for f in files.values():
                    t = f.read_text(encoding="utf-8-sig", errors="replace")
                    first = plain(f.stem + " " + t[:2000])
                    if all(w in first for w in want):
                        texts.append(t)
            for t in texts:
                got = read_table(t, m)
                for (ent, y), v in got.items():
                    rows.add("iso3", ent, m["id"], y, v)
                if got:
                    found.append(m["id"])
                    break
        if not len(rows):
            raise ConnectorError(f"statsnz: no region figures read from {raw_dir}")
        missing = [m["id"] for m in measures() if m["id"] not in found]
        if missing:
            log.warning("statsnz: no figures for %s", ", ".join(missing))
        self.listed_indicators = [
            indicator(m["id"], m["name"], m["description"] + " Stats NZ.", m["unit"], m.get("domain", "population"),
                      self.source_id, f"{picks.get(m['id']) or 'file'}:{m['id']}", decimals=m.get("decimals", 0), default_on=False,
                      bounds=(0, 1e12))
            for m in measures() if m["id"] in found]
        return rows.stage(con, self.source_id, vintage)
