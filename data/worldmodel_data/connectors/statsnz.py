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
import gzip
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
from typing import Iterator

import duckdb

from worldmodel_contract import catalogue
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.tabular import Rows, indicator, num

log = logging.getLogger(__name__)

STATSNZ_API = "https://api.data.stats.govt.nz/rest"
FLOWS_URL = STATSNZ_API + "/dataflow/all/all/latest"
DATA_URL = STATSNZ_API + "/data/{agency},{id},{version}/{key}?dimensionAtObservation=AllDimensions"
STRUCTURE_URL = STATSNZ_API + "/dataflow/{agency}/{id}/{version}?references=all"
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
    """The table for a measure: its `table` when Stats NZ still lists it; else all `find` words
    in its name, most `prefer` words, newest id."""
    named = next((f for f in flows if m.get("table") and f["id"].upper() == str(m["table"]).upper()), None)
    if named:
        return named
    want = [plain(w) for w in m.get("find", [])]
    prefer = [plain(w) for w in m.get("prefer", [])]
    hits = [f for f in flows if all(w in plain(f["name"]) for w in want)]
    if not hits:
        return None
    return max(hits, key=lambda f: (sum(1 for w in prefer if w in plain(f["name"])), f["id"]))


def read_flows(data: bytes) -> list[dict]:
    """The table list as Stats NZ sent it: SDMX-ML (XML) or SDMX-JSON, with or without a byte
    order mark or gzip. Anything else (a web page, a message) fails saying what came back."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    text = data.decode("utf-8-sig", errors="replace").lstrip("\ufeff \r\n\t")
    if text.startswith("{"):
        try:
            return parse_flows_json(json.loads(text))
        except ValueError as exc:
            raise ConnectorError(f"statsnz: the table list is not valid JSON ({exc})") from None
    if not text.startswith("<") or text[:200].lower().lstrip().startswith(("<!doctype html", "<html")):
        snippet = " ".join(text[:160].split())
        raise ConnectorError(f"statsnz: the table list came back as neither XML nor JSON; it starts: {snippet!r}")
    try:
        return parse_flows(text)
    except ET.ParseError as exc:
        snippet = " ".join(text[:160].split())
        raise ConnectorError(f"statsnz: the table list could not be read ({exc}); it starts: {snippet!r}") from None


def parse_flows_json(d: dict) -> list[dict]:
    """Dataflows from SDMX-JSON structure messages ({"data": {"dataflows": [...]}})."""
    flows = (d.get("data") or d).get("dataflows") or (d.get("Dataflows") or {}).get("Dataflow") or []
    out = []
    for f in flows:
        names = f.get("names") or {}
        name = names.get("en") if isinstance(names, dict) else None
        name = name or f.get("name") or ""
        if isinstance(name, dict):
            name = name.get("en") or next(iter(name.values()), "")
        if f.get("id"):
            out.append({"agency": f.get("agencyID") or "STATSNZ", "id": f["id"], "version": f.get("version") or "1.0",
                        "name": str(name).strip()})
    return out


def parse_flows(xml: str) -> list[dict]:
    out = []
    root = ET.fromstring(xml.lstrip("\ufeff"))
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


def _is_time(dim_id: str, name: str) -> bool:
    """A table's year column: TIME_PERIOD, or a dimension of its own such as CEN23_YEAR_001
    ("Census year") or YEAR_POPES_SUB_004 ("Year at 30 June")."""
    d = dim_id.upper()
    return d in ("TIME_PERIOD", "TIME", "YEAR") or "YEAR" in d.split("_") or name.startswith(("year", "census year", "time"))


def _want(keep: dict[str, str], dim_name: str, dim_id: str) -> str | None:
    return next((v for k, v in keep.items() if k and k != "*" and (k in dim_name or k in plain(dim_id))), None)


def _rows(src) -> Iterator[list[str]]:
    """CSV rows from text, or from a file read a line at a time (census tables run to gigabytes)."""
    if isinstance(src, Path):
        with src.open(encoding="utf-8-sig", errors="replace", newline="") as f:
            yield from csv.reader(f)
    else:
        yield from csv.reader(io.StringIO(src.lstrip("\ufeff")))


def read_table(src, m: dict, labels: dict[str, dict[str, str]] | None = None) -> dict[tuple[str, int], float]:
    """(region entity, year) -> value from an SDMX-CSV table (text or a file), for one measure.
    `labels` (dimension id -> code -> name, from the table's structure) names codes the file
    gives bare. Read twice, a row at a time: once to see each column's values, once to keep."""
    labels = {k.upper(): v for k, v in (labels or {}).items()}
    it = _rows(src)
    head = next(it, None)
    if not head:
        return {}
    ids = [h.split(":", 1)[0].strip().upper() for h in head]
    names = [plain(h.split(":", 1)[1] if ":" in h else h) for h in head]
    if "OBS_VALUE" not in ids:
        raise ConnectorError("statsnz: the table has no OBS_VALUE column (not SDMX-CSV)")
    vi = ids.index("OBS_VALUE")
    ti = next((i for i, x in enumerate(ids) if x in ("TIME_PERIOD", "TIME")), None)
    if ti is None:
        ti = next((i for i in range(vi) if _is_time(ids[i], names[i])), None)
    if ti is None:
        raise ConnectorError(f"statsnz: the table has no year column (columns: {', '.join(ids[:vi])})")
    dims = [i for i in range(vi) if i != ti and ids[i] not in ("DATAFLOW", "STRUCTURE", "STRUCTURE_ID", "ACTION")]

    def label(i: int, v: str) -> str:
        if ":" in v:
            return v
        name = labels.get(ids[i], {}).get(v.strip())
        return f"{v}: {name}" if name else v
    seen: dict[int, Counter] = {i: Counter() for i in dims}
    for r in it:
        if len(r) > vi:
            for i in dims:
                seen[i][r[i]] += 1
    # The area dimension: the one naming the most regions.
    regions = {i: {v: region_of(label(i, v)) for v in seen[i]} for i in dims}
    area = max(dims, key=lambda i: len(set(regions[i].values()) - {None}), default=None)
    if area is None or len(set(regions[area].values()) - {None}) < 8:
        return {}
    chosen: dict[int, str] = {}
    keep = {plain(k): plain(v) for k, v in (m.get("keep") or {}).items()}
    anywhere = keep.get("*")
    used = set()
    for i in dims:
        if i == area:
            continue
        values = seen[i]
        want = _want(keep, names[i], ids[i])
        pick = None
        if want:
            pick = next((v for v in values if want in plain(label(i, v).partition(":")[2] or v)), None)
            if pick is None:
                log.warning("statsnz: %s: no '%s' in %s; skipped", m["id"], want, head[i])
                return {}
            used.add(want)
        if pick is None and anywhere:
            pick = next((v for v in values if anywhere in plain(label(i, v).partition(":")[2] or v)), None)
            if pick is not None:
                used.add("*")
        if pick is None and len(values) == 1:
            pick = next(iter(values))
        if pick is None:
            pick = next((v for v in values if is_total(label(i, v))), None)
        if pick is None:
            pick = values.most_common(1)[0][0]
            log.info("statsnz: %s: no total in %s; using %s", m["id"], head[i], pick)
        chosen[i] = pick
    if anywhere and "*" not in used:
        log.warning("statsnz: %s: no '%s' in any column; skipped", m["id"], anywhere)
        return {}
    out: dict[tuple[str, int], float] = {}
    for r in _rows(src) if isinstance(src, Path) else _rows(src):
        if len(r) <= vi or r is head or r[0] == head[0] and r[vi] == head[vi]:
            continue
        if any(r[i] != v for i, v in chosen.items()):
            continue
        ent = regions[area].get(r[area])
        y = re.match(r"\s*(\d{4})", r[ti])
        v = num(r[vi])
        if ent and y and v is not None:
            out[(ent, int(y.group(1)))] = v
    return out


# ----------------------------------------------------------------------------- asking for less
def parse_structure(xml: bytes | str) -> dict:
    """A table's dimensions in key order and the names of their codes, from the SDMX-ML
    structure (dataflow with references=all): {"dims": [(id, name, codelist)], "codes": {codelist: {code: name}}}."""
    text = xml.decode("utf-8-sig", errors="replace") if isinstance(xml, bytes) else xml
    root = ET.fromstring(text.lstrip("\ufeff"))
    tag = lambda el: el.tag.rsplit("}", 1)[-1]  # noqa: E731

    def name_of(el) -> str:
        found = ""
        for c in el:
            if tag(c) == "Name" and (not found or c.get("{http://www.w3.org/XML/1998/namespace}lang") == "en"):
                found = (c.text or "").strip()
        return found
    codes: dict[str, dict[str, str]] = {}
    cl_names: dict[str, str] = {}
    for el in root.iter():
        if tag(el) == "Codelist" and el.get("id"):
            cl_names[el.get("id")] = name_of(el)
            codes[el.get("id")] = {c.get("id"): name_of(c) for c in el if tag(c) == "Code" and c.get("id")}
    dims = []
    for el in root.iter():
        if tag(el) != "Dimension" or not el.get("id"):
            continue
        ref = next((r for r in el.iter() if tag(r) == "Ref" and (r.get("class") == "Codelist" or r.get("package") == "codelist")), None)
        cl = ref.get("id") if ref is not None else None
        dims.append((int(el.get("position") or len(dims) + 1), el.get("id"), cl_names.get(cl or "", ""), cl))
    dims.sort()
    return {"dims": [(d, n, cl) for _, d, n, cl in dims], "codes": codes}


def plan_key(struct: dict, ms: list[dict]) -> str | None:
    """The data key asking only for what the measures need: the regions on the area
    dimension, every year, and on the others the totals and the values `keep` asks for.
    None when the structure gives no area dimension (then the whole table is asked for)."""
    dims, codes = struct["dims"], struct["codes"]
    area = None
    for d, _, cl in dims:
        hits = [c for c, n in codes.get(cl, {}).items() if region_of(f"{c}: {n}")]
        if len(hits) >= 8 and (area is None or len(hits) > len(area[1])):
            area = (d, hits)
    if area is None:
        return None
    parts = []
    for d, name, cl in dims:
        cs = codes.get(cl, {})
        if d == area[0]:
            parts.append("+".join(sorted(area[1])))
            continue
        if _is_time(d, plain(name)) or not cs:
            parts.append("")
            continue
        want: set[str] = set()
        for m in ms:
            keep = {plain(k): plain(v) for k, v in (m.get("keep") or {}).items()}
            w = _want(keep, plain(name), d)
            for v in [w, keep.get("*")]:
                if v:
                    want |= {c for c, n in cs.items() if v in plain(n)}
        want |= {c for c, n in cs.items() if is_total(f"{c}: {n}")}
        parts.append("+".join(sorted(want)) if want and len(cs) > 1 else "")
    return ".".join(parts)


class StatsNZ(Connector):
    source_id = "statsnz"
    pack = "nz"
    needs_env = ("STATSNZ_API_KEY",)
    fetch_every_days = 30
    fetch_version = 2  # 2: asks for the regions and totals only (whole census tables ran to gigabytes); tables named in statsnz.yaml
    stage_version = 2  # 2: year columns such as CEN23_YEAR_001; bare area codes named from the structure; read a row at a time

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        key = self.env("STATSNZ_API_KEY")
        hdr = {"Ocp-Apim-Subscription-Key": key}
        try:
            self.get(FLOWS_URL, raw_dir / "dataflows.xml",
                     headers={**hdr, "Accept": "application/vnd.sdmx.structure+xml;version=2.1, application/xml;q=0.9, "
                                    "application/vnd.sdmx.structure+json;q=0.8, */*;q=0.5"})
        except ConnectorError as exc:
            if "HTTP 401" in str(exc) or "HTTP 403" in str(exc):
                raise ConnectorError("statsnz: the Data Explorer refused the key (check STATSNZ_API_KEY in .env: the "
                                     "primary key of your Aotearoa Data Explorer subscription)") from exc
            raise
        flows = read_flows((raw_dir / "dataflows.xml").read_bytes())
        if not flows:
            raise ConnectorError("statsnz: the table list came back empty")
        with (raw_dir / "statsnz_dataflows.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["agency", "id", "version", "name"])
            w.writerows([[x["agency"], x["id"], x["version"], x["name"]] for x in flows])
        picks, done = {}, set()
        by_flow: dict[str, list[dict]] = {}
        for m in measures():
            f = pick_flow(flows, m)
            picks[m["id"]] = f["id"] if f else None
            if not f:
                log.warning("statsnz: no table found for %s (words: %s)", m["id"], ", ".join(m.get("find", [])))
                continue
            by_flow.setdefault(f["id"], []).append(m)
        for fid, ms in by_flow.items():
            f = next(x for x in flows if x["id"] == fid)
            # Ask for the regions and the totals only: a whole census table can be gigabytes.
            key = "all"
            try:
                self.get(STRUCTURE_URL.format(**f), raw_dir / f"{fid}.structure.xml",
                         headers={**hdr, "Accept": "application/vnd.sdmx.structure+xml;version=2.1, application/xml;q=0.9"}, cached=False)
                struct = parse_structure((raw_dir / f"{fid}.structure.xml").read_bytes())
                key = plan_key(struct, ms) or "all"
                (raw_dir / f"{fid}.labels.json").write_text(json.dumps({d: struct["codes"].get(cl, {}) for d, _, cl in struct["dims"]},
                                                                       ensure_ascii=False), encoding="utf-8")
                (raw_dir / f"{fid}.structure.xml").unlink(missing_ok=True)
            except (ConnectorError, ET.ParseError, OSError) as exc:
                log.warning("statsnz: %s: structure not read (%s); asking for the whole table", fid, exc)
            try:
                self.get(DATA_URL.format(**f, key=key), raw_dir / f"{fid}.csv", cached=False,
                         headers={**hdr, "Accept": "application/vnd.sdmx.data+csv;labels=both"})
                done.add(fid)
            except ConnectorError as exc:
                log.warning("statsnz: %s (%s) not downloaded: %s", fid, f["name"], exc)
                for m in ms:
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
            texts: list[Path] = []
            if picks.get(m["id"]) and picks[m["id"]].upper() in files:
                texts.append(files[picks[m["id"]].upper()])
            elif not picks:  # files saved by hand: match by file name or the table named inside
                want = [plain(w) for w in m.get("find", [])]
                for f in files.values():
                    with f.open(encoding="utf-8-sig", errors="replace") as fh:
                        first = plain(f.stem + " " + fh.read(2000))
                    if (m.get("table") and str(m["table"]).lower() in first.replace(" ", "_")) or all(w in first for w in want):
                        texts.append(f)
            for t in texts:
                lab = raw_dir / f"{t.stem}.labels.json"
                got = read_table(t, m, json.loads(lab.read_text(encoding="utf-8")) if lab.exists() else None)
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
