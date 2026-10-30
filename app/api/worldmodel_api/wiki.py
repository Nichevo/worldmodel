"""Wikipedia introductions and pictures for country pages, fetched on demand and kept locally.

Only Wikipedia's official API is used (https://en.wikipedia.org/w/api.php), and
only within the daily limits in Settings:

* A page is fetched when it is opened and has no copy yet, or its copy is more
  than REFRESH_DAYS old. Opened pages always come first.
* With "wikipedia_background" on, pages nobody has opened yet are fetched in the
  background, one every few minutes, most-opened countries first and then by
  population, using at most half of the day's limit so opened pages always have room.
* Each fetch is two API requests (the article introduction; the credits and
  thumbnail addresses of its pictures) plus up to three thumbnails (the main
  picture, the flag and the locator map), and counts once against the daily limit.
  Pictures are skipped once media/ reaches the pictures limit in Settings.

Article titles and the flag and map file names come from the Wikidata facts in
the warehouse (source wikidata); without them the entity's name is used as the
title and the article's own lead picture is kept.

    <home>/media/wikipedia/countries/<entity>.json   the introduction, links and picture credits
    <home>/media/wikipedia/img/<name>                 thumbnails
    <home>/media/wikipedia/budget.json                fetches made today
    <home>/media/wikipedia/failed.json                pages that could not be fetched, and when
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import httpx

from worldmodel_contract import local

log = logging.getLogger(__name__)

API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "worldmodel/0.1 (personal local tool; https://github.com/Nichevo/worldmodel) httpx"
REFRESH_DAYS = 30
THUMB_WIDTH = 640
TYPES = ("country", "historical_country", "continent", "bloc", "alliance", "world")
BACKGROUND_START, BACKGROUND_GAP, BACKGROUND_IDLE = 60, 180, 1800  # seconds
ROLES = (("photo", "Picture"), ("flag", "Flag"), ("map", "Locator map"))

_lock = threading.Lock()
_client: httpx.Client | None = None


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    return _client


def root() -> Path:
    return local.home() / "media" / "wikipedia"


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def now() -> datetime:
    return datetime.now(timezone.utc)


# ----------------------------------------------------------------------------- daily limit
def budget() -> dict:
    """Fetches made today and the limits: {"day", "used", "limit", "background_limit"}."""
    limit = int(local.load_settings()["wikipedia_countries_daily"])
    b = _read(root() / "budget.json") or {}
    used = b.get("countries", 0) if b.get("day") == date.today().isoformat() else 0
    return {"day": date.today().isoformat(), "used": used, "limit": limit, "background_limit": limit // 2}


def _spend() -> None:
    b = budget()
    _write(root() / "budget.json", {"day": b["day"], "countries": b["used"] + 1})


# ----------------------------------------------------------------------------- the cache
def cached(entity_id: str) -> dict | None:
    return _read(root() / "countries" / f"{entity_id}.json")


def is_stale(page: dict | None) -> bool:
    if not page:
        return True
    try:
        fetched = datetime.fromisoformat(page["fetched_at"])
    except (KeyError, ValueError):
        return True
    return now() - fetched > timedelta(days=REFRESH_DAYS)


def page(entity_id: str, target: dict, fetch: bool = True) -> dict:
    """The stored page for an entity, fetched first when it is missing or a month old
    and today's limit allows. target is from the warehouse (see main.wiki_target).
    status: ok, stale (kept; today's limit is used up or the fetch failed), none, off."""
    have = cached(entity_id)
    out = {"page": have, "status": "ok" if have and not is_stale(have) else "stale" if have else "none",
           "budget": budget(), "message": None}
    if not fetch or not is_stale(have):
        return out
    b = out["budget"]
    if b["limit"] <= 0:
        out["status"] = "off" if not have else out["status"]
        out["message"] = "Wikipedia fetches are off (daily limit 0 in Settings)."
        return out
    if b["used"] >= b["limit"]:
        out["message"] = f"Today's {b['limit']} Wikipedia fetches are used up; this page is fetched tomorrow."
        return out
    if failures().get(entity_id) == date.today().isoformat():
        out["message"] = "Wikipedia could not be reached for this page earlier today; it is tried again tomorrow."
        return out
    try:
        out["page"] = fetch_page(entity_id, target)
        out["status"] = "ok"
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        log.warning("wikipedia: %s failed: %s", entity_id, exc)
        _record_failure(entity_id)
        out["message"] = f"Could not reach Wikipedia ({exc}); tried again tomorrow."
    out["budget"] = budget()
    return out


def failures() -> dict[str, str]:
    """Pages whose last fetch failed, with the day: not retried that day (or, in the background, that month)."""
    return _read(root() / "failed.json") or {}


def _record_failure(entity_id: str) -> None:
    _write(root() / "failed.json", {**failures(), entity_id: date.today().isoformat()})


def fetch_page(entity_id: str, target: dict, reason: str = "opened") -> dict:
    """Fetch one article's introduction and pictures and store them. Counts once against today's limit."""
    with _lock:
        have = cached(entity_id)
        if have and not is_stale(have):  # fetched by another request meanwhile
            return have
        _spend()  # a fetch counts whether or not it works, so failures cannot loop
        title = target.get("article") or target["name"]
        q = _api({"prop": "extracts|pageimages|info|description", "exintro": 1, "explaintext": 1,
                  "piprop": "name", "inprop": "url", "titles": title})
        pages = q.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing") or pages[0].get("invalid"):
            raise ValueError(f"no Wikipedia article named {title!r}")
        p = pages[0]
        files = {"photo": target.get("photo") or p.get("pageimage"), "flag": target.get("flag"),
                 "map": target.get("map")}
        images = _pictures({k: v for k, v in files.items() if v})
        result = {
            "entity_id": entity_id, "title": p["title"], "url": p.get("fullurl"), "description": p.get("description"),
            "extract": (p.get("extract") or "").strip(), "images": images, "wikidata_item": target.get("item"),
            "fetched_at": now().isoformat(timespec="seconds"), "reason": reason,
            "licence": "Text from Wikipedia, CC BY-SA 4.0",
        }
        _write(root() / "countries" / f"{entity_id}.json", result)
        if entity_id in (failed := failures()):
            del failed[entity_id]
            _write(root() / "failed.json", failed)
        log.info("wikipedia: stored %s (%s, %s pictures)", entity_id, p["title"], len(images))
        return result


def _api(params: dict) -> dict:
    r = client().get(API, params={"action": "query", "format": "json", "formatversion": 2, "redirects": 1, **params})
    r.raise_for_status()
    return r.json()


def _pictures(files: dict[str, str]) -> list[dict]:
    """Credits and local thumbnails for the given files ({role: file name}), within the pictures limit."""
    names = {f"File:{name.removeprefix('File:')}": role for role, name in files.items()}
    if not names:
        return []
    q = _api({"prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": THUMB_WIDTH,
              "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl|Credit", "titles": "|".join(names)})
    norm = {n["to"]: n["from"] for n in q.get("query", {}).get("normalized", [])}
    out = []
    for p in q.get("query", {}).get("pages", []):
        info = (p.get("imageinfo") or [None])[0]
        role = names.get(norm.get(p["title"], p["title"])) or names.get(p["title"])
        if not info or not role:
            continue
        meta = info.get("extmetadata", {})
        thumb = info.get("thumburl") or info.get("url")
        local_name = _download(thumb) if thumb else None
        out.append({"role": role, "file": p["title"].removeprefix("File:"), "local": local_name,
                    "width": info.get("thumbwidth"), "height": info.get("thumbheight"),
                    "artist": _plain(meta.get("Artist", {}).get("value")),
                    "licence": _plain(meta.get("LicenseShortName", {}).get("value")),
                    "licence_url": meta.get("LicenseUrl", {}).get("value"),
                    "page_url": info.get("descriptionurl")})
    order = [r for r, _ in ROLES]
    return sorted(out, key=lambda i: order.index(i["role"]))


def _download(url: str) -> str | None:
    """Save one thumbnail under img/, unless the pictures limit is reached. Returns its file name."""
    ext = Path(url.split("?")[0]).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"):
        ext = ".jpg"
    name = hashlib.sha1(url.encode()).hexdigest()[:20] + ext
    path = root() / "img" / name
    if path.exists():
        return name
    if local.pictures_room() <= 0:
        log.info("wikipedia: pictures limit reached; not saving %s", url)
        return None
    r = client().get(url)
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
        log.info("wikipedia: thumbnail %s returned HTTP %s", url, r.status_code)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    return name


TAG = re.compile(r"<[^>]+>")


def _plain(s: str | None) -> str | None:
    if not s:
        return None
    return re.sub(r"\s+", " ", html.unescape(TAG.sub("", s))).strip() or None


def image_path(name: str) -> Path | None:
    """A stored thumbnail by file name (names only; nothing outside img/)."""
    if not re.fullmatch(r"[0-9a-f]{20}\.[a-z]{3,4}", name):
        return None
    path = root() / "img" / name
    return path if path.is_file() else None


def status() -> dict:
    """How many pages are stored, how many are due, and today's fetches."""
    folder = root() / "countries"
    pages = [cached(p.stem) for p in folder.glob("*.json")] if folder.exists() else []
    return {"stored": len(pages), "stale": sum(is_stale(p) for p in pages), "budget": budget(),
            "background": bool(local.load_settings()["wikipedia_background"])}


# ----------------------------------------------------------------------------- background
class Background:
    """Fetches pages nobody has opened yet, slowly, within half of today's limit.

    targets() returns (entity_id, target) pairs in the order to fetch: most-opened
    countries first, then the rest by population. It is given by main.py, which
    knows the warehouse."""

    def __init__(self, targets: Callable[[], list[tuple[str, dict]]]):
        self.targets = targets
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread is None:
            self.thread = threading.Thread(target=self.run, name="wikipedia-background", daemon=True)
            self.thread.start()

    def close(self) -> None:
        self.stop.set()

    def run(self) -> None:
        if self.stop.wait(BACKGROUND_START):
            return
        while not self.stop.is_set():
            wait = BACKGROUND_IDLE
            try:
                if self.step():
                    wait = BACKGROUND_GAP
            except Exception as exc:  # never let the thread die; try again later
                log.warning("wikipedia background: %s", exc)
            self.stop.wait(wait)

    def step(self) -> bool:
        """Fetch the next page due, if allowed now. True if one was fetched."""
        if not local.load_settings()["wikipedia_background"]:
            return False
        b = budget()
        if b["used"] >= b["background_limit"]:
            return False
        failed = failures()
        cutoff = (date.today() - timedelta(days=REFRESH_DAYS)).isoformat()
        for entity_id, target in self.targets():
            if failed.get(entity_id, "") > cutoff or not is_stale(cached(entity_id)):
                continue  # a page that failed is tried again a month later (or when opened)
            try:
                fetch_page(entity_id, target, reason="background")
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                log.info("wikipedia background: %s failed: %s", entity_id, exc)
                _record_failure(entity_id)
            return True
        return False
