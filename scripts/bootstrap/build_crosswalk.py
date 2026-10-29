"""Bootstrap the entity crosswalk in contract/worldmodel_contract/catalogues/.

This was run once to create entities.csv, entity_codes.csv, memberships.csv and
successions.csv. From then on those CSV files are the source of truth and are
edited by hand; re-running this script overwrites them, so only do that on purpose.

Inputs:
  * UN M49 country list with regions, as packaged by
    https://github.com/lukes/ISO-3166-Countries-with-Regional-Codes (all/all.csv)
  * The curated tables below: historical entities, blocs, membership dates,
    display-name overrides and synonyms.

Usage:
  python scripts/bootstrap/build_crosswalk.py path/to/all.csv
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "contract" / "worldmodel_contract" / "catalogues"

# ISO names that are too formal for charts and menus.
SHORT_NAMES = {
    "BOL": "Bolivia",
    "COD": "DR Congo",
    "COG": "Congo",
    "FLK": "Falkland Islands",
    "FSM": "Micronesia (country)",
    "GBR": "United Kingdom",
    "IRN": "Iran",
    "KOR": "South Korea",
    "PRK": "North Korea",
    "LAO": "Laos",
    "MDA": "Moldova",
    "NLD": "Netherlands",
    "PSE": "Palestine",
    "RUS": "Russia",
    "SYR": "Syria",
    "TWN": "Taiwan",
    "TZA": "Tanzania",
    "USA": "United States",
    "VEN": "Venezuela",
    "VNM": "Vietnam",
    "BRN": "Brunei",
    "VAT": "Vatican City",
    "VGB": "British Virgin Islands",
    "VIR": "US Virgin Islands",
    "MAF": "Saint Martin",
    "SXM": "Sint Maarten",
    "SHN": "Saint Helena",
    "UMI": "US Minor Outlying Islands",
    "CIV": "Côte d'Ivoire",
    "TUR": "Türkiye",
    "CZE": "Czechia",
    "MKD": "North Macedonia",
    "SWZ": "Eswatini",
    "CPV": "Cabo Verde",
    "HKG": "Hong Kong",
    "MAC": "Macao",
}

# Extra words people use for a country, for search and the assistant.
SYNONYMS = {
    "USA": "US|USA|America|United States of America",
    "GBR": "UK|Britain|Great Britain|England",
    "RUS": "Russian Federation",
    "KOR": "Korea|Republic of Korea|ROK",
    "PRK": "DPRK|Democratic People's Republic of Korea",
    "COD": "DRC|Congo-Kinshasa|Zaire",
    "COG": "Congo-Brazzaville|Republic of the Congo",
    "CIV": "Ivory Coast",
    "TUR": "Turkey",
    "CZE": "Czech Republic",
    "MKD": "Macedonia",
    "SWZ": "Swaziland",
    "CPV": "Cape Verde",
    "MMR": "Burma",
    "TLS": "East Timor",
    "IRN": "Persia",
    "NLD": "Holland",
    "ARE": "UAE|Emirates",
    "NZL": "NZ|Aotearoa",
    "CHN": "PRC|People's Republic of China",
    "TWN": "Republic of China|Chinese Taipei",
    "VNM": "Viet Nam",
    "LAO": "Lao PDR",
    "SYR": "Syrian Arab Republic",
    "BOL": "Plurinational State of Bolivia",
    "VEN": "Bolivarian Republic of Venezuela",
    "PSE": "West Bank and Gaza|State of Palestine",
    "SAU": "KSA",
    "BIH": "Bosnia",
    "DEU": "West Germany",
}

# Historical states that no longer exist. ISO 3166-3 codes where they exist.
HISTORICAL = [
    # id, name, m49, valid_from, valid_to, synonyms
    ("SUN", "Soviet Union", "810", "1922-12-30", "1991-12-25", "USSR|Union of Soviet Socialist Republics"),
    ("YUG", "Yugoslavia", "890", "1918-12-01", "1992-04-27", "SFR Yugoslavia|Socialist Federal Republic of Yugoslavia"),
    ("SCG", "Serbia and Montenegro", "891", "1992-04-27", "2006-06-03", "FR Yugoslavia|Federal Republic of Yugoslavia"),
    ("CSK", "Czechoslovakia", "200", "1918-10-28", "1992-12-31", ""),
    ("DDR", "East Germany", "278", "1949-10-07", "1990-10-02", "German Democratic Republic|GDR"),
    ("YMD", "South Yemen", "720", "1967-11-30", "1990-05-21", "People's Democratic Republic of Yemen"),
    ("YAR", "North Yemen", "886", "1918-11-01", "1990-05-21", "Yemen Arab Republic"),
    ("ANT", "Netherlands Antilles", "530", "1954-12-15", "2010-10-09", ""),
]

SUCCESSIONS = [
    # predecessor, successor, date, kind
    *[("SUN", s, "1991-12-26", "dissolution") for s in
      ["RUS", "UKR", "BLR", "MDA", "EST", "LVA", "LTU", "GEO", "ARM", "AZE", "KAZ", "KGZ", "TJK", "TKM", "UZB"]],
    *[("YUG", s, "1991-06-25", "secession") for s in ["SVN", "HRV"]],
    ("YUG", "MKD", "1991-09-08", "secession"),
    ("YUG", "BIH", "1992-03-03", "secession"),
    ("YUG", "SCG", "1992-04-27", "continuation"),
    ("SCG", "SRB", "2006-06-05", "dissolution"),
    ("SCG", "MNE", "2006-06-03", "dissolution"),
    ("SRB", "XKX", "2008-02-17", "secession"),
    ("CSK", "CZE", "1993-01-01", "dissolution"),
    ("CSK", "SVK", "1993-01-01", "dissolution"),
    ("DDR", "DEU", "1990-10-03", "merger"),
    ("YMD", "YEM", "1990-05-22", "merger"),
    ("YAR", "YEM", "1990-05-22", "merger"),
    ("ANT", "CUW", "2010-10-10", "dissolution"),
    ("ANT", "SXM", "2010-10-10", "dissolution"),
    ("ANT", "BES", "2010-10-10", "dissolution"),
    ("SDN", "SSD", "2011-07-09", "secession"),
    ("ETH", "ERI", "1993-05-24", "secession"),
    ("IDN", "TLS", "2002-05-20", "secession"),
]

# Blocs and groupings with membership dates. Each needs a check against the
# source column before it is relied on; `verified` starts as "no".
BLOCS = [
    # id, name, type, synonyms, description, source
    ("eu", "European Union", "bloc", "EU|EEC|European Community|European Communities",
     "European Union and its predecessors (EEC from 1958). Membership dates are accession and exit dates.",
     "https://european-union.europa.eu/principles-countries-history/eu-countries_en"),
    ("euro-area", "Euro area", "bloc", "Eurozone|EA",
     "Countries using the euro as their currency.",
     "https://www.ecb.europa.eu/euro/intro/html/index.en.html"),
    ("nato", "NATO", "alliance", "North Atlantic Treaty Organization|OTAN",
     "North Atlantic Treaty Organization members, by accession date.",
     "https://www.nato.int/cps/en/natohq/topics_52044.htm"),
    ("asean", "ASEAN", "bloc", "Association of Southeast Asian Nations",
     "Association of Southeast Asian Nations.",
     "https://asean.org/member-states/"),
    ("nafta", "NAFTA", "bloc", "North American Free Trade Agreement",
     "North American Free Trade Agreement, replaced by USMCA on 2020-07-01.",
     "https://ustr.gov/trade-agreements/free-trade-agreements/united-states-mexico-canada-agreement"),
    ("usmca", "USMCA", "bloc", "CUSMA|T-MEC|United States-Mexico-Canada Agreement",
     "United States-Mexico-Canada Agreement, in force from 2020-07-01 (successor to NAFTA).",
     "https://ustr.gov/trade-agreements/free-trade-agreements/united-states-mexico-canada-agreement"),
    ("mercosur", "Mercosur", "bloc", "Mercosul|Southern Common Market",
     "Southern Common Market full members. Venezuela has been suspended since 2016-12-01 but not expelled.",
     "https://www.mercosur.int/en/about-mercosur/mercosur-countries/"),
    ("opec", "OPEC", "bloc", "Organization of the Petroleum Exporting Countries",
     "Organization of the Petroleum Exporting Countries, with suspensions and exits.",
     "https://www.opec.org/opec_web/en/about_us/25.htm"),
    ("g7", "G7", "group", "Group of Seven",
     "Group of Seven. The EU attends but is not counted as a member here.",
     "https://www.g7italy.it/en/the-g7/"),
    ("g20", "G20", "group", "Group of Twenty",
     "Group of Twenty country members. The EU and African Union are members but are left out of aggregates to avoid double counting.",
     "https://g20.org/about-the-g20/"),
    ("brics", "BRICS", "group", "BRIC|BRICS+",
     "BRICS full members. Saudi Arabia was invited in 2024 but has not confirmed, so it is left out.",
     "https://brics.br/en/about-brics"),
]

EU = [
    *[(c, "1958-01-01", "") for c in ["BEL", "FRA", "DEU", "ITA", "LUX", "NLD"]],
    ("DNK", "1973-01-01", ""), ("IRL", "1973-01-01", ""), ("GBR", "1973-01-01", "2020-01-31"),
    ("GRC", "1981-01-01", ""),
    ("ESP", "1986-01-01", ""), ("PRT", "1986-01-01", ""),
    *[(c, "1995-01-01", "") for c in ["AUT", "FIN", "SWE"]],
    *[(c, "2004-05-01", "") for c in ["CYP", "CZE", "EST", "HUN", "LVA", "LTU", "MLT", "POL", "SVK", "SVN"]],
    ("BGR", "2007-01-01", ""), ("ROU", "2007-01-01", ""),
    ("HRV", "2013-07-01", ""),
]
EURO = [
    *[(c, "1999-01-01", "") for c in ["AUT", "BEL", "FIN", "FRA", "DEU", "IRL", "ITA", "LUX", "NLD", "PRT", "ESP"]],
    ("GRC", "2001-01-01", ""), ("SVN", "2007-01-01", ""), ("CYP", "2008-01-01", ""), ("MLT", "2008-01-01", ""),
    ("SVK", "2009-01-01", ""), ("EST", "2011-01-01", ""), ("LVA", "2014-01-01", ""), ("LTU", "2015-01-01", ""),
    ("HRV", "2023-01-01", ""), ("BGR", "2026-01-01", ""),
]
NATO = [
    *[(c, "1949-08-24", "") for c in ["BEL", "CAN", "DNK", "FRA", "ISL", "ITA", "LUX", "NLD", "NOR", "PRT", "GBR", "USA"]],
    ("GRC", "1952-02-18", ""), ("TUR", "1952-02-18", ""),
    ("DEU", "1955-05-09", ""),
    ("ESP", "1982-05-30", ""),
    *[(c, "1999-03-12", "") for c in ["CZE", "HUN", "POL"]],
    *[(c, "2004-03-29", "") for c in ["BGR", "EST", "LVA", "LTU", "ROU", "SVK", "SVN"]],
    ("ALB", "2009-04-01", ""), ("HRV", "2009-04-01", ""),
    ("MNE", "2017-06-05", ""), ("MKD", "2020-03-27", ""),
    ("FIN", "2023-04-04", ""), ("SWE", "2024-03-07", ""),
]
ASEAN = [
    *[(c, "1967-08-08", "") for c in ["IDN", "MYS", "PHL", "SGP", "THA"]],
    ("BRN", "1984-01-07", ""), ("VNM", "1995-07-28", ""),
    ("LAO", "1997-07-23", ""), ("MMR", "1997-07-23", ""), ("KHM", "1999-04-30", ""),
    ("TLS", "2025-10-26", ""),
]
NAFTA = [(c, "1994-01-01", "2020-06-30") for c in ["USA", "CAN", "MEX"]]
USMCA = [(c, "2020-07-01", "") for c in ["USA", "CAN", "MEX"]]
MERCOSUR = [
    *[(c, "1991-03-26", "") for c in ["ARG", "BRA", "PRY", "URY"]],
    ("VEN", "2012-07-31", ""),
    ("BOL", "2024-07-08", ""),
]
OPEC = [
    *[(c, "1960-09-14", "") for c in ["IRN", "IRQ", "KWT", "SAU", "VEN"]],
    ("QAT", "1961-01-01", "2018-12-31"),
    ("IDN", "1962-01-01", "2008-12-31"), ("IDN", "2016-01-01", "2016-11-30"),
    ("LBY", "1962-01-01", ""),
    ("ARE", "1967-01-01", ""),
    ("DZA", "1969-01-01", ""),
    ("NGA", "1971-01-01", ""),
    ("ECU", "1973-01-01", "1992-12-31"), ("ECU", "2007-10-01", "2019-12-31"),
    ("GAB", "1975-01-01", "1994-12-31"), ("GAB", "2016-07-01", ""),
    ("AGO", "2007-01-01", "2023-12-31"),
    ("GNQ", "2017-05-25", ""),
    ("COG", "2018-06-22", ""),
]
G7 = [*[(c, "1975-11-15", "") for c in ["FRA", "DEU", "ITA", "JPN", "GBR", "USA"]], ("CAN", "1976-06-27", "")]
G20 = [(c, "1999-09-26", "") for c in [
    "ARG", "AUS", "BRA", "CAN", "CHN", "FRA", "DEU", "IND", "IDN", "ITA", "JPN", "KOR", "MEX", "RUS",
    "SAU", "ZAF", "TUR", "GBR", "USA"]]
BRICS = [
    *[(c, "2009-06-16", "") for c in ["BRA", "RUS", "IND", "CHN"]],
    ("ZAF", "2010-12-24", ""),
    *[(c, "2024-01-01", "") for c in ["EGY", "ETH", "IRN", "ARE"]],
    ("IDN", "2025-01-06", ""),
]
BLOC_MEMBERS = {
    "eu": EU, "euro-area": EURO, "nato": NATO, "asean": ASEAN, "nafta": NAFTA, "usmca": USMCA,
    "mercosur": MERCOSUR, "opec": OPEC, "g7": G7, "g20": G20, "brics": BRICS,
}

# UN Population Division location ids for the aggregates it publishes that
# match one of our entities, so its own totals can be checked against ours.
WPP_AGGREGATES = {"world": "900", "africa": "903", "asia": "935", "europe": "908", "oceania": "909"}
# IMF codes that differ from ISO alpha-3.
IMF_CODES = {"XKX": "UVK", "PSE": "WBG"}
IMF_AGGREGATES = {"world": "WEOWORLD"}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main(src: Path) -> None:
    rows = list(csv.DictReader(src.open(encoding="utf-8")))
    entities, codes, members = [], [], []

    def entity(eid, name, etype, short="", iso3="", iso2="", m49="", vfrom="", vto="", syn="", desc=""):
        entities.append(dict(entity_id=eid, name=name, short_name=short or name, type=etype, iso3=iso3,
                             iso2=iso2, m49=m49, valid_from=vfrom, valid_to=vto, synonyms=syn, description=desc))

    def code(eid, scheme, value, vfrom="", vto=""):
        codes.append(dict(entity_id=eid, scheme=scheme, code=value, valid_from=vfrom, valid_to=vto))

    def member(gid, mid, vfrom="", vto="", source="", verified="no"):
        members.append(dict(group_id=gid, member_id=mid, valid_from=vfrom, valid_to=vto, source=source,
                            verified=verified))

    # Groups first so the file reads top-down.
    entity("world", "World", "world", syn="Global|Earth", desc="All countries and areas.")
    geo = {}
    for level, name_col, code_col in [("continent", "region", "region-code"),
                                      ("subregion", "sub-region", "sub-region-code"),
                                      ("intermediate_region", "intermediate-region", "intermediate-region-code")]:
        for r in rows:
            if r[name_col] and r[name_col] not in geo:
                gid = slug(r[name_col])
                if gid == "micronesia":
                    gid = "micronesia-region"
                geo[r[name_col]] = gid
                entity(gid, r[name_col], level, m49=r[code_col],
                       desc=f"UN M49 {level.replace('_', ' ')} (code {r[code_col]}).")
                code(gid, "m49", r[code_col])
    for gid, name, etype, syn, desc, _ in BLOCS:
        entity(gid, name, etype, syn=syn, desc=desc)

    for r in rows:
        iso3 = r["alpha-3"]
        entity(iso3, r["name"], "country", short=SHORT_NAMES.get(iso3, ""), iso3=iso3, iso2=r["alpha-2"],
               m49=r["country-code"], syn=SYNONYMS.get(iso3, ""))
        code(iso3, "iso3", iso3)
        code(iso3, "iso2", r["alpha-2"])
        code(iso3, "m49", r["country-code"])
        code(iso3, "un_wpp", str(int(r["country-code"])))
        code(iso3, "imf", IMF_CODES.get(iso3, iso3))
        member("world", iso3, source="UN M49", verified="yes")
        for col in ["region", "sub-region", "intermediate-region"]:
            if r[col]:
                member(geo[r[col]], iso3, source="UN M49", verified="yes")

    # M49 gives Taiwan no region; the UN Population Division counts it in Eastern Asia.
    for gid in ["asia", "eastern-asia"]:
        member(gid, "TWN", source="UN Population Division (WPP places Taiwan in Eastern Asia)", verified="yes")

    # Kosovo is not in ISO 3166-1 but the UN and IMF publish data for it.
    entity("XKX", "Kosovo", "country", iso3="XKX", iso2="XK", m49="412", vfrom="2008-02-17",
           desc="Not in ISO 3166-1; XKX is the user-assigned code used by the EU and World Bank.")
    for scheme, value in [("iso3", "XKX"), ("iso2", "XK"), ("m49", "412"), ("un_wpp", "412"), ("imf", "UVK")]:
        code("XKX", scheme, value)
    member("world", "XKX", source="UN M49", verified="yes")
    for gid in ["europe", "southern-europe"]:
        member(gid, "XKX", source="UN Population Division (WPP places Kosovo in Southern Europe)")

    for eid, name, m49, vfrom, vto, syn in HISTORICAL:
        entity(eid, name, "historical_country", iso3=eid, m49=m49, vfrom=vfrom, vto=vto, syn=syn)
        code(eid, "iso3", eid, vfrom, vto)
        code(eid, "m49", m49, vfrom, vto)

    for gid, value in WPP_AGGREGATES.items():
        code(gid, "un_wpp", value)
    for gid, value in IMF_AGGREGATES.items():
        code(gid, "imf", value)

    src_by_bloc = {b[0]: b[5] for b in BLOCS}
    for gid, lst in BLOC_MEMBERS.items():
        for mid, vfrom, vto in lst:
            member(gid, mid, vfrom, vto, source=src_by_bloc[gid])

    OUT.mkdir(parents=True, exist_ok=True)
    write(OUT / "entities.csv", entities)
    write(OUT / "entity_codes.csv", codes)
    write(OUT / "memberships.csv", members)
    write(OUT / "successions.csv",
          [dict(predecessor_id=p, successor_id=s, date=d, kind=k) for p, s, d, k in SUCCESSIONS])
    print(f"{len(entities)} entities, {len(codes)} codes, {len(members)} memberships -> {OUT}")


def write(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
