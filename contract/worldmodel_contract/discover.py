"""Discover: interesting things the app finds in its own figures after each refresh.

Each check is simple and explainable, and gives every find a score from 0 to 1 for how
unusual it is:

  record      the latest value is the highest or lowest on record, or since a year long ago
  mover       the latest yearly change is far outside the country's own past changes
  turning     a long steady trend has flattened or reversed in the last five years
  overtake    one country has passed another (a key country, or a near neighbour in the
              ranking), or moved many places in a ranking
  outlier     a country is the highest or lowest in its bloc or region by a wide margin
  disagree    two sources for the same figure have moved far apart
  forecast    a forecaster revised its projection a lot between two releases
  together    a pair of figures that move together (from the relationship scan)
  after       a figure that changes after an event (from the relationship scan)
  revised     a source revised past figures a lot in its newest release

Each find has a headline written from the numbers, a small chart, a category (from the
indicator's topic), tags (countries, indicator, kind, years) and a tone (good news, bad
news or neutral) from whether the figure is better higher or lower. Finds are saved per
build in <home>/warehouse/discover/<build_id>.json; ratings, your tags and the day each
find was first seen are kept in the user folder, so a refresh never loses them.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path

import numpy as np

from worldmodel_contract import local

KINDS = {
    "record": "Records", "mover": "Big movers", "turning": "Turning points", "overtake": "Overtakes",
    "outlier": "Outliers", "disagree": "Sources disagree", "forecast": "Forecast changes",
    "together": "Moving together", "after": "Before and after", "revised": "New data", "opposite": "Opposite trends",
}
CATEGORIES = ["People", "Economy", "Trade", "Money and prices", "Energy", "Climate", "Government and politics",
              "Conflict and security", "Society and laws", "Cities and living", "AI and technology"]
DOMAIN_CATEGORY = {
    "population": "People", "migration": "People", "health": "People", "education": "People", "poverty": "Economy",
    "economy": "Economy", "business": "Economy", "labour": "Economy", "agriculture": "Economy", "aid": "Economy",
    "trade": "Trade", "finance": "Money and prices", "prices": "Money and prices", "housing": "Money and prices",
    "debt": "Money and prices", "energy": "Energy", "environment": "Climate", "climate": "Climate", "geography": "Climate",
    "government": "Government and politics", "politics": "Government and politics", "military": "Conflict and security",
    "conflict": "Conflict and security", "laws": "Society and laws", "crime": "Society and laws", "society": "Society and laws",
    "cities": "Cities and living", "science": "AI and technology", "infrastructure": "AI and technology",
    "ai": "AI and technology", "internet": "AI and technology", "technology": "AI and technology",
    "sectors": "Trade", "markets": "Money and prices", "water": "Climate", "land": "Climate", "transport": "Economy",
}
TONES = ("good", "bad", "neutral")
FIRST_YEAR = 1960
GROUPS = {"oecd": "the OECD", "eu": "the EU", "g20": "the G20", "asean": "ASEAN", "apec": "APEC"}

# Which way is better, from words in the indicator's id or name (your own choices win, from Settings).
_LOWER = re.compile(r"unemploy|death|mortality|poverty|homicide|crime|suicide|emission|co2|ghg|pm25|pollut|undernour|"
                    r"stunting|wasting|malaria|hiv|tuberculosis|deficit|corruption|conflict|fatalit|battle|disaster|"
                    r"out.of.school|inflation|slum|informal|child.labour|gini|inequal", re.I)
_HIGHER = re.compile(r"life.expect|gdp.per|income.per|gni.per|literacy|enrol|school.life|electricity.access|access.to|"
                     r"internet|broadband|renewable|safely.managed|basic.drinking|sanitation|vaccin|immuni|"
                     r"human.develop|hdi|happiness|press.freedom|democracy|turnout|speed|mbps|research|patent", re.I)
_NEUTRAL = re.compile(r"migra|house.price|exchange|population|birth|fertility|pop_|price|rate_of_change|debt", re.I)


def better_when(indicator_id: str, name: str, overrides: dict[str, str] | None = None) -> str:
    """"higher", "lower" or "neither"."""
    o = (overrides or {}).get(indicator_id)
    if o in ("higher", "lower", "neither"):
        return o
    text = f"{indicator_id} {name}"
    if _NEUTRAL.search(text) and not _HIGHER.search(text) and not _LOWER.search(text):
        return "neither"
    if _LOWER.search(text):
        return "lower"
    if _HIGHER.search(text):
        return "higher"
    return "neither"


def tone(better: str, rising: bool | None) -> str:
    if better == "neither" or rising is None:
        return "neutral"
    return "good" if (better == "higher") == rising else "bad"


_CATEGORY_WORDS = [
    ("Climate", r"climate|emission|co2|ghg|temperature|sea.ice|sea.level|forest|pollut|pm25|flood|earthquake|storm|cyclone|wildfire|drought|heatwave"),
    ("Energy", r"energy|electric|oil|gas_|coal|renewable|solar|wind|nuclear|storage|lng"),
    ("Government and politics", r"election|vote|turnout|party|parliament|democra|leader|govern"),
    ("Conflict and security", r"military|conflict|battle|war_|armed|terror|refugee|sanction|arms"),
    ("Society and laws", r"law|crime|prison|homicide|marriage|religio|rights"),
    ("Cities and living", r"city|cities|numbeo|rent|commute|urban"),
    ("AI and technology", r"internet|broadband|ai_|patent|research|semiconductor|mbps"),
    ("Money and prices", r"inflation|price|exchange|interest|policy_rate|credit|debt|house|fx_"),
    ("Trade", r"export|import|trade|tariff|tgx_|tgm_"),
    ("People", r"population|birth|death|life_exp|fertility|migra|school|health|age_"),
]


def category(domain: str | None, text: str = "") -> str:
    """The Discover category, from the indicator's domain, else from words in its id and name."""
    d = (domain or "").lower()
    if d in DOMAIN_CATEGORY:
        return DOMAIN_CATEGORY[d]
    for cat, pat in _CATEGORY_WORDS:
        if re.search(pat, text, re.I):
            return cat
    return "Economy"


def num(v: float, unit: str = "", decimals: int = 1) -> str:
    """A value for a headline: 1.2 million, 45.3%, 3,400."""
    if v is None or not math.isfinite(v):
        return ""
    a = abs(v)
    if unit in ("percent", "%") or unit.startswith("% "):
        s = f"{v:.{min(decimals, 1)}f}%"
    elif a >= 1e12:
        s = f"{v / 1e12:.1f} trillion"
    elif a >= 1e9:
        s = f"{v / 1e9:.1f} billion"
    elif a >= 1e6:
        s = f"{v / 1e6:.1f} million"
    elif a >= 1e4:
        s = f"{v:,.0f}"
    else:
        s = f"{v:,.{max(0, min(decimals, 2))}f}"
    tail = "" if unit in ("percent", "%") or unit.startswith("% ") or not unit else f" {unit}"
    return s + tail


def _lc(name: str) -> str:
    """A name inside a sentence: "House prices" -> "house prices", but "GDP per person" stays."""
    return name[:1].lower() + name[1:] if len(name) > 1 and name[1:2].islower() else name


# ----------------------------------------------------------------------------- the panel
class Panel:
    def __init__(self, entities: list[str], years: list[int]):
        self.entities, self.years = entities, years
        self.ei = {e: n for n, e in enumerate(entities)}
        self.data: dict[str, np.ndarray] = {}
        self.meta: dict[str, dict] = {}


def chosen(con, user_dir: Path | None = None) -> list[str]:
    """The yearly indicators switched on (the defaults with the Indicators page's switches)."""
    rows = con.execute("SELECT indicator_id, default_on, unit FROM indicators WHERE frequency = 'A'").fetchall()
    try:
        data = json.loads(((user_dir or local.user_dir()) / "indicators.json").read_text(encoding="utf-8"))
        over = {k: bool(v) for k, v in (data.get("enabled") or {}).items()}
    except (OSError, ValueError, AttributeError):
        over = {}
    return sorted(i for i, on, unit in rows if unit != "yes/no" and over.get(i, bool(on)))


def load(con, ids: list[str], last_year: int) -> Panel:
    con.execute("CREATE OR REPLACE TEMP TABLE disc_ids (indicator_id VARCHAR)")
    con.executemany("INSERT INTO disc_ids VALUES (?)", [(i,) for i in ids])
    data = con.execute("""
        SELECT s.indicator_id, s.entity_id, year(s.period_start) AS y, s.value
        FROM series s JOIN disc_ids k USING (indicator_id)
        JOIN indicator_sources r ON r.indicator_id = s.indicator_id AND r.source_id = s.source_id AND r.rank = 1
        JOIN entities e ON e.entity_id = s.entity_id
        WHERE s.status = 'E' AND s.breakdown = '' AND s.variant = 'central' AND s.freq = 'A' AND e.type = 'country'
          AND year(s.period_start) BETWEEN ? AND ? AND s.value IS NOT NULL""", [FIRST_YEAR, last_year]).fetchall()
    meta = con.execute("""
        SELECT i.indicator_id, i.name, i.domain, i.unit, i.decimals, coalesce(r.source_id, '')
        FROM indicators i JOIN disc_ids k USING (indicator_id)
        LEFT JOIN indicator_sources r ON r.indicator_id = i.indicator_id AND r.rank = 1""").fetchall()
    entities = sorted({d[1] for d in data})
    p = Panel(entities, list(range(FIRST_YEAR, last_year + 1)))
    by: dict[str, list] = {}
    for ind, ent, y, v in data:
        by.setdefault(ind, []).append((p.ei[ent], y - FIRST_YEAR, v))
    for ind, pts in by.items():
        a = np.full((len(entities), len(p.years)), np.nan)
        r, c, v = zip(*pts)
        a[list(r), list(c)] = v
        p.data[ind] = a
    for i, name, domain, unit, dec, src in meta:
        p.meta[i] = {"name": name, "domain": domain or "", "unit": unit or "", "decimals": dec if dec is not None else 1,
                     "source_id": src}
    return p


def _points(p: Panel, ind: str, e: int, first: int | None = None) -> list[list]:
    row = p.data[ind][e]
    out = [[p.years[j], float(row[j])] for j in range(len(row)) if math.isfinite(row[j])]
    return [x for x in out if first is None or x[0] >= first]


def _find(kind: str, key: str, p: Panel, ind: str, ents: list[str], names: dict[str, str], headline: str, score: float,
          years: list[int], rising: bool | None, better: dict[str, str], detail: str = "", series: list[dict] | None = None,
          mark: list[int] | None = None, value: float | None = None, extra_tags: list[str] | None = None) -> dict:
    m = p.meta.get(ind, {"name": ind, "domain": "", "unit": "", "decimals": 1, "source_id": ""})
    b = better_when(ind, m["name"], better)
    return {
        "key": key, "kind": kind, "category": category(m["domain"], f"{ind} {m['name']}"), "tone": tone(b, rising), "better": b,
        "rising": None if rising is None else bool(rising),
        "score": round(max(0.0, min(1.0, score)), 3), "headline": headline, "detail": detail,
        "entities": ents, "indicator_id": ind, "indicator_name": m["name"], "unit": m["unit"], "decimals": m["decimals"],
        "source_id": m["source_id"], "years": years, "value": value,
        "tags": [*(names.get(e, e) for e in ents), m["name"], KINDS[kind], f"{years[0]}–{years[-1]}" if len(years) > 1 else str(years[0]),
                 *(extra_tags or [])],
        "chart": {"series": series or [], "mark": mark or []},
    }


# ----------------------------------------------------------------------------- checks
def records(p: Panel, names, better, min_years: int = 15, min_since: int = 10) -> list[dict]:
    out = []
    last = len(p.years) - 1
    for ind, a in p.data.items():
        for e in range(a.shape[0]):
            row = a[e]
            ok = np.where(np.isfinite(row))[0]
            if len(ok) < min_years or ok[-1] < last - 3:
                continue
            j = ok[-1]
            v = row[j]
            prev = row[ok[:-1]]
            for high in (True, False):
                beat = prev >= v if high else prev <= v
                if beat.any():
                    since_idx = ok[:-1][np.where(beat)[0][-1]]
                    since = p.years[j] - p.years[since_idx]
                    if since < min_since:
                        continue
                    when = f"since {p.years[since_idx]}"
                    score = 0.35 + 0.5 * min(1, since / 40)
                else:
                    when = f"on record (since {p.years[ok[0]]})"
                    score = 0.55 + 0.4 * min(1, len(ok) / 50)
                m = p.meta[ind]
                ent = p.entities[e]
                out.append(_find("record", f"record:{ind}:{ent}:{p.years[j]}:{'hi' if high else 'lo'}", p, ind, [ent], names,
                                 f"{names.get(ent, ent)}: {_lc(m['name'])} "
                                 f"{'highest' if high else 'lowest'} {when}",
                                 score, [p.years[ok[0]], p.years[j]], high, better,
                                 detail=f"{num(v, m['unit'], m['decimals'])} in {p.years[j]}.",
                                 series=[{"entity_id": ent, "name": names.get(ent, ent), "points": _points(p, ind, e, p.years[j] - 40)}],
                                 mark=[p.years[j]], value=float(v)))
                break
    return out


def movers(p: Panel, names, better, z_min: float = 3.5) -> list[dict]:
    out = []
    last = len(p.years) - 1
    for ind, a in p.data.items():
        m = p.meta[ind]
        for e in range(a.shape[0]):
            row = a[e]
            ok = np.where(np.isfinite(row))[0]
            if len(ok) < 15 or ok[-1] < last - 3 or ok[-2] != ok[-1] - 1:
                continue
            ch = np.diff(row[ok])
            gaps = np.diff(ok)
            ch = ch[gaps == 1]
            if len(ch) < 12:
                continue
            hist, now = ch[-21:-1], ch[-1]
            sd = float(np.std(hist))
            if sd <= 0:
                continue
            z = (now - float(np.mean(hist))) / sd
            if abs(z) < z_min:
                continue
            ent, y = p.entities[e], p.years[ok[-1]]
            before = row[ok[-2]]
            pct = f" ({100 * now / abs(before):+.0f}%)" if before and m["unit"] not in ("percent",) and not m["unit"].startswith("%") else ""
            out.append(_find("mover", f"mover:{ind}:{ent}:{y}", p, ind, [ent], names,
                             f"{names.get(ent, ent)}: {m['name']} {'jumped' if now > 0 else 'fell'} in {y}",
                             0.4 + 0.1 * min(5, abs(z) - z_min + 1), [y - 1, y], now > 0, better,
                             detail=f"From {num(before, m['unit'], m['decimals'])} to {num(row[ok[-1]], m['unit'], m['decimals'])}{pct}: "
                                    f"about {abs(z):.0f} times the usual year-to-year swing.",
                             series=[{"entity_id": ent, "name": names.get(ent, ent), "points": _points(p, ind, e, y - 30)}],
                             mark=[y - 1, y], value=float(row[ok[-1]])))
    return out


def turning(p: Panel, names, better, long: int = 15, short: int = 5) -> list[dict]:
    out = []
    last = len(p.years) - 1
    for ind, a in p.data.items():
        m = p.meta[ind]
        for e in range(a.shape[0]):
            row = a[e, max(0, last - long - short + 1):]
            if np.isfinite(row).sum() < long + short - 2 or not math.isfinite(row[-1]):
                continue
            ch = np.diff(row)
            early, late = ch[:long - 1], ch[long - 1:]
            early, late = early[np.isfinite(early)], late[np.isfinite(late)]
            if len(early) < long - 3 or len(late) < short - 2:
                continue
            same = max((early > 0).mean(), (early < 0).mean())
            s1, s2 = float(np.mean(early)), float(np.mean(late))
            if same < 0.85 or s1 == 0:
                continue
            ratio = s2 / s1
            if ratio > 0.25:
                continue
            ent = p.entities[e]
            y0, y1 = p.years[last - long - short + 1], p.years[last]
            what = "reversed" if ratio < -0.25 else "levelled off"
            out.append(_find("turning", f"turning:{ind}:{ent}:{y1}", p, ind, [ent], names,
                             f"{names.get(ent, ent)}: {m['name']} {what} after {long} years of {'rises' if s1 > 0 else 'falls'}",
                             0.45 + 0.4 * (same - 0.85) / 0.15 + (0.1 if ratio < -0.25 else 0), [y0, y1],
                             (s2 > 0) if ratio < -0.25 else None, better,
                             detail=f"About {num(abs(s1), m['unit'], m['decimals'])} a year {'up' if s1 > 0 else 'down'} until {y1 - short}, "
                                    f"{num(abs(s2), m['unit'], m['decimals'])} a year {'up' if s2 > 0 else 'down'} since.",
                             series=[{"entity_id": ent, "name": names.get(ent, ent), "points": _points(p, ind, e, y0)}],
                             mark=[y1 - short, y1], value=float(row[-1])))
    return out


def overtakes(p: Panel, names, better, keys: list[str], min_countries: int = 40, jump: int = 10) -> list[dict]:
    out = []
    last = len(p.years) - 1
    for ind, a in p.data.items():
        m = p.meta[ind]
        for j in range(last, last - 3, -1):
            now, before = a[:, j], a[:, j - 1]
            both = np.isfinite(now) & np.isfinite(before)
            if both.sum() >= min_countries:
                break
        else:
            continue
        idx = np.where(both)[0]
        r_now = {i: r for r, i in enumerate(sorted(idx, key=lambda i: -now[i]))}
        r_before = {i: r for r, i in enumerate(sorted(idx, key=lambda i: -before[i]))}
        y = p.years[j]
        for k in keys:
            if k not in p.ei or p.ei[k] not in r_now:
                continue
            ki = p.ei[k]
            for o in idx:
                if o == ki:
                    continue
                up = (now[ki] > now[o]) and (before[ki] <= before[o])
                down = (now[ki] < now[o]) and (before[ki] >= before[o])
                if not (up or down) or abs(r_now[o] - r_now[ki]) > 1:
                    continue
                other = p.entities[o]
                first, second = (k, other) if up else (other, k)
                out.append(_find("overtake", f"overtake:{ind}:{first}:{second}:{y}", p, ind, [first, second], names,
                                 f"{names.get(first, first)} passes {names.get(second, second)} in {_lc(m['name'])}",
                                 0.5 + (0.2 if r_now[ki] < 20 else 0), [y - 1, y], None, better,
                                 detail=f"{y}: {names.get(first, first)} {num(now[p.ei[first]], m['unit'], m['decimals'])}, "
                                        f"{names.get(second, second)} {num(now[p.ei[second]], m['unit'], m['decimals'])}. "
                                        f"Rank {r_now[p.ei[first]] + 1} of {len(idx)}.",
                                 series=[{"entity_id": x, "name": names.get(x, x), "points": _points(p, ind, p.ei[x], y - 20)} for x in (first, second)],
                                 mark=[y], value=float(now[p.ei[first]])))
        for i in idx:
            moved = r_before[i] - r_now[i]
            if abs(moved) >= max(jump, len(idx) // 8) and r_now[i] < 30:
                ent = p.entities[i]
                out.append(_find("overtake", f"rank:{ind}:{ent}:{y}", p, ind, [ent], names,
                                 f"{names.get(ent, ent)} {'climbs' if moved > 0 else 'drops'} {abs(moved)} places in {_lc(m['name'])}",
                                 0.35 + 0.3 * min(1, abs(moved) / 30), [y - 1, y], moved > 0, better,
                                 detail=f"Rank {r_before[i] + 1} in {y - 1}, {r_now[i] + 1} in {y}, of {len(idx)} countries.",
                                 series=[{"entity_id": ent, "name": names.get(ent, ent), "points": _points(p, ind, i, y - 20)}],
                                 mark=[y], value=float(now[i])))
    return out


def _trend(row: np.ndarray, years: int) -> tuple[float, float] | None:
    """The straight-line change a year over the last `years`, as a share of the average level,
    and how well a straight line fits (r squared); None with too few figures."""
    seg = row[-years:]
    ok = np.isfinite(seg)
    if ok.sum() < years - 2 or not math.isfinite(seg[-1]):
        return None
    x, y = np.arange(len(seg))[ok], seg[ok]
    level = float(np.mean(np.abs(y)))
    if level == 0 or np.ptp(y) == 0:
        return None
    slope, icept = np.polyfit(x, y, 1)
    fit = slope * x + icept
    r2 = 1 - float(np.sum((y - fit) ** 2)) / float(np.sum((y - y.mean()) ** 2))
    return float(slope) / level, r2


def opposite(p: Panel, names, better, keys: list[str], peers: dict[str, list[str]], years: int = 10,
             min_slope: float = 0.01, min_fit: float = 0.6, per_key: int = 1) -> list[dict]:
    """Countries going opposite ways: over the last `years`, a key country's figure rising
    steadily while a neighbour's or another key country's falls steadily (or the reverse).
    The clearest pair for each key country and figure."""
    out = []
    last = len(p.years) - 1
    y1 = p.years[last]
    for ind, a in p.data.items():
        m = p.meta[ind]
        # Figures stop a year or two before this one: end the window at the last year with enough countries.
        j = next((j for j in range(last, last - 3, -1) if np.isfinite(a[:, j]).sum() >= 2), None)
        if j is None:
            continue
        trends: dict[str, tuple[float, float]] = {}

        def trend(e: str):
            if e not in trends and e in p.ei:
                t = _trend(a[p.ei[e], : j + 1], years)
                trends[e] = t if t and abs(t[0]) >= min_slope and t[1] >= min_fit else None
            return trends.get(e)
        for k in keys:
            tk = trend(k)
            if not tk:
                continue
            cands = []
            for o in dict.fromkeys([*keys, *peers.get(k, [])]):
                if o == k:
                    continue
                to = trend(o)
                if to and (to[0] > 0) != (tk[0] > 0):
                    cands.append((min(abs(tk[0]), abs(to[0])) * min(tk[1], to[1]), o, to))
            for strength, o, to in sorted(cands, reverse=True)[:per_key]:
                pair = sorted([k, o])
                yend, y0 = p.years[j], p.years[j] - years + 1
                up, down = (k, o) if tk[0] > 0 else (o, k)
                ki, oi = p.ei[k], p.ei[o]
                out.append(_find("opposite", f"opposite:{ind}:{pair[0]}:{pair[1]}:{yend}", p, ind, [k, o], names,
                                 f"{m['name']}: rising in {names.get(up, up)}, falling in {names.get(down, down)}",
                                 0.45 + min(0.45, strength * 6), [y0, yend], tk[0] > 0, better,
                                 detail=f"Since {y0}: {names.get(up, up)} up about {100 * abs(trends[up][0]):.1f}% a year, "
                                        f"{names.get(down, down)} down about {100 * abs(trends[down][0]):.1f}% a year. "
                                        f"{yend}: {names.get(k, k)} {num(a[ki, j], m['unit'], m['decimals'])}, "
                                        f"{names.get(o, o)} {num(a[oi, j], m['unit'], m['decimals'])}.",
                                 series=[{"entity_id": x, "name": names.get(x, x), "points": _points(p, ind, p.ei[x], y0 - 10)} for x in (k, o)],
                                 mark=[y0, yend], value=float(a[ki, j])))
    # A pair of key countries is found from both sides: keep it once.
    seen, uniq = set(), []
    for f in out:
        if f["key"] not in seen:
            seen.add(f["key"])
            uniq.append(f)
    return uniq


def outliers(p: Panel, names, better, groups: dict[str, list[str]], z_min: float = 2.5) -> list[dict]:
    out = []
    last = len(p.years) - 1
    for ind, a in p.data.items():
        m = p.meta[ind]
        rate = m["unit"] in ("percent",) or m["unit"].startswith("%") or " per " in f" {m['unit']} " or "index" in m["unit"]
        if not rate:
            continue
        for gid, members in groups.items():
            rows = [p.ei[x] for x in members if x in p.ei]
            for j in range(last, last - 4, -1):
                vals = a[rows, j]
                ok = np.isfinite(vals)
                if ok.sum() >= 8:
                    break
            else:
                continue
            vals_ok = vals[ok]
            mu, sd = float(np.mean(vals_ok)), float(np.std(vals_ok))
            if sd <= 0:
                continue
            for high in (True, False):
                k = int(np.argmax(vals_ok) if high else np.argmin(vals_ok))
                z = (vals_ok[k] - mu) / sd
                if abs(z) < z_min:
                    continue
                e = [r for r, o in zip(rows, ok) if o][k]
                ent, y = p.entities[e], p.years[j]
                out.append(_find("outlier", f"outlier:{ind}:{ent}:{gid}:{y}", p, ind, [ent], names,
                                 f"{names.get(ent, ent)} has the {'highest' if high else 'lowest'} {_lc(m['name'])} "
                                 f"in {GROUPS.get(gid, gid)}",
                                 0.4 + 0.12 * min(4, abs(z) - z_min + 1), [y], high, better,
                                 detail=f"{num(vals_ok[k], m['unit'], m['decimals'])} in {y}, against an average of "
                                        f"{num(mu, m['unit'], m['decimals'])} across {int(ok.sum())} members.",
                                 series=[{"entity_id": ent, "name": names.get(ent, ent), "points": _points(p, ind, e, y - 20)}],
                                 mark=[y], value=float(vals_ok[k]), extra_tags=[GROUPS.get(gid, gid)]))
    return out


def disagree(con, names, better, panel: Panel, keys: list[str], gap: float = 0.25) -> list[dict]:
    """Two sources for one figure, apart by more than `gap` in the latest common year and further apart
    than five years before."""
    rows = con.execute("""
        WITH s AS (
            SELECT s.indicator_id, s.entity_id, year(s.period_start) AS y, s.source_id, s.value, r.rank
            FROM series s JOIN indicator_sources r ON r.indicator_id = s.indicator_id AND r.source_id = s.source_id
            JOIN disc_ids k ON k.indicator_id = s.indicator_id
            WHERE s.status = 'E' AND s.breakdown = '' AND s.variant = 'central' AND s.freq = 'A' AND r.rank <= 2)
        SELECT a.indicator_id, a.entity_id, a.y, a.value AS v1, b.value AS v2, a.source_id AS s1, b.source_id AS s2
        FROM s a JOIN s b ON a.indicator_id = b.indicator_id AND a.entity_id = b.entity_id AND a.y = b.y
        WHERE a.rank = 1 AND b.rank = 2""").fetchall()
    by: dict[tuple, dict[int, tuple]] = {}
    for ind, ent, y, v1, v2, s1, s2 in rows:
        by.setdefault((ind, ent), {})[y] = (v1, v2, s1, s2)
    out = []
    for (ind, ent), ys in by.items():
        if ent not in keys and ent not in panel.ei:
            continue
        last = max(ys)
        v1, v2, s1, s2 = ys[last]
        if not v1 or not v2 or v1 * v2 <= 0:
            continue
        d = abs(v1 - v2) / max(abs(v1), abs(v2))
        old = ys.get(last - 5)
        d_old = abs(old[0] - old[1]) / max(abs(old[0]), abs(old[1])) if old and old[0] and old[1] else None
        if d < gap or (d_old is not None and d_old >= d * 0.7):
            continue
        m = panel.meta.get(ind) or {"name": ind, "unit": "", "decimals": 1, "domain": "", "source_id": s1}
        panel.meta.setdefault(ind, m)
        series = [{"entity_id": ent, "name": src, "points": [[y, float(v[0] if src == s1 else v[1])] for y, v in sorted(ys.items()) if y >= last - 20]}
                  for src in (s1, s2)]
        out.append(_find("disagree", f"disagree:{ind}:{ent}:{last}", panel, ind, [ent], names,
                         f"{names.get(ent, ent)}: sources disagree on {_lc(m['name'])}",
                         0.35 + 0.5 * min(1, d) + (0.1 if ent in keys else 0), [last - 5 if old else last, last], None, better,
                         detail=f"{last}: {s1} {num(v1, m['unit'], m['decimals'])}, {s2} {num(v2, m['unit'], m['decimals'])} "
                                f"({100 * d:.0f}% apart{f', from {100 * d_old:.0f}% five years before' if d_old is not None else ''}).",
                         series=series, mark=[last], value=float(v1), extra_tags=[s1, s2]))
    return out


def forecasts(con, names, better, panel: Panel, keys: list[str]) -> list[dict]:
    """Big revisions to a projection between a source's two newest releases (growth by a point or
    more, other figures by a tenth or more), for the key countries and the world."""
    rows = con.execute("""
        WITH v AS (SELECT source_id, vintage, row_number() OVER (PARTITION BY source_id ORDER BY retrieved_at DESC) AS n
                   FROM vintages),
        o AS (SELECT o.source_id, o.indicator_id, o.entity_id, year(o.period_start) AS y, o.value, v.n, o.vintage
              FROM observations o JOIN v ON v.source_id = o.source_id AND v.vintage = o.vintage
              WHERE v.n <= 2 AND o.status = 'P' AND o.variant = 'central' AND o.breakdown = '' AND o.freq = 'A')
        SELECT a.source_id, a.indicator_id, a.entity_id, a.y, a.value AS now, b.value AS before, a.vintage, b.vintage
        FROM o a JOIN o b ON a.source_id = b.source_id AND a.indicator_id = b.indicator_id AND a.entity_id = b.entity_id
            AND a.y = b.y AND a.n = 1 AND b.n = 2
        WHERE a.y BETWEEN year(current_date) AND year(current_date) + 2""").fetchall()
    out = []
    for src, ind, ent, y, now, before, v1, v2 in rows:
        if ent not in keys and ent != "world":
            continue
        m = panel.meta.get(ind)
        if not m or now is None or before is None:
            continue
        growth = m["unit"] in ("percent",) or m["unit"].startswith("%")
        diff = now - before
        if (growth and abs(diff) < 1) or (not growth and (not before or abs(diff / before) < 0.1)):
            continue
        out.append(_find("forecast", f"forecast:{src}:{ind}:{ent}:{y}:{v1}", panel, ind, [ent], names,
                         f"{src.upper().replace('_', ' ')} {'raises' if diff > 0 else 'cuts'} its {y} forecast of "
                         f"{names.get(ent, ent)}'s {_lc(m['name'])}",
                         0.5 + 0.3 * min(1, abs(diff) / (3 if growth else abs(before) * 0.3 or 1)), [y], diff > 0, better,
                         detail=f"From {num(before, m['unit'], m['decimals'])} ({v2}) to {num(now, m['unit'], m['decimals'])} ({v1}).",
                         series=[], mark=[y], value=float(now), extra_tags=[src]))
    return out


def revised(con, names, better, panel: Panel, keys: list[str], share: float = 0.05) -> list[dict]:
    """Past figures (estimates) for key countries revised by more than `share` in a source's newest release."""
    rows = con.execute("""
        WITH v AS (SELECT source_id, vintage, row_number() OVER (PARTITION BY source_id ORDER BY retrieved_at DESC) AS n
                   FROM vintages),
        o AS (SELECT o.source_id, o.indicator_id, o.entity_id, year(o.period_start) AS y, o.value, v.n, o.vintage
              FROM observations o JOIN v ON v.source_id = o.source_id AND v.vintage = o.vintage
              JOIN disc_ids k ON k.indicator_id = o.indicator_id
              WHERE v.n <= 2 AND o.status = 'E' AND o.variant = 'central' AND o.breakdown = '' AND o.freq = 'A')
        SELECT a.source_id, a.indicator_id, a.entity_id, max(a.y), arg_max(a.value, abs(a.value - b.value) / nullif(abs(b.value), 0)),
               arg_max(b.value, abs(a.value - b.value) / nullif(abs(b.value), 0)), arg_max(a.y, abs(a.value - b.value) / nullif(abs(b.value), 0)),
               max(abs(a.value - b.value) / nullif(abs(b.value), 0)), any_value(a.vintage)
        FROM o a JOIN o b ON a.source_id = b.source_id AND a.indicator_id = b.indicator_id AND a.entity_id = b.entity_id
            AND a.y = b.y AND a.n = 1 AND b.n = 2
        GROUP BY 1, 2, 3""").fetchall()
    out = []
    for src, ind, ent, _last, now, before, y, rel, vin in rows:
        if ent not in keys or rel is None or rel < share or ind not in panel.meta:
            continue
        m = panel.meta[ind]
        out.append(_find("revised", f"revised:{src}:{ind}:{ent}:{vin}", panel, ind, [ent], names,
                         f"New figures: {src.upper().replace('_', ' ')} revised {names.get(ent, ent)}'s {_lc(m['name'])} for {y}",
                         0.35 + 0.4 * min(1, rel / 0.3), [y], now > before, better,
                         detail=f"{y}: from {num(before, m['unit'], m['decimals'])} to {num(now, m['unit'], m['decimals'])} ({100 * (now / before - 1):+.0f}%) in the release of {vin}.",
                         series=[], mark=[y], value=float(now), extra_tags=[src]))
    return out


def from_scan(home: Path, names, better, panel: Panel, limit: int = 15) -> list[dict]:
    """The strongest pairs and event links from the latest relationship scan."""
    from worldmodel_contract import relations as rel
    meta = rel.latest(home)
    out: list[dict] = []
    if not meta:
        return out
    import duckdb
    con = duckdb.connect()
    try:
        if Path(meta["pairs_path"]).exists():
            cols = [c[0] for c in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{Path(meta['pairs_path']).as_posix()}')").fetchall()]
            order = "abs(r) DESC" if "r" in cols else "1"
            where = "WHERE coalesce(built_from, '') = ''" if "built_from" in cols else ""
            for r in con.execute(f"SELECT * FROM read_parquet('{Path(meta['pairs_path']).as_posix()}') {where} ORDER BY {order} LIMIT {limit}").fetchall():
                d = dict(zip(cols, r))
                x, y = d.get("x") or d.get("x_id"), d.get("y") or d.get("y_id")
                if not x or not y:
                    continue
                xn, yn = d.get("x_name") or x, d.get("y_name") or y
                rr = d.get("r")
                ind = y if y in panel.meta else x
                if ind not in panel.meta:
                    continue
                out.append({**_find("together", f"together:{x}:{y}:{meta['build_id'][:8]}", panel, ind, [], names,
                                 f"{xn} and {yn} move together", 0.35 + 0.4 * min(1, abs(rr or 0) * 2),
                                 [int(d.get("year_from") or FIRST_YEAR), int(d.get("year_to") or date.today().year)], None, better,
                                 detail=f"Across {d.get('countries') or 'many'} countries their yearly changes go together (r = {rr:.2f})." if rr is not None else "",
                                 extra_tags=[xn]), "pair": [x, y]})
        if Path(meta["events_path"]).exists():
            cols = [c[0] for c in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{Path(meta['events_path']).as_posix()}')").fetchall()]
            sig = "WHERE q < 0.05" if "q" in cols else ""
            order = "abs(effect) DESC" if "effect" in cols else "1"
            for r in con.execute(f"SELECT * FROM read_parquet('{Path(meta['events_path']).as_posix()}') {sig} ORDER BY {order} LIMIT {limit}").fetchall():
                d = dict(zip(cols, r))
                ind, kind = d.get("indicator_id"), d.get("kind") or d.get("event_kind")
                if not ind or ind not in panel.meta or not kind:
                    continue
                m = panel.meta[ind]
                eff = d.get("effect")
                out.append(_find("after", f"after:{kind}:{ind}:{meta['build_id'][:8]}", panel, ind, [], names,
                                 f"After a {str(kind).replace('_', ' ')}, {_lc(m['name'])} "
                                 f"{'rises' if (eff or 0) > 0 else 'falls'}", 0.4 + 0.3 * min(1, abs(eff or 0)),
                                 [FIRST_YEAR, date.today().year], (eff or 0) > 0, better,
                                 detail=f"Compared with countries in the same income group with no {str(kind).replace('_', ' ')} in those years"
                                        f"{f' ({d.get(chr(110))} events)' if d.get('n') else ''}.", extra_tags=[str(kind)]))
    except Exception:  # noqa: BLE001 - an older scan's columns: skip these finds
        pass
    finally:
        con.close()
    return out


# ----------------------------------------------------------------------------- run, save, load
CHECKS = ("record", "mover", "turning", "overtake", "outlier", "disagree", "forecast", "together", "after", "revised", "opposite")


def compute(con, home: Path | None = None, settings: dict | None = None, today: date | None = None) -> list[dict]:
    """Every find on the warehouse, best first, cut to the number kept (Settings: discover_keep)."""
    s = {**local.SETTINGS, **(settings or {})}
    checks = [c for c in (s.get("discover_checks") or ",".join(CHECKS)).split(",") if c in CHECKS]
    keys = [k for k in (s.get("discover_key_countries") or "").split(",") if k]
    better = s.get("discover_better") or {}
    last_year = (today or date.today()).year
    ids = chosen(con)
    panel = load(con, ids, last_year)
    names = {r[0]: r[1] for r in con.execute("SELECT entity_id, short_name FROM entities").fetchall()}
    members: dict[str, list[str]] = {}
    for g, mbr in con.execute("SELECT group_id, member_id FROM memberships WHERE valid_to IS NULL").fetchall():
        if g in GROUPS:
            members.setdefault(g, []).append(mbr)
    found: list[dict] = []
    if "record" in checks:
        found += records(panel, names, better)
    if "mover" in checks:
        found += movers(panel, names, better)
    if "turning" in checks:
        found += turning(panel, names, better)
    if "overtake" in checks:
        found += overtakes(panel, names, better, keys)
    if "outlier" in checks:
        found += outliers(panel, names, better, members)
    if "disagree" in checks:
        found += disagree(con, names, better, panel, keys)
    if "forecast" in checks:
        found += forecasts(con, names, better, panel, keys)
    if "revised" in checks:
        found += revised(con, names, better, panel, keys)
    if "opposite" in checks:
        found += opposite(panel, names, better, keys, _peers(con, keys))
    if home is not None and ("together" in checks or "after" in checks):
        found += [f for f in from_scan(Path(home), names, better, panel) if f["kind"] in checks]
    # One find per indicator and country per kind (a record and a mover on the same point both stay).
    seen, out = set(), []
    for f in sorted(found, key=lambda f: -(f["score"] + (0.15 if set(f["entities"]) & set(keys) else 0))):
        k = (f["kind"], f["indicator_id"], tuple(f["entities"]))
        if k not in seen:
            seen.add(k)
            out.append(f)
    if s.get("discover_merge", True):
        out = merge_alike(out, panel, names, keys, _world(con, out))
    return out[: int(s.get("discover_keep", 500))]


def _peers(con, keys: list[str]) -> dict[str, list[str]]:
    """Each key country's neighbours for comparison: the countries in its subregion."""
    if not keys:
        return {}
    got = con.execute(f"""SELECT k.member_id, o.member_id FROM memberships k JOIN entities g ON g.entity_id = k.group_id AND g.type = 'subregion'
        JOIN memberships o ON o.group_id = k.group_id AND o.valid_to IS NULL JOIN entities e ON e.entity_id = o.member_id AND e.type = 'country'
        WHERE k.valid_to IS NULL AND k.member_id IN ({', '.join('?' * len(keys))})""", keys).fetchall()
    out: dict[str, list[str]] = {}
    for k, o in got:
        if o != k:
            out.setdefault(k, []).append(o)
    return out


MERGE_KINDS = ("record", "mover", "turning")
MERGE_LINES = 4  # countries drawn as lines on a merged find, against the world


def _shape(f: dict) -> str:
    if f["kind"] == "record":
        return f["key"].rsplit(":", 1)[-1]  # hi or lo
    if f["kind"] == "turning":
        return "reversed" if " reversed " in f["headline"] else "levelled"
    return ""


def _world(con, finds: list[dict]) -> dict[str, list[list]]:
    """The world's figures for the indicators that may be merged (from the warehouse's aggregates)."""
    ids = sorted({f["indicator_id"] for f in finds if f["kind"] in MERGE_KINDS and f.get("indicator_id")})
    if not ids:
        return {}
    try:
        got = con.execute(f"""SELECT indicator_id, year(period_start), value FROM series WHERE entity_id = 'world' AND breakdown = ''
            AND variant = 'central' AND freq = 'A' AND indicator_id IN ({', '.join('?' * len(ids))}) AND value IS NOT NULL ORDER BY 1, 2""", ids).fetchall()
    except Exception:  # noqa: BLE001 - a warehouse without world figures: the middle country stands in
        got = []
    out: dict[str, list[list]] = {}
    for ind, y, v in got:
        out.setdefault(ind, []).append([int(y), float(v)])
    return out


def merge_alike(finds: list[dict], p: Panel, names: dict[str, str], keys: list[str], world: dict[str, list[list]] | None = None) -> list[dict]:
    """The same thing found for several countries (unemployment at a record high in five
    countries in the same year) becomes one find: the countries named, the first few (key
    countries first, then the most unusual) drawn as lines against the world (or the middle country when there is no
    world figure). Finds for one country stay as they are."""
    world = world or {}
    groups: dict[tuple, list[dict]] = {}
    for f in finds:
        if f["kind"] in MERGE_KINDS and len(f["entities"]) == 1 and f.get("indicator_id"):
            groups.setdefault((f["kind"], f["indicator_id"], f.get("rising"), f["years"][-1], _shape(f)), []).append(f)
    done: set[str] = set()
    out = []
    for f in finds:
        if f["key"] in done:
            continue
        g = groups.get((f["kind"], f.get("indicator_id"), f.get("rising"), f["years"][-1], _shape(f))) if f["kind"] in MERGE_KINDS else None
        if not g or len(g) < 2 or len(f["entities"]) != 1:
            out.append(f)
            continue
        done.update(x["key"] for x in g)
        order = sorted(g, key=lambda x: (x["entities"][0] not in keys, -x["score"]))
        ents = [x["entities"][0] for x in order]
        ind, y = f["indicator_id"], f["years"][-1]
        name = f.get("indicator_name") or ind
        shape = _shape(f)
        verb = {("record", "hi"): "at its highest in years", ("record", "lo"): "at its lowest in years",
                ("mover", True): "jumped", ("mover", False): "fell sharply",
                ("turning", "reversed"): "changed direction", ("turning", "levelled"): "levelled off"}
        what = verb.get((f["kind"], shape)) or verb.get((f["kind"], f.get("rising"))) or KINDS[f["kind"]].lower()
        who = [names.get(e, e) for e in ents]
        listed = ", ".join(who[:2]) + (f" and {len(who) - 2} more" if len(who) > 2 else "") if len(who) > 2 else " and ".join(who)
        series = [{"entity_id": x["entities"][0], "name": names.get(x["entities"][0], x["entities"][0]),
                   "points": (x["chart"]["series"][0]["points"] if x["chart"]["series"] else [])} for x in order[:MERGE_LINES]]
        first = min((pt[0] for s_ in series for pt in s_["points"]), default=y - 40)
        ref = [pt for pt in world.get(ind, []) if pt[0] >= first]
        if ref:
            series.append({"entity_id": "world", "name": "World", "points": ref})
        elif ind in p.data:
            a = p.data[ind]
            mid = [[p.years[j], float(np.nanmedian(a[:, j]))] for j in range(len(p.years))
                   if p.years[j] >= first and np.isfinite(a[:, j]).sum() >= 10]
            if mid:
                series.append({"entity_id": "", "name": "Middle country", "points": mid})
        best = order[0]
        out.append({**best,
                    "key": f"alike:{f['kind']}:{ind}:{y}:{shape or f.get('rising')}",
                    "headline": f"{name} {what} in {len(ents)} countries in {y}: {listed}",
                    "detail": ("Most notable: " if len(order) > MERGE_LINES else "") + " ".join(
                        f"{names.get(x['entities'][0], x['entities'][0])}: {x['detail'] or x['headline'].split(': ', 1)[-1]}"
                        for x in order[:3]) + (f" And {len(order) - 3} more." if len(order) > 3 else ""),
                    "members": [{"entity_id": x["entities"][0], "name": names.get(x["entities"][0], x["entities"][0]),
                                 "detail": x["detail"] or x["headline"].split(": ", 1)[-1], "value": x.get("value")} for x in order],
                    "entities": ents, "years": [min(x["years"][0] for x in g), y],
                    "score": round(min(1.0, max(x["score"] for x in g) + 0.04 * min(4, len(g) - 1)), 3),
                    "tags": [*who[:5], name, KINDS[f["kind"]], *[t for t in best["tags"] if t not in who and t not in (name, KINDS[f["kind"]])]],
                    "chart": {"series": series, "mark": best["chart"]["mark"]}, "merged": len(g)})
    return out


def folder(home: Path) -> Path:
    return Path(home) / "warehouse" / "discover"


def save(home: Path, build_id: str, finds: list[dict]) -> Path:
    d = folder(home)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{build_id}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"build_id": build_id, "finds": finds}, default=str), encoding="utf-8")
    tmp.replace(p)
    for old in sorted(d.glob("*.json"))[:-5]:
        old.unlink(missing_ok=True)
    return p


def load_saved(home: Path, build_id: str | None = None, exact: bool = False) -> dict | None:
    """The finds saved for build_id (exact), else for it or the newest build."""
    d = folder(home)
    files = sorted(d.glob("*.json")) if d.is_dir() else []
    if build_id and (d / f"{build_id}.json").is_file():
        pick = d / f"{build_id}.json"
    else:
        pick = None if exact else (files[-1] if files else None)
    if not pick:
        return None
    try:
        return json.loads(pick.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ----------------------------------------------------------------------------- your ratings and tags
def _user_file() -> Path:
    return local.user_dir() / "discover.json"


def user_state() -> dict:
    """{ratings: {key: 1 | -1}, tags: {key: [..]}, tones: {key: tone}, never: [kind], first_seen: {key: date},
    last_visit: iso, kept: {key: {...find}}}"""
    try:
        d = json.loads(_user_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    for k, v in (("ratings", {}), ("tags", {}), ("tones", {}), ("never", []), ("first_seen", {}), ("kept", {})):
        d.setdefault(k, v)
    d.setdefault("last_visit", None)
    return d


def save_user_state(d: dict) -> None:
    p = _user_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, default=str), encoding="utf-8")
    tmp.replace(p)


def weights(finds_by_key: dict[str, dict], ratings: dict[str, int]) -> dict[str, float]:
    """How much each kind, category and tag rises or sinks from your ratings: +15% per Interesting,
    -15% per Not interesting, held between 0.3 and 2."""
    w: dict[str, float] = {}
    for key, r in ratings.items():
        f = finds_by_key.get(key)
        if not f:
            continue
        for t in [f"kind:{f['kind']}", f"cat:{f['category']}", *(f"tag:{x}" for x in f.get("tags", []))]:
            w[t] = w.get(t, 1.0) + 0.15 * (1 if r > 0 else -1)
    return {k: max(0.3, min(2.0, v)) for k, v in w.items()}


def ranked(finds: list[dict], state: dict, keys: list[str], boost: float, tune: bool) -> list[dict]:
    """Finds with your tags, tone changes and rating, scored for you: key countries boosted, your
    ratings applied (Settings: discover_tune), kinds you never want left out."""
    by = {f["key"]: f for f in finds}
    for k, f in state.get("kept", {}).items():
        by.setdefault(k, {**f, "stale": True})  # a find you marked Interesting stays after it stops being found
    w = weights(by, state["ratings"]) if tune else {}
    out = []
    for f in by.values():
        g = dict(f)
        g["rating"] = state["ratings"].get(f["key"], 0)
        g["tags"] = [*f.get("tags", []), *state["tags"].get(f["key"], [])]
        g["my_tags"] = state["tags"].get(f["key"], [])
        g["tone"] = state["tones"].get(f["key"], f["tone"])
        g["first_seen"] = state["first_seen"].get(f["key"])
        g["never"] = f["kind"] in state["never"]
        s = f["score"]
        if set(f.get("entities", [])) & set(keys):
            s *= boost
        if tune:
            for t in [f"kind:{f['kind']}", f"cat:{f['category']}", *(f"tag:{x}" for x in f.get("tags", []))]:
                s *= w.get(t, 1.0) ** (0.5 if t.startswith("tag:") else 1)
        g["rank_score"] = round(s, 4)
        out.append(g)
    out.sort(key=lambda f: -f["rank_score"])
    return out
