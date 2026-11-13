"""Religion and languages: world totals, maps and each country's mix.

Figures come from the warehouse: religion as rel_share / rel_people with a breakdown
rel=<group> (Correlates of War 1945-2010, Pew 2010-2050), plus each Factbook edition's
"Religions" line read for its percentages; languages as lang_share / lang_speakers /
lang_official with a breakdown lang=<code> (Unicode CLDR) and counts from Glottolog,
with names from the texts table. Each function takes `q`, the API's rows(sql, params) helper.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Callable

Q = Callable[[str, list], list[dict]]

GROUPS = [("christian", "Christians"), ("muslim", "Muslims"), ("none", "No religion"), ("hindu", "Hindus"),
          ("buddhist", "Buddhists"), ("folk", "Folk religions"), ("jewish", "Jews"), ("other", "Other religions")]
GROUP_IDS = [g for g, _ in GROUPS]
SOURCE_NAMES = {"pew_religion": "Pew Research Center", "cow_religion": "Correlates of War", "cia_factbook": "CIA Factbook"}
SOURCE_ORDER = ("pew_religion", "cow_religion")

# Words in a Factbook religion line -> group (first match wins; order matters).
_UNSTATED = ("unspecified", "not stated", "unknown", "undeclared", "no answer", "refused")
_KEYWORDS = (
    ("none", ("none", "no religion", "atheis", "agnostic", "unaffiliated", "nonreligious", "non-religious", "irreligi",
              "secular")),
    ("muslim", ("muslim", "islam", "sunni", "shia", "shi'a", "ibadhi", "alawite", "ahmadi")),
    ("jewish", ("jew", "judaism")),
    ("hindu", ("hindu",)),
    ("buddhist", ("buddhis", "lamais")),
    ("christian", ("christian", "catholic", "protestant", "anglican", "orthodox", "presbyterian", "methodist", "baptist",
                   "pentecostal", "lutheran", "evangelical", "mormon", "latter-day", "latter day", "jehovah", "church",
                   "adventist", "reformed", "congregational", "uniting", "calvinist", "coptic", "apostolic",
                   "salvation army", "quaker", "mennonite")),
    ("folk", ("folk", "indigenous", "animis", "traditional", "shinto", "taois", "confucian", "ethnic religion",
              "spiritis", "voodoo", "vodou", "shaman", "ancestral")),
)


def _top_items(text: str) -> list[str]:
    """Top-level comma-separated items, keeping what is inside brackets with its item."""
    out, depth, cur = [], 0, []
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch in ",;" and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    items: list[str] = []
    for s in (x.strip() for x in out):
        if not s:
            continue
        if items and re.fullmatch(r"[\d.]+\s*%.*", s) and "%" not in items[-1]:  # "Muslim, 1.3%"
            items[-1] = f"{items[-1]} {s}"
        else:
            items.append(s)
    return items


def classify(name: str) -> str | None:
    s = name.lower()
    if any(w in s for w in _UNSTATED):
        return None
    for g, words in _KEYWORDS:
        if any(w in s for w in words):
            return g
    return "other"


def factbook_religion(text: str, edition: int) -> dict | None:
    """Shares by group from a Factbook "Religions" line, such as "Christian 37.3% (Catholic 10.1%,
    ...), Hindu 2.7%, none 48.6% (2018 est.)". None when under half the people are placed."""
    clean = text.replace("|", " ")
    year = None
    refs = re.findall(r"\((?:[^()]*?\b)?((?:19|20)\d{2})\b[^()]*?(?:est|census|survey|data)?[^()]*\)", clean)
    if refs:
        year = int(refs[-1])
    shares: dict[str, float] = defaultdict(float)
    for item in _top_items(re.sub(r"\((?:[^()]*?\b)(?:19|20)\d{2}\b[^()]*\)\s*$", "", clean.split(" note:")[0])):
        head = re.sub(r"\([^()]*\)", "", item)  # the branches in brackets are inside the total already
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", head)
        if not m:
            continue
        name = re.sub(r"[\d.,%]+", " ", head).strip(" ,:-")
        g = classify(name)
        if g:
            shares[g] += float(m.group(1))
    total = sum(shares.values())
    if total < 50 or total > 115:
        return None
    return {"edition": edition, "year": year or edition, "shares": {g: round(v, 2) for g, v in shares.items()}}


def factbook_series(q: Q, entity: str) -> list[dict]:
    """One point per year the Factbook's figures refer to (the latest edition saying it)."""
    rows = q("""SELECT edition, content FROM texts WHERE entity_id = ? AND source_id = 'cia_factbook'
                AND lower(field_key) LIKE '%religion%' ORDER BY edition""", [entity])
    by_year: dict[int, dict] = {}
    for r in rows:
        got = factbook_religion(r["content"] or "", int(r["edition"]))
        if got:
            got["text"] = r["content"]
            by_year[got["year"]] = got
    return [by_year[y] for y in sorted(by_year)]


def _rel_rows(q: Q, entity: str | None = None) -> list[dict]:
    where, params = "", []
    if entity:
        where, params = " AND s.entity_id = ?", [entity]
    return q(f"""SELECT s.source_id AS src, s.entity_id AS e, year(s.period_start) AS y, s.indicator_id AS ind,
                        substr(s.breakdown, 5) AS g, s.value AS v, s.status AS st
                 FROM series s JOIN entities en ON en.entity_id = s.entity_id
                 WHERE s.indicator_id IN ('rel_share', 'rel_people') AND s.breakdown LIKE 'rel=%' AND s.variant = 'central'
                   AND NOT s.is_aggregate AND en.type IN ('country', 'historical_country'){where}""", params)


def _pop(q: Q, years: list[int]) -> dict[tuple[str, int], float]:
    if not years:
        return {}
    ph = ", ".join("?" for _ in years)
    rows = q(f"""SELECT entity_id AS e, year(period_start) AS y, avg(value) AS v FROM series
                 WHERE indicator_id = 'pop_total' AND breakdown = '' AND variant = 'central' AND NOT is_aggregate
                   AND year(period_start) IN ({ph}) GROUP BY 1, 2""", years)
    return {(r["e"], r["y"]): r["v"] for r in rows}


def _shares(rows: list[dict]) -> dict[tuple[str, str, int], dict]:
    """(source, entity, year) -> {shares: {group: %}, people: {group: n}, projected}."""
    out: dict[tuple[str, str, int], dict] = {}
    for r in rows:
        k = (r["src"], r["e"], r["y"])
        d = out.setdefault(k, {"shares": {}, "people": {}, "projected": False})
        d["shares" if r["ind"] == "rel_share" else "people"][r["g"]] = r["v"]
        d["projected"] = d["projected"] or r["st"] == "P"
    return out


def religion(q: Q, year: int | None = None, group: str = "christian", since: int | None = None) -> dict:
    data = _shares(_rel_rows(q))
    sources = sorted({k[0] for k in data}, key=lambda s: SOURCE_ORDER.index(s) if s in SOURCE_ORDER else 9)
    years_all = sorted({k[2] for k in data})
    pop = _pop(q, years_all)
    # The world: each source's countries weighted by their people.
    world: dict[str, list[dict]] = {}
    for src in sources:
        acc: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        weight: dict[int, float] = defaultdict(float)
        proj: dict[int, bool] = {}
        for (s, e, y), d in data.items():
            if s != src:
                continue
            w = sum(v for g, v in d["people"].items() if "." not in g) or pop.get((e, y))
            if not w:
                continue
            weight[y] += w
            proj[y] = proj.get(y, False) or d["projected"]
            for g, v in d["shares"].items():
                if "." not in g:
                    acc[y][g] += v / 100 * w
        world[src] = [{"year": y, "projected": proj[y], "people": weight[y],
                       "shares": {g: round(acc[y][g] / weight[y] * 100, 2) for g in GROUP_IDS if g in acc[y]}}
                      for y in sorted(acc) if weight[y]]
    # The map: the best source each country has for the year asked (else the latest year).
    year = year or max((y for (s, e, y), d in data.items() if not d["projected"]), default=None)
    def rank(src: str) -> int:
        return SOURCE_ORDER.index(src) if src in SOURCE_ORDER else 9

    best: dict[str, tuple[str, dict]] = {}
    then: dict[str, tuple[str, dict]] = {}
    for (s, e, y), d in data.items():
        if y == year and (e not in best or rank(s) < rank(best[e][0])):
            best[e] = (s, d)
        if since and y == since and (e not in then or rank(s) < rank(then[e][0])):
            then[e] = (s, d)
    rows = []
    for e, (s, d) in best.items():
        top = {g: v for g, v in d["shares"].items() if "." not in g}
        if not top:
            continue
        largest = max(top, key=top.get)
        r = {"entity_id": e, "source": s, "largest": largest, "largest_share": round(top[largest], 1),
             "share": round(top.get(group, 0.0), 2)}
        if since and e in then:
            r["change"] = round(top.get(group, 0.0) - then[e][1]["shares"].get(group, 0.0), 2)
        rows.append(r)
    rows.sort(key=lambda r: -r["share"])
    return {"groups": [{"id": g, "name": n} for g, n in GROUPS], "sources": [{"id": s, "name": SOURCE_NAMES.get(s, s)}
            for s in sources], "years": years_all, "world": world,
            "map": {"year": year, "group": group, "since": since, "rows": rows}}


def religion_country(q: Q, entity: str) -> dict:
    data = _shares(_rel_rows(q, entity))
    by_source: dict[str, list[dict]] = defaultdict(list)
    for (s, e, y), d in sorted(data.items(), key=lambda kv: kv[0][2]):
        by_source[s].append({"year": y, "projected": d["projected"],
                             "shares": {g: round(v, 2) for g, v in d["shares"].items()}})
    fb = factbook_series(q, entity)
    if fb:
        by_source["cia_factbook"] = [{"year": p["year"], "projected": False, "shares": p["shares"], "edition": p["edition"],
                                      "text": p["text"]} for p in fb]
    return {"entity_id": entity, "groups": [{"id": g, "name": n} for g, n in GROUPS],
            "sources": [{"id": s, "name": SOURCE_NAMES.get(s, s), "points": pts} for s, pts in by_source.items()]}


# ----------------------------------------------------------------------------- languages
def _lang_names(q: Q, codes: list[str] | None = None) -> dict[str, str]:
    rows = q("""SELECT substr(field_key, 6) AS code, any_value(field) AS name FROM texts
                WHERE source_id = 'cldr_languages' AND field_key LIKE 'lang:%' GROUP BY 1""", [])
    return {r["code"]: r["name"] for r in rows}


def languages(q: Q, lang: str | None = None, top: int = 25) -> dict:
    names = _lang_names(q)
    tot = q("""SELECT substr(s.breakdown, 6) AS code, sum(s.value) AS speakers, count(DISTINCT s.entity_id) AS countries
               FROM series s JOIN entities en ON en.entity_id = s.entity_id
               WHERE s.indicator_id = 'lang_speakers' AND s.breakdown LIKE 'lang=%' AND s.variant = 'central'
                 AND NOT s.is_aggregate AND en.type = 'country'
                 AND s.period_start = (SELECT max(period_start) FROM series WHERE indicator_id = 'lang_speakers')
               GROUP BY 1 ORDER BY 2 DESC LIMIT ?""", [top])
    official = q("""SELECT substr(breakdown, 6) AS code, count(DISTINCT entity_id) AS n FROM series
                    WHERE indicator_id = 'lang_official' AND value >= 3 AND NOT is_aggregate GROUP BY 1""", [])
    off = {r["code"]: r["n"] for r in official}
    lang = lang or (tot[0]["code"] if tot else "en")
    shares = q("""SELECT s.entity_id, s.value AS share,
                         (SELECT max(o.value) FROM series o WHERE o.indicator_id = 'lang_official' AND o.entity_id = s.entity_id
                          AND o.breakdown = s.breakdown) AS official
                  FROM series s WHERE s.indicator_id = 'lang_share' AND s.breakdown = ? AND s.variant = 'central'
                    AND NOT s.is_aggregate ORDER BY s.value DESC""", [f"lang={lang}"])
    main_ = q("""SELECT s.entity_id, substr(s.breakdown, 6) AS code, s.value AS share FROM series s
                 WHERE s.indicator_id = 'lang_share' AND s.variant = 'central' AND NOT s.is_aggregate
                 QUALIFY row_number() OVER (PARTITION BY s.entity_id ORDER BY s.value DESC) = 1""", [])
    counts = q("""SELECT entity_id, indicator_id AS ind, value FROM series WHERE indicator_id IN
                  ('lang_count', 'lang_endangered', 'lang_official_count') AND breakdown = '' AND NOT is_aggregate
                  QUALIFY row_number() OVER (PARTITION BY entity_id, indicator_id ORDER BY period_start DESC) = 1""", [])
    by_e: dict[str, dict] = defaultdict(dict)
    for r in counts:
        by_e[r["entity_id"]][r["ind"]] = r["value"]
    # Speakers living where the language is the main one (mostly first-language speakers) and
    # elsewhere (mostly people who learned it): CLDR has no first/second split of its own.
    home = {r["code"]: r["n"] for r in q("""
        WITH m AS (SELECT s.entity_id, s.breakdown FROM series s WHERE s.indicator_id = 'lang_share' AND s.variant = 'central'
                     AND NOT s.is_aggregate QUALIFY row_number() OVER (PARTITION BY s.entity_id ORDER BY s.value DESC) = 1)
        SELECT substr(s.breakdown, 6) AS code, sum(s.value) AS n FROM series s JOIN m USING (entity_id, breakdown)
        JOIN entities en ON en.entity_id = s.entity_id
        WHERE s.indicator_id = 'lang_speakers' AND s.variant = 'central' AND NOT s.is_aggregate AND en.type = 'country'
          AND s.period_start = (SELECT max(period_start) FROM series WHERE indicator_id = 'lang_speakers')
        GROUP BY 1""", [])}
    return {
        "top": [{"code": r["code"], "name": names.get(r["code"], r["code"]), "speakers": r["speakers"],
                 "home": home.get(r["code"], 0.0), "countries": r["countries"], "official_in": off.get(r["code"], 0)} for r in tot],
        "lang": lang, "lang_name": names.get(lang, lang),
        "map": [{"entity_id": r["entity_id"], "share": r["share"], "official": r["official"]} for r in shares],
        "main": [{"entity_id": r["entity_id"], "code": r["code"], "name": names.get(r["code"], r["code"]),
                  "share": r["share"]} for r in main_],
        "counts": [{"entity_id": e, **v} for e, v in by_e.items()],
        "languages": sorted(({"code": c, "name": n} for c, n in names.items()), key=lambda x: x["name"]),
    }


OFFICIAL_WORDS = {4: "official", 3: "official in practice", 2: "official in a region", 1: "official for a minority"}


def languages_country(q: Q, entity: str) -> dict:
    names = _lang_names(q)
    rows = q("""SELECT substr(s.breakdown, 6) AS code, max(s.value) FILTER (WHERE s.indicator_id = 'lang_share') AS share,
                       max(s.value) FILTER (WHERE s.indicator_id = 'lang_official') AS official,
                       max(s.value) FILTER (WHERE s.indicator_id = 'lang_speakers') AS speakers
                FROM series s WHERE s.entity_id = ? AND s.breakdown LIKE 'lang=%' AND s.variant = 'central'
                  AND s.indicator_id IN ('lang_share', 'lang_official', 'lang_speakers') GROUP BY 1
                ORDER BY coalesce(max(s.value) FILTER (WHERE s.indicator_id = 'lang_official'), 0) >= 3 DESC, 2 DESC NULLS LAST""",
             [entity])
    counts = {r["ind"]: r["value"] for r in q("""SELECT indicator_id AS ind, value FROM series WHERE entity_id = ?
              AND indicator_id IN ('lang_count', 'lang_endangered', 'lang_threatened', 'lang_extinct', 'lang_official_count')
              AND breakdown = '' QUALIFY row_number() OVER (PARTITION BY indicator_id ORDER BY period_start DESC) = 1""", [entity])}
    endangered = []
    for r in q("""SELECT field AS name, content, position FROM texts WHERE entity_id = ? AND source_id = 'glottolog'
                  AND section = 'Endangered languages' ORDER BY position, field""", [entity]):
        # content is "status|family|level", most endangered first (older builds: level in position)
        status, family, level = ((r["content"] or "").split("|") + ["", ""])[:3]
        endangered.append({"name": r["name"], "status": status, "family": family,
                           "level": int(level) if level.isdigit() else r["position"]})
    endangered.sort(key=lambda e: -e["level"])
    fb = q("""SELECT edition, content FROM texts WHERE entity_id = ? AND source_id = 'cia_factbook'
              AND lower(field_key) LIKE '%language%' ORDER BY edition DESC LIMIT 1""", [entity])
    return {
        "entity_id": entity,
        "languages": [{"code": r["code"], "name": names.get(r["code"], r["code"]), "share": r["share"],
                       "speakers": r["speakers"], "official": OFFICIAL_WORDS.get(int(r["official"])) if r["official"] else None}
                      for r in rows],
        "counts": counts, "endangered": endangered,
        "factbook": fb[0] if fb else None,
    }
