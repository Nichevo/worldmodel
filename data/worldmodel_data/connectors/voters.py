"""Who votes: turnout by age, sex and group, for the key countries.

us_census_voting
    US Census Bureau, Current Population Survey November supplement, historical
    table A-1 "Reported Voting and Registration by Race, Hispanic Origin, Sex and Age
    Groups: November 1964 to 2024" (hst_vote01.xlsx), downloaded on its own. One
    sheet of blocks, each headed by a "Year" row, two rows of column headings and a
    title row such as "18 to 24 Years, Percent Voted"; then one row per election
    year. Columns: voting-age population (thousands), total percent (all residents
    and citizens), percent by group (White, White non-Hispanic, Black, Asian,
    Hispanic; all residents and citizens) and, in later blocks, Male and Female.
    Shares are of everyone of that age living in the US (citizens or not), as the
    survey reports them, unless the indicator says citizens.

nz_election_turnout (New Zealand pack)
    Electoral Commission, voter turnout statistics for each general election
    (elections.nz, Statistics): the spreadsheet "<year> General Election - Voter
    turnout by electorate and age" (sheets by electorate and age band, by descent,
    and by age band and descent). Loaded by hand; files add up, so load each
    election's file once: `.\\load.bat nz_election_turnout <file>`. National figures
    (the "All electorates" rows) for now; electorates come with the regions work.
    Shares are of people enrolled.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.tabular import Rows, indicator, key, num, xlsx_rows, xlsx_sheet_names

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------------------- US Census
US_URL = ("https://www2.census.gov/programs-surveys/cps/tables/time-series/voting-historical-time-series/"
          "hst_vote01.xlsx")
US_PAGE = "https://www.census.gov/data/tables/time-series/demo/voting-and-registration/voting-historical-time-series.html"
US_AGES = {"18to24": "18_24", "25to44": "25_44", "45to64": "45_64", "65andover": "65_plus"}
US_AGE_LABEL = {"18_24": "18 to 24", "25_44": "25 to 44", "45_64": "45 to 64", "65_plus": "65 and over"}
US_GROUPS = {"white": "white", "whitenonhispanic": "white_nh", "black": "black", "asian": "asian",
             "asian1": "asian", "hispanicanyrace": "hispanic", "hispanic": "hispanic"}
US_GROUP_LABEL = {"white": "White", "white_nh": "White non-Hispanic", "black": "Black", "asian": "Asian",
                  "hispanic": "Hispanic (any race)", "male": "men", "female": "women"}


def read_us_table(path: Path) -> dict[tuple[str, int], float]:
    """Table A-1 as {(indicator id, year): value}."""
    rows = xlsx_rows(path)
    out: dict[tuple[str, int], float] = {}
    starts = [i for i, r in enumerate(rows) if r and key(r[0]) == "year"]
    if not starts:
        raise ConnectorError(f"us_census_voting: {path.name} has no 'Year' heading rows; is it table A-1 (hst_vote01)?")
    for b, i in enumerate(starts):
        end = starts[b + 1] if b + 1 < len(starts) else len(rows)
        if i + 3 >= end:
            continue
        groups, subs = rows[i + 1], rows[i + 2]
        title = key(next((c for c in rows[i + 3] if c), ""))
        measure = "voted" if title.endswith("percentvoted") else "registered" if title.endswith("percentregistered") else None
        if not measure:
            continue
        who = title.removesuffix("percentvoted").removesuffix("percentregistered").replace("years", "")
        age = None if who == "total" else US_AGES.get(who)
        if who != "total" and not age:
            log.warning("us_census_voting: block %r not recognised", rows[i + 3][0])
            continue
        # Which column is which: the group heading carries on to the right until the next one.
        cols: dict[int, str] = {}
        group = None
        for j in range(1, max(len(groups), len(subs))):
            g = groups[j] if j < len(groups) else None
            group = US_GROUPS.get(key(g), key(g)) if g else group
            sub = key(subs[j] if j < len(subs) else None)
            if j == 1:
                cols[j] = "vap"
            elif sub in ("male", "female"):
                cols[j] = sub
            elif j in (2, 3) or group is None:
                cols[j] = "total_citizens" if sub == "citizenpopulation" else "total"
            elif group in US_GROUP_LABEL:
                cols[j] = group + ("_citizens" if sub == "citizenpopulation" else "")
        base = f"us_{measure}" + (f"_age_{age}" if age else "")
        for r in rows[i + 4:end]:
            if not r or not isinstance(r[0], (int, float)) and not re.fullmatch(r"\d{4}", str(r[0] or "").strip()):
                continue
            year = int(float(r[0]))
            for j, what in cols.items():
                v = num(r[j]) if j < len(r) else None
                if v is None:
                    continue
                if what == "vap":
                    if not age and measure == "voted":
                        out[("us_voting_age_population", year)] = v * 1000
                    continue
                if age and what not in ("total", "male", "female"):
                    continue  # by age, only all residents and by sex
                if what.endswith("_citizens") and what != "total_citizens":
                    continue  # groups: all residents only (citizen shares only since 1978)
                ind = base if what == "total" else f"{base}_citizens" if what == "total_citizens" else f"{base}_{what}"
                out[(ind, year)] = v
    if not out:
        raise ConnectorError(f"us_census_voting: no figures read from {path.name}")
    return out


US_NOTE = ("US Census Bureau, Current Population Survey November supplement (table A-1); people's own reports, "
           "which run a few points above the official count. Before 1972 the youngest group is 21 to 24 in most "
           "states.")


def _us_indicators(found: set[str]) -> list[dict]:
    listed = []
    for measure, verb in (("voted", "Voted"), ("registered", "Registered to vote")):
        on = measure == "voted"
        unit = "% of voting-age residents"
        listed.append(indicator(f"us_{measure}", f"{verb}, US (survey)",
                                f"{verb}, as a share of everyone 18 and over living in the US. " + US_NOTE,
                                unit, "politics", "us_census_voting", f"A-1 total {measure}", default_on=on, bounds=(0, 100)))
        listed.append(indicator(f"us_{measure}_citizens", f"{verb}, US citizens (survey)",
                                f"{verb}, as a share of US citizens 18 and over (from 1978). " + US_NOTE,
                                "% of voting-age citizens", "politics", "us_census_voting", f"A-1 total {measure} citizens",
                                default_on=on, bounds=(0, 100)))
        for g, label in US_GROUP_LABEL.items():
            listed.append(indicator(f"us_{measure}_{g}", f"{verb}, US, {label} (survey)",
                                    f"{verb}, as a share of {label} 18 and over living in the US. " + US_NOTE
                                    + (" Race groups changed in 2003, so earlier years are not quite comparable."
                                       if g not in ("male", "female") else ""),
                                    unit, "politics", "us_census_voting", f"A-1 {g} {measure}", default_on=on, bounds=(0, 100)))
        for a, label in US_AGE_LABEL.items():
            listed.append(indicator(f"us_{measure}_age_{a}", f"{verb}, US, aged {label} (survey)",
                                    f"{verb}, as a share of people aged {label} living in the US. " + US_NOTE,
                                    unit, "politics", "us_census_voting", f"A-1 {a} {measure}", default_on=on, bounds=(0, 100)))
            for sx in ("male", "female"):
                listed.append(indicator(f"us_{measure}_age_{a}_{sx}", f"{verb}, US, {US_GROUP_LABEL[sx]} aged {label} (survey)",
                                        f"{verb}, as a share of {US_GROUP_LABEL[sx]} aged {label} living in the US. " + US_NOTE,
                                        unit, "politics", "us_census_voting", f"A-1 {a} {sx} {measure}",
                                        default_on=False, bounds=(0, 100)))
    listed.append(indicator("us_voting_age_population", "Voting-age population, US (survey)",
                            "Everyone 18 and over living in the US, citizens or not. " + US_NOTE, "persons", "politics",
                            "us_census_voting", "A-1 total voting-age population", decimals=0, default_on=False))
    return [i for i in listed if i["id"] in found]


class USCensusVoting(Connector):
    source_id = "us_census_voting"
    fetch_every_days = 90  # updated after each November election

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        dest = raw_dir / "hst_vote01.xlsx"
        self.get(US_URL, dest)
        if dest.read_bytes()[:2] != b"PK":
            dest.unlink()
            raise ConnectorError("us_census_voting: the Census Bureau did not send the spreadsheet. Download table "
                                 f"A-1 (hst_vote01.xlsx) from {US_PAGE} and run: .\\load.bat us_census_voting <file>")
        return US_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".xlsx", ".xlsm"))
        if not files:
            raise ConnectorError(f"us_census_voting: no .xlsx file in {raw_dir}")
        values = read_us_table(files[0])
        rows = Rows()
        for (ind, year), v in values.items():
            rows.add("iso3", "USA", ind, year, v)
        self.listed_indicators = _us_indicators({ind for ind, _ in values})
        return rows.stage(con, self.source_id, vintage)


# ------------------------------------------------------------------------- NZ Electoral Commission
NZ_PAGE = "https://elections.nz/stats-and-research/"
NZ_AGE = re.compile(r"^\s*(\d{2})\s*[-–]\s*(\d{2})\s*$|^\s*(\d{2})\s*\+\s*$")
NZ_DESCENT = {"maoridescent": "maori", "nonmaoridescent": "non_maori"}


def _plain(v) -> str:
    """key() with macrons and accents dropped first (Māori -> maori)."""
    return key(unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode())


def _nz_age(label) -> str | None:
    m = NZ_AGE.match(str(label or ""))
    if not m:
        return None
    return f"{m.group(1)}_{m.group(2)}" if m.group(1) else f"{m.group(3)}_plus"


def read_nz_turnout(path: Path) -> tuple[int, dict[str, tuple[float, float]]]:
    """One Electoral Commission turnout spreadsheet: (election year, {indicator: (voters, enrolled)}),
    national rows only."""
    out: dict[str, tuple[float, float]] = {}
    year = None
    for sheet in xlsx_sheet_names(path):
        rows = xlsx_rows(path, sheet)
        for r in rows[:4]:
            m = re.search(r"((?:19|20)\d\d)\s+general election", str(r[0] if r else "") or "", re.I)
            year = year or (int(m.group(1)) if m else None)
        hi = next((i for i, r in enumerate(rows[:15]) if r and "voters" in [key(c) for c in r]
                   and "totalenrolled" in [key(c) for c in r]), None)
        if hi is None:
            continue
        head = [key(c) for c in rows[hi]]
        ni = head.index("electoratename") if "electoratename" in head else 1
        vi, ti = head.index("voters"), head.index("totalenrolled")
        ai = next((i for i, h in enumerate(head) if h.startswith("ageband")), None)
        di = next((i for i, h in enumerate(head) if "descent" in h), None)
        for r in rows[hi + 1:]:
            if len(r) <= max(vi, ti, ni) or key(r[ni]) != "allelectorates":
                continue
            voters, enrolled = num(r[vi]), num(r[ti])
            if voters is None or not enrolled:
                continue
            age = _nz_age(r[ai]) if ai is not None else None
            descent = NZ_DESCENT.get(_plain(r[di])) if di is not None else None
            parts = (["age_" + age] if age else []) + ([descent] if descent else [])
            if ai is not None and not age and key(r[ai]) not in ("allagebands", "allages"):
                continue
            if di is not None and not descent and _plain(r[di]) not in ("allvoters", ""):
                continue
            ind = "nz_turnout" + "".join("_" + p for p in parts)
            out.setdefault(ind, (voters, enrolled))
    if year is None:
        m = re.search(r"(?:19|20)\d\d", path.name)
        year = int(m.group(0)) if m else None
    if year is None:
        raise ConnectorError(f"nz_election_turnout: no election year in {path.name} (its title or name)")
    if not out:
        raise ConnectorError(f"nz_election_turnout: no 'All electorates' rows with Voters and Total enrolled in {path.name}")
    return year, out


NZ_NOTE = ("Electoral Commission, general election voter turnout statistics: votes cast as a share of people "
           "enrolled.")


def _nz_label(ind: str) -> str:
    rest = ind.removeprefix("nz_turnout").strip("_")
    bits = []
    m = re.match(r"age_(\d+)_(\d+|plus)", rest)
    if m:
        bits.append(f"aged {m.group(1)}+" if m.group(2) == "plus" else f"aged {m.group(1)} to {m.group(2)}")
        rest = rest[m.end():].strip("_")
    if rest == "maori":
        bits.insert(0, "Māori descent")
    elif rest == "non_maori":
        bits.insert(0, "non-Māori descent")
    return ", ".join(bits)


class NZElectionTurnout(Connector):
    source_id = "nz_election_turnout"
    pack = "nz"
    manual = True
    keeps_files = True  # each election's file is loaded once; earlier ones stay

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m-%d")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("nz_election_turnout: the Electoral Commission's turnout spreadsheets are loaded by "
                             f"hand. Download '<year> General Election voter turnout by age' from {NZ_PAGE} and "
                             r"run: .\load.bat nz_election_turnout <file>")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".xlsx", ".xlsm"))
        if not files:
            raise ConnectorError(f"nz_election_turnout: no .xlsx file in {raw_dir}")
        rows, found = Rows(), set()
        for p in files:
            try:
                year, values = read_nz_turnout(p)
            except ConnectorError as exc:
                log.warning("%s", exc)
                continue
            for ind, (voters, enrolled) in values.items():
                rows.add("iso3", "NZL", ind, year, 100 * voters / enrolled)
                found.add(ind)
                if ind == "nz_turnout":
                    rows.add("iso3", "NZL", "nz_enrolled", year, enrolled)
                    rows.add("iso3", "NZL", "nz_voters", year, voters)
        if not len(rows):
            raise ConnectorError("nz_election_turnout: nothing read; are these the Electoral Commission's turnout "
                                 "by age spreadsheets?")
        listed = []
        for ind in sorted(found):
            label = _nz_label(ind)
            listed.append(indicator(ind, "Voter turnout, NZ general election" + (f", {label}" if label else ""),
                                    (f"People {label} who voted, as a share of those enrolled. " if label else
                                     "Everyone who voted, as a share of those enrolled. ") + NZ_NOTE,
                                    "% of enrolled", "politics", self.source_id, f"turnout {ind}",
                                    default_on="maori" not in ind or "age" not in ind, bounds=(0, 100)))
        listed += [
            indicator("nz_enrolled", "Enrolled voters, NZ general election", "People enrolled to vote. " + NZ_NOTE,
                      "persons", "politics", self.source_id, "total enrolled", decimals=0, default_on=False),
            indicator("nz_voters", "Votes cast, NZ general election", "People who voted. " + NZ_NOTE,
                      "persons", "politics", self.source_id, "voters", decimals=0, default_on=False),
        ]
        self.listed_indicators = listed
        return rows.stage(con, self.source_id, vintage)
