"""The local data folder, as both sides see it: user settings, disk use and the refresh log.

The pipeline writes raw downloads, vintages, builds and the refresh log; the app
writes only user files (settings, layouts, history) under user/. Both need the
same answers to "where is everything, how big is it, what are the limits", so
those live here rather than in either side.

    <home>/raw/        source files as downloaded         (pipeline)
    <home>/vintages/   normalised Parquet per vintage     (pipeline)
    <home>/warehouse/  builds, reports, refresh_log.jsonl (pipeline)
    <home>/media/      pictures and page caches           (app: Wikipedia pages fetched on demand)
    <home>/user/       settings, layouts, history         (app)

home is WORLDMODEL_HOME, else a WORLDMODEL_WAREHOUSE that names a folder, else ./var.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

GB = 1024 ** 3

# Every user setting with its default. The app's Settings page edits these; the
# pipeline reads the storage limits. Unknown keys in the file are ignored.
SETTINGS: dict[str, object] = {
    "click_mode": "popup",          # "popup": click opens a popup, shift-click selects; "select": click selects, double-click opens
    "hover_sparkline": True,         # small trend line in the map tooltip
    "popup_tabs": True,              # popups get a tab per indicator shown in the panels
    "side_panel": True,              # the pinboard down the right of the map page
    "disk_limit_gb": 100.0,          # the whole data folder
    "pictures_limit_gb": 2.0,        # media/ (pictures, cached pages)
    "basemap_limit_gb": 20.0,        # basemap/ (the local map files)
    "base_map": "online",            # map detail under the colours: "online" (OpenFreeMap), "local" (map files on this PC) or "plain"
    "basemap_regions": "nzl",        # countries the local map file holds in full detail (street level)
    "basemap_world_zoom": 8,         # how far the local world file goes (6 big towns and motorways ... 10 small towns and most roads)
    "basemap_region_zoom": 15,       # how far the full-detail countries go (15 = every street and building)
    "numbeo_daily": 20,              # single-page Numbeo fetches per day, all countries together
    "wikipedia_countries_daily": 20,
    "wikipedia_cities_daily": 10,
    "wikipedia_background": True,    # fetch pages not yet opened, a few an hour, within half the daily limit
    "history_paused": False,
    "history_retention_days": 0,     # 0 keeps history forever
    "problem_banner": True,          # a banner on every page while a refresh problem is open
    "events_on_charts": True,        # dated events as lines and bands on line charts of up to three countries
    "profile_charts": "",            # indicator ids charted on country pages, in order ("" = the standard set)
    "profile_cards_hidden": "",      # country page cards switched off (debt, housing, cities...)
    "profile_saved": {},             # named country page set-ups: name -> {charts, hidden}
    "profile_average": "",           # a group (oecd, g20, world...) whose average joins a country page's rate charts
    "projections_on_charts": True,   # years after the last estimate (UN projections and the like) on charts
    "event_kinds": "recession,crisis,coup,conflict,disaster,sport,notable,user",  # kinds shown on charts
    "disaster_min_deaths": 100,      # smaller disasters and epidemics stay off the charts (still listed)
    "party_colours": False,          # country page charts coloured by the party in government
    "party_office": "government",    # whose party: the head of "government" (a prime minister) or of "state"
    "ranks_top_n": 10,               # Ranks panels show this many lines unless the panel says otherwise (0 = all)
    "forecast_horizon": 10,          # years the Forecast button on charts looks ahead
    "forecast_ranges": "80+95",      # ranges drawn around a forecast: "80+95", "80" or "none"
    "forecast_official": True,       # with Forecast on, also draw each forecaster's own projections (IMF, OECD, World Bank)
    "places_fetch": True,            # refresh fetches metro and rail, universities and companies from Wikidata (every 4 weeks)
    "pack_nz": True,                 # refresh fetches the New Zealand pack (RBNZ, MBIE energy, elections, justice)
    "holidays_fetch": True,          # refresh reads public holidays from Nager.Date (about 240 small requests every 90 days)
    "crisiswatch_fetch": True,       # refresh reads CrisisWatch (one month's page at a time, a few seconds apart)
    "crisiswatch_backfill": 12,      # older CrisisWatch months filled in per refresh, back to 2003 (0 = only the latest)
    "voting_compare": "USA,CHN,RUS,eu",  # who a country's UN votes are compared with on its Voting card
    # Relationship scan (after each refresh): which figures move together, which comes first
    "relations_scan": True,          # look for relationships after each refresh (and once after update.bat)
    "relations_indicators": "on",    # "on": the indicators switched on (about 120, some 7,000 pairs); "all": every one (overnight)
    "relations_min_countries": 30,   # a pair needs this many countries with data for both
    "relations_min_years": 10,       # and this many years of changes in each of those countries
    "relations_max_minutes": 15,     # stop and keep what is done after this long
    "relations_fdr": 0.05,           # share of reported pairs allowed to be chance finds (false discovery rate)
    # Sectors: one industry across the globe (trade from CEPII BACI, about 2 GB a year)
    "sectors_trade_fetch": True,     # refresh downloads BACI trade by product (every four months)
    "sectors_trade_from": 2005,      # first year of trade kept (BACI starts in 1995; earlier years make the warehouse bigger)
    "sectors_hidden": "",            # sectors left off the Sectors page, comma-separated ids
    # Climate
    "climate_fetch": True,           # refresh fetches the climate sources (temperatures, gases, storms, alerts, projections)
    "climate_storms_from": 1980,     # first year of storm tracks kept on the map (IBTrACS starts in 1980 in this file)
    "climate_live_map": True,        # the Climate page's storms map asks GDACS for the storms, floods and fires happening now
    # Local AI (Ollama on this PC or another; the app's server talks to it)
    "ai_enabled": True,              # Ask AI buttons, the AI notes page and the highlight menu's Ask AI
    "ollama_url": "http://localhost:11434",
    "ai_model": "",                  # default model; "" = the first one installed
    "ai_model_compare": "",          # the model offered for side-by-side answers; "" = none
    "ai_compare_default": False,     # each question goes to both models unless you take the second off
    "ai_temperature": 0.3,
    "ai_context_tokens": 16384,      # Ollama num_ctx: how much text the model reads at once
    "ai_context_default": "data,description,events,highlight",  # context parts ticked by default
    "ai_search_engine": "brave",     # "brave" (needs BRAVE_API_KEY; can cost money), "searxng" (free, local) or "off"
    "searxng_url": "http://localhost:8080",
    "ai_search_results": 5,          # web results given to the model per question
    "ai_search_default": True,       # Search the web is ticked when the Ask AI box opens
    "brave_daily_limit": 30,         # Brave searches a day; 0 = no limit
    "brave_monthly_limit": 0,        # Brave searches a month; 0 = no limit
    "brave_free_monthly": 1000,      # searches the monthly credit covers ($5 at $5 per 1,000)
    "brave_price_per_1000": 5.0,     # US dollars per 1,000 searches past the credit
    "highlight_menu": True,          # selecting text on a page shows Ask AI / Save highlight
}
CHOICES = {"click_mode": ("popup", "select"), "party_office": ("government", "state"),
           "forecast_ranges": ("80+95", "80", "none"), "ai_search_engine": ("brave", "searxng", "off"),
           "base_map": ("online", "local", "plain"),
           "relations_indicators": ("on", "all")}
# Free text settings (addresses and model names), kept to one line.
TEXTS = {"ollama_url", "ai_model", "ai_model_compare", "searxng_url"}
URLS = {"ollama_url", "searxng_url"}
IDS = {"profile_average"}
IDLISTS = {"profile_charts", "profile_cards_hidden", "voting_compare", "sectors_hidden"}  # comma-separated ids, order kept
PROFILES = {"profile_saved"}  # name -> {"charts": idlist, "hidden": idlist}, at most 30
RANGES = {"disk_limit_gb": (1, 10_000), "pictures_limit_gb": (0.1, 1_000), "basemap_limit_gb": (0.1, 5_000),
          "basemap_world_zoom": (4, 15), "basemap_region_zoom": (8, 15), "numbeo_daily": (0, 200),
          "wikipedia_countries_daily": (0, 500), "wikipedia_cities_daily": (0, 500),
          "history_retention_days": (0, 36_500), "disaster_min_deaths": (0, 1_000_000),
          "ranks_top_n": (0, 300), "crisiswatch_backfill": (0, 300), "forecast_horizon": (1, 50),
          "relations_min_countries": (5, 200), "relations_min_years": (5, 60), "relations_max_minutes": (1, 1440),
          "relations_fdr": (0.001, 0.25), "sectors_trade_from": (1995, 2030), "climate_storms_from": (1980, 2030), "ai_temperature": (0, 2),
          "ai_context_tokens": (1024, 1_048_576), "ai_search_results": (1, 20), "brave_daily_limit": (0, 1_000_000),
          "brave_monthly_limit": (0, 10_000_000), "brave_free_monthly": (0, 10_000_000), "brave_price_per_1000": (0, 1_000)}
WARN_AT, CRITICAL_AT = 0.80, 0.95

# Disk categories, in display order. "pictures" is media/ and has its own limit.
CATEGORIES = [("raw", "Raw downloads"), ("vintages", "Vintages (Parquet)"), ("builds", "Warehouse builds"),
              ("reports", "Reports and logs"), ("pictures", "Pictures and pages"), ("basemap", "Map files"), ("user", "Your files"),
              ("other", "Other")]


def home() -> Path:
    if os.environ.get("WORLDMODEL_HOME"):
        return Path(os.environ["WORLDMODEL_HOME"]).expanduser()
    wh = os.environ.get("WORLDMODEL_WAREHOUSE", "")
    if wh and Path(wh).expanduser().is_dir():
        return Path(wh).expanduser()
    return Path.cwd() / "var"


def user_dir() -> Path:
    """WORLDMODEL_USER_DIR, else WORLDMODEL_HOME/user, else ./var/user (where layouts have always been)."""
    if os.environ.get("WORLDMODEL_USER_DIR"):
        return Path(os.environ["WORLDMODEL_USER_DIR"]).expanduser()
    h = os.environ.get("WORLDMODEL_HOME")
    return (Path(h).expanduser() if h else Path.cwd() / "var") / "user"


def refresh_log_path(root: Path | None = None) -> Path:
    return (root or home()) / "warehouse" / "refresh_log.jsonl"


# ----------------------------------------------------------------------------- settings
def _idlist(v) -> str:
    """Comma-separated ids, each checked, repeats dropped, order kept."""
    ids = [w.strip() for w in str(v or "").split(",")]
    return ",".join(dict.fromkeys(w for w in ids if re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", w)))[:8000]


def clean_settings(data: dict, base: dict | None = None) -> dict:
    """The known settings from data, each checked and held to its range; the rest
    (and anything invalid) come from base, else the defaults."""
    out = dict(base or SETTINGS)
    for key, default in SETTINGS.items():
        if key not in data:
            continue
        v = data[key]
        if isinstance(default, bool):
            out[key] = bool(v)
        elif key in PROFILES:
            if isinstance(v, str):
                try:
                    v = json.loads(v or "{}")
                except ValueError:
                    continue
            if not isinstance(v, dict):
                continue
            out[key] = {" ".join(str(name).split())[:40]: {f: _idlist(p.get(f)) for f in ("charts", "hidden")}
                        for name, p in list(v.items())[:30] if str(name).strip() and isinstance(p, dict)}
        elif key in CHOICES:
            if v in CHOICES[key]:
                out[key] = v
        elif key in IDLISTS:
            out[key] = _idlist(v)
        elif key in IDS:  # one entity id such as g20 or NZL, or "" for none
            t = str(v or "").strip()
            if re.fullmatch(r"[A-Za-z0-9_]{0,40}", t):
                out[key] = t
        elif key in TEXTS:
            t = " ".join(str(v or "").split())[:200]
            if key in URLS:
                t = t.rstrip("/")
                if not re.fullmatch(r"https?://[^\s/$.?#][^\s]*", t):
                    continue
            out[key] = t
        elif isinstance(default, str):  # a comma-separated list of words
            out[key] = ",".join(w for w in (x.strip().lower() for x in str(v).split(",")) if re.fullmatch(r"[a-z_]{1,30}", w))[:400]
        elif isinstance(default, (int, float)):
            try:
                num = float(v)
            except (TypeError, ValueError):
                continue
            lo, hi = RANGES[key]
            num = min(hi, max(lo, num))
            out[key] = int(num) if isinstance(default, int) else round(num, 4)
    return out


def load_settings(root: Path | None = None) -> dict:
    """Settings from the user folder (or root/user when given and no WORLDMODEL_USER_DIR)."""
    base = root / "user" if root and not os.environ.get("WORLDMODEL_USER_DIR") else user_dir()
    path = base / "settings.json"
    try:
        return clean_settings(json.loads(path.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(SETTINGS)


# ----------------------------------------------------------------------------- disk use
def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for dirpath, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def disk_usage(root: Path | None = None) -> dict[str, int]:
    """Bytes per category, plus "total"."""
    root = root or home()
    out = {k: 0 for k, _ in CATEGORIES}
    if not root.exists():
        return {**out, "total": 0}
    for child in root.iterdir():
        name = child.name
        if name == "warehouse":
            for sub in child.iterdir():
                out["builds" if sub.name == "builds" else "reports"] += _size(sub)
        elif name == "media":
            out["pictures"] += _size(child)
        elif name in out:
            out[name] += _size(child)
        else:
            out["other"] += _size(child)
    out["total"] = sum(out.values())
    return out


def level(used: float, limit: float) -> str:
    share = used / limit if limit else 0
    return "full" if share >= 1 else "critical" if share >= CRITICAL_AT else "warn" if share >= WARN_AT else "ok"


def storage(root: Path | None = None) -> dict:
    """Disk use against the limits in settings, with a warning level for each limit."""
    s = load_settings(root)
    root = root or home()
    use = disk_usage(root)
    disk, pics = s["disk_limit_gb"] * GB, s["pictures_limit_gb"] * GB
    limits = [
        {"key": "disk", "label": "Whole data folder", "used": use["total"], "limit": disk, "level": level(use["total"], disk)},
        {"key": "pictures", "label": "Pictures and pages", "used": use["pictures"], "limit": pics,
         "level": level(use["pictures"], pics)},
        {"key": "basemap", "label": "Map files", "used": use["basemap"], "limit": s["basemap_limit_gb"] * GB,
         "level": level(use["basemap"], s["basemap_limit_gb"] * GB)},
    ]
    order = ["ok", "warn", "critical", "full"]
    worst = max((lim["level"] for lim in limits), key=order.index)
    return {"home": str(root), "categories": [{"key": k, "label": label, "bytes": use[k]} for k, label in CATEGORIES],
            "total": use["total"], "limits": limits, "level": worst, "warn_at": WARN_AT, "critical_at": CRITICAL_AT,
            "freeable": sum(f["bytes"] for f in freeable_raw(root))}


def pictures_room(root: Path | None = None) -> int:
    """Bytes media/ may still grow by before the pictures limit in Settings."""
    limit = load_settings(root)["pictures_limit_gb"] * GB
    media = (root or home()) / "media"
    return int(limit - (_size(media) if media.exists() else 0))


# ----------------------------------------------------------------------------- freeing space
STAMP = re.compile(r"^\d{8}T\d{6}Z$")


def freeable_raw(root: Path | None = None, keep: int = 2) -> list[dict]:
    """Old raw downloads that can go: per source, all but the newest `keep` fetches,
    never one the download cache still points at. Vintages (the normalised data
    every build reads) are never offered."""
    root = root or home()
    raw = root / "raw"
    if not raw.exists():
        return []
    out = []
    for source in sorted(p for p in raw.iterdir() if p.is_dir()):
        try:
            cached = {Path(e["file"]).parent.as_posix() for e in
                      json.loads((source / "http_cache.json").read_text(encoding="utf-8")).values() if e.get("file")}
        except (FileNotFoundError, json.JSONDecodeError, AttributeError):
            cached = set()
        fetches = sorted((d for d in source.glob("*/*") if d.is_dir() and STAMP.match(d.name)
                          and d.parent.name != "_incoming"), key=lambda d: d.name)
        for d in fetches[:-keep] if keep else fetches:
            rel = d.relative_to(root).as_posix()
            if rel in cached:
                continue
            out.append({"source_id": source.name, "path": rel, "fetched": d.name, "bytes": _size(d)})
    return out


def free_raw(root: Path | None = None, keep: int = 2) -> dict:
    """Delete the old raw downloads listed by freeable_raw. Only ever on request."""
    root = root or home()
    removed, freed = [], 0
    for f in freeable_raw(root, keep):
        shutil.rmtree(root / f["path"], ignore_errors=True)
        if not (root / f["path"]).exists():
            removed.append(f["path"])
            freed += f["bytes"]
            try:  # drop the release folder too once it is empty
                (root / f["path"]).parent.rmdir()
            except OSError:
                pass
    return {"removed": removed, "freed_bytes": freed}


# ----------------------------------------------------------------------------- refresh log
def read_refresh_log(root: Path | None = None) -> list[dict]:
    """One record per refresh or build, oldest first. Builds from before the log
    existed are filled in from their reports and the stored vintages."""
    root = root or home()
    logged: list[dict] = []
    try:
        for line in refresh_log_path(root).read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    logged.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        pass
    known = {r.get("build_id") for r in logged}
    backfill = [r for r in _from_reports(root) if r["build_id"] not in known]
    return sorted(logged + backfill, key=lambda r: r.get("started_at") or "")


def _from_reports(root: Path) -> list[dict]:
    reports = root / "warehouse" / "reports"
    if not reports.exists():
        return []
    manifests = []
    for m in (root / "vintages").glob("*/*/manifest.json"):
        try:
            manifests.append(json.loads(m.read_text()))
        except (OSError, json.JSONDecodeError):
            pass
    out = []
    previous = ""
    for rep in sorted(reports.glob("*.md")):
        build_id = rep.stem
        try:
            started = datetime.strptime(build_id, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
            text = rep.read_text(encoding="utf-8")
        except (ValueError, OSError):
            continue
        counts = {s: 0 for s in ("pass", "warn", "fail", "skip")}
        for line in text.splitlines():
            cells = [c.strip() for c in line.split("|")]
            if len(cells) >= 5 and cells[3] in counts:
                counts[cells[3]] += 1
        # Vintages fetched since the previous build were what this build brought in.
        new = [m for m in manifests if previous < m.get("retrieved_at", "") <= started]
        out.append({
            "build_id": build_id, "kind": "build", "started_at": started, "finished_at": None, "backfilled": True,
            "status": "failed" if "FAILED" in text.split("\n", 3)[2] else "ok", "checks": counts,
            "sources": [{"source_id": m["source_id"], "status": "new", "vintage": m["vintage"], "rows": m.get("row_count"),
                         "download_bytes": sum(f.get("bytes", 0) for f in m.get("files", []))} for m in new],
            "disk": None,
        })
        previous = started
    return out


# ----------------------------------------------------------------------------- problems
# What a failed check means, by check id prefix (first match wins): title, what happened.
CHECK_MEANINGS = (
    ("dbt:unique_combination", "Duplicate rows",
     "A source gave two values for the same country, indicator and year, so the build stopped rather than pick one."),
    ("dbt:within_indicator_bounds", "Values outside the plausible range",
     "Some values are far outside the range set for their indicator, usually a slip or a change of units in the source."),
    ("dbt:not_null", "Required values missing", "Some rows lack a value the warehouse needs, such as a country or indicator."),
    ("dbt:relationships", "Rows that point at nothing",
     "Some rows name a country, indicator or source that the catalogue does not know."),
    ("dbt:accepted_values", "Unexpected codes", "Some rows carry a code (frequency, status, variant, type) that is not allowed."),
    ("dbt:assert_age_groups", "Age groups do not add up", "Population by age does not add up to the total population."),
    ("dbt:assert_", "Totals do not add up", "Totals for the world, continents or groups do not match their parts."),
    ("dbt:", "A warehouse step failed", "One of the steps that builds the warehouse tables stopped with an error."),
    ("coverage:", "Too few countries", "An indicator covers far fewer countries than expected."),
    ("shrinkage", "A source lost many rows",
     "Compared with the last good build, a source or indicator lost a large share of its rows; often a download "
     "cut short or a file whose layout changed."),
    ("spot:", "Known value does not match", "A value checked against its published figure no longer matches."),
    ("whatif:", "Population model check failed", "The population what-if model no longer reproduces the UN figures."),
)
AFTER_FAILED_BUILD = ("Nothing changed in the app: it keeps the last good data. Copy the details and send them "
                      "in the project thread to get it fixed.")
AFTER_FAILED_FETCH = ("The source kept its previous data and the rest of the refresh went ahead. If it keeps "
                      "happening, copy the details and send them in the project thread.")


def _meaning(check_id: str) -> tuple[str, str]:
    for prefix, title, explain in CHECK_MEANINGS:
        if check_id.startswith(prefix):
            return title, explain
    return check_id, "A validation check failed."


def _report_failures(root: Path, build_id: str | None) -> list[dict]:
    """The failed checks of a build from its report, for runs logged before failures were recorded."""
    if not build_id:
        return []
    try:
        text = (root / "warehouse" / "reports" / f"{build_id}.md").read_text(encoding="utf-8")
    except OSError:
        return []
    out, by_id, current = [], {}, None
    for line in text.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) >= 6 and cells[3] == "fail":
            by_id[cells[1]] = {"check_id": cells[1], "kind": cells[2], "detail": cells[4], "examples": []}
            out.append(by_id[cells[1]])
        elif line.startswith("## "):
            m = re.match(r"## Failing rows: (.+)$", line)
            current = by_id.get(m.group(1).strip()) if m else None
        elif current is not None and line.startswith("- ") and len(current["examples"]) < 12:
            current["examples"].append(line[2:])
    return out


def problems(root: Path | None = None) -> list[dict]:
    """Each distinct failure in the refresh log (a failed check, a source that could not be
    downloaded, a build that stopped), with how often it happened, when first and last,
    and whether it is still open (no successful run since). Open ones first, newest first."""
    root = root or home()
    try:
        from worldmodel_contract import catalogue
        names = {s.id: s.name for s in catalogue.sources().values()}
    except Exception:  # noqa: BLE001 - names are a nicety
        names = {}
    runs = read_refresh_log(root)
    found: dict[str, dict] = {}

    def note(key: str, when: str, run: dict, **info) -> None:
        p = found.setdefault(key, {"key": key, "times": 0, "first_seen": when, "in_a_row": 0, "runs": [], **info})
        p.update({k: v for k, v in info.items() if v not in (None, "", [])})
        p["times"] += 1
        p["last_seen"] = when
        p["build_id"] = run.get("build_id")
        p["runs"].append(when)

    builds: list[tuple[str, set[str] | None]] = []  # (when, failing check keys); None when not known
    fetches: dict[str, list[tuple[str, bool]]] = {}  # source -> (when, fetched ok)
    for run in runs:
        when = run.get("started_at") or ""
        for s in run.get("sources") or []:
            sid = s.get("source_id")
            if s.get("status") == "error":
                note(f"fetch:{sid}", when, run, kind="fetch", source_id=sid,
                     title=f"Download failed: {names.get(sid, sid)}",
                     explain="The source could not be fetched.", todo=AFTER_FAILED_FETCH,
                     summary=s.get("error") or "", examples=[])
            if s.get("status") in ("new", "unchanged", "error"):
                fetches.setdefault(sid, []).append((when, s.get("status") != "error"))
        if run.get("kind") == "load":  # files loaded by hand: they clear a refused download, but are not a build
            continue
        if run.get("status") == "ok":
            builds.append((when, set()))
            continue
        if run.get("status") != "failed":
            continue
        failures = run.get("failures")
        if failures is None:
            failures = _report_failures(root, run.get("build_id"))
        keys: set[str] | None = set()
        if not failures:
            error = run.get("error") or "the build stopped"
            key = "build:" + re.sub(r"\d+", "#", error.split(":")[0])[:80]
            note(key, when, run, kind="build", title="The build stopped", explain=error, todo=AFTER_FAILED_BUILD,
                 summary=error, examples=[])
            keys = None if "validation gate" in error else {key}  # gates failed but not recorded: unknown which
        for f in failures:
            cid = f.get("check_id", "?")
            title, explain = _meaning(cid)
            note(f"check:{cid}", when, run, kind="check", check_id=cid, title=title, explain=explain,
                 todo=AFTER_FAILED_BUILD, summary=f.get("detail") or "", examples=f.get("examples") or [])
            keys.add(f"check:{cid}")
        builds.append((when, keys))

    for p in found.values():
        # Each later attempt either shows the problem again or shows it gone; a build stops
        # on every failing check at once, so one failing on something else still clears it.
        if p["kind"] == "fetch":
            attempts = [(w, not ok) for w, ok in fetches.get(p["source_id"], [])]
        else:
            attempts = [(w, p["key"] in k) for w, k in builds if k is not None]
        p["fixed_at"] = next((w for w, hit in attempts if w > p["last_seen"] and not hit), None)
        p["open"] = p["fixed_at"] is None
        n = 0
        for w, hit in reversed([a for a in attempts if a[0] <= p["last_seen"]]):  # failures in a row up to the latest
            if not hit:
                break
            n += 1
        p["in_a_row"] = n
        p.pop("runs")
    out = sorted(found.values(), key=lambda p: p["last_seen"], reverse=True)
    return sorted(out, key=lambda p: not p["open"])
