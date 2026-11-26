"""Counts for the Live page's Ship counts and Plane counts tabs: how many ships and planes by kind,
flag, airline, where from, where to and more, from the same rows as the tables (saved details and
positions while collecting)."""

from __future__ import annotations

import time
from collections import Counter

TOP = 25


def _top(counter: Counter, labels: dict | None = None, top: int = TOP) -> dict:
    """The `top` biggest (0: all) with counts and shares."""
    total = sum(counter.values())
    n = top
    rows = [{"key": k, "label": (labels or {}).get(k, k), "count": c, "share": c / total if total else 0}
            for k, c in counter.most_common(n or None)]
    return {"rows": rows, "distinct": len(counter), "counted": total}


def _place(p: dict | None) -> str | None:
    if not p:
        return None
    name = p.get("city") or p.get("name")
    return f"{name}, {p['country']}" if name and p.get("country") else name


def _band(v, bands: list[tuple[float, str]], none: str) -> str:
    if v is None:
        return none
    for top, label in bands:
        if v < top:
            return label
    return bands[-1][1]


SHIP_LENGTH = [(25, "Under 25 m"), (50, "25 to 50 m"), (100, "50 to 100 m"), (200, "100 to 200 m"), (300, "200 to 300 m"), (1e9, "300 m and over")]
PLANE_HEIGHT = [(1000, "Under 1,000 m"), (3000, "1,000 to 3,000 m"), (6000, "3,000 to 6,000 m"), (9000, "6,000 to 9,000 m"), (11000, "9,000 to 11,000 m"), (1e9, "11,000 m and over")]


def ships(rows: list[dict], groups: dict[str, str], top: int = TOP) -> dict:
    """Counts over ship table rows; groups maps a kind group to its label."""
    now = time.time()
    by = {k: Counter() for k in ("group", "type", "flag", "came_from", "came_country", "going_to", "going_country", "status", "length")}
    flag_names: dict = {}
    moving = recent = new = 0
    for r in rows:
        by["group"][r.get("group") or "unknown"] += 1
        by["type"][r.get("type") or "Not said yet"] += 1
        if r.get("flag_code"):
            by["flag"][r["flag_code"]] += 1
            flag_names[r["flag_code"]] = r.get("flag") or r["flag_code"]
        else:
            by["flag"]["?"] += 1
            flag_names["?"] = "Not known"
        lp = r.get("last_port") or {}
        came = _place(lp) or r.get("from_typed")
        if came:
            by["came_from"][came] += 1
        if lp.get("country"):
            by["came_country"][lp["country"]] += 1
        tp = r.get("to_port") or {}
        going = _place(tp) or (str(r.get("destination") or "").strip().upper() or None)
        if going:
            by["going_to"][going] += 1
        if tp.get("country"):
            by["going_country"][tp["country"]] += 1
        by["status"][r.get("status") or "Not said"] += 1
        by["length"][_band(r.get("length_m"), SHIP_LENGTH, "Not said")] += 1
        if (r.get("speed_kn") or 0) >= 0.5:
            moving += 1
        if (r.get("last_seen") or 0) >= now - 3600:
            recent += 1
        if (r.get("first_seen") or 0) >= now - 86400:
            new += 1
    return {"total": len(rows), "moving": moving, "heard_last_hour": recent, "first_seen_last_day": new,
            "parts": [
                {"id": "group", "title": "By kind", **_top(by["group"], groups, top=top)},
                {"id": "type", "title": "By AIS type", **_top(by["type"], top=top)},
                {"id": "flag", "title": "By flag", **_top(by["flag"], flag_names, top=top)},
                {"id": "came_from", "title": "Came from (last port, or typed FROM)", **_top(by["came_from"], top=top)},
                {"id": "came_country", "title": "Came from, by country", **_top(by["came_country"], top=top)},
                {"id": "going_to", "title": "Going to (port, or destination as typed)", **_top(by["going_to"], top=top)},
                {"id": "going_country", "title": "Going to, by country", **_top(by["going_country"], top=top)},
                {"id": "status", "title": "By status", **_top(by["status"], top=top)},
                {"id": "length", "title": "By length", **_top(by["length"], top=10)},
            ]}


def planes(rows: list[dict], groups: dict[str, str], top: int = TOP) -> dict:
    """Counts over plane table rows; groups maps a plane group to its label."""
    by = {k: Counter() for k in ("group", "airline", "flag", "from", "to", "route", "model", "height")}
    flag_names: dict = {}
    military = airline_n = 0
    codes: dict[str, str] = {}
    for p in rows:
        by["group"][p.get("group") or "unknown"] += 1
        if p.get("airline"):
            by["airline"][p["airline"]] += 1
            airline_n += 1
            if p.get("airline_code"):
                codes[p["airline"]] = p["airline_code"]
        else:
            by["airline"]["No airline (private, military, other)"] += 1
        f = p.get("flag") or "?"
        by["flag"][f] += 1
        flag_names[f] = p.get("country") or ("Not known" if f == "?" else f)
        fr, to = _place(p.get("from")), _place(p.get("to"))
        if fr:
            by["from"][fr] += 1
        if to:
            by["to"][to] += 1
        if fr and to:
            by["route"][f"{fr} to {to}"] += 1
        by["model"][p.get("model") or p.get("category_name") or "Not known"] += 1
        by["height"][_band(p.get("altitude_m"), PLANE_HEIGHT, "Not sent")] += 1
        military += bool(p.get("military"))
    return {"total": len(rows), "airline": airline_n, "military": military, "airline_codes": codes,
            "parts": [
                {"id": "group", "title": "By kind", **_top(by["group"], groups, top=top)},
                {"id": "airline", "title": "By airline", **_top(by["airline"], top=top)},
                {"id": "flag", "title": "By country of registration", **_top(by["flag"], flag_names, top=top)},
                {"id": "from", "title": "Flying from", **_top(by["from"], top=top)},
                {"id": "to", "title": "Flying to", **_top(by["to"], top=top)},
                {"id": "route", "title": "Busiest routes", **_top(by["route"], top=top)},
                {"id": "model", "title": "By aircraft", **_top(by["model"], top=top)},
                {"id": "height", "title": "By height", **_top(by["height"], top=10)},
            ]}


def _airport_text(a: dict | None) -> str:
    return " ".join(str(a.get(k) or "") for k in ("name", "iata", "icao", "city", "country")).lower() if a else ""


def filter_planes(rows: list[dict], group: str = "", airline: str = "", flag: str = "", q: str = "", frm: str = "", to: str = "") -> list[dict]:
    """The plane rows matching the counts tab's filters (the same as the planes table's)."""
    ql, fl, tl = q.strip().lower(), frm.strip().lower(), to.strip().lower()
    out = []
    for p in rows:
        if group and p.get("group") != group:
            continue
        if airline and ((airline == "-" and p.get("airline")) or (airline != "-" and p.get("airline") != airline)):
            continue
        if flag and (p.get("flag") or "").upper() != flag.upper():
            continue
        if fl and fl not in _airport_text(p.get("from")):
            continue
        if tl and tl not in _airport_text(p.get("to")):
            continue
        if ql and not any(ql in str(p.get(k) or "").lower() for k in ("callsign", "id", "country", "airline", "reg", "type", "model")):
            continue
        out.append(p)
    return out
