"""Between countries: UN votes, the Security Council, sanctions, IMF programmes, WTO
disputes and treaties.

unga_votes
    Erik Voeten's UN General Assembly voting data on Harvard Dataverse (CC0). The
    dataset's file list comes from the Dataverse API; two files are read:
    the agreement scores (for each pair of countries and year, the share of votes on
    which they agreed, abstentions counting as half) and the ideal points (each
    country's position on a single scale of how it votes, where higher means voting
    more like the United States and its allies). Countries are Correlates of War codes
    (ccode), turned into entities with COW below, or ISO codes where the file has them.
    Stored: unga_agreement (percent, breakdown = the other country) and
    unga_ideal_point.

un_vetoes
    The UN library's list of Security Council vetoes (one row per draft, with the date,
    the draft, the agenda item and the permanent members that voted no), and the
    Council's list of countries elected as members with their years. Vetoes and seats
    become events of kind "un".

gsdb
    The Global Sanctions Database: one row per sanction case, with the sanctioned and
    sanctioning states, first and last year and which kinds of measure (trade, arms,
    military aid, financial, travel, other) and why. A file you request and load
    yourself. Each case becomes a "sanction" event on the sanctioned country, and
    sanctions_active counts each country's cases in force per year (and
    sanctions_imposed the cases where it is the sender).

imf_mona
    The IMF's MONA database of lending arrangements: one row per programme review, so
    rows are joined by arrangement number. Each programme becomes an "imf" event from
    approval to its (revised) end date, sized by the amount agreed (SDR million).
    The download link is found on the MONA page; the file can be saved by hand.

wto_disputes
    The WTO's chronological list of dispute cases: DS number, respondent, subject,
    complainant and date of the request for consultations. Each case is a
    "trade_dispute" event on the respondent and on each complainant.

un_treaties
    The status page of each treaty in TREATIES at the UN Treaty Collection (one page
    each, a second apart): who signed and when, and who ratified, acceded or succeeded
    and when. Joining becomes a "treaty" event (signing alone, an event saying so), and
    treaties_joined counts how many of these treaties a country has joined by each year.
"""

from __future__ import annotations

import calendar
import csv
import html
import io
import json
import logging
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import duckdb

from worldmodel_contract import catalogue
from worldmodel_data.connectors.base import Connector, ConnectorError, sql_str
from worldmodel_data.connectors.events_common import EMPTY_OBSERVATIONS, country, make_date, stage_events
from worldmodel_data.connectors.tabular import Rows, entity_for, key, num, xlsx_rows

log = logging.getLogger(__name__)

MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}


def text_of(fragment: str) -> str:
    """Plain text from a piece of HTML: tags dropped, entities decoded, spaces squeezed."""
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", fragment, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>|</p>|</li>|</div>|</h[1-6]>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s).replace("\xa0", " ")
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*", "\n", s)).strip()


def table_rows(page: str) -> list[list[str]]:
    """Every row of every HTML table on a page, as lists of cell texts."""
    out = []
    for tr in re.findall(r"<tr\b.*?</tr>", page, flags=re.S | re.I):
        cells = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", tr, flags=re.S | re.I)
        if cells:
            out.append([text_of(c) for c in cells])
    return out


def parse_day(s: str | None) -> tuple[date | None, str]:
    """A date written as "16 Dec 1966", "16 December 1966", "1966-12-16", "December 1966" or "1966"."""
    s = (s or "").strip()
    if not s:
        return None, "day"
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return make_date(m.group(1), m.group(2), m.group(3))
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?,?\s+(\d{4})", s)
    if m and m.group(2).lower() in MONTHS:
        return make_date(m.group(3), MONTHS[m.group(2).lower()], m.group(1))
    m = re.search(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),\s*(\d{4})", s)  # December 16, 1966
    if m and m.group(1).lower() in MONTHS:
        return make_date(m.group(3), MONTHS[m.group(1).lower()], m.group(2))
    m = re.search(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{4})", s)
    if m and m.group(1).lower() in MONTHS:
        return make_date(m.group(2), MONTHS[m.group(1).lower()])
    m = re.search(r"\b(1[89]\d\d|20\d\d)\b", s)
    if m:
        return make_date(m.group(1))
    return None, "day"


def iso_date(v) -> date | None:
    """A date from an Excel cell or a text date."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and 1900 < v < 2200:
        return date(int(v), 1, 1)
    m = re.fullmatch(r"\s*(\d{1,2})-([A-Za-z]{3})-(\d{2})\s*", str(v or ""))  # MONA's "26-Jun-06"
    if m:
        try:
            return datetime.strptime(f"{m[1]}-{m[2].title()}-{m[3]}", "%d-%b-%y").date()
        except ValueError:
            pass
    d, _ = parse_day(str(v) if v is not None else "")
    return d


# ---------------------------------------------------------------- UN General Assembly votes
DATAVERSE = "https://dataverse.harvard.edu"
DATASET = "doi:10.7910/DVN/LEJUQZ"

# Correlates of War state codes -> entity id; (code, until) pairs for codes whose state changed.
COW = {
    2: "USA", 20: "CAN", 31: "BHS", 40: "CUB", 41: "HTI", 42: "DOM", 51: "JAM", 52: "TTO", 53: "BRB", 54: "DMA",
    55: "GRD", 56: "LCA", 57: "VCT", 58: "ATG", 60: "KNA", 70: "MEX", 80: "BLZ", 90: "GTM", 91: "HND", 92: "SLV",
    93: "NIC", 94: "CRI", 95: "PAN", 100: "COL", 101: "VEN", 110: "GUY", 115: "SUR", 130: "ECU", 135: "PER",
    140: "BRA", 145: "BOL", 150: "PRY", 155: "CHL", 160: "ARG", 165: "URY", 200: "GBR", 205: "IRL", 210: "NLD",
    211: "BEL", 212: "LUX", 220: "FRA", 221: "MCO", 223: "LIE", 225: "CHE", 230: "ESP", 232: "AND", 235: "PRT",
    255: "DEU", 260: "DEU", 265: "DDR", 290: "POL", 305: "AUT", 310: "HUN", 315: "CSK", 316: "CZE", 317: "SVK",
    325: "ITA", 331: "SMR", 338: "MLT", 339: "ALB", 341: "MNE", 343: "MKD", 344: "HRV", 346: "BIH", 347: "XKX",
    349: "SVN", 350: "GRC", 352: "CYP", 355: "BGR", 359: "MDA", 360: "ROU", 366: "EST", 367: "LVA",
    368: "LTU", 369: "UKR", 370: "BLR", 371: "ARM", 372: "GEO", 373: "AZE", 375: "FIN", 380: "SWE", 385: "NOR",
    390: "DNK", 395: "ISL", 402: "CPV", 403: "STP", 404: "GNB", 411: "GNQ", 420: "GMB", 432: "MLI", 433: "SEN",
    434: "BEN", 435: "MRT", 436: "NER", 437: "CIV", 438: "GIN", 439: "BFA", 450: "LBR", 451: "SLE", 452: "GHA",
    461: "TGO", 471: "CMR", 475: "NGA", 481: "GAB", 482: "CAF", 483: "TCD", 484: "COG", 490: "COD", 500: "UGA",
    501: "KEN", 510: "TZA", 516: "BDI", 517: "RWA", 520: "SOM", 522: "DJI", 530: "ETH", 531: "ERI", 540: "AGO",
    541: "MOZ", 551: "ZMB", 552: "ZWE", 553: "MWI", 560: "ZAF", 565: "NAM", 570: "LSO", 571: "BWA", 572: "SWZ",
    580: "MDG", 581: "COM", 590: "MUS", 591: "SYC", 600: "MAR", 615: "DZA", 616: "TUN", 620: "LBY", 625: "SDN",
    626: "SSD", 630: "IRN", 640: "TUR", 645: "IRQ", 651: "EGY", 652: "SYR", 660: "LBN", 663: "JOR", 666: "ISR",
    670: "SAU", 680: "YMD", 690: "KWT", 692: "BHR", 694: "QAT", 696: "ARE", 698: "OMN", 700: "AFG", 701: "TKM",
    702: "TJK", 703: "KGZ", 704: "UZB", 705: "KAZ", 710: "CHN", 712: "MNG", 713: "TWN", 731: "PRK", 732: "KOR",
    740: "JPN", 750: "IND", 760: "BTN", 770: "PAK", 771: "BGD", 775: "MMR", 780: "LKA", 781: "MDV", 790: "NPL",
    800: "THA", 811: "KHM", 812: "LAO", 816: "VNM", 820: "MYS", 830: "SGP", 835: "BRN", 840: "PHL", 850: "IDN",
    860: "TLS", 900: "AUS", 910: "PNG", 920: "NZL", 935: "VUT", 940: "SLB", 946: "KIR", 947: "TUV", 950: "FJI",
    955: "TON", 970: "NRU", 983: "MHL", 986: "PLW", 987: "FSM", 990: "WSM",
}
# Codes that stood for different states over time: (last year, entity) in order.
COW_BY_YEAR = {
    365: ((1991, "SUN"), (9999, "RUS")),
    345: ((1991, "YUG"), (2005, "SCG"), (9999, "SRB")),
    678: ((1989, "YAR"), (9999, "YEM")),
}


def cow_entity(code, year: int) -> str | None:
    try:
        c = int(float(code))
    except (TypeError, ValueError):
        return None
    if c in COW_BY_YEAR:
        return next(e for until, e in COW_BY_YEAR[c] if year <= until)
    return COW.get(c)


def _col(header: list[str], *names: str) -> str | None:
    """The first header matching one of the names (compared loosely), or None."""
    keys = {key(h): h for h in header}
    for n in names:
        if key(n) in keys:
            return keys[key(n)]
    return None


def _ind(*a, **k) -> dict:
    from worldmodel_data.connectors.tabular import indicator

    return indicator(*a, **k)


UNGA_INDICATORS = [
    _ind("unga_agreement", "UN General Assembly agreement", "How often two countries voted the same way in the UN "
         "General Assembly that year (yes, no or abstain), in percent. The breakdown is the other country.",
         "percent", "world", "unga_votes", "agree", breakdowns=["partner"], bounds=(0, 100)),
    _ind("unga_ideal_point", "UN voting position (ideal point)", "Where a country's UN General Assembly votes put it "
         "on one scale, from the voting record (Bailey, Strezhnev and Voeten). Higher is closer to the United States "
         "and the Western order; lower is further.", "index", "world", "unga_votes", "IdealPoint", decimals=2,
         bounds=(-10, 10)),
]
SANCTION_INDICATORS = [
    _ind("sanctions_active", "Sanctions in force on the country", "How many sanctions (by countries, the UN or the EU) "
         "were in force on the country that year, from the Global Sanctions Data Base.", "count", "world", "gsdb",
         "active", decimals=0, aggregation={"method": "sum"}, bounds=(0, 1000)),
    _ind("sanctions_imposed", "Sanctions the country imposed", "How many sanctions the country had in force on others "
         "that year, from the Global Sanctions Data Base.", "count", "world", "gsdb", "imposed", decimals=0,
         aggregation={"method": "sum"}, bounds=(0, 5000)),
]
TREATY_INDICATORS = [
    _ind("treaties_joined", "Major UN treaties joined", "How many of a fixed list of major UN treaties (human "
         "rights, arms control, climate, the sea, the ICC) the country had ratified or acceded to by the end of the year.",
         "count", "world", "un_treaties", "joined", decimals=0, bounds=(0, 100)),
]


class UNGAVotes(Connector):
    source_id = "unga_votes"
    fetch_every_days = 28

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        r = self.client.get(f"{DATAVERSE}/api/datasets/:persistentId/", params={"persistentId": DATASET})
        if r.status_code != 200:
            raise ConnectorError(f"unga_votes: Dataverse answered HTTP {r.status_code} for the file list")
        files = r.json().get("data", {}).get("latestVersion", {}).get("files", [])
        picked = pick_files(files)
        if not picked:
            raise ConnectorError("unga_votes: no agreement-scores or ideal-points file in the dataset's file list")
        for file_id, name in picked:
            self.get(f"{DATAVERSE}/api/access/datafile/{file_id}?format=original", raw_dir / name)
        return f"{DATAVERSE}/dataset.xhtml?persistentId={DATASET}"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = [p for p in raw_dir.iterdir() if p.suffix.lower() in (".csv", ".tab", ".tsv")]
        agree = next((p for p in files if "agree" in p.name.lower()), None)
        ideal = next((p for p in files if "ideal" in p.name.lower()), None)
        if not agree and not ideal:
            raise ConnectorError(f"unga_votes: no agreement-scores or ideal-points file in {raw_dir}")
        rows = Rows()
        agreement = agreement_query(con, agree, self.source_id, vintage) if agree else None
        if ideal:
            ideal_rows(con, ideal, rows)
        if not rows and not agreement:
            raise ConnectorError("unga_votes: nothing read; the files' columns may have changed")
        log.info("unga_votes: %s ideal points%s", len(rows), ", and agreement scores" if agreement else "")
        self.listed_indicators = UNGA_INDICATORS
        staged = rows.stage(con, self.source_id, vintage)
        return f"{staged} UNION ALL {agreement}" if agreement else staged


def pick_files(files: list[dict]) -> list[tuple[int, str]]:
    """(id, name) of the newest agreement-scores file and the newest ideal-points file in a Dataverse file list."""
    out = []
    for word in ("agree", "ideal"):
        found = []
        for f in files:
            df = f.get("dataFile", {})
            name = df.get("originalFileName") or df.get("filename") or ""
            if word in name.lower() and re.search(r"\.(csv|tab|tsv)$", name, re.I):
                found.append((df.get("id"), re.sub(r"\.tab$", ".csv", name, flags=re.I), name))
        if found:
            fid, name, _ = max(found, key=lambda x: (re.findall(r"(20\d\d)", x[2])[-1:] or ["0"], x[2]))
            out.append((fid, name))
    return out


def _read(con: duckdb.DuckDBPyConnection, path: Path, table: str) -> list[str]:
    con.execute(f"CREATE OR REPLACE TEMP TABLE {table} AS SELECT * FROM read_csv({sql_str(path.as_posix())}, "
                "header = true, all_varchar = true, auto_detect = true)")
    return [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]


def cow_table(con: duckdb.DuckDBPyConnection) -> None:
    """cow_map(code, first_year, last_year, entity): the COW codes as a table, for joins."""
    rows = [(c, 0, 9999, e) for c, e in COW.items()]
    for c, spans in COW_BY_YEAR.items():
        lo = 0
        for until, e in spans:
            rows.append((c, lo, until, e))
            lo = until + 1
    con.execute("CREATE OR REPLACE TEMP TABLE cow_map (code INTEGER, first_year INTEGER, last_year INTEGER, entity VARCHAR)")
    con.executemany("INSERT INTO cow_map VALUES (?, ?, ?, ?)", rows)


def agreement_query(con: duckdb.DuckDBPyConnection, path: Path, source_id: str, vintage: str) -> str | None:
    """unga_agreement for every pair of countries and year, both directions, in percent.
    Done in SQL: the file has a row per pair and year (millions of rows)."""
    header = _read(con, path, "agree_raw")
    year = _col(header, "year")
    value = _col(header, "agree", "agreement", "agreementscore")
    iso_a, iso_b = _col(header, "iso3c.x", "iso3c1", "iso1"), _col(header, "iso3c.y", "iso3c2", "iso2")
    cow_a, cow_b = _col(header, "ccode1", "ccode.x"), _col(header, "ccode2", "ccode.y")
    if not (year and value and ((iso_a and iso_b) or (cow_a and cow_b))):
        log.warning("unga_votes: %s has no year, agreement and country columns (%s)", path.name, ", ".join(header[:12]))
        return None
    base = (f'SELECT TRY_CAST(TRY_CAST("{year}" AS DOUBLE) AS INTEGER) AS y, TRY_CAST("{value}" AS DOUBLE) AS v')
    if iso_a and iso_b:
        pairs = (f'{base}, upper(trim("{iso_a}")) AS ea, upper(trim("{iso_b}")) AS eb FROM agree_raw')
    else:
        cow_table(con)
        pairs = (f'{base}, ma.entity AS ea, mb.entity AS eb FROM (SELECT *, TRY_CAST(TRY_CAST("{cow_a}" AS DOUBLE) AS INTEGER) AS ca, '
                 f'TRY_CAST(TRY_CAST("{cow_b}" AS DOUBLE) AS INTEGER) AS cb, TRY_CAST(TRY_CAST("{year}" AS DOUBLE) AS INTEGER) AS yy '
                 f'FROM agree_raw) r JOIN cow_map ma ON ma.code = r.ca AND r.yy BETWEEN ma.first_year AND ma.last_year '
                 f'JOIN cow_map mb ON mb.code = r.cb AND r.yy BETWEEN mb.first_year AND mb.last_year')
    con.execute(f"""CREATE OR REPLACE TABLE unga_agree AS
        WITH p AS ({pairs}),
        both_ways AS (SELECT ea AS x, eb AS partner, y, v FROM p UNION ALL SELECT eb, ea, y, v FROM p)
        SELECT x, partner, y, round(CASE WHEN any_value(v) <= 1 THEN any_value(v) * 100 ELSE any_value(v) END, 2) AS v
        FROM both_ways WHERE x IS NOT NULL AND partner IS NOT NULL AND x <> '' AND partner <> '' AND x <> partner
          AND y IS NOT NULL AND v IS NOT NULL
        GROUP BY x, partner, y""")
    if not con.execute("SELECT count(*) FROM unga_agree").fetchone()[0]:
        return None
    return (f"SELECT {sql_str(source_id)} AS source_id, {sql_str(vintage)} AS vintage, 'iso3' AS scheme, x AS source_code, "
            "'unga_agreement' AS indicator_id, make_date(y, 1, 1) AS period_start, 'A' AS freq, partner AS breakdown, "
            "'central' AS variant, v AS value, 'E' AS status FROM unga_agree")


def ideal_rows(con: duckdb.DuckDBPyConnection, path: Path, rows: Rows) -> None:
    header = _read(con, path, "ideal_raw")
    year, session = _col(header, "year"), _col(header, "session")
    value = _col(header, "IdealPointAll", "IdealPoint", "idealpoint")
    iso, cow = _col(header, "iso3c", "iso3"), _col(header, "ccode")
    if not ((year or session) and value and (iso or cow)):
        log.warning("unga_votes: %s has no year, ideal point and country columns (%s)", path.name, ", ".join(header[:12]))
        return
    when = year or session
    cols = f'"{iso}"' if iso else "NULL"
    cols += f', "{cow}"' if cow else ", NULL"
    for c, cc, y, v in con.execute(f'SELECT {cols}, "{when}", "{value}" FROM ideal_raw').fetchall():
        yr, val = num(y), num(v)
        if yr is None or val is None:
            continue
        yr = int(yr) + (1945 if not year else 0)  # session 1 met in 1946
        # the ISO code where there is one; former states (the USSR) have only their COW code
        e = (entity_for("iso3", c.strip().upper()) if c and c.strip() not in ("", "NA") else None) or cow_entity(cc, yr)
        if e:
            rows.add("iso3", e, "unga_ideal_point", yr, round(val, 3))


# ---------------------------------------------------------------- Security Council
VETO_PAGE = "https://research.un.org/en/docs/sc/quick/veto"
MEMBERS_PAGE = "https://www.un.org/securitycouncil/content/countries-elected-members"
# Since 2026 the library's page shows the list in a frame from this address (found on the page
# each time; this copy is for verify.bat, whose saved page does not include the frame).
VETO_TABLE = "https://ydsftksff8.execute-api.us-east-1.amazonaws.com/dev/render_meeting_veto/sc_veto_list/EN"
PERMANENT = {"China": "CHN", "France": "FRA", "Russian Federation": "RUS", "USSR": "SUN", "United Kingdom": "GBR",
             "United States": "USA", "United States of America": "USA", "Union of Soviet Socialist Republics": "SUN",
             "Soviet Union": "SUN"}


class UNVetoes(Connector):
    source_id = "un_vetoes"
    stage_version = 2  # 2: members listed with their terms on the next line
    fetch_version = 2  # 2: the veto table, now in a frame
    fetch_every_days = 28

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        from worldmodel_data.scrape import PageReader

        with PageReader(self, planned=2) as pages:
            outer = pages.read(VETO_PAGE, raw_dir / "vetoes.html", expect=r"veto", what="vetoes list")
            frame = veto_frame(outer)
            if frame:  # since 2026 the list itself is a separate page shown in a frame
                pages.planned += 1
                pages.read(frame, raw_dir / "veto_table.html", expect=r"negative vote", what="vetoes table")
            pages.read(MEMBERS_PAGE, raw_dir / "elected_members.html", expect=r"elected", what="elected members list")
        return f"{VETO_PAGE} {MEMBERS_PAGE}"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        pages = [p for p in raw_dir.iterdir() if p.suffix.lower() in (".html", ".htm")]
        if not pages:
            raise ConnectorError(f"un_vetoes: no saved pages in {raw_dir}")
        rows, unmatched = [], set()
        for p in pages:
            page = p.read_text(encoding="utf-8", errors="replace")
            if "veto" in p.name.lower() or re.search(r"negative vote", page, re.I):
                got = veto_events(page, unmatched)
                if not got and veto_frame(page):
                    log.warning("un_vetoes: %s is the outer page; the list is in a frame (%s). Open that address "
                                "and save it into this folder too.", p.name, veto_frame(page))
                rows += got
            else:
                rows += seat_events(page, unmatched)
        if not rows:
            raise ConnectorError("un_vetoes: no vetoes or members read; the pages' layout may have changed")
        self.events_query = stage_events(con, self.source_id, vintage, rows, unmatched)
        return EMPTY_OBSERVATIONS


def veto_events(page: str, unmatched: set[str]) -> list[tuple]:
    out, n = [], defaultdict(int)
    for cells in table_rows(page):
        if len(cells) < 4:
            continue
        d, prec = parse_day(cells[0])
        if d is None:
            continue
        draft = cells[1].split("\n")[0].strip()
        agenda = cells[-2] if len(cells) >= 5 else cells[2]
        who = cells[-1]
        for name in re.split(r"[,;\n]| and ", who):
            name = re.sub(r"\(.*?\)|\d+", "", name).strip(" .")
            if not name:
                continue
            ent = PERMANENT.get(name) or country(name, d, unmatched)
            if not ent:
                continue
            n[(ent, d)] += 1
            topic = re.sub(r"\s+", " ", agenda).strip()[:200]
            out.append((ent, f"veto:{ent}:{d.isoformat()}:{n[(ent, d)]}", "un", "veto",
                        f"Vetoed a Security Council draft{': ' + topic if topic else ''}", d, None, prec, None, None,
                        None, None, None, None, VETO_PAGE, f"Draft {draft}." if draft else None))
    return out


def veto_frame(page: str | None) -> str | None:
    """The address of the frame that holds the veto table on the library's page, if any."""
    m = re.search(r"""<iframe\b[^>]*\bsrc=["']([^"']*veto[^"']*)["']""", page or "", re.I)
    if not m:
        return None
    url = html.unescape(m.group(1))
    return "https:" + url if url.startswith("//") else url


def seat_events(page: str, unmatched: set[str]) -> list[tuple]:
    """Elected members: a country and its terms ("1946-1947, 1955-1956"), on one line or
    with the terms on the line after the name."""
    out, last = [], ""
    for line in text_of(page).split("\n"):
        terms = re.findall(r"(\d{4})\s*[-–—]\s*(\d{4})", line)
        if not terms:
            last = line.strip()
            continue
        name = re.split(r"\d{4}", line, maxsplit=1)[0]
        name = re.sub(r"\(.*?\)|\*", "", name).strip(" :,-–\t")
        if not name:
            name = re.sub(r"\(.*?\)|\*", "", last).strip(" :,-–\t")
        last = ""
        if not name or len(name) > 60:
            continue
        for y1, y2 in terms:
            start = date(int(y1), 1, 1)
            ent = country(name, start, unmatched)
            if not ent:
                continue
            out.append((ent, f"seat:{ent}:{y1}", "un", "council_seat", "Elected member of the UN Security Council",
                        start, date(int(y2), 12, 31), "year", None, None, None, None, None, None, MEMBERS_PAGE,
                        f"Term {y1} to {y2}."))
    return out


# ---------------------------------------------------------------- sanctions
GSDB_FIELDS = {
    "case": ("caseid", "case", "id"),
    "target": ("sanctionedstate", "sanctioned", "target"),
    "target_iso": ("sanctionedstateiso3", "sanctionediso3", "targetiso3"),
    "sender": ("sanctioningstate", "sanctioning", "sender"),
    "sender_iso": ("sanctioningstateiso3", "sanctioningiso3", "senderiso3"),
    "begin": ("begin", "start", "beginyear", "startyear"),
    "end": ("end", "endyear"),
    "begin_month": ("beginmonth", "startmonth"),
    "end_month": ("endmonth",),
    "objective": ("objective", "objectives"),
    "descr": ("descrtrade",),
}
# Names in the database that the country list does not know: older names, the blocs and
# organisations that impose (or are under) sanctions, and the armed groups under them.
GSDB_NAMES: dict[str, tuple[str, ...]] = {
    "ceylon": ("LKA",), "malaya": ("MYS",), "malagasy republic": ("MDG",), "transjordan": ("JOR",),
    "rhodesia": ("ZWE",), "north vietnam": ("VNM",), "south vietnam": ("RVN",), "fry": ("YUG",),
    "eu": ("eu",), "eec": ("eu",), "european union": ("eu",), "nato": ("nato",), "g7": ("g7",), "nafta": ("nafta",),
    "mercosur": ("mercosur",), "opec": ("opec",), "asean": ("asean",),
    "un": ("un",), "united nations": ("un",), "african union": ("african-union",), "organisation of african unity": ("oau",),
    "league of arab states": ("arab-league",), "ecowas": ("ecowas",), "eeu": ("eaeu",), "comecon": ("comecon",),
    "cocom": ("cocom",), "commonwealth": ("commonwealth",), "organization of american states": ("oas",),
    "pacific islands forum": ("pif",), "sadc": ("sadc",), "osce": ("osce",), "csce": ("osce",), "g8": ("g8",),
    "oic": ("oic",), "eccas": ("eccas",), "oapec": ("oapec",), "organization of eastern caribbean states": ("oecs",),
    "unasur": ("unasur",), "kimberly process participants": ("kimberley-process",), "wto": ("wto",), "imf": ("imf",),
    "isil/al-qaeda": ("isil", "al-qaeda"), "terrorist organizations (al-qaeda)": ("al-qaeda",),
    "terrorist organizations (taliban)": ("taliban",), "terrorist organizations (taliban and al-qaeda)": ("taliban", "al-qaeda"),
    "terrorist organizations (isil and anf)": ("isil", "al-nusra"),
}
# The second half of a name written with a comma ("Korea, North", "Gambia, The").
NAME_TAILS = {"the", "north", "south", "arab rep.", "rep.", "islamic rep.", "dem. rep.", "dem. people's rep.",
              "democratic republic of the", "republic of the", "federated states of", "bolivarian rep."}


def _gsdb_ids(name: str, when: date) -> tuple[str, ...]:
    """The entities one name stands for (two for "ISIL/Al-Qaeda"), or none."""
    found = GSDB_NAMES.get(name.lower())
    if found:
        return found
    one = catalogue.country_by_name(name, when)
    return (one,) if one else ()


def gsdb_names(cell: str, when: date) -> list[str]:
    """The countries in one cell: "United States, United Kingdom, France" is three, while
    "Korea, North" and "Congo, Democratic Republic of the" are one each."""
    out: list[str] = []
    for part in (p.strip() for p in str(cell or "").split(",")):
        if not part:
            continue
        if out and (part.lower() in NAME_TAILS
                    or (not _gsdb_ids(part, when) and _gsdb_ids(f"{out[-1]}, {part}", when))):
            out[-1] = f"{out[-1]}, {part}"
        else:
            out.append(part)
    return out


def _month(v) -> int:
    return MONTHS.get(str(v or "").strip().lower()[:3], 1)


MEASURES = (("trade", "trade"), ("arms", "arms"), ("military", "military aid"), ("financial", "financial"),
            ("travel", "travel"), ("other", "other"))


class GlobalSanctions(Connector):
    source_id = "gsdb"
    manual = True
    stage_version = 2  # 2: several countries in one cell (release 5), months, cases still in force

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:
            m = re.search(r"(?:v|_|r)(\d)(?:[._]|$)", f.stem, re.I)
            if m:
                return f"V{m.group(1)}"
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("gsdb: the Global Sanctions Database is sent on request; save it in manual\\gsdb "
                             "and run .\\load.bat gsdb")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".xlsx", ".csv"))
        if not files:
            raise ConnectorError(f"gsdb: no .xlsx or .csv file in {raw_dir} (save an .xls or .dta file as .xlsx first)")
        # The financial-sanctions companion file (GSDB-FS) can sit beside the main release; read the main one.
        main = [p for p in files if not re.search(r"(^|[^a-z])fs([^a-z]|$)|financial", p.stem, re.I)]
        f = (main or files)[-1]
        table = (list(csv.reader(io.StringIO(f.read_text(encoding="utf-8-sig", errors="replace"))))
                 if f.suffix.lower() == ".csv" else xlsx_rows(f))
        events, values, unmatched = sanction_rows(table, datetime.now().year)
        if not events:
            raise ConnectorError(f"gsdb: no sanction cases read from {f.name}; the columns may have changed")
        self.events_query = stage_events(con, self.source_id, vintage, events, unmatched)
        self.listed_indicators = SANCTION_INDICATORS
        return values.stage(con, self.source_id, vintage)


def _fields(header: list, fields: dict) -> dict[str, int]:
    keys = [key(h) for h in header]
    out = {}
    for field, names in fields.items():
        i = next((i for i, k in enumerate(keys) if k in {key(n) for n in names}), None)
        if i is not None:
            out[field] = i
    return out


def sanction_rows(table: list[list], this_year: int) -> tuple[list[tuple], Rows, set[str]]:
    start = next((i for i, r in enumerate(table[:10]) if {"target", "begin"} <= set(_fields(r, GSDB_FIELDS))), None)
    if start is None:
        return [], Rows(), set()
    col = _fields(table[start], GSDB_FIELDS)
    keys = [key(h) for h in table[start]]
    measure_cols = [(keys.index(k), label) for k, label in MEASURES if k in keys]
    get = lambda r, f: r[col[f]] if f in col and col[f] < len(r) else None  # noqa: E731
    events, unmatched = [], set()
    active: dict[tuple[str, int], int] = defaultdict(int)
    imposed: dict[tuple[str, int], int] = defaultdict(int)
    # The last year the database covers: a case ending then is still in force, not ended.
    last = max((int(v) for r in table[start + 1:] if (v := num(get(r, "end"))) is not None), default=this_year)
    last = min(last, this_year)
    for i, r in enumerate(table[start + 1:]):
        y0, y1 = num(get(r, "begin")), num(get(r, "end"))
        if y0 is None:
            continue
        y0 = int(y0)
        y1 = int(y1) if y1 is not None and y1 >= y0 else None
        when = date(y0, _month(get(r, "begin_month")), 1)
        targets = []
        iso = entity_for("iso3", str(get(r, "target_iso") or "").strip().upper())
        for name in ([] if iso else gsdb_names(get(r, "target"), when)):
            found = _gsdb_ids(name, when)
            if not found:
                unmatched.add(name)
            targets += [f for f in found if f not in targets]
        if iso:
            targets = [iso]
        if not targets:
            continue
        sender_name = str(get(r, "sender") or "").strip()
        sender_iso = entity_for("iso3", str(get(r, "sender_iso") or "").strip().upper())
        senders = [sender_iso] if sender_iso else list(dict.fromkeys(
            f for n in gsdb_names(sender_name, when) for f in _gsdb_ids(n, when)))
        kinds = [label for j, label in measure_cols if j < len(r) and num(r[j])]
        case = str(get(r, "case") or i + 1).strip()
        why = str(get(r, "objective") or "").replace("_", " ").strip()
        detail = "; ".join(filter(None, [f"Measures: {', '.join(kinds)}" if kinds else "",
                                        f"Aims: {why}" if why else "", f"Case {case} in the Global Sanctions Database"]))
        end = None
        if y1 is not None and y1 < last:
            m = MONTHS.get(str(get(r, "end_month") or "").strip().lower()[:3], 12)  # no month: the year's end
            end = date(y1, m, calendar.monthrange(y1, m)[1])
        for target in targets:
            events.append((target, f"gsdb:{case}:{target}", "sanction", ", ".join(kinds) or None,
                           f"Sanctions by {sender_name or 'another country'}", when, end, "year", None, None, None, None,
                           None, sender_name or None, None, detail))
            for y in range(y0, (y1 if y1 is not None else this_year) + 1):
                active[(target, y)] += 1
        for sender in senders:
            for y in range(y0, (y1 if y1 is not None else this_year) + 1):
                imposed[(sender, y)] += 1
    values = Rows()
    for (e, y), n in active.items():
        values.add("iso3", e, "sanctions_active", y, n)
    for (e, y), n in imposed.items():
        values.add("iso3", e, "sanctions_imposed", y, n)
    return events, values, unmatched


# ---------------------------------------------------------------- IMF programmes
MONA_PAGE = "https://www.imf.org/mona/arrangements"
# Since 2026 the MONA pages build each file in the browser from this address, which answers
# {"data": [{"Arrangement Number": 570, "Country Name": ..., ...}, ...]} (one row per review).
MONA_API = "https://www.imf.org/api/mona/downloadReportProxy?reportName=Description.xlsx"
MONA_FIELDS = {
    "number": ("arrangementnumber", "arrangementno", "arrangementid"),
    "country": ("countryname", "country"),
    "type": ("arrangementtype", "facility", "type"),
    "approval": ("approvaldate", "dateofapproval", "boardapprovaldate"),
    "approval_year": ("approvalyear",),
    "end": ("revisedenddate", "currenttermination", "currentexpirationdate"),
    "initial_end": ("initialenddate", "initialexpirationdate", "expirationdate"),
    "access": ("totalaccess", "totalaccesssdr", "amountagreed", "totalamountagreed", "amountapproved"),
}
IMF_TYPES = {"SBA": "Stand-By Arrangement", "EFF": "Extended Fund Facility", "ECF": "Extended Credit Facility",
             "SCF": "Standby Credit Facility", "PRGF": "Poverty Reduction and Growth Facility", "FCL": "Flexible Credit Line",
             "PLL": "Precautionary and Liquidity Line", "RSF": "Resilience and Sustainability Facility",
             "PCI": "Policy Coordination Instrument", "PSI": "Policy Support Instrument", "SAF": "Structural Adjustment Facility",
             "ESAF": "Enhanced Structural Adjustment Facility", "RFI": "Rapid Financing Instrument", "RCF": "Rapid Credit Facility"}


class IMFMona(Connector):
    source_id = "imf_mona"
    fetch_every_days = 28

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    fetch_version = 2  # 2: the MONA data address behind the 2026 pages

    def download(self, raw_dir: Path, release: str) -> str:
        dest = raw_dir / "mona_description.json"
        self.get(MONA_API, dest, cached=False)
        head = dest.read_bytes()[:4]
        if head.startswith(b"PK"):  # a real workbook, should the address start sending one
            dest.rename(raw_dir / "mona_description.xlsx")
        elif not head.lstrip().startswith(b"{"):
            dest.unlink(missing_ok=True)
            raise ConnectorError(f"imf_mona: {MONA_API} did not answer with the arrangements data; save 'Description' "
                                 f"from {MONA_PAGE} into var\\manual\\imf_mona")
        return MONA_API

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".xlsx", ".csv", ".json"))
        if not files:
            raise ConnectorError(f"imf_mona: no .xlsx or .csv file in {raw_dir} (save an .xls file as .xlsx first)")
        events, unmatched = [], set()
        for f in files:
            if f.suffix.lower() == ".json":
                table = mona_json_table(f)
            elif f.suffix.lower() == ".csv":
                table = list(csv.reader(io.StringIO(f.read_text(encoding="utf-8-sig", errors="replace"))))
            else:
                table = xlsx_rows(f)
            events += programme_events(table, unmatched)
        if not events:
            raise ConnectorError("imf_mona: no programmes read; the file's columns may have changed")
        uniq = {e[1]: e for e in events}
        self.events_query = stage_events(con, self.source_id, vintage, list(uniq.values()), unmatched)
        return EMPTY_OBSERVATIONS


def mona_json_table(path: Path) -> list[list]:
    """The MONA data address's answer as a table: a heading row, then one row per record."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConnectorError(f"imf_mona: {path.name} is not the MONA data ({exc})") from None
    recs = doc.get("data") if isinstance(doc, dict) else doc
    if not isinstance(recs, list) or not recs:
        return []
    keys = list(dict.fromkeys(k for r in recs[:50] if isinstance(r, dict) for k in r))
    return [keys] + [[r.get(k) for k in keys] for r in recs if isinstance(r, dict)]


def httpx_join(base: str, link: str) -> str:
    from urllib.parse import urljoin
    return urljoin(base, link)


def programme_events(table: list[list], unmatched: set[str]) -> list[tuple]:
    start = next((i for i, r in enumerate(table[:15]) if {"country", "type"} <= set(_fields(r, MONA_FIELDS))
                  and ({"approval", "approval_year"} & set(_fields(r, MONA_FIELDS)))), None)
    if start is None:
        return []
    col = _fields(table[start], MONA_FIELDS)
    get = lambda r, f: r[col[f]] if f in col and col[f] < len(r) else None  # noqa: E731
    found: dict[str, dict] = {}
    for r in table[start + 1:]:
        name = str(get(r, "country") or "").strip()
        approved = iso_date(get(r, "approval")) or iso_date(get(r, "approval_year"))
        if not name or not approved:
            continue
        kind = str(get(r, "type") or "").strip().upper()
        number = str(get(r, "number") or f"{name}:{kind}:{approved}").strip()
        end = iso_date(get(r, "end")) or iso_date(get(r, "initial_end"))
        access = num(get(r, "access"))
        have = found.get(number)
        if have:  # later reviews: keep the latest end date and the largest amount
            have["end"] = max(filter(None, (have["end"], end)), default=None)
            have["access"] = max(filter(None, (have["access"], access)), default=None)
            continue
        found[number] = {"name": name, "kind": kind, "approved": approved, "end": end, "access": access}
    out = []
    for number, p in found.items():
        # MONA writes "AFGHANISTAN,ISLAMIC REPUBLIC OF": the part before the comma is the plain name.
        ent = catalogue.country_by_name(p["name"], p["approved"]) or \
            country(p["name"].split(",")[0].strip(), p["approved"], unmatched)
        if not ent:
            continue
        label = IMF_TYPES.get(p["kind"], p["kind"] or "lending")
        size = p["access"] / 1e6 if p["access"] and p["access"] > 1e5 else p["access"]  # SDR or SDR thousands -> millions
        out.append((ent, f"imf:{number}", "imf", p["kind"] or None, f"IMF programme: {label}", p["approved"], p["end"],
                    "day", size, "SDR million" if size else None, None, None, None, None, MONA_PAGE,
                    f"Arrangement {number}." if number and not number.startswith(p["name"]) else None))
    return out


# ---------------------------------------------------------------- WTO disputes
WTO_PAGE = "https://www.wto.org/english/tratop_e/dispu_e/dispu_status_e.htm"
# Since 2026 the page is built in the browser from these two script files: every case (DS
# number, title, complainants and respondent as codes, date, status) and the status names.
WTO_CASES = "https://www.wto.org/library/disputes/dispute_case_arrays_e.js"
WTO_STATUSES = "https://www.wto.org/library/disputes/dispute_arrays_e.js"
WTO_EU = {"European Communities", "European Union", "EC", "EU"}
WTO_CODES = {"EEC": "eu", "CHT": "TWN", "ROM": "ROU"}  # the WTO's own codes that are not ISO


class WTODisputes(Connector):
    source_id = "wto_disputes"
    stage_version = 2  # 2: the WTO's case data file; parties split properly on saved pages
    fetch_version = 2  # 2: the case data file instead of the page
    fetch_every_days = 28

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        from worldmodel_data.scrape import PageReader

        with PageReader(self, planned=2) as pages:
            pages.read(WTO_CASES, raw_dir / "dispute_case_arrays_e.js", expect=r"ds_array\[\d+\]", what="cases data")
            pages.read(WTO_STATUSES, raw_dir / "dispute_arrays_e.js", expect=r"status_code", what="status names")
        return WTO_CASES

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        unmatched: set[str] = set()
        cases = raw_dir / "dispute_case_arrays_e.js"
        if cases.exists():
            statuses = raw_dir / "dispute_arrays_e.js"
            rows = case_array_events(cases.read_text(encoding="utf-8", errors="replace"),
                                     statuses.read_text(encoding="utf-8", errors="replace") if statuses.exists() else "",
                                     unmatched)
        else:  # the page saved from a browser, with the list on it
            pages = [p for p in raw_dir.iterdir() if p.suffix.lower() in (".html", ".htm")]
            if not pages:
                raise ConnectorError(f"wto_disputes: no saved page or cases file in {raw_dir}")
            rows = dispute_events(pages[0].read_text(encoding="utf-8", errors="replace"), unmatched)
        if not rows:
            raise ConnectorError("wto_disputes: no cases read; the page's layout may have changed")
        self.events_query = stage_events(con, self.source_id, vintage, rows, unmatched)
        return EMPTY_OBSERVATIONS


def _wto_party(name: str, on: date, unmatched: set[str]) -> str | None:
    name = re.sub(r"\(.*?\)", "", name).strip(" .;,")
    name = re.sub(r"\s+and (certain|its|a) member states?$", "", name, flags=re.I)
    if name in WTO_EU:
        return "eu"
    return country(name, on, unmatched)


def _js_fields(block: str) -> dict[str, str]:
    return {k: html.unescape(v).replace("\xa0", " ").strip() for k, v in re.findall(r'(\w+)\s*:\s*"((?:[^"\\]|\\.)*)"', block)}


def _wto_code(code: str, unmatched: set[str]) -> str | None:
    code = code.strip().upper()
    if not code:
        return None
    ent = WTO_CODES.get(code) or entity_for("iso3", code)
    if not ent:
        unmatched.add(code)
    return ent


def case_array_events(cases: str, statuses: str, unmatched: set[str]) -> list[tuple]:
    """Each case in the WTO's dispute_case_arrays_e.js: one event on the respondent and one on
    each complainant, dated by the request for consultations."""
    from worldmodel_contract.catalogue import entities

    names = {k: e.short_name or e.name for k, e in entities().items()}
    status = {c: n for c, n in re.findall(r'status_code:\s*"(\w+)",\s*status_name:\s*"([^"]*)"', statuses)}
    out = []
    for no, block in re.findall(r"ds_array\[(\d+)\]\s*=\s*\{(.*?)\};", cases, re.S):
        f = _js_fields(block)
        d, prec = parse_day((f.get("start_date") or "").replace("/", "-"))
        if d is None:
            continue
        ds = f.get("code") or f"DS{no}"
        num_ = ds.removeprefix("DS")
        url = f"https://www.wto.org/english/tratop_e/dispu_e/cases_e/ds{num_}_e.htm"
        subject = (f.get("title") or "").strip(" .")[:200]
        st = status.get((f.get("status") or "").split("#")[0])
        detail = f"Current status: {st}." if st else None
        respondents = [e for e in (_wto_code(c, unmatched) for c in (f.get("destination") or "").split("#")) if e]
        complainants = [e for e in (_wto_code(c, unmatched) for c in (f.get("origin") or "").split("#")) if e]
        by = ", ".join(names.get(c, c) for c in complainants)
        against = ", ".join(names.get(r, r) for r in respondents)
        for r in respondents:
            out.append((r, f"{ds}:r", "trade_dispute", "respondent",
                        f"WTO dispute {ds}{' brought by ' + by if by else ''}: {subject}", d, None, prec, None, None,
                        None, None, None, None, url, detail))
        for c in complainants:
            out.append((c, f"{ds}:c:{c}", "trade_dispute", "complainant",
                        f"Brought WTO dispute {ds} against {against}: {subject}", d, None, prec, None, None,
                        None, None, None, None, url, detail))
    return out


def _wto_names(text: str, on: date, unmatched: set[str]) -> list[tuple[str, str]]:
    """(name, entity) for each party in "Antigua and Barbuda, Venezuela, Bolivarian Republic of"."""
    bits = [b.strip() for b in text.split(",") if b.strip()]
    out, i = [], 0
    while i < len(bits):
        two = f"{bits[i]}, {bits[i + 1]}" if i + 1 < len(bits) else None
        if two and catalogue.country_by_name(two, on):
            out.append((two, catalogue.country_by_name(two, on)))
            i += 2
            continue
        ent = _wto_party(bits[i], on, set())
        if ent:
            out.append((bits[i], ent))
        else:
            parts = [p.strip() for p in re.split(r" and ", bits[i]) if p.strip()]
            found = [(p, _wto_party(p, on, set())) for p in parts] if len(parts) > 1 else []
            if found and all(e for _, e in found):
                out += found
            else:
                unmatched.add(bits[i])
        i += 1
    return out


def dispute_events(page: str, unmatched: set[str]) -> list[tuple]:
    """Each case: "DS123 ... Respondent — Subject ... Complainant: X ... 12 May 1999"."""
    text = text_of(page)
    chunks = re.split(r"(?=\bDS\s?\d{1,4}\b)", text)
    out, seen = [], set()
    for chunk in chunks:
        m = re.match(r"DS\s?(\d{1,4})\b[:.\s]*(.*)", chunk, re.S)
        if not m or m.group(1) in seen:
            continue
        body = re.sub(r"\s+", " ", m.group(2)).strip()
        parts = re.split(r"\s+[—–-]{1,2}\s+", body, maxsplit=1)
        if len(parts) < 2:
            continue
        respondent_name, rest = parts[0].strip(), parts[1]
        subject = re.split(r"\s*(?:Short title|Complainant|Date|Current status|Consultations requested|Request for consultations|Summary)\b",
                           rest)[0].strip(" .")[:200]
        d, prec = parse_day(rest)
        if d is None:
            continue
        seen.add(m.group(1))
        ds = f"DS{m.group(1)}"
        url = f"https://www.wto.org/english/tratop_e/dispu_e/cases_e/ds{m.group(1)}_e.htm"
        respondent = _wto_party(respondent_name, d, unmatched)
        cm = re.search(r"Complainants?\s*:?\s*([^;\n]+?)(?:\s+(?:Date|Respondent|Third|Current|Request|Consultations|\d)|[;\n]|$)", rest)
        parties = _wto_names(cm.group(1).strip(" ."), d, unmatched) if cm else []
        by = ", ".join(n for n, _ in parties) or None
        if respondent:
            out.append((respondent, f"{ds}:r", "trade_dispute", "respondent",
                        f"WTO dispute {ds}{' brought by ' + by if by else ''}: {subject}", d, None, prec, None, None,
                        None, None, None, None, url, None))
        for _, ent in parties:
            if ent:
                out.append((ent, f"{ds}:c:{ent}", "trade_dispute", "complainant",
                            f"Brought WTO dispute {ds} against {respondent_name}: {subject}", d, None, prec, None, None,
                            None, None, None, None, url, None))
    return out


# ---------------------------------------------------------------- treaties
UNTC = "https://treaties.un.org/Pages/ViewDetails.aspx?src=TREATY&mtdsg_no={no}&chapter={ch}&clang=_en"
# (key, short name, UNTC number, chapter)
TREATIES = (
    ("genocide", "Genocide Convention", "IV-1", 4),
    ("cerd", "Convention on the Elimination of Racial Discrimination", "IV-2", 4),
    ("icescr", "International Covenant on Economic, Social and Cultural Rights", "IV-3", 4),
    ("iccpr", "International Covenant on Civil and Political Rights", "IV-4", 4),
    ("cedaw", "Convention on the Elimination of Discrimination against Women", "IV-8", 4),
    ("cat", "Convention against Torture", "IV-9", 4),
    ("crc", "Convention on the Rights of the Child", "IV-11", 4),
    ("iccpr_op2", "Second Optional Protocol to the ICCPR (abolishing the death penalty)", "IV-12", 4),
    ("crpd", "Convention on the Rights of Persons with Disabilities", "IV-15", 4),
    ("refugees", "Refugee Convention (1951)", "V-2", 5),
    ("rome", "Rome Statute of the International Criminal Court", "XVIII-10", 18),
    ("unclos", "UN Convention on the Law of the Sea", "XXI-6", 21),
    ("bbnj", "High Seas Treaty (Biodiversity Beyond National Jurisdiction)", "XXI-10", 21),
    ("mine_ban", "Mine Ban Treaty (Ottawa)", "XXVI-5", 26),
    ("cluster", "Convention on Cluster Munitions", "XXVI-6", 26),
    ("att", "Arms Trade Treaty", "XXVI-8", 26),
    ("tpnw", "Treaty on the Prohibition of Nuclear Weapons", "XXVI-9", 26),
    ("montreal", "Montreal Protocol (ozone layer)", "XXVII-2-a", 27),
    ("unfccc", "UN Framework Convention on Climate Change", "XXVII-7", 27),
    ("kyoto", "Kyoto Protocol", "XXVII-7-a", 27),
    ("paris", "Paris Agreement", "XXVII-7-d", 27),
    ("minamata", "Minamata Convention on Mercury", "XXVII-17", 27),
)
TREATY_NAMES = {k: n for k, n, _, _ in TREATIES}


class UNTreaties(Connector):
    source_id = "un_treaties"
    stage_version = 2  # 2: UN spellings, the EU, header rows left out
    fetch_every_days = 28

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        from worldmodel_data.scrape import PageReader

        got = []
        with PageReader(self, planned=len(TREATIES)) as pages:
            for k, _, no, ch in TREATIES:
                if pages.read(UNTC.format(no=no, ch=ch), raw_dir / f"treaty_{k}.html", missing_ok=True, what=k,
                              expect=r"participant") is not None:
                    got.append(k)
        if not got:
            raise ConnectorError("un_treaties: none of the treaty pages could be downloaded")
        return f"{len(got)} treaty pages from treaties.un.org"

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        events, unmatched = [], set()
        for p in sorted(raw_dir.glob("*.htm*")):
            k = treaty_key(p.name, p.read_text(encoding="utf-8", errors="replace"))
            if not k:
                log.warning("un_treaties: %s is not one of the known treaties; skipped", p.name)
                continue
            events += treaty_events(k, p.read_text(encoding="utf-8", errors="replace"), unmatched)
        if not events:
            raise ConnectorError("un_treaties: no signatures or ratifications read; the pages' layout may have changed")
        self.events_query = stage_events(con, self.source_id, vintage, events, unmatched)
        self.listed_indicators = TREATY_INDICATORS
        return joined_counts(events, datetime.now().year).stage(con, self.source_id, vintage)


def treaty_key(file_name: str, page: str) -> str | None:
    m = re.match(r"treaty_([a-z0-9_]+)\.html?$", file_name)
    if m and m.group(1) in TREATY_NAMES:
        return m.group(1)
    for k, _, no, _ in TREATIES:  # a page saved by hand: find its number in the page
        if re.search(rf"mtdsg_no={re.escape(no)}&|\b{re.escape(no)}\b", page):
            return k
    return None


# Rows of a treaty page's top table ("Entry into force: ...", "Registration: ...") and notes,
# which have dates in them but are not participants.
TREATY_NOT_PARTIES = re.compile(r"^(entry into force|registration|status|text|note|notes|signatories|parties|"
                                r"depositary|participants?|adopted|concluded|declarations?|reservations?)\b", re.I)
TREATY_BLOCS = {"european union": "eu", "european community": "eu", "european economic community": "eu"}


def treaty_events(k: str, page: str, unmatched: set[str]) -> list[tuple]:
    out = []
    for cells in table_rows(page):
        if len(cells) < 3 or re.search(r"participant", cells[0], re.I):
            continue
        name = re.sub(r"\d+|\*", "", cells[0]).strip(" ,.:")
        if TREATY_NOT_PARTIES.match(name):
            continue
        signed, _ = parse_day(cells[1])
        joined, _ = parse_day(cells[2])
        if not name or not (signed or joined):
            continue
        how = re.search(r"\b(a|d|A|AA)\s*$", cells[2].strip())
        how = {"a": "acceded", "d": "succeeded", "A": "accepted", "AA": "approved"}.get(how.group(1) if how else "", "ratified")
        ent = TREATY_BLOCS.get(name.lower()) or country(name, joined or signed, unmatched)
        if not ent:
            continue
        url = UNTC.format(no=next(no for kk, _, no, _ in TREATIES if kk == k), ch=next(ch for kk, _, _, ch in TREATIES if kk == k))
        if joined:
            out.append((ent, f"{k}:{ent}", "treaty", k, f"Joined the {TREATY_NAMES[k]}", joined, None, "day", None, None,
                        None, None, None, None, url, f"{how.capitalize()} on {joined.isoformat()}"
                        + (f"; signed {signed.isoformat()}" if signed else "") + "."))
        else:
            out.append((ent, f"{k}:{ent}", "treaty", k, f"Signed the {TREATY_NAMES[k]} (not yet ratified)", signed, None,
                        "day", None, None, None, None, None, None, url, "Signed only."))
    return out


def joined_counts(events: list[tuple], this_year: int) -> Rows:
    """treaties_joined: how many of the listed treaties each country had joined by the end of each year."""
    first: dict[str, list[int]] = defaultdict(list)
    for e in events:
        if e[4].startswith("Joined") and e[0] not in TREATY_BLOCS.values():  # countries only
            first[e[0]].append(e[5].year)
    rows = Rows()
    for ent, years in first.items():
        years.sort()
        for y in range(years[0], this_year + 1):
            rows.add("iso3", ent, "treaties_joined", y, sum(1 for x in years if x <= y))
    return rows
