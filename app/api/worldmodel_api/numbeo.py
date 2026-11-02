"""Numbeo prices for one city or country, fetched only when asked (a button on the
city or country page) and within the daily limit in Settings (numbeo_daily).

One page per fetch, in US dollars:
    https://www.numbeo.com/cost-of-living/city_result.jsp?country=<country>&city=<city>&displayCurrency=USD
    https://www.numbeo.com/cost-of-living/country_result.jsp?country=<country>&displayCurrency=USD
The page's price table (meal out, rent, salary, transport, groceries...) and its
summary of monthly costs are kept in media/numbeo/<kind>/<id>.json. Numbeo's figures
are crowd-sourced; the yearly city indices come from the hand-saved rankings pages
(source numbeo).
"""

from __future__ import annotations

import html
import json
import logging
import re
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx

from worldmodel_contract import local

log = logging.getLogger(__name__)

BASE = "https://www.numbeo.com/cost-of-living/"
USER_AGENT = "worldmodel/0.1 (personal local tool; one page when asked) httpx"
_lock = threading.Lock()


def root() -> Path:
    return local.home() / "media" / "numbeo"


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _write(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def budget() -> dict:
    limit = int(local.load_settings()["numbeo_daily"])
    b = _read(root() / "budget.json") or {}
    used = b.get("used", 0) if b.get("day") == date.today().isoformat() else 0
    return {"day": date.today().isoformat(), "used": used, "limit": limit}


def _spend() -> None:
    b = budget()
    _write(root() / "budget.json", {"day": b["day"], "used": b["used"] + 1})


US_STATES = dict(zip(
    "Alabama Alaska Arizona Arkansas California Colorado Connecticut Delaware Florida Georgia Hawaii Idaho Illinois "
    "Indiana Iowa Kansas Kentucky Louisiana Maine Maryland Massachusetts Michigan Minnesota Mississippi Missouri "
    "Montana Nebraska Nevada New_Hampshire New_Jersey New_Mexico New_York North_Carolina North_Dakota Ohio Oklahoma "
    "Oregon Pennsylvania Rhode_Island South_Carolina South_Dakota Tennessee Texas Utah Vermont Virginia Washington "
    "West_Virginia Wisconsin Wyoming District_of_Columbia".replace("_", "~").split(),
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI "
    "SC SD TN TX UT VT VA WA WV WI WY DC".split()))
US_STATES = {k.replace("~", " "): v for k, v in US_STATES.items()}


def city_name(name: str, country_id: str, admin1: str | None) -> str:
    """Numbeo's usual name for a city: US cities carry their state ("Portland, OR")."""
    if country_id == "USA" and admin1 in US_STATES:
        return f"{name}, {US_STATES[admin1]}"
    return name


def page_url(country: str, city: str | None = None) -> str:
    if city:
        return BASE + "city_result.jsp?" + urlencode({"country": country, "city": city, "displayCurrency": "USD"})
    return BASE + "country_result.jsp?" + urlencode({"country": country, "displayCurrency": "USD"})


def cached(kind: str, item_id: str) -> dict | None:
    if kind not in ("cities", "countries") or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", item_id):
        return None
    return _read(root() / kind / f"{item_id}.json")


def fetch(kind: str, item_id: str, country: str, city: str | None, client: httpx.Client | None = None) -> dict:
    """Fetch and store one page's prices. Raises ValueError with a message for the page when it cannot."""
    with _lock:
        b = budget()
        if b["limit"] <= 0:
            raise ValueError("Numbeo fetches are off (daily limit 0 in Settings).")
        if b["used"] >= b["limit"]:
            raise ValueError(f"Today's {b['limit']} Numbeo pages are used up; try again tomorrow or raise the limit in Settings.")
        _spend()
        url = page_url(country, city)
        own = client is None
        client = client or httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        try:
            r = client.get(url)
        except httpx.HTTPError as exc:
            raise ValueError(f"Could not reach Numbeo ({exc}).") from exc
        finally:
            if own:
                client.close()
        if r.status_code != 200:
            raise ValueError(f"Numbeo answered HTTP {r.status_code}; open the page in your browser instead.")
        data = parse(r.text)
        if not data["items"]:
            raise ValueError("Numbeo's page had no price table (the city may be missing or named differently there).")
        out = {"kind": kind, "id": item_id, "country": country, "city": city, "url": url, "currency": "USD",
               "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **data}
        _write(root() / kind / f"{item_id}.json", out)
        return out


_TAG = re.compile(r"<[^>]+>")


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", s))).replace("\xa0", " ").strip()


def _number(s: str) -> float | None:
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", s.replace("\xa0", " "))
    return float(m.group(0).replace(",", "")) if m else None


def parse(page: str) -> dict:
    """Prices from a Numbeo cost of living page: [{section, item, value}] and the monthly cost summary."""
    items, section = [], ""
    for t in re.findall(r"<table[^>]*data_wide_table[^>]*>(.*?)</table>", page, re.S | re.I):
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S | re.I):
            th = re.search(r"<th[^>]*>(.*?)</th>", tr, re.S | re.I)
            if th and not re.search(r"<td", tr, re.I):
                section = _text(th.group(1)).split(" Edit")[0]
                continue
            tds = re.findall(r"<td([^>]*)>(.*?)</td>", tr, re.S | re.I)
            if len(tds) < 2:
                continue
            price = next((c for a, c in tds if "priceValue" in a), tds[1][1])
            v = _number(_text(price))
            name = _text(tds[0][1])
            if name and v is not None:
                items.append({"section": section, "item": name, "value": v})
    summary = {}
    if m := re.search(r"single person estimated monthly costs are\s*(?:<[^>]+>\s*)*([\d,.]+)", page, re.I):
        summary["single_without_rent"] = _number(m.group(1))
    if m := re.search(r"family of four estimated monthly costs are\s*(?:<[^>]+>\s*)*([\d,.]+)", page, re.I):
        summary["family_without_rent"] = _number(m.group(1))
    return {"items": items, "summary": summary}
