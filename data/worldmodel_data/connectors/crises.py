"""Financial crises over two centuries: Reinhart and Rogoff's crisis years by country.

crisis_history
    The Behavioral Finance & Financial Stability project's "Global Crises Data by
    Country" (Carmen Reinhart, with Kenneth Rogoff, Christoph Trebesch and Vincent
    Reinhart): for about 70 countries, every year from 1800, whether the country was in
    a banking crisis, a systemic crisis, in default on its domestic or foreign debt, in a
    currency crisis (a fall of 15% or more against the dollar or pound in a year), an
    inflation crisis (above 20% a year) or a stock market crash, plus inflation itself.

    The site has no fixed download address, so the workbook is loaded by hand
    (var\\manual\\crisis_history). Any table with a year column, a country column (code
    or name, or one sheet per country named after it) and crisis columns named as in
    the workbook is read; columns it does not know are left out.

Each crisis kind is stored as a yearly 0/1 indicator (crisis_banking and so on) and
crisis_kinds counts how many kinds a country was in that year. Runs of crisis years
become events of kind "crisis" (subkind the crisis kind), so they show as bands on
charts and on the Events page.
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import date, datetime
from pathlib import Path

import duckdb
from worldmodel_contract import catalogue

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.events_common import stage_events
from worldmodel_data.connectors.tabular import (
    Rows,
    entity_for,
    indicator,
    key,
    num,
    xlsx_rows,
    xlsx_sheet_names,
)

log = logging.getLogger(__name__)

PAGE = "https://www.hbs.edu/behavioral-finance-and-financial-stability/data/Pages/global.aspx"

# kind -> (header beginnings, compared loosely; indicator name; event title)
KINDS: dict[str, tuple[tuple[str, ...], str, str]] = {
    "banking": (("bankingcrisis",), "Banking crisis", "Banking crisis"),
    "systemic": (("systemiccrisis",), "Systemic banking crisis", "Systemic banking crisis"),
    "default_external": (("sovereignexternaldebt1", "externaldebtindefault", "externaldefault", "defaultsexternal"),
                         "In default on foreign debt", "Default on foreign debt"),
    "default_domestic": (("domesticdebtindefault", "domesticdefault"), "In default on domestic debt",
                         "Default on domestic debt"),
    "currency": (("currencycris",), "Currency crisis", "Currency crisis"),
    "inflation": (("inflationcris",), "Inflation crisis", "Inflation crisis (over 20% a year)"),
    "stock_crash": (("stockmarketcrash", "stockmarketcrisis"), "Stock market crash", "Stock market crash"),
}
INFLATION = ("inflationannualpercentages", "inflationannual", "annualinflation")
SKIP = ("notes", "note")  # Banking_Crisis_Notes and the like hold words, not flags


def _match(head: list[str]) -> dict[str, int]:
    """Column index for each crisis kind (and 'rate' for inflation) found in a header row."""
    out: dict[str, int] = {}
    for i, h in enumerate(head):
        if not h or h.endswith(SKIP):
            continue
        for kind, (starts, _, _) in KINDS.items():
            if kind not in out and h.startswith(starts):
                out[kind] = i
        if "rate" not in out and h.startswith(INFLATION) and "cris" not in h:
            out["rate"] = i
    return out


def flag(v) -> float | None:
    """1 for a crisis year, 0 for none; blanks and "n/a" are unknown. Yes/No also work."""
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("yes", "y", "true"):
        return 1.0
    if s in ("no", "n", "false"):
        return 0.0
    n = num(v)
    if n is None:
        return None
    return 1.0 if n > 0 else 0.0


def _entity(code, name: str, year: int) -> str | None:
    c = str(code or "").strip().upper()
    if len(c) == 3:
        e = entity_for("iso3", c)
        if e:
            return e
    return catalogue.country_by_name(name, date(year, 7, 1)) if name else None


def read_tables(raw_dir: Path) -> list[tuple[str, list[list]]]:
    tables: list[tuple[str, list[list]]] = []
    for p in sorted(raw_dir.iterdir()):
        if p.suffix.lower() == ".csv":
            with p.open(encoding="utf-8-sig", errors="replace", newline="") as f:
                tables.append((p.stem, list(csv.reader(f))))
        elif p.suffix.lower() in (".xlsx", ".xlsm"):
            for i, name in enumerate(xlsx_sheet_names(p)):
                tables.append((name, xlsx_rows(p, i)))
    return tables


def read(tables: list[tuple[str, list[list]]]) -> tuple[dict[tuple[str, str, int], float], set[str]]:
    """Values by (entity, kind, year), kinds as in KINDS plus 'rate' (inflation %), and names not matched."""
    vals: dict[tuple[str, str, int], float] = {}
    unmatched: set[str] = set()
    for label, table in tables:
        hi = None
        for i, r in enumerate(table[:30]):
            head = [key(c) for c in r]
            if "year" in head and len(_match(head)) >= 2:
                hi = i
                break
        if hi is None:
            continue
        head = [key(c) for c in table[hi]]
        cols = _match(head)
        yi = head.index("year")
        ci = next((i for i, h in enumerate(head) if h in ("cc3", "iso3", "iso", "code", "countrycode")), None)
        ni = next((i for i, h in enumerate(head) if h in ("country", "countryname", "name")), None)
        for r in table[hi + 1:]:
            if len(r) <= yi or num(r[yi]) is None:
                continue
            y = int(num(r[yi]))
            if not 1500 <= y <= 2100:
                continue
            name = str(r[ni] or "").strip() if ni is not None and ni < len(r) else label
            ent = _entity(r[ci] if ci is not None and ci < len(r) else None, name, y)
            if not ent:
                if name:
                    unmatched.add(name)
                continue
            for kind, i in cols.items():
                if i >= len(r):
                    continue
                v = num(r[i]) if kind == "rate" else flag(r[i])
                if v is not None:
                    vals[(ent, kind, y)] = v
    return vals, unmatched


def runs(years: list[int]) -> list[tuple[int, int]]:
    """Consecutive years as (first, last) runs."""
    out: list[tuple[int, int]] = []
    for y in sorted(years):
        if out and y == out[-1][1] + 1:
            out[-1] = (out[-1][0], y)
        else:
            out.append((y, y))
    return out


class CrisisHistory(Connector):
    source_id = "crisis_history"
    manual = True

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:  # 20160923_global_crisis_data.xlsx
            m = re.match(r"(\d{4})(\d{2})\d{2}_", f.name)
            if m:
                return f"{m.group(1)}-{m.group(2)}"
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError(f"crisis_history: download 'Global Crises Data by Country' from {PAGE} and save it "
                             "in var\\manual\\crisis_history")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        vals, unmatched = read(read_tables(raw_dir))
        if not vals:
            raise ConnectorError("crisis_history: no table with a Year column and crisis columns (Banking Crisis, "
                                 "Currency Crises ...) was found; is it the Global Crises Data workbook?")
        rows = Rows()
        counts: dict[tuple[str, int], float] = {}
        years: dict[tuple[str, str], list[int]] = {}
        for (ent, kind, y), v in vals.items():
            if kind == "rate":
                rows.add("iso3", ent, "rr_inflation", y, v)
                continue
            rows.add("iso3", ent, f"crisis_{kind}", y, v)
            if kind != "systemic":  # a systemic crisis is a kind of banking crisis, not one more
                counts[(ent, y)] = counts.get((ent, y), 0.0) + v
            if v:
                years.setdefault((ent, kind), []).append(y)
        for (ent, y), n in counts.items():
            rows.add("iso3", ent, "crisis_kinds", y, n)
        events = []
        for (ent, kind), ys in years.items():
            title = KINDS[kind][2]
            for a, b in runs(ys):
                events.append((ent, f"{ent}:{kind}:{a}", "crisis", kind, title, date(a, 1, 1), date(b, 12, 31),
                               "year", float(b - a + 1), "years", None, None, None, None, PAGE,
                               f"{title}, {a}" + (f" to {b}" if b > a else "") + " (Reinhart and Rogoff)"))
        log.info("crisis_history: %s values, %s crisis spells", len(rows), len(events))
        self.events_query = stage_events(con, self.source_id, vintage, events, unmatched)
        note = "Reinhart and Rogoff, Global Crises Data by Country (Behavioral Finance & Financial Stability project)."
        self.listed_indicators = [
            indicator(f"crisis_{k}", name, f"{name} that year: 1 yes, 0 no. {note}", "yes = 1", "debt",
                      self.source_id, k, decimals=0, aggregation={"method": "sum"}, bounds=(0, 1))
            for k, (_, name, _) in KINDS.items()
        ] + [
            indicator("crisis_kinds", "Kinds of financial crisis at once",
                      "How many kinds of crisis a country was in that year: banking, foreign or domestic default, "
                      f"currency, inflation, stock market crash (0 to 6). {note}", "kinds", "debt", self.source_id,
                      "count", decimals=0, aggregation={"method": "sum"}, bounds=(0, 6)),
            indicator("rr_inflation", "Inflation, two centuries", "Consumer price inflation, % a year, from 1800 "
                      f"where known. {note}", "%", "prices", self.source_id, "inflation", decimals=1,
                      bounds=(-100, 1e12)),
        ]
        return rows.stage(con, self.source_id, vintage)
