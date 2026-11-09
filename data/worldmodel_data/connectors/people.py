"""People: the languages spoken in each country, and religion.

cow_religion
    Correlates of War World Religion Data, national file (WRP_national.csv): people in
    each religion and its main branches, by country every 5 years from 1945 to 2010.

pew_religion
    Pew Research Center's religious composition by country (2010, 2020, projections to
    2050), loaded by hand from its report tables (see PewReligion).

Religion comes as rel_share and rel_people with a breakdown rel=<group>: christian,
muslim, none, hindu, buddhist, folk, jewish, other, and branches such as christian.catholic.

cldr_languages
    Unicode CLDR's territory information (cldr-json, supplemental/territoryInfo.json):
    for every country, the languages spoken there with the share of people who speak
    each (first or second language, not told apart) and its official status
    (official, de facto official, official in a region, official for a minority).
    Language names in English come from cldr-localenames-full (en/languages.json).
    Shares are estimates kept up to date for software, so they are graded exploratory.

glottolog
    Glottolog (CLDF release on GitHub): every known language with the countries it is
    spoken in, its family and the Agglomerated Endangerment Status (AES: not endangered,
    threatened, shifting, moribund, nearly extinct, extinct), compiled from UNESCO,
    Ethnologue's EGIDS and the Catalogue of Endangered Languages. Counted per country.

Both list each language by name in the texts table (section "Languages" or "Endangered
languages"), so the Languages page and country cards can name them.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import duckdb

from worldmodel_data.connectors.base import Connector, ConnectorError, sql_str
from worldmodel_data.connectors.tabular import Rows, entity_for, indicator, num

log = logging.getLogger(__name__)

CLDR_BASE = "https://raw.githubusercontent.com/unicode-org/cldr-json/main/cldr-json/"
CLDR_FILES = {"territoryInfo.json": "cldr-core/supplemental/territoryInfo.json",
              "languages.json": "cldr-localenames-full/main/en/languages.json"}
# Official status -> the value stored (higher is more official) and how it reads.
OFFICIAL = {"official": (4, "official"), "de_facto_official": (3, "official in practice"),
            "official_regional": (2, "official in a region"), "official_minority": (1, "official for a minority")}

GLOTTOLOG_BASE = "https://raw.githubusercontent.com/glottolog/glottolog-cldf/master/cldf/"
GLOTTOLOG_FILES = ("languages.csv", "values.csv")
AES = {"aes-not_endangered": (1, "not endangered"), "aes-threatened": (2, "threatened"),
       "aes-shifting": (3, "shifting"), "aes-moribund": (4, "moribund"),
       "aes-nearly_extinct": (5, "nearly extinct"), "aes-extinct": (6, "extinct")}
SPOKEN = {"spoken l1 language", "sign language"}  # Glottolog categories counted as languages people speak


def _texts_query(con: duckdb.DuckDBPyConnection, source_id: str, vintage: str, rows: list[tuple]) -> str:
    """rows: (entity id, edition, section, field, field_key, content, position) -> the texts query."""
    con.execute("CREATE TABLE tx (code VARCHAR, edition INTEGER, section VARCHAR, field VARCHAR, field_key VARCHAR, "
                "content VARCHAR, position BIGINT)")
    if rows:
        con.executemany("INSERT INTO tx VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    return (f"SELECT {sql_str(source_id)} AS source_id, {sql_str(vintage)} AS vintage, 'iso3' AS scheme, code AS source_code, "
            "edition, section, field, field_key, content, position FROM tx")


class _Yearly(Connector):
    def default_release(self, fetched_at: datetime) -> str:
        return fetched_at.strftime("%Y-%m")

    def release_from_files(self, files: list[Path]) -> str | None:
        return None


def language_name(code: str, names: dict[str, str]) -> str:
    """'zh_Hant' -> 'Chinese (Traditional)' where CLDR names it, else the base language's name."""
    c = code.replace("_", "-")
    if c in names:
        return names[c]
    base, _, rest = c.partition("-")
    return f"{names[base]} ({rest})" if base in names and rest else names.get(base, code)


class CLDRLanguages(_Yearly):
    source_id = "cldr_languages"
    fetch_every_days = 90  # CLDR releases twice a year

    def download(self, raw_dir: Path, release: str) -> str:
        for name, path in CLDR_FILES.items():
            self.get(CLDR_BASE + path, raw_dir / name)
        return CLDR_BASE

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        info_path = raw_dir / "territoryInfo.json"
        if not info_path.exists():
            raise ConnectorError(f"cldr_languages: territoryInfo.json missing from {raw_dir}")
        doc = json.loads(info_path.read_text(encoding="utf-8"))["supplemental"]
        names_path = raw_dir / "languages.json"
        names: dict[str, str] = {}
        if names_path.exists():
            names = json.loads(names_path.read_text(encoding="utf-8"))["main"]["en"]["localeDisplayNames"]["languages"]
        year = int(release[:4]) if re.match(r"\d{4}", release or "") else datetime.now().year
        rows, texts = Rows(), []
        for iso2, t in doc["territoryInfo"].items():
            ent = entity_for("iso2", iso2)
            if not ent:
                continue
            pop = num(t.get("_population"))
            langs = sorted(t.get("languagePopulation", {}).items(), key=lambda kv: -(num(kv[1].get("_populationPercent")) or 0))
            for pos, (code, v) in enumerate(langs):
                share = num(v.get("_populationPercent"))
                bd = f"lang={code}"
                rows.add("iso3", ent, "lang_share", year, share, breakdown=bd)
                if share is not None and pop:
                    rows.add("iso3", ent, "lang_speakers", year, share / 100 * pop, breakdown=bd)
                status = OFFICIAL.get(v.get("_officialStatus") or "")
                if status:
                    rows.add("iso3", ent, "lang_official", year, status[0], breakdown=bd)
                texts.append((ent, year, "Languages", language_name(code, names), f"lang:{code}",
                              status[1] if status else "", pos))
            official = [c for c, v in langs if (v.get("_officialStatus") or "") in ("official", "de_facto_official")]
            rows.add("iso3", ent, "lang_listed", year, len(langs))
            rows.add("iso3", ent, "lang_official_count", year, len(official))
            if langs:
                rows.add("iso3", ent, "lang_main_share", year, num(langs[0][1].get("_populationPercent")))
        if not len(rows):
            raise ConnectorError("cldr_languages: no languages read from territoryInfo.json")
        self.texts_query = _texts_query(con, self.source_id, vintage, texts)
        note = "Unicode CLDR territory information: estimates kept for software, first and second language together."
        self.listed_indicators = [
            indicator("lang_share", "People who speak a language (%)",
                      "Share of the country's people who speak each language, as a first or second language. Pick the "
                      "language as the breakdown (lang=en for English).", "% of people", "society", self.source_id,
                      "languagePopulation:_populationPercent", decimals=1, bounds=(0, 100), notes=note,
                      breakdowns=["lang"], default_on=False),
            indicator("lang_speakers", "Speakers of a language", "People who speak each language, first or second "
                      "language: the share times CLDR's own population figure. Adds up across countries to world totals.",
                      "people", "society", self.source_id, "languagePopulation:speakers", decimals=0, notes=note,
                      breakdowns=["lang"], aggregation={"method": "sum"}, default_on=False),
            indicator("lang_official", "Official status of a language", "4 official, 3 official in practice, 2 official "
                      "in a region, 1 official for a minority.", "status", "society", self.source_id,
                      "languagePopulation:_officialStatus", decimals=0, bounds=(0, 4), notes=note, breakdowns=["lang"],
                      default_on=False),
            indicator("lang_listed", "Languages with a share listed (CLDR)", "How many languages CLDR lists for the "
                      "country with the share of people who speak each.", "languages", "society", self.source_id,
                      "territoryInfo:count", decimals=0, notes=note),
            indicator("lang_official_count", "Official languages", "Languages official nationally, by law or in "
                      "practice.", "languages", "society", self.source_id, "territoryInfo:official", decimals=0, notes=note),
            indicator("lang_main_share", "Share speaking the main language (%)", "Share of people who speak the "
                      "country's most widely spoken language. Lower means more people get by in other languages.",
                      "% of people", "society", self.source_id, "territoryInfo:main", decimals=1, bounds=(0, 100), notes=note),
        ]
        return rows.stage(con, self.source_id, vintage)


class Glottolog(_Yearly):
    source_id = "glottolog"
    fetch_every_days = 180  # a release or two a year

    def download(self, raw_dir: Path, release: str) -> str:
        for name in GLOTTOLOG_FILES:
            self.get(GLOTTOLOG_BASE + name, raw_dir / name)
        return GLOTTOLOG_BASE

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        lang_path, values_path = raw_dir / "languages.csv", raw_dir / "values.csv"
        if not lang_path.exists():
            raise ConnectorError(f"glottolog: languages.csv missing from {raw_dir}")
        status: dict[str, str] = {}
        category: dict[str, str] = {}
        if values_path.exists():
            with values_path.open(encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    if r["Parameter_ID"] == "aes":
                        status[r["Language_ID"]] = r.get("Code_ID") or ""
                    elif r["Parameter_ID"] == "category":
                        category[r["Language_ID"]] = (r.get("Value") or "").lower()
        year = int(release[:4]) if re.match(r"\d{4}", release or "") else datetime.now().year
        families = {}
        langs = []
        with lang_path.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("Level") == "family":
                    families[r["ID"]] = r["Name"]
                elif r.get("Level") == "language":
                    langs.append(r)
        counts: dict[str, Counter] = defaultdict(Counter)
        texts = []
        for r in langs:
            cat = category.get(r["ID"], "spoken l1 language")
            if cat not in SPOKEN:
                continue
            aes = AES.get(status.get(r["ID"], ""))
            for iso2 in filter(None, (r.get("Countries") or "").split(";")):
                ent = entity_for("iso2", iso2.strip())
                if not ent:
                    continue
                c = counts[ent]
                c["all"] += 1
                if aes:
                    c[aes[0]] += 1
                if aes and aes[0] >= 2:  # threatened or worse: named on the card
                    family = families.get(r.get("Family_ID") or "", "isolate" if r.get("Is_Isolate") == "true" else "")
                    texts.append((ent, year, "Endangered languages", r["Name"], f"glotto:{r['ID']}",
                                  f"{aes[1]}|{family}", aes[0]))
        if not counts:
            raise ConnectorError("glottolog: no languages with countries read")
        rows = Rows()
        for ent, c in counts.items():
            rows.add("iso3", ent, "lang_count", year, c["all"])
            rows.add("iso3", ent, "lang_endangered", year, c[3] + c[4] + c[5])
            rows.add("iso3", ent, "lang_threatened", year, c[2])
            rows.add("iso3", ent, "lang_extinct", year, c[6])
        self.texts_query = _texts_query(con, self.source_id, vintage, texts)
        note = "Glottolog, Agglomerated Endangerment Status (from UNESCO, EGIDS and the Catalogue of Endangered Languages)."
        self.listed_indicators = [
            indicator("lang_count", "Languages spoken", "Languages spoken in the country (spoken and sign languages, "
                      "a language spoken in several countries counts in each).", "languages", "society", self.source_id,
                      "languages:count", decimals=0, notes=note),
            indicator("lang_endangered", "Endangered languages", "Languages spoken in the country that are shifting, "
                      "moribund or nearly extinct: children no longer learn them, or only the oldest people speak them.",
                      "languages", "society", self.source_id, "aes:3-5", decimals=0, notes=note),
            indicator("lang_threatened", "Threatened languages", "Languages still learned by children but losing ground.",
                      "languages", "society", self.source_id, "aes:2", decimals=0, notes=note, default_on=False),
            indicator("lang_extinct", "Languages no longer spoken", "Languages of the country with no speakers left.",
                      "languages", "society", self.source_id, "aes:6", decimals=0, notes=note, default_on=False),
        ]
        return rows.stage(con, self.source_id, vintage)


# ----------------------------------------------------------------------------- religion
# The groups shown everywhere, in this order, and what each source calls them.
RELIGIONS = (("christian", "Christians"), ("muslim", "Muslims"), ("none", "No religion"), ("hindu", "Hindus"),
             ("buddhist", "Buddhists"), ("folk", "Folk religions"), ("jewish", "Jews"), ("other", "Other religions"))
RELIGION_NAMES = dict(RELIGIONS)
SUBGROUPS = {"christian.catholic": "Catholics", "christian.protestant": "Protestants", "christian.orthodox": "Orthodox",
             "christian.anglican": "Anglicans", "christian.other": "Other Christians",
             "muslim.sunni": "Sunni Muslims", "muslim.shia": "Shia Muslims", "muslim.other": "Other Muslims"}

COW_URL = "https://correlatesofwar.org/wp-content/uploads/WRP_national.csv"
# COW World Religion Data columns (counts of people) -> group.
COW_COLUMNS = {"chrstgen": "christian", "islmgen": "muslim", "nonrelig": "none", "hindgen": "hindu", "budgen": "buddhist",
               "judgen": "jewish", "shntgen": "folk", "taogen": "folk", "confgen": "folk", "anmgen": "folk",
               "syncgen": "folk", "sikhgen": "other", "bahgen": "other", "jaingen": "other", "zorogen": "other",
               "othrgen": "other",
               "chrstcat": "christian.catholic", "chrstprot": "christian.protestant", "chrstorth": "christian.orthodox",
               "chrstang": "christian.anglican", "chrstothr": "christian.other",
               "islmsun": "muslim.sunni", "islmshi": "muslim.shia"}
# Correlates of War state numbers -> entity ids (states since 1945).
COW_STATES = {
    2: "USA", 20: "CAN", 31: "BHS", 40: "CUB", 41: "HTI", 42: "DOM", 51: "JAM", 52: "TTO", 53: "BRB", 54: "DMA",
    55: "GRD", 56: "LCA", 57: "VCT", 58: "ATG", 60: "KNA", 70: "MEX", 80: "BLZ", 90: "GTM", 91: "HND", 92: "SLV",
    93: "NIC", 94: "CRI", 95: "PAN", 100: "COL", 101: "VEN", 110: "GUY", 115: "SUR", 130: "ECU", 135: "PER",
    140: "BRA", 145: "BOL", 150: "PRY", 155: "CHL", 160: "ARG", 165: "URY", 200: "GBR", 205: "IRL", 210: "NLD",
    211: "BEL", 212: "LUX", 220: "FRA", 221: "MCO", 223: "LIE", 225: "CHE", 230: "ESP", 232: "AND", 235: "PRT",
    255: "DEU", 260: "DEU", 265: "DDR", 290: "POL", 305: "AUT", 310: "HUN", 315: "CSK", 316: "CZE", 317: "SVK",
    325: "ITA", 331: "SMR", 338: "MLT", 339: "ALB", 341: "MNE", 343: "MKD", 344: "HRV", 346: "BIH", 347: "XKX",
    349: "SVN", 350: "GRC", 352: "CYP", 355: "BGR", 359: "MDA", 360: "ROU", 366: "EST", 367: "LVA", 368: "LTU",
    369: "UKR", 370: "BLR", 371: "ARM", 372: "GEO", 373: "AZE", 375: "FIN", 380: "SWE", 385: "NOR", 390: "DNK",
    395: "ISL", 402: "CPV", 403: "STP", 404: "GNB", 411: "GNQ", 420: "GMB", 432: "MLI", 433: "SEN", 434: "BEN",
    435: "MRT", 436: "NER", 437: "CIV", 438: "GIN", 439: "BFA", 450: "LBR", 451: "SLE", 452: "GHA", 461: "TGO",
    471: "CMR", 475: "NGA", 481: "GAB", 482: "CAF", 483: "TCD", 484: "COG", 490: "COD", 500: "UGA", 501: "KEN",
    510: "TZA", 516: "BDI", 517: "RWA", 520: "SOM", 522: "DJI", 530: "ETH", 531: "ERI", 540: "AGO", 541: "MOZ",
    551: "ZMB", 552: "ZWE", 553: "MWI", 560: "ZAF", 565: "NAM", 570: "LSO", 571: "BWA", 572: "SWZ", 580: "MDG",
    581: "COM", 590: "MUS", 591: "SYC", 600: "MAR", 615: "DZA", 616: "TUN", 620: "LBY", 625: "SDN", 626: "SSD",
    630: "IRN", 640: "TUR", 645: "IRQ", 651: "EGY", 652: "SYR", 660: "LBN", 663: "JOR", 666: "ISR", 670: "SAU",
    678: "YAR", 679: "YEM", 680: "YMD", 690: "KWT", 692: "BHR", 694: "QAT", 696: "ARE", 698: "OMN", 700: "AFG",
    701: "TKM", 702: "TJK", 703: "KGZ", 704: "UZB", 705: "KAZ", 710: "CHN", 712: "MNG", 713: "TWN", 731: "PRK",
    732: "KOR", 740: "JPN", 750: "IND", 760: "BTN", 770: "PAK", 771: "BGD", 775: "MMR", 780: "LKA", 781: "MDV",
    790: "NPL", 800: "THA", 811: "KHM", 812: "LAO", 816: "VNM", 817: "RVN", 820: "MYS", 830: "SGP", 835: "BRN",
    840: "PHL", 850: "IDN", 860: "TLS", 900: "AUS", 910: "PNG", 920: "NZL", 935: "VUT", 940: "SLB", 946: "KIR",
    947: "TUV", 950: "FJI", 955: "TON", 970: "NRU", 983: "MHL", 986: "PLW", 987: "FSM", 990: "WSM",
}


def cow_entity(ccode, year: int) -> str | None:
    """A COW state number as an entity: Russia is the Soviet Union until 1991, Serbia is
    Yugoslavia until 1992 and Serbia and Montenegro until 2006."""
    try:
        c = int(float(ccode))
    except (TypeError, ValueError):
        return None
    if c == 365:
        return "SUN" if year < 1992 else "RUS"
    if c == 345:
        return "YUG" if year < 1992 else "SCG" if year < 2006 else "SRB"
    return COW_STATES.get(c)


def religion_indicators(source_id: str, series: str, note: str) -> list[dict]:
    return [
        indicator("rel_share", "Religion: share of people (%)",
                  "Share of the country's people in each religious group (rel=christian, muslim, none, hindu, buddhist, "
                  "folk, jewish, other; christian.catholic and the like for branches).", "% of people", "society",
                  source_id, f"{series}:share", decimals=1, bounds=(0, 100), notes=note, breakdowns=["rel"]),
        indicator("rel_people", "Religion: number of people", "People in each religious group.", "people",
                  "society", source_id, f"{series}:people", decimals=0, notes=note, breakdowns=["rel"],
                  aggregation={"method": "sum"}, default_on=False),
        indicator("rel_none_share", "No religion (% of people)", "Share of people with no religion: atheists, "
                  "agnostics and people who name none.", "% of people", "society", source_id, f"{series}:none",
                  decimals=1, bounds=(0, 100), notes=note),
        indicator("rel_largest_share", "Largest religion's share (%)", "Share of people in the country's largest "
                  "religious group. Lower means a more mixed country.", "% of people", "society", source_id,
                  f"{series}:largest", decimals=1, bounds=(0, 100), notes=note),
    ]


def _add_religion(rows: Rows, ent: str, year: int, people: dict[str, float], pop: float | None,
                  shares: dict[str, float] | None = None, status: str = "E") -> None:
    shares = dict(shares or {})
    if pop:
        for g, n in people.items():
            shares.setdefault(g, n / pop * 100)
    for g, v in shares.items():
        rows.add("iso3", ent, "rel_share", year, v, breakdown=f"rel={g}", status=status)
    for g, n in people.items():
        rows.add("iso3", ent, "rel_people", year, n, breakdown=f"rel={g}", status=status)
    if "none" in shares:
        rows.add("iso3", ent, "rel_none_share", year, shares["none"], status=status)
    top = [v for g, v in shares.items() if "." not in g]
    if top:
        rows.add("iso3", ent, "rel_largest_share", year, max(top), status=status)


class COWReligion(_Yearly):
    source_id = "cow_religion"
    frozen = True  # a closed dataset (1945-2010)

    def default_release(self, fetched_at: datetime) -> str:
        return "1.1"

    def download(self, raw_dir: Path, release: str) -> str:
        self.get(COW_URL, raw_dir / "WRP_national.csv")
        return COW_URL

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        files = sorted(raw_dir.glob("*.csv"))
        if not files:
            raise ConnectorError(f"cow_religion: no CSV in {raw_dir} (WRP_national.csv)")
        rows = Rows()
        with files[0].open(encoding="utf-8-sig", errors="replace", newline="") as f:
            for r in csv.DictReader(f):
                r = {k.strip().lower(): v for k, v in r.items() if k}
                y = num(r.get("year"))
                ent = cow_entity(r.get("state") or r.get("ccode"), int(y)) if y else None
                if not ent:
                    continue
                people: dict[str, float] = defaultdict(float)
                for c, g in COW_COLUMNS.items():
                    v = num(r.get(c))
                    if v is not None:
                        people[g] += v
                pop = num(r.get("pop"))
                if "muslim" in people and ("muslim.sunni" in people or "muslim.shia" in people):
                    people["muslim.other"] = max(0.0, people["muslim"] - people.get("muslim.sunni", 0) - people.get("muslim.shia", 0))
                _add_religion(rows, ent, int(y), dict(people), pop)
        if not len(rows):
            raise ConnectorError("cow_religion: no rows read; expected the WRP national file (year, state, chrstgen ...)")
        self.listed_indicators = religion_indicators(self.source_id, "WRP_national",
                                                     "Correlates of War World Religion Data, every 5 years 1945-2010.")
        return rows.stage(con, self.source_id, vintage)


# Pew's names for its groups -> ours (headers compared loosely).
PEW_GROUPS = {"christian": "christian", "christians": "christian", "muslim": "muslim", "muslims": "muslim",
              "unaffiliated": "none", "religiouslyunaffiliated": "none", "religiousnones": "none", "none": "none",
              "hindu": "hindu", "hindus": "hindu", "buddhist": "buddhist", "buddhists": "buddhist",
              "folkreligion": "folk", "folkreligions": "folk", "jew": "jewish", "jews": "jewish", "jewish": "jewish",
              "otherreligion": "other", "otherreligions": "other", "other": "other"}


class PewReligion(_Yearly):
    """Pew Research Center, religious composition by country (2010, 2020, and projections to 2050).
    Pew publishes it as report tables, so it is loaded by hand: any table with a country column,
    a year column (or the year in the sheet or file name) and one column per religious group, as
    shares (%) or numbers of people."""

    source_id = "pew_religion"
    manual = True

    def download(self, raw_dir: Path, release: str) -> str:
        raise ConnectorError("pew_religion: save Pew's religious composition table in var\\manual\\pew_religion "
                             "(see Data status for the link)")

    def stage(self, con: duckdb.DuckDBPyConnection, raw_dir: Path, release: str, vintage: str) -> str:
        from worldmodel_contract import catalogue

        from worldmodel_data.connectors.tabular import key, xlsx_rows, xlsx_sheet_names

        tables: list[tuple[str, list[list]]] = []
        for p in sorted(raw_dir.iterdir()):
            if p.suffix.lower() == ".csv":
                with p.open(encoding="utf-8-sig", errors="replace", newline="") as f:
                    tables.append((p.name, list(csv.reader(f))))
            elif p.suffix.lower() in (".xlsx", ".xlsm"):
                for i, name in enumerate(xlsx_sheet_names(p)):
                    tables.append((f"{p.name} {name}", xlsx_rows(p, i)))
        rows = Rows()
        for label, table in tables:
            hi = next((i for i, r in enumerate(table[:30]) if sum(key(c) in PEW_GROUPS for c in r) >= 3), None)
            if hi is None:
                continue
            head = [key(c) for c in table[hi]]
            ci = next((i for i, h in enumerate(head) if h in ("country", "countryname", "name", "location", "countries")), 0)
            yi = next((i for i, h in enumerate(head) if h == "year"), None)
            pi = next((i for i, h in enumerate(head) if h in ("population", "totalpopulation", "allreligions", "total")), None)
            groups = {i: PEW_GROUPS[h] for i, h in enumerate(head) if h in PEW_GROUPS}
            fy = re.search(r"(19|20)\d{2}", label)
            for r in table[hi + 1:]:
                if len(r) <= max(groups):
                    continue
                name = str(r[ci] or "").strip()
                y = int(num(r[yi])) if yi is not None and num(r[yi]) else int(fy.group(0)) if fy else None
                ent = catalogue.country_by_name(name) or entity_for("iso3", name.upper())
                if not ent or not y:
                    continue
                vals = {g: num(r[i]) for i, g in groups.items() if num(r[i]) is not None}
                if not vals:
                    continue
                total = sum(vals.values())
                pop = num(r[pi]) if pi is not None else None
                status = "P" if y > datetime.now().year else "E"
                if 95 <= total <= 105 or max(vals.values()) <= 100 and not pop:
                    _add_religion(rows, ent, y, {}, None, vals, status)
                else:
                    _add_religion(rows, ent, y, vals, pop or total, None, status)
        if not len(rows):
            raise ConnectorError("pew_religion: no table with a country column and religious groups (Christians, "
                                 "Muslims, Unaffiliated ...) was found")
        self.listed_indicators = religion_indicators(self.source_id, "pew", "Pew Research Center, Global Religious "
                                                     "Futures and religious composition by country.")
        return rows.stage(con, self.source_id, vintage)
