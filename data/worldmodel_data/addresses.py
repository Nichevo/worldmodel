"""A weekly check that the addresses sources download from still answer.

Many sources are fetched monthly or yearly, so a moved file would only show up as a failed
download weeks later. Each successful download remembers the addresses it read (at most a
few per source, without their query strings, so no key is kept); a refresh then asks each
remembered address once a week (a HEAD request, or a one-byte GET where HEAD is refused)
for the sources it did not fetch that day, and Data status lists the ones that have gone.

Saved at <home>/warehouse/addresses.json:
  {"sources": {source_id: {"urls": [...], "at": iso}}, "checked_at": iso,
   "results": {source_id: [{"url", "status", "code", "note"}]}}
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

log = logging.getLogger(__name__)

PER_SOURCE = 3      # addresses remembered per source
GAP = 0.5           # seconds between requests to the same host
GONE = {404, 410}   # the address is no longer there
# Anything else under 500 counts as answering: 401/403 (needs a key or a browser), 405 (no
# HEAD), 400 (an API that wants its query), 429 (busy) all mean the address still exists.


def _file(home: Path) -> Path:
    return home / "warehouse" / "addresses.json"


def load(home: Path) -> dict:
    try:
        return json.loads(_file(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(home: Path, data: dict) -> None:
    f = _file(home)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(f)


def plain(url: str) -> str | None:
    """The address without query or fragment (keys travel there), or None if not http(s)."""
    try:
        u = urlsplit(str(url))
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not u.netloc or "@" in u.netloc:
        return None
    return urlunsplit((u.scheme, u.netloc, u.path or "/", "", ""))


def pick(urls: list[str]) -> list[str]:
    """Up to PER_SOURCE distinct addresses, spread over hosts first."""
    seen, out, hosts = set(), [], set()
    clean = [p for p in (plain(u) for u in urls) if p]
    for first_pass in (True, False):
        for u in clean:
            host = urlsplit(u).netloc
            if u in seen or (first_pass and host in hosts):
                continue
            seen.add(u)
            hosts.add(host)
            out.append(u)
            if len(out) >= PER_SOURCE:
                return out
    return out


def remember(home: Path, source_id: str, urls: list[str]) -> None:
    """Keep the addresses a successful download read."""
    chosen = pick(urls)
    if not chosen:
        return
    data = load(home)
    data.setdefault("sources", {})[source_id] = {"urls": chosen, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        _save(home, data)
    except OSError as exc:
        log.warning("could not keep the download addresses of %s: %s", source_id, exc)


def due(home: Path, every_days: float) -> bool:
    if not every_days:
        return False
    at = load(home).get("checked_at")
    if not at:
        return True
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(at) >= timedelta(days=every_days)
    except ValueError:
        return True


def ask(client: httpx.Client, url: str) -> dict:
    """One address: ok, gone (404/410) or down (no answer, or a server error)."""
    try:
        r = client.head(url)
        if r.status_code in (405, 501) or r.status_code in GONE:
            # Some servers answer HEAD wrongly; a one-byte GET settles it.
            with client.stream("GET", url, headers={"Range": "bytes=0-0"}) as g:
                r = g
        code = r.status_code
    except httpx.HTTPError as exc:
        return {"url": url, "status": "down", "code": None, "note": exc.__class__.__name__}
    if code in GONE:
        return {"url": url, "status": "gone", "code": code, "note": f"the site says {code}: the file has moved or been removed"}
    if code >= 500:
        return {"url": url, "status": "down", "code": code, "note": f"the site answered {code} (may be a bad day)"}
    return {"url": url, "status": "ok", "code": code, "note": ""}


def check(home: Path, skip: set[str] | None = None, client: httpx.Client | None = None, say=print) -> dict:
    """Ask every remembered address (except the sources in skip, fetched just now); save and
    return {source_id: [result, ...]} for the sources with an address that did not answer."""
    from worldmodel_data.connectors.base import USER_AGENT

    data = load(home)
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True)
    results: dict[str, list] = {}
    last_at: dict[str, float] = {}
    try:
        for source_id, entry in sorted((data.get("sources") or {}).items()):
            if skip and source_id in skip:
                continue
            for url in entry.get("urls", []):
                host = urlsplit(url).netloc
                wait = GAP - (time.monotonic() - last_at.get(host, 0.0))
                if wait > 0:
                    time.sleep(wait)
                results.setdefault(source_id, []).append(ask(client, url))
                last_at[host] = time.monotonic()
    finally:
        if own:
            client.close()
    bad = {s: rows for s, rows in results.items() if any(r["status"] != "ok" for r in rows)}
    data = load(home)  # a download may have remembered something meanwhile
    data["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["checked"] = len(results)
    data["results"] = bad
    _save(home, data)
    gone = [s for s, rows in bad.items() if any(r["status"] == "gone" for r in rows)]
    say(f"Download addresses: {len(results)} sources checked, {len(gone)} with a file that has gone"
        + (f" ({', '.join(gone)})" if gone else "") + (f", {len(bad) - len(gone)} not answering" if len(bad) > len(gone) else "") + ".")
    return bad
