"""The data release calendar: which figures come out soon for New Zealand, Australia, the
UK and the US, and, once out, how they compared with the app's own nowcast.

Dates come from release_calendar.yaml (typed in from the official schedules: BLS, BEA,
the Fed, the RBNZ, the Bank of England, the RBA; Stats NZ's are estimated from its usual
timing) and, with Settings > Outlook > calendar_live on, from two calendars read once a day:

* the ONS release calendar API (api.beta.ons.gov.uk/v1/search/releases), UK headline releases;
* the ABS future releases page (abs.gov.au/release-calendar/future-releases/<YYYYMM>), Australia's.
"""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

import httpx

from worldmodel_contract import catalogue, local

log = logging.getLogger(__name__)

ONS = "https://api.beta.ons.gov.uk/v1/search/releases"
ABS = "https://www.abs.gov.au/release-calendar/future-releases/{ym}"
USER_AGENT = "worldmodel/0.1 (personal local tool; https://github.com/Nichevo/worldmodel) httpx"
NZ_TZ = ZoneInfo("Pacific/Auckland")

# Headline releases kept from the live calendars: (words in the title, kind, indicator).
ONS_KEEP = ((("gdp first quarterly estimate", "gdp quarterly estimate", "gdp monthly estimate"), "gdp", "gdp_growth_q"),
            (("consumer price inflation",), "prices", "inflation"),
            (("labour market overview",), "jobs", "unemployment"),
            (("retail sales",), "spending", ""),
            (("public sector finances",), "government", ""),
            (("uk trade",), "trade", ""))
ABS_KEEP = ((("national accounts",), "gdp", "gdp_growth_q"),
            (("consumer price index",), "prices", "inflation"),
            (("labour force, australia",), "jobs", "unemployment"),
            (("wage price index",), "jobs", ""),
            (("monthly household spending",), "spending", ""),
            (("international trade in goods",), "trade", ""),
            (("building approvals",), "building", ""))
KIND_NAMES = {"gdp": "GDP", "prices": "Prices", "jobs": "Jobs", "rates": "Interest rates", "spending": "Spending",
              "government": "Government", "trade": "Trade", "building": "Building"}

_mem: dict = {}


def _keep(title: str, rules) -> tuple[str, str] | None:
    t = title.lower()
    for words, kind, ind in rules:
        if any(w in t for w in words):
            return kind, ind
    return None


def ons_items(data: dict) -> list[dict]:
    out = []
    for r in data.get("releases") or []:
        d = r.get("description") or {}
        title = (d.get("title") or "").strip()
        k = _keep(title, ONS_KEEP)
        if not k or d.get("cancelled"):
            continue
        when = str(d.get("release_date") or "")
        try:
            at = datetime.fromisoformat(when.replace("Z", "+00:00"))
        except ValueError:
            continue
        local_at = at.astimezone(ZoneInfo("Europe/London"))
        out.append({"country": "GBR", "title": title, "date": local_at.date().isoformat(), "time": local_at.strftime("%H:%M"),
                    "tz": "Europe/London", "kind": k[0], "indicator": k[1], "period": "",
                    "url": "https://www.ons.gov.uk" + (r.get("uri") or "/releasecalendar"),
                    "estimated": bool(d.get("provisional_date")) and not d.get("finalised"), "from": "ONS calendar"})
    return out


ABS_WHEN = re.compile(r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\d{1,2})\s+([A-Z][a-z]+)\s+(\d{4})\s+(\d{1,2}):(\d{2})\s*([ap]m)", re.I)
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]


def abs_items(page: str) -> list[dict]:
    """Releases from an ABS future-releases page: a date line, then the title, then the reference period."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</(p|div|li|h\d|a|span|time|td|tr)>", "\n", text, flags=re.I)
    lines = [html.unescape(re.sub(r"<[^>]+>", " ", ln)).strip() for ln in text.split("\n")]
    lines = [re.sub(r"\s+", " ", ln) for ln in lines if ln.strip()]
    out = []
    for i, ln in enumerate(lines):
        m = ABS_WHEN.search(ln)
        if not m:
            continue
        rest = [x for x in lines[i + 1:i + 6] if x.lower() not in ("updated information", "view current release")]
        if not rest:
            continue
        title = rest[0]
        k = _keep(title, ABS_KEEP)
        if not k:
            continue
        period = next((x.split(":", 1)[-1].strip() for x in rest[1:4] if x.lower().startswith("reference period")), "")
        day, mon, yr, hh, mm, ap = m.groups()
        h = int(hh) % 12 + (12 if ap.lower() == "pm" else 0)
        try:
            d = date(int(yr), MONTHS.index(mon.lower()) + 1, int(day))
        except ValueError:
            continue
        out.append({"country": "AUS", "title": title, "date": d.isoformat(), "time": f"{h:02d}:{mm}", "tz": "Australia/Sydney",
                    "kind": k[0], "indicator": k[1], "period": period, "url": "https://www.abs.gov.au/release-calendar/future-releases",
                    "estimated": False, "from": "ABS calendar"})
    return out


def _get(url: str, params: dict | None = None) -> str:
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        return r.text


def _cache_path():
    return local.home() / "outlook" / "calendar_live.json"


def live(enabled: bool, today: date, fetch: Callable[..., str] = _get) -> tuple[list[dict], list[str]]:
    """The ONS and ABS releases, read at most once a day (kept on disk); notes say what failed."""
    if not enabled:
        return [], ["Live calendars are off in Settings; the UK and Australia show central bank dates only."]
    key = today.isoformat()
    if _mem.get("day") == key:
        return _mem["items"], _mem["notes"]
    try:
        kept = json.loads(_cache_path().read_text(encoding="utf-8"))
        if kept.get("day") == key:
            _mem.update(kept)
            return kept["items"], kept["notes"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    items, notes = [], []
    try:
        data = json.loads(fetch(ONS, {"release-type": "type-upcoming", "limit": 500, "sort": "release_date_asc",
                                      "fromDate": key, "toDate": (today + timedelta(days=60)).isoformat()}))
        items += ons_items(data)
    except (httpx.HTTPError, OSError, ValueError) as exc:
        notes.append(f"The ONS calendar could not be read ({exc}).")
    for ym in {today.strftime("%Y%m"), (today.replace(day=1) + timedelta(days=32)).strftime("%Y%m")}:
        try:
            items += abs_items(fetch(ABS.format(ym=ym)))
        except (httpx.HTTPError, OSError, ValueError) as exc:
            notes.append(f"The ABS calendar could not be read ({exc}).")
            break
    got = {"day": key, "items": items, "notes": notes}
    if not notes:  # failures are tried again next time
        _mem.update(got)
        try:
            _cache_path().parent.mkdir(parents=True, exist_ok=True)
            _cache_path().write_text(json.dumps(got), encoding="utf-8")
        except OSError:
            pass
    return items, notes


def _quarter_of(period: str) -> str | None:
    m = re.search(r"(\d{4}) Q([1-4])", period or "")
    return f"{m.group(1)} Q{m.group(2)}" if m else None


def calendar(enabled: bool, countries: list[str], days_back: int = 7, days_ahead: int = 42, today: date | None = None,
             nowcasts: dict | None = None, fetch: Callable[..., str] = _get) -> dict:
    """Releases from days_back ago to days_ahead on, soonest first, each with its time in New Zealand
    and, for GDP, the app's nowcast for that quarter."""
    today = today or datetime.now(NZ_TZ).date()
    lo, hi = today - timedelta(days=days_back), today + timedelta(days=days_ahead)
    typed = [{**r, "from": "official schedule" if not r.get("estimated") else "estimated from usual timing"}
             for r in catalogue.release_calendar()]
    extra, notes = live(enabled, today, fetch)
    seen = {(r["country"], r["date"], r["title"]) for r in typed}
    items = typed + [r for r in extra if (r["country"], r["date"], r["title"]) not in seen]
    nowcasts = nowcasts or {}
    out = []
    for r in items:
        if r["country"] not in countries:
            continue
        try:
            d = date.fromisoformat(str(r["date"]))
            hh, mm = (int(x) for x in str(r.get("time") or "00:00").split(":"))
            at = datetime(d.year, d.month, d.day, hh, mm, tzinfo=ZoneInfo(r.get("tz") or "UTC"))
        except (ValueError, KeyError):
            continue
        if not lo <= d <= hi:
            continue
        nz = at.astimezone(NZ_TZ)
        item = {**r, "date": d.isoformat(), "nz_time": nz.strftime("%a %d %b %H:%M"), "nz_date": nz.date().isoformat(),
                "past": nz.date() < today, "kind_name": KIND_NAMES.get(r.get("kind", ""), r.get("kind", "").title())}
        q = _quarter_of(r.get("period", ""))
        if r.get("kind") == "gdp" and q and q in nowcasts.get(r["country"], {}):
            item["expected"] = {"value": nowcasts[r["country"]][q]["estimate"], "what": "the app's nowcast, % on the quarter"}
        out.append(item)
    out.sort(key=lambda x: (x["nz_date"], x["nz_time"]))
    return {"items": out, "notes": notes, "today": today.isoformat()}
