"""The public API: the app's data for scripts, Python, Excel and AI assistants, under /api/public/v1.

Off until switched on in Settings > API access. When on:
  - from this PC (localhost) no key is needed;
  - from another PC on the network a key is needed (made in Settings > API access), sent as
    `Authorization: Bearer <key>`, an `X-API-Key` header or `?key=`; each key has a daily limit
    and every call is logged (user/api_log.jsonl, the last 5,000 calls).
Nothing here opens the app to the internet: the app listens on this PC and the home network only.
Keys count and limit other PCs' scripts; they are not a lock on the data, since the app's own pages
(and /api/v1) are open to the home network as before. The web app (port 3030) passes each request
on naming the PC it came from (app/web/app/api/public/[...path]/route.ts).

Keys are kept hashed in user/api_keys.json; the key itself is shown once, when made.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import ipaddress
import json
import secrets
import threading
from datetime import date, datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from worldmodel_api import userdata

_lock = threading.Lock()
KEYS_FILE = "api_keys.json"
LOG_FILE = "api_log.jsonl"
LOG_KEEP = 5000
OFF = ("The API is switched off. Switch it on in the app: Settings > API access "
       "(it is off by default, so nothing can read the data until you choose to).")


# ----------------------------------------------------------------------------- keys and the log
def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def keys() -> list[dict]:
    return userdata._read_json(KEYS_FILE, {"keys": []}).get("keys", [])


def _save_keys(items: list[dict]) -> None:
    userdata._write_json(KEYS_FILE, {"keys": items})


def key_list() -> list[dict]:
    """Keys without their hashes, with today's use."""
    today = date.today().isoformat()
    return [{"id": k["id"], "name": k["name"], "start": k["start"], "made": k["made"], "last_used": k.get("last_used"),
             "today": k.get("days", {}).get(today, 0), "total": sum(k.get("days", {}).values()),
             "daily_limit": k.get("daily_limit")} for k in keys()]


def make_key(name: str, daily_limit: int | None = None) -> dict:
    name = " ".join(str(name or "").split())[:60] or "Key"
    key = "wm_" + secrets.token_urlsafe(24)
    item = {"id": secrets.token_hex(4), "name": name, "start": key[:7], "hash": _hash(key), "made": userdata.now(),
            "days": {}, "daily_limit": daily_limit}
    with _lock:
        _save_keys([*keys(), item])
    return {"id": item["id"], "name": name, "key": key}


def revoke_key(key_id: str) -> bool:
    with _lock:
        cur = keys()
        left = [k for k in cur if k["id"] != key_id]
        _save_keys(left)
    return len(left) < len(cur)


def _log(who: str, request: Request, status: int) -> None:
    line = json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "who": who,
                       "from": _client(request), "path": request.url.path, "query": str(request.url.query)[:300],
                       "status": status})
    path = userdata._path(LOG_FILE)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        if path.stat().st_size > 2_000_000:  # keep the last LOG_KEEP calls
            lines = path.read_text(encoding="utf-8").splitlines()[-LOG_KEEP:]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def recent(n: int = 50) -> list[dict]:
    try:
        lines = userdata._path(LOG_FILE).read_text(encoding="utf-8").splitlines()[-n:]
    except FileNotFoundError:
        return []
    out = []
    for ln in reversed(lines):
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def mcp_command() -> str:
    """Where worldmodel-mcp is installed (beside this Python), for the MCP settings example."""
    import shutil
    import sys
    from pathlib import Path
    exe = Path(sys.executable).parent
    for p in (exe / "Scripts" / "worldmodel-mcp.exe", exe / "worldmodel-mcp.exe", exe / "worldmodel-mcp"):
        if p.exists():
            return str(p)
    return shutil.which("worldmodel-mcp") or "worldmodel-mcp"


# ----------------------------------------------------------------------------- who is asking
def _loopback(addr: str | None) -> bool:
    if not addr:
        return False
    addr = addr.strip().strip("[]")
    if addr in ("localhost", "testclient"):
        return True
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return ip.is_loopback or (getattr(ip, "ipv4_mapped", None) is not None and ip.ipv4_mapped.is_loopback)


def _client(request: Request) -> str:
    fwd = [x.strip() for x in request.headers.get("x-forwarded-for", "").split(",") if x.strip()]
    return fwd[0] if fwd else (request.client.host if request.client else "")


def is_local(request: Request) -> bool:
    """From this PC: the connection is from this PC and so is everyone it was passed on for
    (the web app on port 3030 passes requests on, naming the PC they came from)."""
    fwd = [x.strip() for x in request.headers.get("x-forwarded-for", "").split(",") if x.strip()]
    host = request.client.host if request.client else None
    return _loopback(host) and all(_loopback(x) for x in fwd)


def _given_key(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-api-key") or request.query_params.get("key")


def guard(request: Request) -> str:
    """Every public call passes here: is the API on, is it from this PC or with a good key, is the key within its limit."""
    s = userdata.settings()
    if not s.get("api_public_on"):
        raise HTTPException(403, OFF)
    given = _given_key(request)
    if not given and is_local(request):
        _log("this PC", request, 200)
        return "this PC"
    if not given:
        _log("no key", request, 401)
        raise HTTPException(401, "A key is needed from another PC: make one in the app, Settings > API access, "
                                 "and send it as 'Authorization: Bearer <key>'.")
    h = _hash(given)
    today = date.today().isoformat()
    with _lock:
        items = keys()
        hit = next((k for k in items if secrets.compare_digest(k["hash"], h)), None)
        if hit is None:
            pass
        else:
            limit = hit.get("daily_limit") or int(s.get("api_daily_limit", 2000))
            used = hit.setdefault("days", {}).get(today, 0)
            if used >= limit:
                hit = {**hit, "_over": limit}
            else:
                hit["days"][today] = used + 1
                hit["days"] = dict(sorted(hit["days"].items())[-60:])
                hit["last_used"] = userdata.now()
                _save_keys(items)
    if hit is None:
        _log("bad key", request, 401)
        raise HTTPException(401, "That key is not known (it may have been taken back in Settings > API access).")
    if "_over" in hit:
        _log(hit["name"], request, 429)
        raise HTTPException(429, f"This key has used its {hit['_over']} calls for today; the count starts again at midnight.")
    _log(hit["name"], request, 200)
    return hit["name"]


router = APIRouter(prefix="/api/public/v1", tags=["Public API"], dependencies=[Depends(guard)])


def _m():
    from worldmodel_api import main  # the app's own calls; imported late to avoid a loop
    return main


# ----------------------------------------------------------------------------- calls
@router.get("/")
def index():
    """What this API offers."""
    return {"calls": {
        "/countries": "Countries, groups and blocs: ids and names (type=country|group|world|continent)",
        "/indicators": "Indicators: ids, names, units, topics (q= to search)",
        "/search": "Turn words into ids: q=new zealand, q=inflation",
        "/data": "Figures: indicator=, entities=NZL,AUS, from=, to=, source=, as_of=YYYY-MM-DD, format=json|csv",
        "/forecast": "A statistical forecast with p10/p50/p90 (and p2.5/p97.5): indicator=, entity=, horizon=",
        "/chart.svg": "A line chart picture: indicator=, entities=, from=, to=",
        "/events": "Dated events: entities=, kinds=, start=, end=, q=",
        "/crowd": "Crowd forecasts (Polymarket, Metaculus, Manifold): country=, q=, status=",
        "/predictions": "Your predictions log (GET), add one (POST)",
        "/alike": "Countries most like one country: entity=, preset=, year=",
        "/synthetic": "Synthetic comparison: entity=, indicator=, year=",
    }, "docs": "/api/docs#/Public%20API"}


@router.get("/countries")
def countries(type: str | None = Query(None, description="country, group, world or continent; none for all")):
    m = _m()
    sql = "SELECT entity_id AS id, short_name AS name, name AS full_name, type FROM entities"
    return m.rows(sql + (" WHERE type = ?" if type else "") + " ORDER BY type, short_name", [type] if type else [])


@router.get("/indicators")
def indicators(q: str | None = None):
    m = _m()
    like = f"%{q}%" if q else "%"
    return m.rows("SELECT indicator_id AS id, name, unit, domain AS topic, description FROM indicators "
                  "WHERE name ILIKE ? OR description ILIKE ? OR synonyms ILIKE ? ORDER BY domain, name", [like, like, like])


@router.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=100)):
    return _m().search(q, limit)


@router.get("/data")
def data(indicator: str, entities: str | None = Query(None, description="Comma-separated ids; none for every country"),
         start: int | None = Query(None, alias="from"), end: int | None = Query(None, alias="to"),
         source: str | None = None, as_of: date | None = Query(None, description="Figures as known on this date"),
         projections: bool = True, format: str = Query("json", pattern="^(json|csv)$")):
    m = _m()
    if not m.rows("SELECT 1 FROM indicators WHERE indicator_id = ?", [indicator]):
        raise HTTPException(404, f"no indicator {indicator}; /indicators lists them")
    found = m._series(indicator, entities, None, start, end, source, "", "central", projections, as_of)
    out = [{"entity": r["entity_id"], "year": int(str(r["period_start"])[:4]), "period": str(r["period"]), "value": r["value"],
            "status": "projection" if r["status"] == "P" else "estimate", "source": r["source_id"], "vintage": r["vintage"]}
           for r in found]
    if format == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["entity", "year", "period", "value", "status", "source", "vintage"])
        w.writeheader()
        w.writerows(out)
        return Response(buf.getvalue(), media_type="text/csv")
    meta = m.rows("SELECT name, unit FROM indicators WHERE indicator_id = ?", [indicator])[0]
    return {"indicator": indicator, "name": meta["name"], "unit": meta["unit"], "as_of": as_of, "rows": out}


@router.get("/forecast")
def forecast(indicator: str, entity: str, horizon: int = Query(10, ge=1, le=50)):
    f = _m()._stat_forecast(indicator, entity, None, horizon, None)
    pts = [{"year": p["year"], "p50": p["mean"], "p10": p.get("lo80"), "p90": p.get("hi80"),
            "p2_5": p.get("lo95"), "p97_5": p.get("hi95")} for p in f.get("points", [])]
    return {"indicator": indicator, "entity": entity, "model": f.get("model_name"), "last_year": f.get("history_end"),
            "last_value": f.get("last_value"), "points": pts,
            "note": "p10 to p90 is the 80% range from the model's own back-test misses; p50 the central path."}


@router.get("/chart.svg")
def chart(indicator: str, entities: str = "NZL", start: int | None = Query(None, alias="from"),
          end: int | None = Query(None, alias="to"), width: int = Query(720, ge=200, le=2400),
          height: int = Query(360, ge=120, le=1600)):
    m = _m()
    meta = m.rows("SELECT name, unit FROM indicators WHERE indicator_id = ?", [indicator])
    if not meta:
        raise HTTPException(404, f"no indicator {indicator}")
    ids = m.split(entities)[:8]
    found = m._series(indicator, ",".join(ids), None, start, end, None, "", "central", True, None)
    names = {r["entity_id"]: r["short_name"] for r in
             m.rows("SELECT entity_id, short_name FROM entities WHERE entity_id IN (SELECT unnest(?))", [ids])}
    lines: dict[str, list[tuple[float, float, bool]]] = {}
    for r in found:
        if r["value"] is None or r["freq"] != "A":
            continue
        lines.setdefault(r["entity_id"], []).append((int(str(r["period_start"])[:4]), float(r["value"]), r["status"] == "P"))
    return Response(svg_chart(f"{meta[0]['name']}{' (' + meta[0]['unit'] + ')' if meta[0]['unit'] else ''}",
                              {names.get(e, e): sorted(v) for e, v in lines.items()}, width, height),
                    media_type="image/svg+xml")


@router.get("/events")
def events(entities: str | None = None, kinds: str | None = None, start: str | None = None, end: str | None = None,
           q: str | None = None, limit: int = Query(500, ge=1, le=5000)):
    return _m().events(entities=entities, members=False, kinds=kinds, sources=None, start=start, end=end, min_size=None,
                       q=q, limit=limit)


@router.get("/crowd")
def crowd(country: str | None = None, q: str | None = None, status: str | None = "open", limit: int = Query(50, ge=1, le=500)):
    out = _m().crowd_list(site=None, category=None, country=country, status=status, q=q, indicator=None, followed=False,
                          hidden=False, sort="busy", days=7, limit=limit, offset=0)
    return {k: out[k] for k in out if k not in ("categories", "sites")}


@router.get("/predictions")
def predictions(entity: str | None = None, indicator: str | None = None, state: str | None = None):
    return _m().predictions_list(who=None, category=None, entity=entity, indicator=indicator, state=state)["items"]


@router.post("/predictions")
def predictions_add(p: dict = Body(..., examples=[{"question": "NZ inflation in 2026", "kind": "number", "value": 2.4,
                                                   "low": 2, "high": 3, "due": "2027-04-30", "indicator": "inflation",
                                                   "entity": "NZL", "year": 2026, "who_kind": "app", "who": "My script"}])):
    return _m().predictions_add(p)


@router.get("/alike")
def alike(entity: str, preset: str = "everything", year: int | None = None, n: int = Query(10, ge=1, le=40)):
    return _m().alike(entity=entity, preset=preset, indicators=None, year=year, n=n, decades=False)


@router.get("/synthetic")
def synthetic(entity: str, indicator: str, year: int, pool: str | None = None, start: int | None = None):
    return _m().synthetic_view(entity=entity, indicator=indicator, year=year, pool=pool, start=start, end=None, placebos=True)


# ----------------------------------------------------------------------------- a chart without a browser
PALETTE = ["#2a78c6", "#d9822b", "#3b9e5d", "#b8457a", "#7a5cc2", "#a08a2b", "#3aa6a6", "#c4473c"]


def _nice(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    raw = (hi - lo) / n
    mag = 10 ** int(f"{raw:e}".split("e")[1])
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw)
    start = (lo // step) * step
    out, v = [], start
    while v <= hi + step * 0.001:
        out.append(round(v, 10))
        v += step
    return out


def _fmt(v: float) -> str:
    a = abs(v)
    if a >= 1e12:
        return f"{v / 1e12:g}T"
    if a >= 1e9:
        return f"{v / 1e9:g}B"
    if a >= 1e6:
        return f"{v / 1e6:g}M"
    if a >= 1e4:
        return f"{v / 1e3:g}k"
    return f"{v:g}"


def svg_chart(title: str, lines: dict[str, list[tuple[float, float, bool]]], w: int = 720, h: int = 360) -> str:
    """A plain line chart as SVG: one line per country, projections dashed."""
    esc = html.escape
    pad_l, pad_r, pad_t, pad_b = 56, 16, 34, 46
    pts = [p for ps in lines.values() for p in ps]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
             'font-family="Segoe UI, Arial, sans-serif" font-size="12">',
             f'<rect width="{w}" height="{h}" fill="#fff"/>',
             f'<text x="{pad_l}" y="20" font-size="14" font-weight="600" fill="#222">{esc(title)}</text>']
    if not pts:
        parts.append(f'<text x="{w / 2}" y="{h / 2}" text-anchor="middle" fill="#777">No figures</text></svg>')
        return "".join(parts)
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    lo, hi = min(p[1] for p in pts), max(p[1] for p in pts)
    if 0 < lo < 0.25 * hi:
        lo = 0.0  # start at zero when the lines are well above it anyway
    yt = _nice(lo, hi)
    y0, y1 = yt[0], yt[-1]
    x1 = x1 if x1 > x0 else x0 + 1
    X = lambda x: pad_l + (x - x0) / (x1 - x0) * (w - pad_l - pad_r)  # noqa: E731
    Y = lambda y: h - pad_b - (y - y0) / ((y1 - y0) or 1) * (h - pad_t - pad_b)  # noqa: E731
    for t in yt:
        parts.append(f'<line x1="{pad_l}" x2="{w - pad_r}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="#e5e5e5"/>'
                     f'<text x="{pad_l - 6}" y="{Y(t) + 4:.1f}" text-anchor="end" fill="#666">{_fmt(t)}</text>')
    for t in _nice(x0, x1, 6):
        if x0 <= t <= x1:
            parts.append(f'<text x="{X(t):.1f}" y="{h - pad_b + 16}" text-anchor="middle" fill="#666">{int(t)}</text>')
    legend_x = pad_l
    for i, (name, ps) in enumerate(lines.items()):
        col = PALETTE[i % len(PALETTE)]
        est = [p for p in ps if not p[2]]
        proj = ([est[-1]] if est else []) + [p for p in ps if p[2]]
        for seg, dash in ((est, ""), (proj, ' stroke-dasharray="5 4"')):
            if len(seg) > 1:
                d = " ".join(f"{'M' if j == 0 else 'L'}{X(p[0]):.1f},{Y(p[1]):.1f}" for j, p in enumerate(seg))
                parts.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="2"{dash}/>')
        parts.append(f'<rect x="{legend_x}" y="{h - 18}" width="10" height="10" fill="{col}"/>'
                     f'<text x="{legend_x + 14}" y="{h - 9}" fill="#333">{esc(name)}</text>')
        legend_x += 24 + 7 * len(name)
    parts.append(f'<text x="{w - pad_r}" y="{h - 9}" text-anchor="end" fill="#999" font-size="10">worldmodel</text></svg>')
    return "".join(parts)
