"""Storage, the refresh log and looking after the sources."""

from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta

from fastapi import Body, HTTPException, Query

from worldmodel_contract import catalogue, local
from worldmodel_api import numbeo, relationships, userdata, wiki
from worldmodel_api import upkeep as upkeep_jobs
from worldmodel_api.core import api, rows


# ----------------------------------------------------------------------------- storage, refresh log
@api.get("/storage")
def storage():
    """Disk use of the data folder by category against the limits in Settings, with warning levels."""
    return local.storage()


@api.post("/storage/free-up")
def free_up(keep: int = Query(2, ge=1, le=10)):
    """Delete old raw downloads, keeping the newest `keep` per source. Never vintages or builds."""
    return local.free_raw(keep=keep)


@api.get("/refresh-log")
def refresh_log():
    """One record per refresh or build, oldest first (see worldmodel_data.monitor)."""
    return local.read_refresh_log()


@api.get("/manual-files")
def manual_files():
    """Files you save by hand: each source that needs one always (by_hand) or when its site
    refuses a refresh, with where to get it, what is in its var/manual folder, when it was
    last loaded, and whether anything needs doing now."""
    from datetime import datetime, timezone
    folder_root = local.home() / "manual"
    loaded = {r["source_id"]: r["retrieved_at"] for r in rows(
        "SELECT source_id, max(retrieved_at) AS retrieved_at FROM vintages GROUP BY source_id")}
    failing = {p["source_id"]: p for p in local.problems() if p.get("kind") == "fetch" and p.get("open")}
    out = []
    for s in catalogue.sources().values():
        if not s.manual:
            continue
        folder = folder_root / s.id
        files = sorted((f for f in folder.iterdir() if f.is_file() and not f.name.startswith(("_", ".", "~$"))),
                       key=lambda f: f.stat().st_mtime, reverse=True) if folder.is_dir() else []
        last = loaded.get(s.id)
        last_dt = datetime.fromisoformat(str(last)) if last else None
        if last_dt and last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        newest = datetime.fromtimestamp(files[0].stat().st_mtime, timezone.utc) if files else None
        if newest and (last_dt is None or newest > last_dt):
            todo, why = "load", f"{files[0].name} is in the folder but not loaded yet"
        elif s.manual.by_hand and last is None and not s.manual.optional:
            todo, why = "download", "Not loaded yet"
        elif s.id in failing:
            todo, why = "download", f"The last refresh could not download it ({failing[s.id].get('summary') or 'refused'})"
        else:
            todo, why = None, ""
        out.append({"source_id": s.id, "name": s.name, "by_hand": s.manual.by_hand, "optional": s.manual.optional, "get": s.manual.get,
                    "what": s.manual.what, "cadence": s.cadence, "folder": f"var\\manual\\{s.id}",
                    "files": [f.name for f in files[:5]], "last_loaded": str(last) if last else None,
                    "todo": todo, "why": why, "command": f".\\load.bat {s.id}"})
    out.sort(key=lambda r: (r["todo"] is None, not r["by_hand"], r["name"]))
    return out


@api.get("/scrapers")
def scrapers():
    """Sources read from web pages (the scraping tools): how each runs, what it reads, the
    setting that governs it, when it last ran, how far it got and why it stopped, if it did."""
    settings = local.load_settings()
    runs = local.read_scrape_log()
    loaded = {r["source_id"]: r["retrieved_at"] for r in rows(
        "SELECT source_id, max(retrieved_at) AS retrieved_at FROM vintages GROUP BY source_id")}
    failing = {p["source_id"]: p for p in local.problems() if p.get("kind") == "fetch" and p.get("open")}
    out = []
    for s in catalogue.sources().values():
        if not s.scraper:
            continue
        today = None
        if s.id == "numbeo":
            b = numbeo.budget()
            today = f"{b['used']} of {b['limit']} pages today"
        elif s.id == "wikipedia":
            c, t, e = wiki.budget("countries"), wiki.budget("cities"), wiki.budget("empires")
            today = (f"{c['used']} of {c['limit']} countries, {t['used']} of {t['limit']} cities and "
                     f"{e['used']} of {e['limit']} empires today")
        last = loaded.get(s.id)
        prob = failing.get(s.id)
        out.append({"source_id": s.id, "name": s.name, "run": s.scraper.run, "reads": s.scraper.reads,
                    "setting": s.scraper.setting or None,
                    "setting_value": settings.get(s.scraper.setting) if s.scraper.setting else None,
                    "last_run": runs.get(s.id), "last_loaded": str(last) if last else None, "today": today,
                    "problem": (prob.get("summary") or "the last refresh failed") if prob else None})
    out.sort(key=lambda r: (r["problem"] is None and not (r["last_run"] or {}).get("stopped"), r["name"]))
    return {"gap_seconds": settings.get("scrape_gap_seconds"), "sources": out}


@api.get("/fetch-methods")
def fetch_methods_list():
    """How each source is fetched: what it can do (refresh from the site, verify.bat in your
    browser, your own file), what you chose, what Automatic chose and why, and how its last
    refresh went. Written by the data side on every refresh and update.bat."""
    from worldmodel_contract import fetch_methods as fm
    state = fm.read_state()
    choices = fm.read_choices()
    meta = catalogue.sources()
    last: dict[str, dict] = {}
    for run in local.read_refresh_log():
        for s in run.get("sources") or []:
            if s.get("source_id"):
                last[s["source_id"]] = {"at": run.get("started_at"), "status": s.get("status"),
                                        "note": s.get("error") or s.get("note") or ""}
    out = []
    for sid, e in sorted((state.get("sources") or {}).items()):
        can = [m for m in e.get("can") or [] if m in fm.METHODS]
        choice = choices.get(sid) if choices.get(sid) in can else None
        auto = e.get("auto") if e.get("auto") in can else None
        m = meta.get(sid)
        out.append({"source_id": sid, "name": m.name if m else sid, "can": can, "kind": e.get("kind"),
                    "kind_label": fm.SITE_KINDS.get(e.get("kind") or "", ""), "choice": choice or "auto",
                    "auto": auto or fm.effective(None, None, can), "method": fm.effective(choice, auto, can),
                    "since": e.get("since"), "why": e.get("why") if auto and auto != "site" else None,
                    "retry_from": e.get("retry_from") if not choice else None,
                    "last_kind": e.get("last_kind"), "last_error": e.get("last_error"), "last": last.get(sid)})
    return {"written_at": state.get("written_at"), "labels": fm.LABELS, "kinds": fm.SITE_KINDS,
            "blocked_in_a_row": fm.BLOCKED_IN_A_ROW, "sources": out}


@api.put("/fetch-methods/{source_id}")
def fetch_methods_set(source_id: str, change: dict = Body(...)):
    """Choose how one source is fetched: {"method": "auto" | "site" | "verify" | "file"}."""
    from worldmodel_contract import fetch_methods as fm
    e = (fm.read_state().get("sources") or {}).get(source_id)
    if e is None:
        raise HTTPException(404, f"no source {source_id} (run update.bat if it is new)")
    method = change.get("method")
    if method != "auto" and method not in (e.get("can") or []):
        raise HTTPException(422, f"{source_id} can be fetched by: auto, {', '.join(e.get('can') or [])}")
    fm.set_choice(source_id, method)
    return next(r for r in fetch_methods_list()["sources"] if r["source_id"] == source_id)


@api.get("/problems")
def problems():
    """Each distinct failure in the refresh log, with how often it happened and whether it is still open."""
    return local.problems()


# ----------------------------------------------------------------------------- looking after the sources
def _todo_state() -> dict:
    try:
        data = json.loads((local.user_dir() / "todo.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _source_uses() -> dict[str, list[str]]:
    """source -> names of the indicators that read it."""
    out: dict[str, list[str]] = {}
    for i in catalogue.indicators().values():
        for s in i.sources:
            out.setdefault(s.source_id, []).append(i.name)
    return out


def _todo_items() -> list[dict]:
    """Everything that needs you, each once: files waiting for a source, files to save or
    load, sources failing, keys missing and forms to fill in. Things being handled by
    themselves (retrying, not due yet) stay out."""
    from worldmodel_contract import inbox as inbox_mod

    s = userdata.settings()
    off = set(filter(None, (s.get("sources_off") or "").split(",")))
    uses = _source_uses()
    names = {x.id: x.name for x in catalogue.sources().values()}
    items: list[dict] = []

    def add(key: str, kind: str, title: str, why: str, *, source_id: str | None = None, link: str | None = None,
            command: str | None = None, button: str | None = None, what: str | None = None, folder: str | None = None,
            order: int = 5, **extra) -> None:
        n = len(uses.get(source_id or "", []))
        items.append({"key": key, "kind": kind, "title": title, "why": why, "source_id": source_id, "link": link,
                      "command": command, "button": button, "what": what, "folder": folder, "uses": n,
                      "uses_names": uses.get(source_id or "", [])[:6], "order": order, **extra})

    box = inbox_mod.state(local.home(), s)
    for w in box["waiting"]:
        add(f"inbox:{w['name']}", "inbox", f"Which source is {w['name']}?",
            "It is in the inbox, but the app could not tell which source it belongs to." if not w["candidates"]
            else f"It could be {', '.join(w['candidate_names'].values())}.", button="assign", order=0,
            name=w["name"], candidates=w["candidates"])
    handled = set()
    for m in manual_files():
        if not m["todo"] or m["source_id"] in off:
            continue
        handled.add(m["source_id"])
        if m["todo"] == "load":
            add(f"load:{m['source_id']}", "load", f"Load {m['name']}", m["why"], source_id=m["source_id"],
                command=m["command"], button="load", folder=m["folder"], order=1)
        else:
            add(f"file:{m['source_id']}", "download", f"Save the file for {m['name']}", m["why"], source_id=m["source_id"],
                link=m["get"], what=m["what"], folder=m["folder"], button="get", order=3)
    try:
        ways = {r["source_id"]: r["method"] for r in fetch_methods_list()["sources"]}
    except Exception:  # noqa: BLE001 - written by the data side; may be missing
        ways = {}
    for p in local.problems():
        if not p.get("open"):
            continue
        sid = p.get("source_id")
        if sid in handled or sid in off:
            continue
        if p.get("kind") == "fetch" and sid:
            verify = ways.get(sid) == "verify"
            add(f"problem:{p['key']}", "failing", f"{names.get(sid, sid)} did not download",
                (p.get("summary") or "The last refresh could not fetch it.")[:400], source_id=sid,
                command=f".\\verify.bat {sid}" if verify else None, button="refresh", order=2, times=p.get("times"))
        else:
            add(f"problem:{p['key']}", "check", p.get("title") or "A check failed",
                (p.get("summary") or p.get("explain") or "")[:400], source_id=sid, order=2, times=p.get("times"),
                todo_text=p.get("todo"))
    for k in relationships.keys():
        if not k["active"] or k["source"] in off:
            continue
        missing = [e["name"] for e in k["env"] if not e["set"]]
        if missing:
            add(f"key:{k['source']}", "key", f"Add the key for {k['name']}", k.get("unlocks") or "", source_id=k["source"],
                link=k.get("signup"), button="key", order=4, env=missing)
    for sid, info in inbox_mod.source_info(local.home()).items():
        if sid in off:
            continue
        blank = [v for v in info.get("needs_settings") or [] if not s.get(v)]
        if blank:
            add(f"form:{sid}", "form", f"Fill in the form for {names.get(sid, sid)}",
                "Its site asks who is downloading; the refresh fetches it once the form in Settings is filled in.",
                source_id=sid, link="/settings", order=4)
    if s.get("find_data", True):
        from worldmodel_api import dateno
        for w in dateno.wishes():
            where = ", ".join(filter(None, [w.get("publisher"), ", ".join(w.get("countries") or [])]))
            add(f"wish:{w['id']}", "wish", f"Make a source from {w['title']}",
                " · ".join(filter(None, [where, " ".join(w.get("formats") or []), w.get("licence"), w.get("note")])) or "Kept from Find data.",
                link=w.get("url"), order=6, wish_id=w["id"])
    items.sort(key=lambda r: (r["order"], -r["uses"], r["title"]))
    return items


def _sig(item: dict) -> str:
    return f"{item['kind']}|{item['why'][:200]}"


@api.get("/todo")
def todo():
    """The To do list: items that need you, without those you marked done (until they change)
    or snoozed (until the date passes)."""
    st = _todo_state()
    today = date.today().isoformat()
    shown, hidden = [], []
    for it in _todo_items():
        mark = st.get(it["key"]) or {}
        if mark.get("done") == _sig(it) or (mark.get("snooze_until") or "") > today:
            hidden.append({**it, "mark": mark})
        else:
            shown.append(it)
    # Datasets kept from Find data wait on a source being written, not on you: listed, not counted on the menu.
    return {"items": shown, "count": sum(1 for i in shown if i["kind"] != "wish"), "hidden": hidden}


@api.put("/todo/{key:path}")
def todo_mark(key: str, change: dict = Body(...)):
    """Mark an item: {"action": "done"} (hidden until it changes), {"action": "snooze", "days": 7},
    or {"action": "clear"} (shown again)."""
    st = _todo_state()
    item = next((i for i in _todo_items() if i["key"] == key), None)
    action = change.get("action")
    if action == "clear":
        st.pop(key, None)
    elif item is None:
        raise HTTPException(404, "no such item (it may have been dealt with already)")
    elif action == "done":
        st[key] = {"done": _sig(item), "at": date.today().isoformat()}
    elif action == "snooze":
        days = max(1, min(365, int(change.get("days") or 7)))
        st[key] = {"snooze_until": (date.today() + timedelta(days=days)).isoformat()}
    else:
        raise HTTPException(422, "action is done, snooze or clear")
    path = local.user_dir() / "todo.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(st, indent=1), encoding="utf-8")
    return todo()


@api.get("/inbox")
def inbox_state():
    """Files waiting in the inbox (with the app's guess), files filed lately, and the folders the app looks in."""
    from worldmodel_contract import inbox as inbox_mod
    return inbox_mod.state(local.home(), userdata.settings())


@api.post("/inbox/assign")
def inbox_assign(change: dict = Body(...)):
    """File one waiting file into the source you chose ({"name", "source_id"}) and load it; the
    app remembers files named like it."""
    from worldmodel_contract import inbox as inbox_mod
    sid = str(change.get("source_id") or "")
    if sid not in catalogue.sources():
        raise HTTPException(422, f"unknown source {sid}")
    try:
        e = inbox_mod.assign(str(change.get("name") or ""), sid, local.home())
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except OSError as exc:
        raise HTTPException(409, f"could not move it: {exc}")
    try:
        job = upkeep_jobs.start("load", [sid])
    except RuntimeError as exc:
        job = {"note": f"{exc} It loads at the next refresh."}
    return {"filed": e, "job": job}


@api.get("/jobs")
def jobs_status():
    """The refresh, inbox, download or backup job running now (or the last one), with its console lines and progress."""
    return upkeep_jobs.status()


@api.post("/jobs")
def jobs_start(change: dict = Body(...)):
    """Start a job: {"kind": "refresh" | "inbox" | "get" | "backup" | "load", "sources": [...] (optional)}."""
    kind = str(change.get("kind") or "")
    known = set(catalogue.sources())
    sources = [x for x in (change.get("sources") or []) if x in known]
    try:
        return upkeep_jobs.start(kind, sources)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except OSError as exc:
        raise HTTPException(500, f"could not start it: {exc}")


_HEALTH_SIZES: dict = {"at": 0.0, "sizes": {}}


def _source_sizes() -> dict[str, int]:
    """Bytes on disk per source (downloads and stored vintages), worked out at most every 10 minutes."""
    import time as _t
    if _t.monotonic() - _HEALTH_SIZES["at"] < 600 and _HEALTH_SIZES["sizes"]:
        return _HEALTH_SIZES["sizes"]
    out: dict[str, int] = {}
    for part in ("raw", "vintages", "manual"):
        base = local.home() / part
        if not base.is_dir():
            continue
        for d in base.iterdir():
            if d.is_dir():
                total = 0
                for dirpath, _, files in os.walk(d):
                    for f in files:
                        try:
                            total += os.path.getsize(os.path.join(dirpath, f))
                        except OSError:
                            pass
                out[d.name] = out.get(d.name, 0) + total
    _HEALTH_SIZES.update(at=_t.monotonic(), sizes=out)
    return out


@api.get("/address-check")
def address_check():
    """The weekly check of download addresses: when it last ran and the sources whose
    remembered addresses did not answer (gone: 404/410; down: no answer or a server error)."""
    try:
        got = json.loads((local.home() / "warehouse" / "addresses.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        got = {}
    every = userdata.settings().get("address_check_days", 7)
    bad = [{"source_id": s, "results": r, "gone": any(x.get("status") == "gone" for x in r)}
           for s, r in sorted((got.get("results") or {}).items())]
    return {"checked_at": got.get("checked_at"), "checked": got.get("checked", 0),
            "remembered": len(got.get("sources") or {}), "every_days": every, "problems": bad}


@api.get("/source-health")
def source_health():
    """Every source in one table: how it is doing, when it last worked, when it is next due,
    how it is fetched, its size on disk, rows loaded, what reads it, and whether it is switched off."""
    from datetime import datetime as _dt
    from worldmodel_contract import inbox as inbox_mod
    s = userdata.settings()
    off = set(filter(None, (s.get("sources_off") or "").split(",")))
    info = inbox_mod.source_info(local.home())
    vint = {r["source_id"]: r for r in rows(
        "SELECT source_id, max(retrieved_at) AS loaded, arg_max(row_count, retrieved_at) AS rows_n, "
        "arg_max(release, retrieved_at) AS release FROM vintages GROUP BY source_id")}
    last_ok: dict[str, str] = {}
    last_note: dict[str, str] = {}
    for run in local.read_refresh_log():
        for e in run.get("sources") or []:
            sid = e.get("source_id")
            if e.get("status") in ("new", "unchanged"):
                last_ok[sid] = run.get("started_at") or ""
            if sid:
                last_note[sid] = e.get("error") or e.get("note") or ""
    failing = {p["source_id"]: p for p in local.problems() if p.get("kind") == "fetch" and p.get("open")}
    try:
        ways = {r["source_id"]: r for r in fetch_methods_list()["sources"]}
    except Exception:  # noqa: BLE001
        ways = {}
    sizes = _source_sizes()
    uses = _source_uses()
    domains: dict[str, dict[str, int]] = {}
    for i in catalogue.indicators().values():
        for src in i.sources:
            domains.setdefault(src.source_id, {}).setdefault(i.domain, 0)
            domains[src.source_id][i.domain] += 1
    now = _dt.now()
    out = []
    for m in catalogue.sources().values():
        if m.status != "active":
            continue
        sid = m.id
        inf = info.get(sid) or {}
        v = vint.get(sid) or {}
        loaded = str(v["loaded"]) if v.get("loaded") else None
        every = inf.get("every_days")
        due = None
        if inf.get("manual"):
            due = "when you save a newer file"
        elif inf.get("frozen"):
            due = "never (an archive)"
        elif loaded and every:
            d = _dt.fromisoformat(loaded[:19]) + timedelta(days=every)
            due = "next refresh" if d <= now else d.date().isoformat()
        elif loaded or sid in info:
            due = "every refresh"
        if sid in off:
            state = "off"
        elif sid in failing:
            state = "failing"
        elif not loaded:
            state = "never"
        elif due == "next refresh":
            state = "due"
        else:
            state = "ok"
        dom = domains.get(sid) or {}
        out.append({"source_id": sid, "name": m.name, "publisher": m.publisher, "cadence": m.cadence, "url": m.url,
                    "state": state, "off": sid in off, "by_hand": bool(m.manual and m.manual.by_hand),
                    "method": (ways.get(sid) or {}).get("method"), "last_ok": last_ok.get(sid), "loaded": loaded,
                    "release": v.get("release"), "rows": v.get("rows_n"), "due": due, "bytes": sizes.get(sid, 0),
                    "failing": (failing[sid].get("summary") or "")[:300] if sid in failing else None,
                    "note": last_note.get(sid, "")[:300], "uses": len(uses.get(sid, [])), "uses_names": uses.get(sid, [])[:8],
                    "group": max(dom, key=dom.get) if dom else "other", "fetched": sid in info,
                    "scraper": bool(m.scraper), "on_demand": sid in ("wikipedia", "numbeo")})
    order = {"failing": 0, "never": 1, "due": 2, "ok": 3, "off": 4}
    out.sort(key=lambda r: (order[r["state"]], r["name"]))
    return {"sources": out, "off": sorted(off)}


@api.put("/keys/{env}")
def keys_set(env: str, change: dict = Body(...)):
    """Save one key into the .env file on this computer ({"value": "..."}; empty removes it).
    Only names the app knows are accepted; the key is never sent back."""
    from worldmodel_contract import upkeep as upkeep_mod
    known = {v for e in catalogue.api_keys() for v in (e.get("env") or [])}
    if env not in known:
        raise HTTPException(404, f"unknown key {env}")
    value = str(change.get("value") or "").strip()
    if any(c in value for c in "\r\n\"'") or len(value) > 500:
        raise HTTPException(422, "a key is one line, without quotes")
    path = upkeep_mod.env_file()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [ln for ln in lines if not re.match(rf"\s*{re.escape(env)}\s*=", ln)]
    if value:
        lines.append(f"{env}={value}")
        os.environ[env] = value
    else:
        os.environ.pop(env, None)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"env": env, "set": bool(value), "file": str(path)}


@api.get("/upkeep")
def upkeep_state():
    """The scheduled refresh (as Windows has it) and the backups made so far."""
    from worldmodel_contract import upkeep as upkeep_mod
    s = userdata.settings()
    return {"schedule": upkeep_mod.schedule_state(), "backup_folder": str(upkeep_mod.backup_dir(s)),
            "backups": upkeep_mod.backups(s)[:20], "env_file": str(upkeep_mod.env_file())}


@api.put("/upkeep/schedule")
def upkeep_schedule(change: dict = Body(...)):
    """Turn the scheduled refresh on or off ({"on", "often", "day", "time"}); saves the settings and tells Windows."""
    from worldmodel_contract import upkeep as upkeep_mod
    s = userdata.settings()
    new = local.clean_settings({"schedule_on": bool(change.get("on")), "schedule_often": change.get("often", s["schedule_often"]),
                                "schedule_day": change.get("day", s["schedule_day"]), "schedule_time": change.get("time", s["schedule_time"])}, s)
    res = upkeep_mod.schedule(new["schedule_on"], new["schedule_often"], new["schedule_day"], new["schedule_time"])
    if res["ok"]:
        userdata.save_settings(new)
    return {**res, "schedule": upkeep_mod.schedule_state()}
