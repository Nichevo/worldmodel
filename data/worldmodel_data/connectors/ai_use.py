"""AI use by country.

eurostat_ai
    Eurostat isoc_eb_ai, "Artificial intelligence by size class of enterprise":
    the share of enterprises (10 or more employees, excluding the financial
    sector) using at least one AI technology (indic_is E_AI_TANY, unit PC_ENT),
    for EU members, EFTA and candidate countries, from 2021. Downloaded as
    SDMX-CSV from Eurostat's dissemination API.

anthropic_aei
    Anthropic Economic Index: how much people in each country use Claude, as the
    share of all use (usage_pct) and use per working-age person against the world
    average (usage_per_capita_index, 1 = average). The dataset lives on Hugging
    Face (Anthropic/EconomicIndex); the newest release's enriched Claude.ai file
    (aei_enriched_claude_ai_*.csv) is found from the dataset's file list. A copy
    can be given instead: `.\\load.bat anthropic_aei <file.csv>`. Long format:
    geo_id, geography, date_start, facet, variable, cluster_name, value.

ms_ai_diffusion
    Microsoft AI Economy Institute, AI Diffusion Report: the share of the
    working-age population using AI tools, by country. Published as a report with
    a downloadable table, so it is loaded by hand: `.\\load.bat ms_ai_diffusion
    <file.csv or .xlsx>`. Any table with a country column (name or ISO code) and a
    column whose name says share, usage, users, adoption or diffusion is read; the
    year comes from a year column, else the file name, else the load date.
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import datetime
from pathlib import Path

import duckdb

from worldmodel_contract import catalogue
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.housing import code, col, year_of
from worldmodel_data.connectors.tabular import Rows, entity_for, indicator, key, num, xlsx_rows

log = logging.getLogger(__name__)

# Eurostat's own two-letter codes that differ from ISO 3166.
EUROSTAT_GEO = {"EL": "GR", "UK": "GB"}


def iso_entity(c: str) -> str | None:
    c = (c or "").strip().upper()
    c = EUROSTAT_GEO.get(c, c)
    return entity_for("iso2", c) if len(c) == 2 else entity_for("iso3", c) if len(c) == 3 else None


# ------------------------------------------------------------------------------------------ Eurostat
EUROSTAT_URL = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/isoc_eb_ai?format=SDMX-CSV&compressed=false"
SIZE_PREFERENCE = ("10_C10_S951_XK", "10_C10", "GE10")


class EurostatAI(Connector):
    source_id = "eurostat_ai"
    fetch_every_days = 28  # yearly survey

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(EUROSTAT_URL, raw_dir / "isoc_eb_ai.csv")
        return EUROSTAT_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        p = raw_dir / "isoc_eb_ai.csv"
        with p.open(encoding="utf-8-sig", newline="") as f:
            data = list(csv.DictReader(f))
        if not data:
            raise ConnectorError(f"eurostat_ai: no rows in {p.name}")
        h = data[0].keys()
        ind_c, unit_c, size_c, geo_c, period, obs = (col(h, "indic_is"), col(h, "unit"), col(h, "size_emp"),
                                                     col(h, "geo"), col(h, "TIME_PERIOD"), col(h, "OBS_VALUE"))
        if not all((ind_c, geo_c, period, obs)):
            raise ConnectorError("eurostat_ai: the file lacks indic_is, geo, TIME_PERIOD or OBS_VALUE")
        picked = [r for r in data if code(r[ind_c]) == "E_AI_TANY" and (not unit_c or code(r[unit_c]) == "PC_ENT")]
        sizes = {code(r[size_c]) for r in picked} if size_c else {""}
        size = next((s for s in SIZE_PREFERENCE if s in sizes), sorted(sizes)[0] if sizes else "")
        rows = Rows()
        for r in picked:
            if size_c and code(r[size_c]) != size:
                continue
            ent = iso_entity(code(r[geo_c]))
            y = year_of(r[period])
            if ent and y:
                rows.add("iso3", ent, "ai_use_enterprises", y, num(r[obs]))
        if not len(rows):
            raise ConnectorError("eurostat_ai: no E_AI_TANY values (share of enterprises using AI) in the file")
        self.listed_indicators = [indicator(
            "ai_use_enterprises", "Enterprises using AI (% of enterprises)",
            "Share of enterprises with 10 or more employees (outside finance) using at least one artificial "
            "intelligence technology, such as text mining, speech recognition, machine learning or generating "
            "content. Eurostat ICT usage survey, EU and nearby countries.",
            "% of enterprises", "technology", self.source_id, "isoc_eb_ai:E_AI_TANY", decimals=1,
            bounds=(0, 100), aggregation={"method": "none"})]
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------- Anthropic Economic Index
HF_API = "https://huggingface.co/api/datasets/Anthropic/EconomicIndex"
HF_FILE = "https://huggingface.co/datasets/Anthropic/EconomicIndex/resolve/main/{path}"
KNOWN_FILE = "release_2025_09_15/data/output/aei_enriched_claude_ai_2025-08-04_to_2025-08-11.csv"
AEI_FILE = re.compile(r"aei_enriched_claude_ai_(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})\.csv$")
AEI_VARIABLES = {
    "usage_per_capita_index": ("ai_claude_use_per_capita_index", "Claude use per person (index, world = 1)",
                               "How much people in the country use Claude for each person of working age, against the "
                               "world average: 1 is average, 2 twice as much. Anthropic Economic Index, one week of "
                               "Claude.ai conversations.", "index, world = 1", 2),
    "usage_pct": ("ai_claude_use_share", "Share of world Claude use (%)",
                  "The country's share of all Claude.ai conversations in the sample week. Anthropic Economic Index.",
                  "% of world use", 2),
}


class AnthropicAEI(Connector):
    source_id = "anthropic_aei"
    fetch_every_days = 28

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:
            m = AEI_FILE.search(f.name)
            if m:
                return m.group(2)
        return None

    def newest_file(self) -> str:
        try:
            r = self.client.get(HF_API)
            r.raise_for_status()
            names = [s.get("rfilename", "") for s in r.json().get("siblings", [])]
            found = sorted((AEI_FILE.search(n).group(2), n) for n in names if AEI_FILE.search(n))
            if found:
                return found[-1][1]
        except Exception as exc:  # noqa: BLE001 - fall back to the known file
            log.warning("anthropic_aei: could not list the dataset's files (%s); trying the known file", exc)
        return KNOWN_FILE

    def download(self, raw_dir: Path, release: str) -> str:
        path = self.newest_file()
        url = HF_FILE.format(path=path)
        self.get(url, raw_dir / Path(path).name)
        return url

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() == ".csv")
        if not files:
            raise ConnectorError(f"anthropic_aei: no .csv file in {raw_dir}")
        rows, seen = Rows(), set()
        for p in files:
            m = AEI_FILE.search(p.name)
            with p.open(encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                h = reader.fieldnames or []
                geo, geog, var, val, cluster, facet, start = (col(h, "geo_id"), col(h, "geography"), col(h, "variable"),
                                                             col(h, "value"), col(h, "cluster_name"), col(h, "facet"),
                                                             col(h, "date_start"))
                if not all((geo, var, val)):
                    raise ConnectorError(f"anthropic_aei: {p.name} lacks geo_id, variable or value; is it the "
                                         "Economic Index's long-format file?")
                for r in reader:
                    if geog and r[geog].strip().lower() != "country":
                        continue
                    if facet and r[facet].strip().lower() not in ("country", ""):
                        continue
                    if cluster and r[cluster].strip() not in ("", "nan", "None"):
                        continue
                    target = AEI_VARIABLES.get(r[var].strip())
                    ent = iso_entity(r[geo])
                    y = year_of(r[start]) if start else None
                    y = y or (int(m.group(1)[:4]) if m else int(release[:4]))
                    if not target or not ent or (ent, target[0], y) in seen:
                        continue
                    seen.add((ent, target[0], y))
                    rows.add("iso3", ent, target[0], y, num(r[val]))
        if not len(rows):
            raise ConnectorError("anthropic_aei: no country-level usage_pct or usage_per_capita_index rows found")
        self.listed_indicators = [indicator(i, n, d, u, "technology", self.source_id, v, decimals=dp,
                                            aggregation={"method": "none"}) for v, (i, n, d, u, dp) in AEI_VARIABLES.items()]
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------------- Microsoft AI Diffusion
VALUE_HEADER = re.compile(r"share|usage|users?|adoption|diffusion|percent|pct", re.I)
COUNTRY_HEADER = re.compile(r"^(country|economy|nation|iso.?3?|iso_?code|country_?code|market)", re.I)


def _table(path: Path) -> list[list]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return xlsx_rows(path)
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


MS_REPO_API = "https://api.github.com/repos/microsoft/ai-diffusion-report/contents/data"
MS_RAW = "https://raw.githubusercontent.com/microsoft/ai-diffusion-report/main/data/"
MS_KNOWN = "AI_Diffusion_Q22026_Update.csv"  # used when the folder cannot be listed
PERIOD = re.compile(r"\b(H[12]|Q[1-4])\s*((?:19|20)\d\d)\b|\b((?:19|20)\d\d)\s*(H[12]|Q[1-4])\b", re.I)


def _period_order(header: str) -> tuple[int, int] | None:
    """(year, part) of a column such as "H2 2025 AI Diffusion" or "Q1 2026"; parts sort H1 < Q1-Q2 < H2 < Q3-Q4."""
    m = PERIOD.search(header)
    if not m:
        return None
    part, year = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
    part = part.upper()
    rank = {"H1": 2, "H2": 4}.get(part) or int(part[1])  # Q1 1, H1 2, Q2 2, Q3 3, H2 4, Q4 4
    return int(year), rank


class MicrosoftAIDiffusion(Connector):
    """Microsoft AI Economy Institute's AI Diffusion: the share of people using generative AI,
    by country, from github.com/microsoft/ai-diffusion-report (MIT). The country file has one
    column per period (H1 2025, H2 2025, Q1 2026...); each year takes its latest period."""
    source_id = "ms_ai_diffusion"
    fetch_every_days = 28

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:
            m = re.search(r"((?:19|20)\d\d)(?:[-_ ]?(H[12]|Q[1-4]|\d\d))?", f.name)
            if m:
                return m.group(1)
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        """The newest country CSV in the repository's data folder (the folder is listed through
        GitHub's API; if that is refused, the last known file name is tried)."""
        name = MS_KNOWN
        try:
            r = self.client.get(MS_REPO_API, headers={"Accept": "application/vnd.github+json"})
            r.raise_for_status()
            found = [f["name"] for f in r.json() if f.get("type") == "file" and f["name"].lower().endswith(".csv")
                     and "diffusion" in f["name"].lower()]
            if found:
                def order(n: str):
                    m = re.search(r"(Q[1-4]|H[12])\s*_?((?:19|20)\d\d)", n, re.I)
                    return (int(m.group(2)), m.group(1).upper()) if m else (0, n)
                name = max(found, key=order)
        except Exception as exc:  # noqa: BLE001 - the known name still works
            log.warning("ms_ai_diffusion: could not list %s (%s); trying %s", MS_REPO_API, exc, MS_KNOWN)
        self.get(MS_RAW + name, raw_dir / name)
        return MS_RAW + name

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".csv", ".xlsx", ".xlsm"))
        if not files:
            raise ConnectorError(f"ms_ai_diffusion: no .csv or .xlsx file in {raw_dir}")
        rows, unmatched = Rows(), set()
        for p in files:
            table = _table(p)
            hi = next((i for i, r in enumerate(table[:30]) if any(COUNTRY_HEADER.match(str(c or "").strip()) for c in r)), None)
            if hi is None:
                raise ConnectorError(f"ms_ai_diffusion: no country column found in {p.name}")
            header = [str(c or "").strip() for c in table[hi]]
            ci = next(i for i, c in enumerate(header) if COUNTRY_HEADER.match(c))
            vals = [i for i, c in enumerate(header) if VALUE_HEADER.search(c) and i != ci]
            yi = next((i for i, c in enumerate(header) if key(c) in ("year", "period", "date")), None)
            if not vals:
                raise ConnectorError(f"ms_ai_diffusion: no column naming a share or usage in {p.name} "
                                     f"(columns: {', '.join(header)})")
            # One column per period: each year takes its latest period. Otherwise the first share column.
            periods = {i: _period_order(header[i]) for i in vals}
            by_year: dict[int, tuple[tuple[int, int], int]] = {}
            for i, o in periods.items():
                if o and (o[0] not in by_year or o > by_year[o[0]][0]):
                    by_year[o[0]] = (o, i)
            vi = vals[0]
            file_year = re.search(r"(?:19|20)\d\d", p.name)
            for r in table[hi + 1:]:
                if len(r) <= max(ci, vi):
                    continue
                name = str(r[ci] or "").strip()
                if not name:
                    continue
                ent = iso_entity(name) if re.fullmatch(r"[A-Za-z]{2,3}", name) else catalogue.country_by_name(name)
                if not ent:
                    unmatched.add(name)
                    continue
                cells = [(y, i) for y, (_, i) in by_year.items()] if by_year else [(None, vi)]
                for y, i in cells:
                    if len(r) <= i:
                        continue
                    v = num(r[i])
                    if v is not None and 0 < v <= 1 and "%" not in str(r[i]):
                        v *= 100  # a share given as a fraction
                    if y is None:
                        y = (year_of(str(r[yi])) if yi is not None else None) or \
                            (int(file_year.group(0)) if file_year else int(release[:4]))
                    rows.add("iso3", ent, "ai_use_population", y, v)
        if unmatched:
            log.warning("ms_ai_diffusion: names not matched to a country: %s", ", ".join(sorted(unmatched)[:20]))
        if not len(rows):
            raise ConnectorError("ms_ai_diffusion: no values read; is it the AI Diffusion Report's country table?")
        self.listed_indicators = [indicator(
            "ai_use_population", "People using AI (% of working-age people)",
            "Share of the working-age population using generative AI tools, estimated by Microsoft's AI Economy "
            "Institute from anonymised use of its products, adjusted for market share.",
            "% of working-age people", "technology", self.source_id, "ai_user_share", decimals=1, bounds=(0, 100),
            aggregation={"method": "none"})]
        return rows.stage(con, self.source_id, vintage)


__all__ = ["EurostatAI", "AnthropicAEI", "MicrosoftAIDiffusion"]
