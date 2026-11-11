"""Crowd forecasts (Polymarket, Metaculus, Manifold) and published conflict forecasts (ViEWS):
which questions are read, and how a question is matched to countries, an indicator and a
category. Shared by the data side (connectors/crowd.py, crowd_tables.py) and the app.

A question's key is "<site>:<the site's own id>". Chances are 0 to 1."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

SITES = {"polymarket": "Polymarket", "metaculus": "Metaculus", "manifold": "Manifold"}
SITE_URLS = {"polymarket": "https://polymarket.com", "metaculus": "https://www.metaculus.com",
             "manifold": "https://manifold.markets"}

# The categories read, with each site's own tags for them. A question in none of these
# tags is still kept when its title matches the category's words (below).
CATEGORIES = {
    "politics": "Politics and elections",
    "economics": "Economy and markets",
    "geopolitics": "Geopolitics and conflict",
    "climate": "Climate, energy and nature",
    "science": "Science, health and technology",
}
SITE_TAGS = {
    "polymarket": {"politics": ["politics", "elections", "world-elections", "global-elections"],
                   "economics": ["economy", "fed", "inflation", "economic-policy", "tariffs"],
                   "geopolitics": ["geopolitics", "world", "ukraine", "middle-east", "china"],
                   "climate": ["climate", "weather", "climate-science"],
                   "science": ["science", "ai", "health", "space"]},
    "metaculus": {"politics": ["elections", "politics"],
                  "economics": ["economy-business", "finance"],
                  "geopolitics": ["geopolitics", "nuclear"],
                  "climate": ["environment-climate", "natural-sciences"],
                  "science": ["health-pandemics", "artificial-intelligence", "computing-and-math", "space"]},
    "manifold": {"politics": ["politics-default", "world-politics", "elections"],
                 "economics": ["economics-default", "finance", "inflation"],
                 "geopolitics": ["geopolitics", "ukraine-russia", "israel-hamas", "china"],
                 "climate": ["climate", "weather"],
                 "science": ["science-default", "ai", "health", "space"]},
}
CATEGORY_WORDS = {
    "politics": r"elect|vote|president|prime minister|parliament|senate|congress|referendum|party|governor|coalition|impeach|resign",
    "economics": r"gdp|inflation|recession|interest rate|central bank|fed\b|rbnz|unemploy|tariff|default|debt|stock|s&p|nasdaq|oil price|currency|dollar",
    "geopolitics": r"war|invade|invasion|ceasefire|troops|missile|nuclear|nato|sanction|attack|strike|conflict|coup|treaty|annex|blockade",
    "climate": r"temperature|warmest|hottest|emission|co2|carbon|hurricane|cyclone|el ni|la ni|sea ice|climate|wildfire|drought",
    "science": r"vaccine|pandemic|outbreak|virus|disease|ai\b|artificial intelligence|agi|launch|mars|moon|fusion|nobel",
}
# Words that make a question geopolitics whatever the site filed it under.
GEO_STRONG = re.compile(r"\b(war|wars|invade[sd]?|invasion|ceasefire|troops|missiles?|blockade|annex(es|ed)?|coup|military strikes?|"
                        r"nuclear (weapons?|test|strike|attack))\b", re.I)
# Not read at all: sport, crypto prices, entertainment and markets about the sites themselves.
EXCLUDE = re.compile(r"\b(nfl|nba|mlb|nhl|ufc|premier league|champions league|world cup|super bowl|grand prix|f1\b|tennis|"
                     r"golf|bitcoin|btc|ethereum|eth\b|solana|crypto|memecoin|token|airdrop|oscar|grammy|emmy|box office|"
                     r"album|taylor swift|youtube|tiktok|spotify|manifold|polymarket|metaculus|mrbeast|elon tweet|tweets?)\b", re.I)

# Indicators a question's title can be about (first match wins).
INDICATOR_WORDS = [
    (r"\binflation\b|\bcpi\b|consumer prices", "inflation"),
    (r"\bunemploy", "unemployment"),
    (r"\brecession\b|\bgdp\b|economic growth|economy grow|economy shrink", "gdp_growth"),
    (r"interest rate|policy rate|official cash rate|\bocr\b|rate (cut|hike)|cut rates|raise rates|fed funds", "bis_policy_rate"),
    (r"government debt|public debt|debt.to.gdp", "govt_debt_gdp"),
    (r"\bpopulation\b", "pop_total"),
    (r"life expectancy", "life_expectancy"),
    (r"\bco2\b|carbon emissions|greenhouse gas emissions", "co2_gcp"),
]

# What people from a country are called, and other names titles use, for the countries most
# asked about (country names themselves come from the entities table).
DEMONYMS = {
    "USA": ["American", "Americans", "U.S.", "US", "USA", "United States", "Trump", "Biden", "Harris", "Vance", "Fed",
            "Federal Reserve", "White House", "Congress", "Senate", "Supreme Court"],
    "GBR": ["British", "Britain", "UK", "U.K.", "England", "English", "Scotland", "Scottish", "Wales", "Welsh", "Starmer",
            "Bank of England", "Westminster"],
    "NZL": ["New Zealander", "New Zealanders", "Kiwi", "Kiwis", "NZ", "Luxon", "RBNZ", "Aotearoa"],
    "AUS": ["Australian", "Australians", "Albanese", "RBA"],
    "CAN": ["Canadian", "Canadians", "Carney"], "CHN": ["Chinese", "Beijing", "Xi Jinping", "PRC"],
    "RUS": ["Russian", "Russians", "Kremlin", "Putin", "Moscow"], "UKR": ["Ukrainian", "Ukrainians", "Kyiv", "Zelensky", "Zelenskyy"],
    "ISR": ["Israeli", "Israelis", "Netanyahu", "IDF"], "PSE": ["Palestinian", "Palestinians", "Gaza", "West Bank", "Hamas"],
    "IRN": ["Iranian", "Iranians", "Tehran", "Khamenei"], "IND": ["Indian", "Modi", "Delhi"], "JPN": ["Japanese", "Tokyo", "BOJ"],
    "KOR": ["South Korean", "South Korea", "Seoul"], "PRK": ["North Korean", "North Korea", "Kim Jong Un", "Pyongyang"],
    "TWN": ["Taiwanese", "Taipei"], "DEU": ["German", "Germans", "Berlin", "Bundestag"], "FRA": ["French", "Paris", "Macron"],
    "ITA": ["Italian", "Italians", "Meloni", "Rome"], "ESP": ["Spanish", "Madrid"], "BRA": ["Brazilian", "Lula", "Bolsonaro"],
    "MEX": ["Mexican", "Mexicans"], "ARG": ["Argentine", "Argentinian", "Milei"], "TUR": ["Turkish", "Erdogan", "Türkiye", "Turkiye"],
    "SAU": ["Saudi", "Saudis", "Riyadh"], "EGY": ["Egyptian"], "PAK": ["Pakistani", "Islamabad"], "VEN": ["Venezuelan", "Maduro"],
    "SYR": ["Syrian", "Damascus"], "LBN": ["Lebanese", "Hezbollah", "Beirut"], "YEM": ["Yemeni", "Houthi", "Houthis"],
    "POL": ["Polish", "Warsaw"], "HUN": ["Hungarian", "Orban", "Orbán"], "NLD": ["Dutch", "Netherlands"], "SWE": ["Swedish"],
    "NOR": ["Norwegian"], "FIN": ["Finnish"], "DNK": ["Danish", "Greenland"], "IRL": ["Irish", "Ireland"],
    "ZAF": ["South African"], "NGA": ["Nigerian"], "ETH": ["Ethiopian"], "SDN": ["Sudanese", "RSF"], "COL": ["Colombian"],
    "CHL": ["Chilean"], "PER": ["Peruvian"], "IDN": ["Indonesian", "Jakarta"], "PHL": ["Filipino", "Philippine", "Manila"],
    "VNM": ["Vietnamese"], "THA": ["Thai", "Bangkok"], "MYS": ["Malaysian"], "SGP": ["Singaporean"],
    "AFG": ["Afghan", "Taliban", "Kabul"], "IRQ": ["Iraqi", "Baghdad"], "SRB": ["Serbian"], "ROU": ["Romanian"],
    "GRC": ["Greek", "Athens"], "PRT": ["Portuguese"], "BEL": ["Belgian"], "CHE": ["Swiss"], "AUT": ["Austrian"],
    "CZE": ["Czech"], "MDA": ["Moldovan"], "GEO": ["Georgian", "Tbilisi"], "ARM": ["Armenian"], "AZE": ["Azerbaijani"],
    "KAZ": ["Kazakh"], "BLR": ["Belarusian", "Lukashenko"], "CUB": ["Cuban"], "HTI": ["Haitian"], "FJI": ["Fijian"],
    "PNG": ["Papua New Guinean"], "WSM": ["Samoan"], "TON": ["Tongan"],
}
# Names that are also something else: matched only with a hint of the country nearby.
AMBIGUOUS = {
    "GEO": re.compile(r"tbilisi|georgian dream|south caucasus|georgia's (parliament|president|prime minister)", re.I),
    "JOR": re.compile(r"amman|king abdullah|jordanian", re.I),
    "TCD": re.compile(r"n'djamena|chadian|republic of chad", re.I),
    "NER": re.compile(r"niamey|nigerien|sahel|junta", re.I),
    "TUR": re.compile(r"turkish|ankara|erdogan|istanbul|türkiye|turkiye", re.I),
}
_US_STATE_CONTEXT = re.compile(r"senate|governor|primary|atlanta|county|state house|house race", re.I)


def build_terms(entities: list[tuple[str, str, str, str]]) -> list[tuple[str, re.Pattern]]:
    """Country entities (entity_id, name, short_name, synonyms with |) to (entity_id, pattern) pairs."""
    out = []
    for ent, name, short, syn in entities:
        words = {w.strip() for w in [name or "", short or "", *(syn or "").split("|"), *DEMONYMS.get(ent, [])] if w and len(w.strip()) > 1}
        words = {w for w in words if not (w.isupper() and len(w) <= 3 and ent not in DEMONYMS)}  # bare codes only where listed
        if not words:
            continue
        alts = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
        # Short upper-case names (US, UK, NZ) only as whole upper-case words
        out.append((ent, re.compile(rf"(?<![\w.])(?:{alts})(?![\w])")))
    return out


def match_countries(text: str, terms: list[tuple[str, re.Pattern]], limit: int = 6) -> list[str]:
    """Entity ids named in a question's title (and description start), in the order first named."""
    if not text:
        return []
    found = []
    for ent, pat in terms:
        m = pat.search(text)
        if not m:
            continue
        if ent in AMBIGUOUS and not AMBIGUOUS[ent].search(text):
            continue
        if ent == "USA" and m.group(0) == "US" and not re.search(r"\bUS\b", text):
            continue
        found.append((m.start(), ent))
    if "GEO" in [e for _, e in found] and _US_STATE_CONTEXT.search(text):
        found = [(p, e) for p, e in found if e != "GEO"]
    return [e for _, e in sorted(found)][:limit]


def match_indicator(text: str) -> str | None:
    for pat, ind in INDICATOR_WORDS:
        if re.search(pat, text or "", re.I):
            return ind
    return None


def categorise(text: str, tags: list[str], site: str) -> str | None:
    """The question's category: by the site's tags first, then by the words in its title. War and
    conflict words win over the tags (sites file a blockade or an invasion under economics or politics)."""
    tags = {t.lower() for t in tags or []}
    if GEO_STRONG.search(text or ""):
        return "geopolitics"
    for cat, by_site in ((c, SITE_TAGS[site].get(c, [])) for c in CATEGORIES):
        if tags & set(by_site):
            return cat
    for cat, words in CATEGORY_WORDS.items():
        if re.search(words, text or "", re.I):
            return cat
    return None


def wanted(text: str) -> bool:
    return not EXCLUDE.search(text or "")


# ----------------------------------------------------------------------------- follow and hide
def follow_path(root: Path | None = None) -> Path:
    """The questions you follow or hide (crowd_follow.json in the user folder)."""
    if os.environ.get("WORLDMODEL_USER_DIR"):
        return Path(os.environ["WORLDMODEL_USER_DIR"]).expanduser() / "crowd_follow.json"
    if root is not None:
        return Path(root) / "user" / "crowd_follow.json"
    from worldmodel_contract.local import user_dir
    return user_dir() / "crowd_follow.json"


def load_follow(root: Path | None = None) -> dict[str, list[str]]:
    try:
        d = json.loads(follow_path(root).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        d = {}
    return {"follow": [str(x) for x in d.get("follow", [])][:2000], "hide": [str(x) for x in d.get("hide", [])][:5000]}


def save_follow(data: dict[str, list[str]], root: Path | None = None) -> None:
    p = follow_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(p)


def brier(p: float, outcome: bool) -> float:
    return (p - (1.0 if outcome else 0.0)) ** 2
