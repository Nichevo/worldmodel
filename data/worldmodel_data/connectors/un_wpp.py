"""UN World Population Prospects connector.

Reads the standard CSV files of a WPP release:
  * WPP<release>_Demographic_Indicators_Medium.csv.gz  (one row per location and year)
  * WPP<release>_PopulationByAge5GroupSex_Medium.csv.gz (five-year age groups by sex)
  * WPP<release>_Demographic_Indicators_OtherVariants.csv.gz (optional: the low and
    high variants and the 80% and 95% prediction intervals, as variants low, high,
    lower80 .. upper95; a failed download of it only warns)
from https://population.un.org/wpp/downloads (CSV format). Population counts in
the files are in thousands; the catalogue's `scale` turns them into persons.

Years after the release's last estimate year are projections (status P).
"""

from __future__ import annotations

import csv
import gzip
import logging
import re
from datetime import datetime
from pathlib import Path

import duckdb
import httpx

from worldmodel_data.connectors.base import Connector, ConnectorError, sql_str

log = logging.getLogger(__name__)

BASE_URL = "https://population.un.org/wpp/assets/Excel%20Files/1_Indicator%20(Standard)/CSV_FILES/"
INDICATORS_FILE = "WPP{release}_Demographic_Indicators_Medium.csv.gz"
AGE_FILE = "WPP{release}_PopulationByAge5GroupSex_Medium.csv.gz"
VARIANTS_FILE = "WPP{release}_Demographic_Indicators_OtherVariants.csv.gz"
# WPP variant labels kept from the other-variants file, and what they become. The
# rest (constant fertility, zero migration and so on) are left out for now.
OTHER_VARIANTS = """CASE
    WHEN Variant = 'Low' THEN 'low'
    WHEN Variant = 'High' THEN 'high'
    WHEN regexp_matches(Variant, '^lower 80', 'i') THEN 'lower80'
    WHEN regexp_matches(Variant, '^upper 80', 'i') THEN 'upper80'
    WHEN regexp_matches(Variant, '^lower 95', 'i') THEN 'lower95'
    WHEN regexp_matches(Variant, '^upper 95', 'i') THEN 'upper95'
END"""
LATEST_RELEASE = "2024"
# Last year of estimates in each release; later years are projections.
ESTIMATES_END = {"2024": 2023, "2022": 2021}

DERIVED_AGE = {
    "derived:age_0_14": "sum(PopTotal) FILTER (WHERE AgeGrpStart < 15)",
    "derived:age_15_64": "sum(PopTotal) FILTER (WHERE AgeGrpStart >= 15 AND AgeGrpStart < 65)",
    "derived:age_65_plus": "sum(PopTotal) FILTER (WHERE AgeGrpStart >= 65)",
    "derived:share_0_14": "100 * sum(PopTotal) FILTER (WHERE AgeGrpStart < 15) / sum(PopTotal)",
    "derived:share_65_plus": "100 * sum(PopTotal) FILTER (WHERE AgeGrpStart >= 65) / sum(PopTotal)",
    "derived:old_age_dependency": "100 * sum(PopTotal) FILTER (WHERE AgeGrpStart >= 65)"
                                  " / sum(PopTotal) FILTER (WHERE AgeGrpStart >= 15 AND AgeGrpStart < 65)",
}
SEX_COLUMNS = {"PopTotal": "total", "PopMale": "male", "PopFemale": "female"}


class UNWPP(Connector):
    source_id = "un_wpp"

    def default_release(self, fetched_at: datetime) -> str:
        return LATEST_RELEASE

    def release_from_files(self, files: list[Path]) -> str | None:
        for f in files:
            m = re.match(r"WPP(\d{4})_", f.name)
            if m:
                return m.group(1)
        return None

    def download(self, raw_dir: Path, release: str) -> str:
        urls = [BASE_URL + name.format(release=release) for name in (INDICATORS_FILE, AGE_FILE)]
        for url in urls:
            self.get(url, raw_dir / url.rsplit("/", 1)[-1])
        extra = BASE_URL + VARIANTS_FILE.format(release=release)
        try:
            self.get(extra, raw_dir / extra.rsplit("/", 1)[-1])
            urls.append(extra)
        except (ConnectorError, httpx.HTTPError) as exc:
            (raw_dir / extra.rsplit("/", 1)[-1]).unlink(missing_ok=True)
            log.warning("un_wpp: no projection ranges this time (%s)", exc)
        return " ".join(urls)

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        ind_file = _find(raw_dir, "Demographic_Indicators")
        age_file = _find(raw_dir, "PopulationByAge5GroupSex")
        est_end = ESTIMATES_END.get(release, int(release) - 1 if release.isdigit() else 9999)
        status = f"CASE WHEN Time > {est_end} THEN 'P' ELSE 'E' END"
        aggregates = ", ".join(sql_str(c) for c in sorted(self.known_codes("un_wpp")))
        keep = f"Variant = 'Medium' AND (coalesce(ISO3_code, '') <> '' OR CAST(LocID AS VARCHAR) IN ({aggregates}))"
        series = self.series_map()
        head = f"SELECT 'un_wpp' AS source_id, {sql_str(vintage)} AS vintage, 'un_wpp' AS scheme, " \
               f"CAST(LocID AS VARCHAR) AS source_code"
        tail = f"make_date(Time, 1, 1) AS period_start, 'A' AS freq"
        parts = []

        con.execute(f"CREATE TABLE wpp_ind AS SELECT * FROM {_read(ind_file)} WHERE {keep}")
        cols = {r[0] for r in con.execute("DESCRIBE wpp_ind").fetchall()}
        for code, (indicator, scale) in series.items():
            if code.startswith("derived:") or "|" in code:
                continue
            if code not in cols:
                log.warning("un_wpp: column %s (for %s) not in %s", code, indicator, ind_file.name)
                continue
            parts.append(f"{head}, {sql_str(indicator)} AS indicator_id, {tail}, '' AS breakdown, "
                         f"'central' AS variant, CAST({code} AS DOUBLE) * {scale} AS value, {status} AS status "
                         f"FROM wpp_ind")

        var_file = _find(raw_dir, "Demographic_Indicators_OtherVariants")
        if var_file is not None:
            con.execute(f"""CREATE TABLE wpp_var AS SELECT *, {OTHER_VARIANTS} AS wm_variant FROM {_read(var_file)}
                WHERE {keep.replace("Variant = 'Medium'", "Time > " + str(est_end))}""")
            con.execute("DELETE FROM wpp_var WHERE wm_variant IS NULL")
            var_cols = {r[0] for r in con.execute("DESCRIBE wpp_var").fetchall()}
            for code, (indicator, scale) in series.items():
                if code.startswith("derived:") or "|" in code or code not in var_cols:
                    continue
                parts.append(f"{head}, {sql_str(indicator)} AS indicator_id, {tail}, '' AS breakdown, "
                             f"wm_variant AS variant, CAST({code} AS DOUBLE) * {scale} AS value, 'P' AS status "
                             f"FROM wpp_var")

        if age_file is not None:
            con.execute(f"CREATE TABLE wpp_age AS SELECT * FROM {_read(age_file)} WHERE {keep}")
            for code, (indicator, scale) in series.items():
                if "|" in code:  # the pyramid: one row per age group and sex
                    for col, sex in SEX_COLUMNS.items():
                        parts.append(
                            f"{head}, {sql_str(indicator)} AS indicator_id, {tail}, "
                            f"'age=' || AgeGrp || '|sex={sex}' AS breakdown, 'central' AS variant, "
                            f"CAST({col} AS DOUBLE) * {scale} AS value, {status} AS status FROM wpp_age")
                elif code in DERIVED_AGE:
                    parts.append(
                        f"{head}, {sql_str(indicator)} AS indicator_id, {tail}, '' AS breakdown, "
                        f"'central' AS variant, ({DERIVED_AGE[code]}) * {scale} AS value, {status} AS status "
                        f"FROM wpp_age GROUP BY LocID, Time")
        else:
            log.warning("un_wpp: no age-group file in %s; age structure indicators skipped", raw_dir)

        if not parts:
            raise ConnectorError("un_wpp: none of the catalogue's series were found in the files")
        return "\nUNION ALL\n".join(parts)


def _find(raw_dir: Path, marker: str) -> Path | None:
    hits = sorted(p for p in raw_dir.iterdir() if marker in p.name and p.name.endswith((".csv", ".csv.gz"))
                  and (marker.endswith("OtherVariants") or "OtherVariants" not in p.name))
    if marker == "Demographic_Indicators" and not hits:
        raise ConnectorError(f"un_wpp: no *{marker}*.csv(.gz) file in {raw_dir}")
    return hits[0] if hits else None


FIXED_TYPES = {"LocID": "INTEGER", "ISO3_code": "VARCHAR", "ISO2_code": "VARCHAR", "SDMX_code": "VARCHAR",
               "Notes": "VARCHAR", "Variant": "VARCHAR", "Time": "INTEGER", "AgeGrp": "VARCHAR",
               "AgeGrpStart": "INTEGER"}


def _read(path: Path) -> str:
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8-sig") as fh:
        header = next(csv.reader([fh.readline()]))
    types = ", ".join(f"'{c}': '{t}'" for c, t in FIXED_TYPES.items() if c in header)
    return f"read_csv({sql_str(path.as_posix())}, header = true, types = {{{types}}}, sample_size = 100000)"
