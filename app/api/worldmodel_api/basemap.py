"""The local map file: street-level detail under the map's colours without going online.

Settings > Map picks where the detail comes from: "online" (OpenFreeMap's free tiles,
nothing stored), "local" (files made here, kept in <data folder>/basemap/) or "plain".

The local files are cut from the Protomaps daily planet build (OpenStreetMap data, ODbL)
with the go-pmtiles tool, which reads only the parts it needs:

    world.pmtiles   the whole world down to basemap_world_zoom (8: towns, motorways, rail)
    <ISO3>.pmtiles  each country in basemap_regions down to basemap_region_zoom (15: every street)

    https://build-metadata.protomaps.dev/builds.json      the list of daily builds
    https://build.protomaps.com/<yyyymmdd>.pmtiles         one build (about 120 GB; never downloaded whole)
    https://github.com/protomaps/go-pmtiles/releases       the tool (one program, downloaded once)
    https://github.com/protomaps/basemaps-assets           the fonts for place names

"Check size" runs the tool with --dry-run and shows how big the files would be; "Make map
files" (and "Refresh map file" later) runs it for real in the background. Both say what
went wrong in plain words; nothing is deleted until the new file is complete.
"""

from __future__ import annotations

import io
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import tarfile
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

from worldmodel_contract import local

log = logging.getLogger(__name__)

BUILDS = "https://build-metadata.protomaps.dev/builds.json"
BUILD_URL = "https://build.protomaps.com/{key}"
TOOL_RELEASES = "https://api.github.com/repos/protomaps/go-pmtiles/releases/latest"
ASSETS_ZIP = "https://github.com/protomaps/basemaps-assets/archive/refs/heads/main.zip"
FONTS = ("Noto Sans Regular", "Noto Sans Medium", "Noto Sans Italic")
SHAPES = Path(__file__).resolve().parents[2] / "web" / "public" / "geo" / "countries.json"
USER_AGENT = "worldmodel/0.1 (personal local tool) httpx"

_lock = threading.Lock()
_job: dict = {"state": "idle"}


def root() -> Path:
    return local.home() / "basemap"


def _client(timeout: float = 60) -> httpx.Client:
    return httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT})


def _human(n: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} TB"


# ----------------------------------------------------------------------------- what is there
def files() -> list[dict]:
    """The map files on disk, world first."""
    d = root()
    if not d.is_dir():
        return []
    meta = _read(d / "files.json") or {}
    out = []
    for p in sorted(d.glob("*.pmtiles"), key=lambda p: (p.stem != "world", p.stem)):
        m = meta.get(p.name, {})
        out.append({"name": p.name, "region": p.stem, "bytes": p.stat().st_size, "made": m.get("made"),
                    "build": m.get("build"), "maxzoom": m.get("maxzoom")})
    return out


def fonts_ready() -> bool:
    return (root() / "fonts" / FONTS[0] / "0-255.pbf").exists()


def status() -> dict:
    s = local.load_settings()
    with _lock:
        job = dict(_job)
    return {"files": files(), "fonts": fonts_ready(), "tool": _tool_path() is not None, "job": job,
            "regions": regions(s), "world_zoom": s["basemap_world_zoom"], "region_zoom": s["basemap_region_zoom"],
            "base_map": s["base_map"]}


def regions(settings: dict | None = None) -> list[str]:
    s = settings or local.load_settings()
    return [r.upper() for r in str(s.get("basemap_regions") or "").split(",") if r.strip()]


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ----------------------------------------------------------------------------- the tool
def _tool_path() -> Path | None:
    for name in ("pmtiles.exe", "pmtiles"):
        p = root() / "tool" / name
        if p.exists():
            return p
    found = shutil.which("pmtiles")
    return Path(found) if found else None


def asset_for(assets: list[dict], system: str | None = None, machine: str | None = None) -> dict | None:
    """The release asset for this computer: Windows/Linux/Darwin and x86_64/arm64."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
    for a in assets:
        n = a["name"].lower()
        if system in n and arch in n and (n.endswith(".zip") or n.endswith(".tar.gz")):
            return a
    return None


def get_tool(client: httpx.Client) -> Path:
    have = _tool_path()
    if have:
        return have
    r = client.get(TOOL_RELEASES)
    r.raise_for_status()
    asset = asset_for(r.json().get("assets", []))
    if not asset:
        raise RuntimeError(f"no go-pmtiles download for {platform.system()} {platform.machine()}; "
                           "download pmtiles from github.com/protomaps/go-pmtiles/releases into "
                           f"{root() / 'tool'}")
    body = client.get(asset["browser_download_url"]).content
    out = root() / "tool"
    out.mkdir(parents=True, exist_ok=True)
    if asset["name"].lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            for m in z.namelist():
                if Path(m).name in ("pmtiles", "pmtiles.exe"):
                    (out / Path(m).name).write_bytes(z.read(m))
    else:
        with tarfile.open(fileobj=io.BytesIO(body)) as t:
            for m in t.getmembers():
                if Path(m.name).name == "pmtiles" and m.isfile():
                    (out / "pmtiles").write_bytes(t.extractfile(m).read())  # type: ignore[union-attr]
    tool = _tool_path()
    if not tool:
        raise RuntimeError(f"the go-pmtiles download {asset['name']} had no pmtiles program in it")
    if os.name != "nt":
        tool.chmod(0o755)
    return tool


def get_fonts(client: httpx.Client) -> None:
    if fonts_ready():
        return
    body = client.get(ASSETS_ZIP).content
    out = root() / "fonts"
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        for m in z.namelist():
            parts = Path(m).parts
            if len(parts) >= 4 and parts[1] == "fonts" and parts[2] in FONTS and m.endswith(".pbf"):
                p = out / parts[2] / parts[3]
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(z.read(m))
    if not fonts_ready():
        raise RuntimeError("the fonts download had no Noto Sans fonts in it")


def latest_build(client: httpx.Client) -> str:
    """The newest Protomaps build's file name, such as 20261101.pmtiles."""
    r = client.get(BUILDS)
    r.raise_for_status()
    keys = sorted(b["key"] for b in r.json() if str(b.get("key", "")).endswith(".pmtiles"))
    if not keys:
        raise RuntimeError(f"{BUILDS} lists no builds")
    return keys[-1]


# ----------------------------------------------------------------------------- the regions
def region_file(iso3: str) -> Path:
    """The country's own outline as a GeoJSON file, for the tool's --region."""
    shapes = json.loads(SHAPES.read_text(encoding="utf-8"))
    for f in shapes["features"]:
        if (f.get("properties") or {}).get("iso3") == iso3:
            p = root() / "work" / f"{iso3}.geojson"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"type": "FeatureCollection", "features": [f]}), encoding="utf-8")
            return p
    raise RuntimeError(f"no country outline for {iso3}")


def plan(settings: dict | None = None) -> list[dict]:
    """The files to make: the world, then each full-detail country."""
    s = settings or local.load_settings()
    out = [{"name": "world.pmtiles", "region": "world", "maxzoom": int(s["basemap_world_zoom"])}]
    out += [{"name": f"{r}.pmtiles", "region": r, "maxzoom": int(s["basemap_region_zoom"])} for r in regions(s)]
    return out


SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*(B|kB|KB|MB|GB|TB|KiB|MiB|GiB|TiB)\b")
UNITS = {"b": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12, "kib": 2 ** 10, "mib": 2 ** 20, "gib": 2 ** 30, "tib": 2 ** 40}


def size_from(text: str) -> float | None:
    """The size the tool's --dry-run reports (its last size on a line that says total or size)."""
    found = None
    for line in text.splitlines():
        if re.search(r"total|size|archive", line, re.I):
            for v, u in SIZE.findall(line):
                found = float(v) * UNITS[u.lower()]
    return found


def _args(tool: Path, build: str, item: dict, out: Path, dry: bool) -> list[str]:
    a = [str(tool), "extract", BUILD_URL.format(key=build), str(out), f"--maxzoom={item['maxzoom']}"]
    if item["region"] != "world":
        a.append(f"--region={region_file(item['region'])}")
    if dry:
        a.append("--dry-run")
    return a


def _run(args: list[str], timeout: float | None) -> str:
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    text = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        raise RuntimeError(text.strip().splitlines()[-1] if text.strip() else f"pmtiles stopped with code {p.returncode}")
    return text


def estimate() -> dict:
    """How big the files would be, without making them."""
    with _client() as client:
        tool = get_tool(client)
        build = latest_build(client)
    items = []
    for item in plan():
        text = _run(_args(tool, build, item, root() / "work" / item["name"], dry=True), timeout=600)
        items.append({**item, "bytes": size_from(text)})
    total = sum(i["bytes"] or 0 for i in items)
    return {"build": build, "items": items, "bytes": total, "size": _human(total), **room(total)}


def room(need: float) -> dict:
    s = local.load_settings()
    have = sum(f["bytes"] for f in files())
    limit = s["basemap_limit_gb"] * local.GB
    free = shutil.disk_usage(local.home() if local.home().exists() else Path.cwd()).free
    fits = need <= limit and need <= free + have
    why = None if fits else (f"needs {_human(need)} but the map files limit is {_human(limit)} (Settings > Storage)"
                             if need > limit else f"needs {_human(need)} but the disk has {_human(free)} free")
    return {"fits": fits, "why": why}


# ----------------------------------------------------------------------------- making the files
def start() -> dict:
    with _lock:
        if _job.get("state") == "running":
            return dict(_job)
        _job.clear()
        _job.update(state="running", step="Getting ready", started=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    threading.Thread(target=_make, daemon=True).start()
    return dict(_job)


def _step(text: str) -> None:
    with _lock:
        _job["step"] = text
    log.info("basemap: %s", text)


def _make() -> None:
    try:
        with _client(timeout=600) as client:
            _step("Getting the map tool (once)")
            tool = get_tool(client)
            _step("Getting the fonts for place names (once)")
            get_fonts(client)
            build = latest_build(client)
        meta = _read(root() / "files.json") or {}
        for item in plan():
            _step(f"Making {item['name']} (down to zoom {item['maxzoom']}) from the {build[:8]} build")
            tmp = root() / "work" / item["name"]
            tmp.parent.mkdir(parents=True, exist_ok=True)
            _run(_args(tool, build, item, tmp, dry=False), timeout=None)
            tmp.replace(root() / item["name"])
            meta[item["name"]] = {"made": datetime.now(timezone.utc).isoformat(timespec="seconds"), "build": build,
                                  "maxzoom": item["maxzoom"]}
            (root() / "files.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        with _lock:
            _job.update(state="done", step="Map files ready", finished=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    except Exception as exc:  # shown on the Settings page
        log.warning("basemap: %s", exc)
        with _lock:
            _job.update(state="failed", error=_explain(exc))


def _explain(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPError):
        return f"Could not reach the map download site ({exc}). Check the internet connection and try again."
    if isinstance(exc, FileNotFoundError):
        return f"A file was missing: {exc}"
    return str(exc)


def remove(name: str) -> bool:
    p = root() / name
    if p.suffix != ".pmtiles" or p.parent != root() or not p.exists():
        return False
    p.unlink()
    return True
