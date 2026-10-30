"""Education: how much schooling people have had, history and projections, and the
UN's human development indices.

wittgenstein
    Wittgenstein Centre Human Capital Data Explorer, version 3 (IIASA, VID, Univ. of
    Vienna), the middle-of-the-road scenario (SSP2), as the R data files its own
    download tool reads: bmys.rds (mean years of schooling, 1950 to 2100) and
    bprop.rds (shares of people by highest level of education, 2020 to 2100), for
    ages 25 and over, by sex. Values after 2020 are projections. Fetched from IIASA,
    or from the copy on GitHub if IIASA does not answer. Countries by UN M49 code.

undp_hdr
    UNDP Human Development Report composite indices, complete time series (one CSV,
    found on the report's downloads page): the Human Development Index and its parts
    (life expectancy, expected and mean years of schooling, income per person), the
    gender and inequality-adjusted indices, by year since 1990.
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import datetime
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.tabular import Rows, indicator, num

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------------------------- Wittgenstein
WIC_BASES = ("https://wicshiny2023.iiasa.ac.at/wcde-data/wcde-v3-batch/2/",
             "https://raw.githubusercontent.com/guyabel/wcde-data/master/wcde-v3-batch/2/")
WIC_FILES = ("bmys.rds", "bprop.rds")
WIC_BASE_YEAR = 2020  # later values are projections
WIC_LEVELS = {  # level in the file -> (indicator suffix, name); "Post Secondary" is the sum of the last three
    "No Education": ("none", "no schooling"),
    "Incomplete Primary": ("incomplete_primary", "incomplete primary school"),
    "Primary": ("primary", "primary school"),
    "Lower Secondary": ("lower_secondary", "lower secondary school"),
    "Upper Secondary": ("upper_secondary", "upper secondary school"),
    "Short Post Secondary": ("short_post_secondary", "short post-secondary courses"),
    "Bachelor": ("bachelor", "a bachelor's degree"),
    "Master and higher": ("master", "a master's degree or higher"),
    "Post Secondary": ("post_secondary", "any education after secondary school"),
}
WIC_SEX = {"Both": "", "Female": "_female", "Male": "_male"}


class Wittgenstein(Connector):
    source_id = "wittgenstein"
    frozen = True  # a version is fixed once published; a new version needs a new connector release

    def default_release(self, fetched_at: datetime) -> str:
        return "v3"

    def release_from_files(self, files: list[Path]) -> str | None:
        return "v3"

    def download(self, raw_dir: Path, release: str) -> str:
        errors = []
        for base in WIC_BASES:
            try:
                for name in WIC_FILES:
                    self.get(base + name, raw_dir / name)
                return base
            except ConnectorError as exc:
                errors.append(str(exc))
                log.warning("wittgenstein: %s failed (%s)", base, exc)
        raise ConnectorError("wittgenstein: no copy could be downloaded: " + "; ".join(errors))

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        rows = Rows()
        for value in ("bmys", "bprop"):
            for c, y, sex, edu, v in _wic_table(raw_dir, value):
                if sex not in WIC_SEX or v is None or v != v:
                    continue
                y = int(float(y))
                if value == "bmys":
                    ind = "wic_mys" + WIC_SEX[sex]
                elif edu in WIC_LEVELS and sex == "Both":
                    ind = "wic_edu_" + WIC_LEVELS[edu][0]
                else:
                    continue
                rows.add("un_wpp", str(int(float(c))), ind, y, float(v), status="P" if y > WIC_BASE_YEAR else "E")
        if not len(rows):
            raise ConnectorError(f"wittgenstein: no values read from {raw_dir}")
        self.listed_indicators = WIC_INDICATORS
        return rows.stage(con, self.source_id, vintage)


def _wic_table(raw_dir: Path, value: str):
    """(country code, year, sex, education, value) for ages 25+, from <value>.rds, or a CSV with the same columns."""
    rds, plain = raw_dir / f"{value}.rds", raw_dir / f"{value}.csv"
    if rds.exists():
        try:
            import rdata  # reads R's .rds files; only needed here
        except ImportError as exc:
            raise ConnectorError("wittgenstein: the rdata package is missing; run update.bat") from exc
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = rdata.read_rds(str(rds))
        df = df[df["age"] == "25+"]
        edu = df["education"] if "education" in df else [None] * len(df)
        yield from zip(df["country_code"], df["year"], df["sex"], edu, df[value])
    elif plain.exists():
        with plain.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("age") == "25+":
                    yield r["country_code"], r["year"], r["sex"], r.get("education"), num(r.get(value))


WIC_NOTE = ("Wittgenstein Centre Human Capital Data Explorer v3, middle-of-the-road scenario (SSP2); people aged 25 "
            "and over; projections after 2020.")
WIC_INDICATORS = [
    indicator("wic_mys" + suffix, f"Mean years of schooling{label} (25+, Wittgenstein)",
              f"Average number of years {who} aged 25 and over have spent in formal education. " + WIC_NOTE,
              "years", "education", "wittgenstein", f"bmys:25+:{sex}", decimals=1, default_on=not suffix)
    for sex, suffix, label, who in (("Both", "", "", "people"), ("Female", "_female", ", women", "women"),
                                    ("Male", "_male", ", men", "men"))
] + [
    indicator(f"wic_edu_{ind}", f"Highest education: {text} (% of adults)",
              f"Share of people aged 25 and over whose highest level of education is {text}. " + WIC_NOTE,
              "% of people 25+", "education", "wittgenstein", f"bprop:25+:{level}", decimals=1,
              default_on=ind in ("post_secondary", "bachelor", "upper_secondary", "none"))
    for level, (ind, text) in WIC_LEVELS.items()
]


# --------------------------------------------------------------------------------------------- UNDP HDR
HDR_PAGE = "https://hdr.undp.org/data-center/documentation-and-downloads"
HDR_SITE = "https://hdr.undp.org"
HDR_FILE = re.compile(r"""href=["']([^"']*HDR(\d{2})_Composite_indices_complete_time_series\.csv)["']""", re.I)
# Column prefix -> (indicator, name, unit, decimals, description, on by default)
HDR_SERIES = {
    "hdi": ("hdi", "Human Development Index", "index (0-1)", 3,
            "UNDP's summary of a long and healthy life, education and a decent standard of living, from 0 to 1.", True),
    "le": ("hdr_life_expectancy", "Life expectancy at birth (UNDP)", "years", 1,
           "Life expectancy at birth as used in the Human Development Index.", False),
    "eys": ("expected_years_schooling", "Expected years of schooling", "years", 1,
            "Years of schooling a child starting school now can expect if today's enrolment rates hold.", True),
    "eys_f": ("expected_years_schooling_female", "Expected years of schooling, girls", "years", 1,
              "Expected years of schooling for girls.", False),
    "eys_m": ("expected_years_schooling_male", "Expected years of schooling, boys", "years", 1,
              "Expected years of schooling for boys.", False),
    "mys": ("hdr_mean_years_schooling", "Mean years of schooling (25+, UNDP)", "years", 1,
            "Average years of schooling of people aged 25 and over, as used in the Human Development Index.", True),
    "mys_f": ("hdr_mean_years_schooling_female", "Mean years of schooling, women (25+, UNDP)", "years", 1,
              "Average years of schooling of women aged 25 and over.", False),
    "mys_m": ("hdr_mean_years_schooling_male", "Mean years of schooling, men (25+, UNDP)", "years", 1,
              "Average years of schooling of men aged 25 and over.", False),
    "gnipc": ("hdr_gni_per_person", "GNI per person (UNDP, PPP)", "2021 PPP $", 0,
              "Gross national income per person in 2021 purchasing-power dollars, as used in the HDI.", False),
    "gdi": ("gender_development_index", "Gender Development Index", "ratio", 3,
            "Women's HDI divided by men's: 1 is parity, below 1 women are behind.", True),
    "gii": ("gender_inequality_index", "Gender Inequality Index", "index (0-1)", 3,
            "Inequality between women and men in health, empowerment and work; 0 is equality.", True),
    "ihdi": ("inequality_adjusted_hdi", "Inequality-adjusted HDI", "index (0-1)", 3,
             "The HDI discounted for how unequally health, education and income are shared.", True),
    "phdi": ("planetary_hdi", "Planetary pressures-adjusted HDI", "index (0-1)", 3,
             "The HDI adjusted for carbon emissions and material use per person.", False),
}


class UNDPHDR(Connector):
    source_id = "undp_hdr"
    fetch_every_days = 60

    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y")

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:
            if m := re.search(r"HDR(\d{2})_", f.name, re.I):
                return f"20{m.group(1)}"
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        page = raw_dir / "page.html"
        try:
            self.get(HDR_PAGE, page)
            links = HDR_FILE.findall(page.read_text(encoding="utf-8", errors="replace"))
        finally:
            page.unlink(missing_ok=True)
        if not links:
            raise ConnectorError(f"undp_hdr: no HDRnn_Composite_indices_complete_time_series.csv link on {HDR_PAGE}. "
                                 "Download it by hand and load it with: worldmodel-data fetch undp_hdr --from <file>")
        link = max(links, key=lambda x: x[1])[0]
        url = link if link.startswith("http") else HDR_SITE + link
        self.get(url, raw_dir / Path(url).name)
        return url

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(raw_dir.glob("*.csv"))
        if not files:
            raise ConnectorError(f"undp_hdr: no .csv file in {raw_dir}")
        raw = files[-1].read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        reader = csv.reader(text.splitlines())
        header = [h.strip().lower() for h in next(reader)]
        if "iso3" not in header:
            raise ConnectorError(f"undp_hdr: {files[-1].name} has no iso3 column")
        iso = header.index("iso3")
        cols = {}
        for i, h in enumerate(header):
            m = re.fullmatch(r"([a-z_]+?)_(\d{4})", h)
            if m and m.group(1) in HDR_SERIES:
                cols[i] = (HDR_SERIES[m.group(1)][0], int(m.group(2)))
        rows = Rows()
        for r in reader:
            if len(r) <= iso or not re.fullmatch(r"[A-Z]{3}", r[iso].strip()):
                continue  # regions and groups are ZZA.VHHD and the like
            for i, (ind, y) in cols.items():
                if i < len(r):
                    rows.add("iso3", r[iso].strip(), ind, y, num(r[i]))
        if not len(rows):
            raise ConnectorError(f"undp_hdr: no values read from {files[-1].name}")
        present = {ind for ind, _ in cols.values()}
        self.listed_indicators = [
            indicator(ind, name, desc + " UNDP Human Development Report.", unit,
                      "education" if "schooling" in name else "development", "undp_hdr", prefix,
                      decimals=dec, default_on=on)
            for prefix, (ind, name, unit, dec, desc, on) in HDR_SERIES.items() if ind in present]
        return rows.stage(con, self.source_id, vintage)
