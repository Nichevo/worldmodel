"""Public cameras for the map's Cameras layer: road agencies' traffic cameras and Windy's webcam
directory (beaches, surf, harbours, cities). Only cameras their owners publish for the public to
watch; nothing is saved, and the pictures are shown straight from each owner's server.

- NZ Transport Agency Waka Kotahi: every state highway camera (the Journey Planner's list, no key).
- Queensland (QLDTraffic GeoJSON API): QLDTRAFFIC_API_KEY, else the public key in its published spec.
- New South Wales (Live Traffic NSW): needs a free TFNSW_API_KEY from the Transport for NSW open data hub.
- London (TfL JamCams): pictures and 10-second clips, no key ("Powered by TfL Open Data").
- California (Caltrans CCTV, twelve districts): pictures and live video streams, no key.
- Finland (Fintraffic Digitraffic road weather cameras): pictures, no key, CC BY 4.0.
- Windy Webcams API (WINDY_WEBCAMS_API_KEY, free tier): webcams in the area in view, worldwide,
  the most watched plus beaches and coasts; picture links expire after ten minutes, so the card asks
  for a fresh one when it opens.

An agency's list is read only when the area in view reaches its region, and kept six hours.
"""

from __future__ import annotations

import os
import re
import threading
import time

import httpx

from worldmodel_api.live import boxes, inside

UA = {"User-Agent": "worldmodel (personal research tool)", "Digitraffic-User": "worldmodel/personal"}
LIST_KEEP = 6 * 3600       # seconds an agency's camera list is kept
RETRY_AFTER = 15 * 60      # after a failed read, seconds before asking that agency again
WAIT = 6.0                 # seconds a view waits for agency lists still being read
RETRY_SOON = 10            # seconds after which the map asks again for lists still being read
WINDY_KEEP = 9 * 60        # Windy's picture links last ten minutes on the free tier
WINDY = "https://api.windy.com/webcams/api/v3/webcams"
QLD_PUBLIC_KEY = "3e83add325cbb69ac4d8e5bf433d770b"  # published in QLDTraffic's API specification for public use

# Where each agency's cameras are (west, south, east, north): its list is read only when the view reaches it.
REGIONS: dict[str, tuple[float, float, float, float]] = {
    "nzta": (165.0, -48.0, 179.5, -33.5),
    "qld": (137.0, -29.5, 154.0, -9.0),
    "nsw": (140.9, -37.7, 153.8, -28.0),
    "tfl": (-0.65, 51.2, 0.4, 51.8),
    "caltrans": (-124.6, 32.4, -114.0, 42.1),
    "finland": (19.0, 59.4, 32.0, 70.2),
}
SOURCE_NAME = {
    "nzta": "NZ Transport Agency Waka Kotahi", "qld": "QLDTraffic (Queensland Government)",
    "nsw": "Live Traffic NSW (Transport for NSW)", "tfl": "Powered by TfL Open Data",
    "caltrans": "Caltrans", "finland": "Fintraffic Digitraffic (CC BY 4.0)", "windy": "Windy.com webcams",
}
SOURCE_PAGE = {
    "nzta": "https://www.journeys.nzta.govt.nz/traffic-cameras/", "qld": "https://qldtraffic.qld.gov.au/",
    "nsw": "https://www.livetraffic.com/", "tfl": "https://tfl.gov.uk/traffic/status/",
    "caltrans": "https://quickmap.dot.ca.gov/", "finland": "https://www.digitraffic.fi/en/road-traffic/",
}


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _cam(source: str, cid, name, lat, lon, kind: str = "traffic", **more) -> dict | None:
    lat, lon = _f(lat), _f(lon)
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    props = {"id": f"{source}:{cid}", "name": str(name or "Camera").strip(), "kind": kind, "source": source}
    props.update({k: v for k, v in more.items() if v not in (None, "", [])})
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}, "properties": props}


# ----------------------------------------------------------------------------- each agency's list
def parse_nzta(body: dict) -> list[dict]:
    out = []
    for f in body.get("features") or []:
        p = f.get("properties") or {}
        lon, lat = ((f.get("geometry") or {}).get("coordinates") or [p.get("Longitude"), p.get("Latitude")])[:2]
        out.append(_cam("nzta", p.get("ExternalId") or p.get("id"), p.get("Name"), lat, lon,
                        about=p.get("Description"), direction=p.get("Direction"), image=p.get("ImageUrl"),
                        offline=bool(p.get("Offline") or p.get("UnderMaintenance")) or None))
    return [c for c in out if c]


def parse_qld(body: dict) -> list[dict]:
    out = []
    for f in body.get("features") or []:
        p = f.get("properties") or {}
        lon, lat = ((f.get("geometry") or {}).get("coordinates") or [None, None])[:2]
        image = p.get("image_url") or p.get("imageUrl") or p.get("url")
        if not image:
            continue
        out.append(_cam("qld", p.get("id"), p.get("description") or p.get("locality"), lat, lon,
                        about=", ".join(x for x in (p.get("locality"), p.get("district")) if x) or None,
                        direction=p.get("direction"), image=image))
    return [c for c in out if c]


def parse_nsw(body: dict) -> list[dict]:
    out = []
    for f in body.get("features") or []:
        p = f.get("properties") or {}
        lon, lat = ((f.get("geometry") or {}).get("coordinates") or [None, None])[:2]
        image = p.get("href") or p.get("image") or p.get("url")
        if not image:
            continue
        out.append(_cam("nsw", f.get("id") or p.get("id") or p.get("title"), p.get("title"), lat, lon,
                        about=p.get("view"), direction=p.get("direction"), image=image))
    return [c for c in out if c]


def parse_tfl(body: list) -> list[dict]:
    out = []
    for place in body or []:
        extra = {a.get("key"): a.get("value") for a in place.get("additionalProperties") or []}
        if not extra.get("imageUrl"):
            continue
        out.append(_cam("tfl", str(place.get("id", "")).replace("JamCams_", ""), place.get("commonName"),
                        place.get("lat"), place.get("lon"), direction=extra.get("view"), image=extra.get("imageUrl"),
                        video=extra.get("videoUrl"), offline=(str(extra.get("available", "true")).lower() == "false") or None))
    return [c for c in out if c]


def parse_caltrans(body: dict) -> list[dict]:
    out = []
    for row in body.get("data") or []:
        c = row.get("cctv") or {}
        loc = c.get("location") or {}
        img = c.get("imageData") or {}
        image = (img.get("static") or {}).get("currentImageURL")
        stream = img.get("streamingVideoURL")
        if not image and not stream:
            continue
        district = loc.get("district") or ""
        out.append(_cam("caltrans", f"{district}-{c.get('index')}", loc.get("locationName"), loc.get("latitude"), loc.get("longitude"),
                        about=", ".join(x for x in (loc.get("nearbyPlace"), loc.get("county") and f"{loc['county']} County") if x) or None,
                        direction=loc.get("direction"), image=image or None, stream=stream or None,
                        offline=(str(c.get("inService", "true")).lower() == "false") or None))
    return [c for c in out if c]


ROAD = {"vt": "main road", "kt": "road", "st": "road", "mt": "road", "yt": "road"}


def _fi_name(raw: str) -> str:
    """'kt51_Inkoo' -> 'Inkoo (road 51)'."""
    m = re.match(r"^(vt|kt|st|mt|yt)(\d+)_(.+)$", raw or "", re.I)
    if not m:
        return (raw or "Road weather camera").replace("_", " ")
    return f"{m.group(3).replace('_', ' ')} ({ROAD[m.group(1).lower()]} {m.group(2)})"


def parse_finland(body: dict) -> list[dict]:
    out = []
    for f in body.get("features") or []:
        p = f.get("properties") or {}
        lon, lat = ((f.get("geometry") or {}).get("coordinates") or [None, None])[:2]
        presets = [x["id"] for x in p.get("presets") or [] if x.get("id") and x.get("inCollection", True)]
        if not presets:
            continue
        images = [f"https://weathercam.digitraffic.fi/{x}.jpg" for x in presets[:6]]
        out.append(_cam("finland", p.get("id") or f.get("id"), _fi_name(p.get("name") or ""), lat, lon, kind="weather",
                        image=images[0], images=images if len(images) > 1 else None,
                        offline=(p.get("collectionStatus") not in (None, "GATHERING")) or None))
    return [c for c in out if c]


def _get(client: httpx.Client, url: str, **kw):
    r = client.get(url, **kw)
    if r.status_code == 429:
        raise Busy()
    if r.status_code in (401, 403):
        raise Refused(r.status_code)
    r.raise_for_status()
    return r.json()


class Busy(Exception):
    pass


class Refused(Exception):
    pass


def read_list(source: str, client: httpx.Client) -> list[dict]:
    """One agency's whole camera list, read now."""
    if source == "nzta":
        return parse_nzta(_get(client, "https://www.journeys.nzta.govt.nz/assets/map-data-cache/cameras.json"))
    if source == "qld":
        key = (os.environ.get("QLDTRAFFIC_API_KEY") or "").strip() or QLD_PUBLIC_KEY
        return parse_qld(_get(client, "https://api.qldtraffic.qld.gov.au/v1/webcams", params={"apikey": key}))
    if source == "nsw":
        key = (os.environ.get("TFNSW_API_KEY") or "").strip()
        return parse_nsw(_get(client, "https://api.transport.nsw.gov.au/v1/live/cameras", headers={"Authorization": f"apikey {key}"}))
    if source == "tfl":
        return parse_tfl(_get(client, "https://api.tfl.gov.uk/Place/Type/JamCam"))
    if source == "caltrans":
        out: list[dict] = []
        for d in range(1, 13):
            try:
                out += parse_caltrans(_get(client, f"https://cwwp2.dot.ca.gov/data/d{d}/cctv/cctvStatusD{d:02d}.json"))
            except httpx.HTTPStatusError:
                continue  # a district without cameras or a list being rebuilt: the others still show
        if not out:
            raise httpx.HTTPError("no district answered")
        return out
    if source == "finland":
        return parse_finland(_get(client, "https://tie.digitraffic.fi/api/weathercam/v1/stations"))
    raise KeyError(source)


def _why(source: str, exc: Exception) -> str:
    name = SOURCE_NAME[source].split(" (")[0]
    if isinstance(exc, Busy):
        return (f"{name} is busy (too many requests on the shared public key); a free key of your own in "
                "QLDTRAFFIC_API_KEY (Settings > Keys) helps." if source == "qld" else f"{name} is busy; trying again later.")
    if isinstance(exc, Refused):
        return (f"{name} refused the key: check TFNSW_API_KEY in Settings > Keys." if source == "nsw"
                else f"{name} refused the request ({exc}).")
    return f"{name} did not answer ({exc.__class__.__name__}); trying again in {RETRY_AFTER // 60} min."


def _meets(region: tuple[float, float, float, float], bx: list) -> bool:
    w0, s0, e0, n0 = region
    return any(w <= e0 and e >= w0 and s <= n0 and n >= s0 for w, s, e, n in bx)


# ----------------------------------------------------------------------------- Windy webcams
def windy_kind(cats: list) -> str:
    ids = {str(c.get("id") if isinstance(c, dict) else c).lower() for c in cats or []}
    if ids & {"beach", "coast"}:
        return "beach"
    if "traffic" in ids:
        return "traffic"
    if ids & {"meteo", "mountain", "lake", "landscape", "forest", "river"}:
        return "nature"
    return "city"


def windy_image(w: dict) -> str | None:
    imgs = w.get("images") or {}
    for part in ("current", "daylight"):
        got = imgs.get(part) or {}
        for size in ("preview", "thumbnail", "icon"):
            if got.get(size):
                return got[size]
    return None


def parse_windy(body: dict) -> list[dict]:
    out = []
    for w in body.get("webcams") or []:
        if w.get("status") not in (None, "active"):
            continue
        loc = w.get("location") or {}
        cats = w.get("categories") or []
        out.append(_cam("windy", w.get("webcamId"), w.get("title"), loc.get("latitude"), loc.get("longitude"),
                        kind=windy_kind(cats), about=", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x) or None,
                        image=windy_image(w), player=(w.get("player") or {}).get("live") or (w.get("player") or {}).get("day"),
                        page=(w.get("urls") or {}).get("detail"),
                        categories=[c.get("name") for c in cats if isinstance(c, dict) and c.get("name")][:4] or None))
    return [c for c in out if c]


class Cameras:
    """Agencies' camera lists are read in the background, one thread per agency: a wide view
    (the whole Pacific, say) can reach six agencies and California alone is twelve files, which
    took longer than the web app's proxy waits (it then reported "socket hang up"). A view waits
    up to WAIT seconds for lists not yet read, gets what is ready, and asks again RETRY_SOON
    seconds later for the rest."""

    def __init__(self) -> None:
        self.lock = threading.Lock()      # held only to read and write the lists, never over the network
        self.lists: dict[str, tuple[float, list[dict]]] = {}
        self.failed: dict[str, tuple[float, str]] = {}
        self.loading: dict[str, threading.Thread] = {}
        self.windy: dict[tuple, tuple[float, list[dict]]] = {}
        self.windy_error: tuple[float, str] | None = None

    def _due(self, source: str) -> bool:
        """Whether an agency's list needs reading (not kept, and not failed a short while ago)."""
        now = time.time()
        kept, failed = self.lists.get(source), self.failed.get(source)
        return not (kept and now - kept[0] < LIST_KEEP) and not (failed and now - failed[0] < RETRY_AFTER)

    def _load(self, source: str, client: httpx.Client | None = None) -> None:
        own = client is None
        client = client or httpx.Client(timeout=25, headers=UA, follow_redirects=True)
        try:
            cams = read_list(source, client)
        except (httpx.HTTPError, ValueError, KeyError, Busy, Refused) as exc:
            with self.lock:
                self.failed[source] = (time.time(), _why(source, exc))
            return
        finally:
            if own:
                client.close()
        with self.lock:
            self.lists[source] = (time.time(), cams)
            self.failed.pop(source, None)

    def _source(self, source: str, client: httpx.Client) -> tuple[list[dict], str | None]:
        """An agency's list, read now with the given client if due (used by tests and one-off callers)."""
        with self.lock:
            due = self._due(source)
        if due:
            self._load(source, client)
        with self.lock:
            kept, failed = self.lists.get(source), self.failed.get(source)
        return (kept[1] if kept else []), (failed[1] if failed else None)

    def _windy(self, bx: list, client: httpx.Client) -> tuple[list[dict], str | None]:
        key = (os.environ.get("WINDY_WEBCAMS_API_KEY") or "").strip()
        if not key:
            return [], None
        if self.windy_error and time.time() - self.windy_error[0] < RETRY_AFTER:
            return [], self.windy_error[1]
        out: list[dict] = []
        for w, s, e, n in bx:
            box = (round(w * 2) / 2, round(s * 2) / 2, round(e * 2) / 2, round(n * 2) / 2)
            kept = self.windy.get(box)
            if kept and time.time() - kept[0] < WINDY_KEEP:
                out += kept[1]
                continue
            got: list[dict] = []
            base = {"bbox": f"{n:.3f},{e:.3f},{s:.3f},{w:.3f}", "limit": 50, "include": "location,images,player,categories,urls"}
            try:
                for extra in ({"sortKey": "popularity", "sortDirection": "desc"},
                              {"categories": "beach,coast", "categoryOperation": "or", "sortKey": "popularity", "sortDirection": "desc"}):
                    got += parse_windy(_get(client, WINDY, params={**base, **extra}, headers={"x-windy-api-key": key}))
            except (httpx.HTTPError, ValueError, Busy, Refused) as exc:
                why = ("Windy refused the key: check WINDY_WEBCAMS_API_KEY in Settings > Keys." if isinstance(exc, Refused)
                       else "Windy's free webcam requests are used up for now; trying again later." if isinstance(exc, Busy)
                       else f"Windy webcams did not answer ({exc.__class__.__name__}).")
                self.windy_error = (time.time(), why)
                return out, why
            seen: set = set()
            got = [c for c in got if not (c["properties"]["id"] in seen or seen.add(c["properties"]["id"]))]
            self.windy[box] = (time.time(), got)
            if len(self.windy) > 200:  # forget the oldest boxes
                for k in sorted(self.windy, key=lambda k: self.windy[k][0])[:100]:
                    self.windy.pop(k, None)
            out += got
        self.windy_error = None
        return out, None

    def get(self, west: float, south: float, east: float, north: float, client: httpx.Client | None = None) -> dict:
        """Cameras in view. With a client (tests), lists are read there and then; without one,
        in the background (see the class)."""
        bx = boxes(west, south, east, north)
        notes: list[str] = []
        feats: list[dict] = []
        wanted = []
        for source, region in REGIONS.items():
            if not _meets(region, bx):
                continue
            if source == "nsw" and not (os.environ.get("TFNSW_API_KEY") or "").strip():
                notes.append("NSW cameras need a free Transport for NSW key: TFNSW_API_KEY in Settings > Keys.")
                continue
            wanted.append(source)
        if client is not None:
            for source in wanted:
                self._source(source, client)
        else:
            threads = []
            with self.lock:
                for source in wanted:
                    t = self.loading.get(source)
                    if not (t and t.is_alive()) and self._due(source):
                        t = threading.Thread(target=self._load, args=(source,), name=f"cameras-{source}", daemon=True)
                        self.loading[source] = t
                        t.start()
                    if t and t.is_alive():
                        threads.append(t)
            until = time.monotonic() + WAIT
            for t in threads:
                t.join(max(0.0, until - time.monotonic()))
        waiting = []
        with self.lock:
            for source in wanted:
                kept, failed = self.lists.get(source), self.failed.get(source)
                if kept:
                    feats += [c for c in kept[1] if inside(*c["geometry"]["coordinates"], bx)]
                t = self.loading.get(source)
                if client is None and t and t.is_alive():
                    waiting.append(SOURCE_NAME[source].split(" (")[0])
                elif failed and not (kept and kept[0] > failed[0]):
                    notes.append(failed[1])
        own = client is None
        wclient = client or httpx.Client(timeout=20, headers=UA, follow_redirects=True)
        try:
            web, why = self._windy(bx, wclient)
        finally:
            if own:
                wclient.close()
        seen = {(round(c["geometry"]["coordinates"][0], 3), round(c["geometry"]["coordinates"][1], 3)) for c in feats}
        feats += [c for c in web if (round(c["geometry"]["coordinates"][0], 3), round(c["geometry"]["coordinates"][1], 3)) not in seen]
        if why:
            notes.append(why)
        if not (os.environ.get("WINDY_WEBCAMS_API_KEY") or "").strip():
            notes.append("Beach, surf and city webcams worldwide come with a free Windy key: WINDY_WEBCAMS_API_KEY in Settings > Keys.")
        out = {"type": "FeatureCollection", "features": feats, "count": len(feats), "source": "Road agencies and Windy webcams",
               "at": int(time.time())}
        if waiting:
            notes.insert(0, f"Still reading the camera lists of {', '.join(waiting)}; they show in a moment.")
            out["retry_in"] = RETRY_SOON
        if notes:
            out["note"] = " ".join(dict.fromkeys(notes))
        return out

    def windy_one(self, webcam_id: int, client: httpx.Client | None = None) -> dict:
        """A fresh picture and player for one Windy webcam (picture links expire after ten minutes)."""
        key = (os.environ.get("WINDY_WEBCAMS_API_KEY") or "").strip()
        if not key:
            return {"error": "Needs a free Windy key: WINDY_WEBCAMS_API_KEY in Settings > Keys."}
        own = client is None
        client = client or httpx.Client(timeout=20, headers=UA)
        try:
            body = _get(client, f"{WINDY}/{int(webcam_id)}", params={"include": "location,images,player,categories,urls"},
                        headers={"x-windy-api-key": key})
        except (httpx.HTTPError, ValueError, Busy, Refused) as exc:
            return {"error": f"Windy did not give this webcam ({exc.__class__.__name__})."}
        finally:
            if own:
                client.close()
        got = parse_windy({"webcams": [body]})
        if not got:
            return {"error": "Windy says this webcam is not active."}
        p = got[0]["properties"]
        return {"image": p.get("image"), "player": p.get("player"), "page": p.get("page"), "name": p.get("name"),
                "updated": body.get("lastUpdatedOn")}


CAMERAS = Cameras()
