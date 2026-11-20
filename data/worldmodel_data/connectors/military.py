"""Military strength by country, and who sells weapons to whom.

gfp
    Global Firepower: about 30 counts for 145 countries (troops, aircraft by type, tanks,
    armoured vehicles, artillery, ships by type, defence budget, ports and airports) and its
    own PowerIndex score. Read politely: the countries listing (one page: every country's
    PowerIndex), then each country's page, key countries first, a few a refresh (Settings:
    gfp_pages_per_refresh), each country again only when a new yearly edition is out. Pages
    saved by hand in var\\manual\\gfp (verify.bat opens them) load the same way. The counts
    become yearly series (gfp_*), the year being the edition's, and military_strength rows.
    PowerIndex is Global Firepower's own blend with a method it does not publish: the app
    shows it labelled as such, never as a grade.
sipri_arms
    SIPRI's Arms Transfers Database trade register: every deal for major weapons since 1950,
    supplier, recipient, weapon, numbers, years and SIPRI's trend-indicator value. Saved by
    hand from armstransfers.sipri.org (get.bat opens it; choose the trade register and CSV).
    The yearly arms import and export totals already come through the World Bank.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import date, datetime
from html import unescape
from pathlib import Path

import duckdb

from worldmodel_contract import osint
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.cities import country_by_name
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS
from worldmodel_data.connectors.tabular import Rows, indicator, num
from worldmodel_data.connectors.wars import page_text

log = logging.getLogger(__name__)

GFP = "https://www.globalfirepower.com/"
GFP_LISTING = GFP + "countries-listing.php"
GFP_COUNTRY = GFP + "country-military-strength-detail.php?country_id={slug}"
GFP_LINK = re.compile(r'<a[^>]+href="[^"]*country-military-strength-detail\.php\?country_id=([\w-]+)"[^>]*>(.*?)</a>', re.I | re.S)
KEY_FIRST = ("new-zealand", "australia", "united-kingdom", "united-states-of-america", "china", "russia", "ukraine", "india", "japan")
NUMBER = re.compile(r"\$?\s*(\d[\d,]*(?:\.\d+)?)")
_LABELS = [(mid, re.compile(rf"(?:{pat})", re.I)) for mid, pat, *_ in osint.GFP_MEASURES]


def _settings() -> dict:
    try:
        from worldmodel_contract.local import load_settings
        from worldmodel_data.config import paths
        return load_settings(paths().home)
    except Exception:  # noqa: BLE001 - settings unreadable: defaults
        return {}


def gfp_edition(html: str, fallback: int) -> int:
    m = re.search(r"\b(?:GFP|Global Firepower)\s*(20\d\d)\b|\b(20\d\d)\s+Military Strength", html, re.I)
    return int(m.group(1) or m.group(2)) if m else fallback


def gfp_listing(html: str) -> dict[str, dict]:
    """slug -> {name, power_index} from the countries listing."""
    out: dict[str, dict] = {}
    for slug, inner in GFP_LINK.findall(html):
        text = page_text(inner)
        lines = [ln for ln in text.splitlines() if ln.strip()]
        pi = re.search(r"PwrIndx\s*:?\s*([\d.]+)", text, re.I)
        name = next((ln for ln in lines if re.search(r"[A-Za-z]", ln) and not re.search(r"PwrIndx|^\d|rank", ln, re.I)), "")
        rec = out.setdefault(slug, {"name": name or slug.replace("-", " ").title(), "power_index": None})
        if pi and rec["power_index"] is None:
            rec["power_index"] = float(pi.group(1))
    return out


def gfp_values(html: str) -> dict[str, float]:
    """measure id -> value from a country page: each line that is a measure's label, and the
    first number on it (after a colon) or on one of the next three lines."""
    lines = page_text(html).splitlines()
    out: dict[str, float] = {}
    for i, ln in enumerate(lines):
        label, _, rest = ln.partition(":")
        label = re.sub(r"\(.*?\)", "", label).strip(" *:\t")
        if not label or len(label) > 60:
            continue
        mid = next((mid for mid, pat in _LABELS if pat.fullmatch(label)), None)
        if not mid or mid in out:
            continue
        for cand in [rest, *lines[i + 1:i + 4]]:
            m = NUMBER.search(cand or "")
            if m and not re.search(r"[A-Za-z]{4,}", (cand or "")[: m.start()]):
                out[mid] = float(m.group(1).replace(",", ""))
                break
    return out


def _slug_country(slug: str, name: str | None = None) -> str | None:
    return country_by_name(name) or country_by_name(slug.replace("-", " ")) or {
        "united-states-of-america": "USA", "united-kingdom": "GBR", "south-korea": "KOR", "north-korea": "PRK",
        "czechia": "CZE", "democratic-republic-of-the-congo": "COD", "republic-of-the-congo": "COG"}.get(slug)


class GlobalFirepower(Connector):
    source_id = "gfp"
    switch = "gfp_fetch"
    fetch_every_days = 7
    keeps_files = True

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        from worldmodel_data.scrape import PageReader

        per_run = int(_settings().get("gfp_pages_per_refresh", 12))
        last = self.last_vintage_dir(raw_dir)
        held: dict[str, int] = {}
        if last:
            for f in last.glob("gfp_country_*.json"):
                try:
                    held[f.stem.removeprefix("gfp_country_")] = int(json.loads(f.read_text(encoding="utf-8"))["edition"])
                except (ValueError, KeyError):
                    continue
        with PageReader(self, planned=1 + per_run) as pages:
            html = pages.read(GFP_LISTING, raw_dir / "gfp_listing.html", expect=r"country_id=", what="countries listing")
            edition = gfp_edition(html, date.today().year)
            listing = gfp_listing(html)
            order = [s for s in KEY_FIRST if s in listing] + sorted(s for s in listing if s not in KEY_FIRST)
            due = [s for s in order if held.get(s, 0) < edition][:per_run]
            for slug in due:
                tmp = raw_dir / f"gfp_{slug}.html.part"
                page = pages.read(GFP_COUNTRY.format(slug=slug), tmp, expect=r"PwrIndx|Military", what=listing[slug]["name"])
                vals = gfp_values(page)
                if len(vals) >= 8:
                    (raw_dir / f"gfp_country_{slug}.json").write_text(json.dumps(
                        {"slug": slug, "name": listing[slug]["name"], "edition": gfp_edition(page, edition), "values": vals}),
                        encoding="utf-8")
                else:
                    log.warning("gfp: only %s figures read from %s's page; left for the next refresh", len(vals), slug)
                tmp.unlink(missing_ok=True)
        return GFP_LISTING

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows: dict[tuple[str, int, str], float] = {}
        fallback = int(release[:4])
        for f in sorted(raw_dir.iterdir()):
            if f.name.startswith("gfp_country_") and f.suffix == ".json":
                d = json.loads(f.read_text(encoding="utf-8"))
                ent = _slug_country(d["slug"], d.get("name"))
                if ent:
                    for mid, v in d["values"].items():
                        rows[(ent, int(d["edition"]), mid)] = v
            elif f.suffix.lower() in (".html", ".htm"):
                html = f.read_text(encoding="utf-8", errors="replace")
                edition = gfp_edition(html, fallback)
                if len(GFP_LINK.findall(html)) >= 3 and "listing" in f.name.lower() or len(GFP_LINK.findall(html)) > 20:  # the listing
                    for slug, rec in gfp_listing(html).items():
                        ent = _slug_country(slug, rec["name"])
                        if ent and rec["power_index"] is not None:
                            rows.setdefault((ent, edition, "gfp_power_index"), rec["power_index"])
                    continue
                vals = gfp_values(html)  # a country page saved by hand: the country from its title or name
                title = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
                name = re.sub(r"\s*(?:\d{4}\s*)?Military Strength.*$", "", unescape(title.group(1)).strip(), flags=re.I) if title else ""
                ent = country_by_name(name) or _slug_country(re.sub(r"^gfp_|\.html?$", "", f.name, flags=re.I))
                if ent and len(vals) >= 8:
                    for mid, v in vals.items():
                        rows[(ent, edition, mid)] = v
        if not rows:
            raise ConnectorError(f"gfp: no figures read from {raw_dir}")
        con.execute("CREATE TABLE ms (country_code VARCHAR, edition INTEGER, measure VARCHAR, value DOUBLE)")
        con.executemany("INSERT INTO ms VALUES (?, ?, ?, ?)", [(*k, v) for k, v in rows.items()])
        self.history_queries = {"military_strength": "SELECT * FROM ms"}
        obs = Rows()
        for (ent, edition, mid), v in rows.items():
            obs.add("iso3", ent, mid, edition, v)
        self.listed_indicators = [indicator(
            mid, name, ("Global Firepower's own score blending about 60 factors; lower is stronger. Its method and weights are "
                        "not published, so treat it as one outfit's view, not a measurement." if mid == "gfp_power_index" else
                        f"{name}, as estimated by Global Firepower for its yearly edition (the year shown)."),
            unit, "military", self.source_id, f"gfp:{mid}", decimals=4 if mid == "gfp_power_index" else 0,
            aggregation={"method": "none" if mid == "gfp_power_index" else "sum"})
            for mid, _, name, unit, _ in osint.GFP_MEASURES]
        log.info("gfp: %s countries", len({k[0] for k in rows}))
        return obs.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- SIPRI trade register
def _pick(cells: list[str], *words: str) -> int | None:
    for w in words:
        for j, c in enumerate(cells):
            if w in c:
                return j
    return None


def _party(name: str) -> str:
    n = re.sub(r"\*+$", "", (name or "").strip())
    return country_by_name(n) or n


def sipri_deals(text: str) -> list[tuple]:
    sep = ";" if text[:5000].count(";") > text[:5000].count(",") else ","
    table = list(csv.reader(io.StringIO(text), delimiter=sep))
    head = next(((i, [c.strip().lower() for c in r]) for i, r in enumerate(table[:30])
                 if any("supplier" in c for c in (x.lower() for x in r)) and any("recipient" in c for c in (x.lower() for x in r))), None)
    if not head:
        return []
    i, cells = head
    col = {
        "supplier": _pick(cells, "supplier"), "recipient": _pick(cells, "recipient"), "ordered": _pick(cells, "year of order", "order"),
        "number": _pick(cells, "number delivered", "number ordered", "number"), "weapon": _pick(cells, "designation", "weapon"),
        "description": _pick(cells, "description"), "years": _pick(cells, "year(s) of delivery", "delivery"),
        "status": _pick(cells, "status"), "tiv": _pick(cells, "tiv of delivered", "tiv for total", "tiv"),
    }
    out = []
    for row in table[i + 1:]:
        def cell(k):
            j = col.get(k)
            return row[j].strip() if j is not None and j < len(row) else ""
        sup, rec = cell("supplier"), cell("recipient")
        if not sup or not rec:
            continue
        years = [int(y) for y in re.findall(r"(19\d\d|20\d\d)", cell("years"))]
        ordered = num(cell("ordered"))
        out.append((_party(sup), _party(rec), int(ordered) if ordered else None, min(years) if years else None,
                    max(years) if years else None, cell("weapon") or None, cell("description") or None,
                    num(re.sub(r"[()]", "", cell("number"))), num(cell("tiv")), cell("status") or None))
    return out


class SIPRIArms(Connector):
    source_id = "sipri_arms"
    manual = True

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("sipri_arms: saved by hand (get.bat opens SIPRI's Arms Transfers Database)")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = []
        for f in sorted(raw_dir.iterdir()):
            if f.suffix.lower() in (".csv", ".txt"):
                rows += sipri_deals(f.read_text(encoding="utf-8-sig", errors="replace"))
        if not rows:
            raise ConnectorError(f"sipri_arms: no deals read from {raw_dir}; is it the trade register as CSV?")
        con.execute("CREATE TABLE ad (supplier VARCHAR, recipient VARCHAR, ordered INTEGER, delivered_from INTEGER, "
                    "delivered_to INTEGER, weapon VARCHAR, description VARCHAR, number DOUBLE, tiv DOUBLE, status VARCHAR)")
        con.executemany("INSERT INTO ad VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        self.history_queries = {"arms_deals": "SELECT * FROM ad"}
        log.info("sipri_arms: %s deals", f"{len(rows):,}")
        return EMPTY_OBSERVATIONS
