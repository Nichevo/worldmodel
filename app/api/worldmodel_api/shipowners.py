"""Who owns, runs and built a ship, from free sources, asked once per ship when its details are
opened and kept for 30 days in <home>/live/ships/owners.json.

- Global Fishing Watch's vessel identity API (needs a free GFW_API_TOKEN; non-commercial use):
  registered owners, flags, registry details and authorisations. Best for fishing boats and the
  carriers that serve them.
- Wikidata (no key): notable ships by IMO number, with builder, operator, owner, year and a picture,
  and Wikimedia Commons photos filed under the ship's "IMO nnnnnnn" category (free licences).
- Equasis has owners and managers for nearly every merchant ship but forbids automated reading,
  so it is only a link (search by IMO there after signing in).

Each part is a setting (Settings > Transport). A failed lookup is not kept, so it is tried again
next time.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

GFW_SEARCH = "https://gateway.api.globalfishingwatch.org/v3/vessels/search"
GFW_DATASET = "public-global-vessel-identity:latest"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
EQUASIS = "https://www.equasis.org/EquasisWeb/public/HomePage"
KEEP = 30 * 86400
UA = {"User-Agent": "worldmodel (personal research tool)"}
_lock = threading.Lock()


def gfw_token() -> str:
    return (os.environ.get("GFW_API_TOKEN") or "").strip()


class Owners:
    def __init__(self, folder: Path) -> None:
        self.file = folder / "owners.json"
        self.cache: dict[str, dict] | None = None

    def _load(self) -> dict[str, dict]:
        if self.cache is None:
            try:
                self.cache = json.loads(self.file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.cache = {}
        return self.cache

    def _save(self) -> None:
        now = time.time()
        data = {k: v for k, v in (self.cache or {}).items() if now - v.get("at", 0) < KEEP}
        self.cache = data
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        tmp.replace(self.file)

    def peek(self, key: str, part: str) -> dict | None:
        """A part already kept for a ship (fresh or not), without asking anyone."""
        with _lock:
            hit = self._load().get(f"{part}:{key}")
        return hit.get("value") if hit else None

    def get(self, key: str, part: str, fetch) -> dict | None:
        """A part (gfw, wikidata) for a ship, from the file when fresh, else fetched and kept."""
        with _lock:
            hit = self._load().get(f"{part}:{key}")
            if hit and time.time() - hit.get("at", 0) < KEEP:
                return hit.get("value")
        try:
            value = fetch()
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
            log.info("ship owners %s for %s: %s", part, key, exc)
            return {"error": f"did not answer ({exc.__class__.__name__})"}
        with _lock:
            self._load()[f"{part}:{key}"] = {"at": int(time.time()), "value": value}
            try:
                self._save()
            except OSError as exc:
                log.warning("ship owners: could not save: %s", exc)
        return value


# ----------------------------------------------------------------------------- Global Fishing Watch
def _first(xs, *keys):
    for x in xs or []:
        for k in keys:
            if x.get(k) not in (None, "", []):
                return x[k]
    return None


def _src(v) -> str | None:
    return ", ".join(map(str, v)) if isinstance(v, list) else v


def _day(v) -> str | None:
    return str(v)[:10] if v else None


def parse_gfw(body: dict, imo: str | None, mmsi: str) -> dict | None:
    """The best matching entry of a vessel search: same IMO, else same MMSI, else none."""
    entries = body.get("entries") or []

    def ids(e):
        rows = (e.get("registryInfo") or []) + (e.get("selfReportedInfo") or [])
        return {str(r.get("imo") or "") for r in rows}, {str(r.get("ssvid") or "") for r in rows}

    pick = next((e for e in entries if imo and imo in ids(e)[0]), None) or next((e for e in entries if mmsi in ids(e)[1]), None)
    if not pick:
        return None
    reg = pick.get("registryInfo") or []
    extra = [x for r in reg for x in (r.get("extraFields") or [])]
    owners = []
    for o in pick.get("registryOwners") or []:
        if o.get("name"):
            owners.append({"name": o["name"], "flag": o.get("flag"), "from": _day(o.get("dateFrom")), "to": _day(o.get("dateTo")),
                           "source": _src(o.get("sourceCode"))})
    owners.sort(key=lambda o: o.get("to") or "9999", reverse=True)
    flags = []
    for r in sorted(pick.get("selfReportedInfo") or [], key=lambda r: r.get("transmissionDateFrom") or ""):
        f = r.get("flag")
        if f and (not flags or flags[-1]["flag"] != f):
            flags.append({"flag": f, "from": _day(r.get("transmissionDateFrom")), "to": _day(r.get("transmissionDateTo"))})
    auths = []
    for a in pick.get("registryPublicAuthorizations") or []:
        src = a.get("sourceCode")
        auths.append({"by": _src(src), "from": _day(a.get("dateFrom")), "to": _day(a.get("dateTo"))})
    gear = _first(pick.get("combinedSourcesInfo"), "geartypes")
    if isinstance(gear, list):
        gear = ", ".join(str(g.get("name") if isinstance(g, dict) else g) for g in gear)
    return {
        "name": _first(reg, "shipname") or _first(pick.get("selfReportedInfo"), "shipname"),
        "flag": _first(reg, "flag"), "imo": _first(reg, "imo"), "callsign": _first(reg, "callsign"),
        "length_m": _first(reg, "lengthM"), "tonnage_gt": _first(reg, "tonnageGt"),
        "built": _first(extra, "builtYear"), "gear": gear or None,
        "owners": owners[:10], "flags": flags[-10:], "authorisations": auths[:10],
        "link": f"https://globalfishingwatch.org/map/vessel/{pick['selfReportedInfo'][0]['id']}"
        if (pick.get("selfReportedInfo") or [{}])[0].get("id") else None,
    }


def gfw(imo: str | None, mmsi: str, token: str) -> dict | None:
    params = [("query", imo or mmsi), ("datasets[0]", GFW_DATASET), ("includes[0]", "OWNERSHIP"),
              ("includes[1]", "AUTHORIZATIONS"), ("limit", "5")]
    with httpx.Client(timeout=20, headers={**UA, "Authorization": f"Bearer {token}"}) as client:
        r = client.get(GFW_SEARCH, params=params)
        if r.status_code in (401, 403):
            return {"error": "Global Fishing Watch refused the token (check GFW_API_TOKEN in Settings > Keys)."}
        if r.status_code == 429:
            raise httpx.HTTPError("rate limited")
        r.raise_for_status()
        return parse_gfw(r.json(), imo, mmsi) or {"none": True}


# ----------------------------------------------------------------------------- Wikidata
def wikidata_query(imo: str) -> str:
    return f"""SELECT ?ship ?shipLabel ?builderLabel ?operatorLabel ?ownerLabel ?classLabel ?launched ?entered ?image ?article ?teu ?length ?beam ?draft WHERE {{
  ?ship wdt:P458 "{imo}" .
  OPTIONAL {{ ?ship wdt:P176 ?builder }} OPTIONAL {{ ?ship wdt:P137 ?operator }} OPTIONAL {{ ?ship wdt:P127 ?owner }}
  OPTIONAL {{ ?ship wdt:P289 ?class }} OPTIONAL {{ ?ship wdt:P619 ?launched }} OPTIONAL {{ ?ship wdt:P729 ?entered }}
  OPTIONAL {{ ?ship wdt:P18 ?image }}
  OPTIONAL {{ ?ship p:P1083 ?cap . ?cap ps:P1083 ?teu ; pq:P518 wd:Q488021 }}
  OPTIONAL {{ ?ship wdt:P2043 ?length }} OPTIONAL {{ ?ship wdt:P2261 ?beam }} OPTIONAL {{ ?ship wdt:P2262 ?draft }}
  OPTIONAL {{ ?article schema:about ?ship ; schema:isPartOf <https://en.wikipedia.org/> }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
}} LIMIT 40"""


def parse_wikidata(body: dict) -> dict | None:
    rows = (body.get("results") or {}).get("bindings") or []
    if not rows:
        return None

    def vals(k):
        return list(dict.fromkeys(r[k]["value"] for r in rows if k in r))

    def year(k):
        v = vals(k)
        return v[0][:4] if v else None

    def num(k):  # 'maximum capacity' in TEU, length, beam, draught (metres as Wikidata usually gives them)
        for v in vals(k):
            try:
                x = float(v)
            except ValueError:
                continue
            if x > 0:
                return int(x) if k == "teu" else round(x, 2)
        return None

    return {"name": (vals("shipLabel") or [None])[0], "builder": vals("builderLabel"), "operator": vals("operatorLabel"),
            "owner": vals("ownerLabel"), "class": (vals("classLabel") or [None])[0], "launched": year("launched"),
            "entered_service": year("entered"), "image": (vals("image") or [None])[0],
            "wikipedia": (vals("article") or [None])[0], "link": (vals("ship") or [None])[0],
            "teu": num("teu"), "length_m": num("length"), "beam_m": num("beam"), "draught_m": num("draft")}


def wikidata(imo: str) -> dict | None:
    with httpx.Client(timeout=20, headers={**UA, "Accept": "application/sparql-results+json"}) as client:
        r = client.get(WIKIDATA_SPARQL, params={"query": wikidata_query(imo), "format": "json"})
        r.raise_for_status()
        return parse_wikidata(r.json()) or {"none": True}


# ----------------------------------------------------------------------------- Wikimedia Commons photos
COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def parse_commons(body: dict) -> list[dict]:
    """Photos in a Commons 'IMO nnnnnnn' category: thumbnail, page, author and licence."""
    import re as _re

    out = []
    for page in sorted(((body.get("query") or {}).get("pages") or {}).values(), key=lambda p: p.get("index", 0)):
        info = (page.get("imageinfo") or [{}])[0]
        if not info.get("thumburl"):
            continue
        meta = info.get("extmetadata") or {}

        def text(k):
            return _re.sub(r"<[^>]+>", "", str((meta.get(k) or {}).get("value") or "")).strip() or None

        out.append({"thumb": info["thumburl"], "page": info.get("descriptionurl"), "title": page.get("title", "").removeprefix("File:"),
                    "author": text("Artist"), "licence": text("LicenseShortName"), "date": (text("DateTimeOriginal") or "")[:10] or None})
    return out


def commons(imo: str, limit: int = 6) -> list[dict]:
    params = {"action": "query", "format": "json", "generator": "categorymembers", "gcmtitle": f"Category:IMO {imo}",
              "gcmtype": "file", "gcmlimit": str(limit), "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": "400",
              "iiextmetadatafilter": "Artist|LicenseShortName|DateTimeOriginal"}
    with httpx.Client(timeout=20, headers=UA) as client:
        r = client.get(COMMONS_API, params=params)
        r.raise_for_status()
        return parse_commons(r.json())


# ----------------------------------------------------------------------------- together
def owner(store: Owners, mmsi: int, detail: dict, settings: dict) -> dict:
    imo = str(detail.get("imo") or "").strip() or None
    if imo and not imo.isdigit():
        imo = None
    out: dict = {"mmsi": mmsi, "imo": imo, "gfw": None, "wikidata": None, "photos": None, "equasis": None, "notes": []}
    if settings.get("ship_owners_gfw", True):
        token = gfw_token()
        if not token:
            out["notes"].append("Global Fishing Watch needs a free GFW_API_TOKEN (Settings > Keys).")
        else:
            out["gfw"] = store.get(imo or str(mmsi), "gfw", lambda: gfw(imo, str(mmsi), token))
    if settings.get("ship_owners_wikidata", True):
        if imo:
            out["wikidata"] = store.get(imo, "wikidata", lambda: wikidata(imo))
            photos = store.get(imo, "commons", lambda: commons(imo))
            out["photos"] = photos if isinstance(photos, list) else None
        else:
            out["notes"].append("Wikidata is searched by IMO number, which this ship has not sent.")
    if settings.get("ship_owners_equasis", True):
        out["equasis"] = {"href": EQUASIS, "imo": imo,
                          "how": f"Sign in to Equasis (free) and search IMO {imo}." if imo else "Sign in to Equasis (free) and search the ship's name."}
    return out
