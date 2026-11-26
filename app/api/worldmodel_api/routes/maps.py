"""Map layer details and the electricity mix map."""

from __future__ import annotations

import json
from typing import Literal

from fastapi import HTTPException, Query, Request
from fastapi.responses import Response

from worldmodel_api import climate, core, grid, hazards, ports, userdata, weather
from worldmodel_api import layer_details as layer_info
from worldmodel_api.core import _has_cities, api, rows
from worldmodel_api.routes.cities import _city_score


# ----------------------------------------------------------------------------- map layer details
def _layer_key() -> str:
    o = core.warehouse.current()
    return f"{o.path}:{o.mtime}"


def _live_layer(layer_id: str) -> dict:
    return json.loads(layer(layer_id).body)


@api.get("/layer-details")
def layer_details_list():
    """Every map layer the Details page can count, with its items and countries now."""
    return layer_info.overview(rows)


@api.get("/layer-details/country/{entity_id}")
def layer_details_country(entity_id: str):
    """One country's items on each counted map layer, with its rank among countries."""
    return layer_info.country(rows, _layer_key(), entity_id)


@api.get("/layer-details/{layer_id}")
def layer_details(layer_id: str):
    """One map layer by country and by group (count, per million people, per 10,000 km², size total,
    official total and coverage), with the spread of its sizes and categories."""
    got = layer_info.detail(rows, _layer_key(), layer_id, _live_layer, hazards.country_of)
    if "error" in got:
        raise HTTPException(404, got["error"])
    return got


@api.get("/layer-details/{layer_id}/coverage")
def layer_details_coverage(layer_id: str):
    """How complete a layer is in each country: against an official figure, or what countries of a
    similar income have (an estimate); graded good, part or thin."""
    got = layer_info.coverage(rows, _layer_key(), layer_id, _live_layer, hazards.country_of)
    if "error" in got:
        raise HTTPException(404, got["error"])
    return got


@api.get("/layer-details/{layer_id}/gaps")
def layer_details_gaps(layer_id: str, country: str | None = Query(None, description="A country id; all if left out"),
                       limit: int = Query(300, ge=1, le=5000)):
    """Blank spots: towns of 100,000 people or more with none of the layer's items within 25 km."""
    got = layer_info.gaps(rows, _layer_key(), layer_id, country, _live_layer, hazards.country_of, limit)
    if "error" in got:
        raise HTTPException(404, got["error"])
    return got


@api.get("/layer-details/{layer_id}/items")
def layer_details_items(layer_id: str, country: str | None = Query(None, description="A country, council or group id; '-' for none"),
                        q: str | None = None, sort: Literal["size", "name"] = "size",
                        limit: int = Query(200, ge=1, le=5000), offset: int = Query(0, ge=0)):
    """A layer's items, biggest first (or by name), for one country or group or all."""
    return layer_info.list_items(rows, _layer_key(), layer_id, country, q, sort, limit, offset, _live_layer, hazards.country_of)


@api.get("/weather/status")
def weather_status():
    """The forecast run the weather layers draw (its steps, colours and keys), and a look for a newer
    run in the background when one is due (Settings > Climate > Weather)."""
    return weather.status(userdata.settings())


@api.get("/weather/tiles/{field}/{run}/{step}/{z}/{x}/{y}.png")
def weather_tile(field: str, run: str, step: int, z: int, x: int, y: int):
    """A 256-pixel tile of one forecast field (temp, rain, cloud, wind, pressure) for one run and hour."""
    if not run.isdigit() or len(run) != 10:
        raise HTTPException(404, "no such run")
    try:
        png = weather.tile(userdata.settings(), field, run, step, z, x, y)
    except ImportError:
        raise HTTPException(503, "The eccodes package is missing: run update.bat to install it.") from None
    if png is None:
        raise HTTPException(404, "no such forecast step on this PC (a newer run may have replaced it)")
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=21600"})


@api.get("/weather/at")
def weather_at(lat: float, lon: float, step: int = 0):
    """Every forecast field's value at a point for one step (the line under the map pointer)."""
    try:
        return weather.at(userdata.settings(), lat, lon, step)
    except ImportError:
        return {"step": step, "values": {}, "note": "The eccodes package is missing: run update.bat to install it."}


@api.get("/weather/clouds/{z}/{x}/{y}.png")
def weather_clouds(z: int, x: int, y: int):
    """The latest satellite infrared (Himawari, GOES East and West) as see-through clouds."""
    if not (0 <= z <= 10) or not (0 <= y < 2 ** z) or not userdata.settings().get("weather_maps", True):
        raise HTTPException(404, "no such tile")
    return Response(weather.clouds_tile(z, x, y), media_type="image/png", headers={"Cache-Control": "max-age=600"})


@api.get("/weather/point")
def weather_point(lat: float, lon: float):
    """A place's weather now and hourly forecast (Open-Meteo or MET Norway, Settings > Climate > Weather)."""
    s = userdata.settings()
    if not s.get("weather_maps", True):
        return {"lat": lat, "lon": lon, "error": "Weather is switched off in Settings > Climate."}
    return weather.point(s, lat, lon)


@api.get("/layers/{layer_id}")
def layer(layer_id: str, request: Request):
    """One overlay's features, as GeoJSON. storms_active is read live from NOAA (kept an hour)."""
    if layer_id in ("fires_now", "fires_week", "heat_now", "coral_alerts"):
        on = bool(userdata.settings().get("hazards_live", True))
        data = (hazards.fires("7d" if layer_id == "fires_week" else "24h", on) if layer_id.startswith("fires")
                else hazards.heat(_hazard_cities(), on) if layer_id == "heat_now" else hazards.coral(on))
        return Response(json.dumps(data, separators=(",", ":")), media_type="application/geo+json",
                        headers={"Cache-Control": "max-age=900"})
    if layer_id == "city_stress":
        got = _city_score("stress", None)
        data = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
             "properties": {"city": r["city_id"], "name": r["name"], "country": r["country"], "score": r["score"],
                            "rank": r["rank"], "of": len(got["rows"]), "parts": r["n_parts"]}}
            for r in got["rows"] if r["lat"] is not None and r["lon"] is not None]}
        return Response(json.dumps(data, separators=(",", ":")), media_type="application/geo+json")
    if layer_id == "port_pressure":
        data = ports.layer(rows)
        return Response(json.dumps(data, separators=(",", ":")), media_type="application/geo+json")
    if layer_id == "power_links":
        data = grid.power_links(rows)
        return Response(json.dumps(data, separators=(",", ":")), media_type="application/geo+json")
    if layer_id == "storms_active":
        data = climate.active_storms(bool(userdata.settings().get("climate_live_map", True)))
        return Response(json.dumps(data, separators=(",", ":")), media_type="application/geo+json",
                        headers={"Cache-Control": "max-age=900"})
    found = rows("SELECT geojson FROM layers WHERE layer_id = ?", [layer_id])
    if not found:
        raise HTTPException(404, f"no map layer {layer_id}; a refresh loads the map layers")
    body = found[0]["geojson"]
    if len(body) > 200_000 and "gzip" in (request.headers.get("accept-encoding") or ""):
        # Big dot layers (every hospital from every list) go a fifth the size over the network.
        return Response(_gzipped(layer_id, body), media_type="application/geo+json",
                        headers={"Cache-Control": "max-age=3600", "Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
    return Response(body, media_type="application/geo+json", headers={"Cache-Control": "max-age=3600"})


_gz: dict[str, tuple[int, bytes]] = {}


def _gzipped(layer_id: str, body: str) -> bytes:
    """A layer's GeoJSON gzipped, kept until the layer changes."""
    import gzip
    key = hash(body)
    hit = _gz.get(layer_id)
    if hit and hit[0] == key:
        return hit[1]
    data = gzip.compress(body.encode("utf-8"), compresslevel=5)
    _gz[layer_id] = (key, data)
    return data


def _hazard_cities() -> list[dict]:
    """The big cities the heat layer checks: a million people or more, biggest first (at most 600)."""
    if not _has_cities():
        return []
    return [{"name": r["name"], "country": r["country_id"], "lon": r["lon"], "lat": r["lat"]} for r in rows(
        "SELECT name, country_id, lat, lon FROM cities WHERE population >= 1000000 AND lat IS NOT NULL ORDER BY population DESC LIMIT 600")]


# ----------------------------------------------------------------------------- electricity mix map
ELEC_MIX = {"coal": ["coal_electricity"], "gas": ["gas_electricity"], "oil": ["oil_electricity"],
            "nuclear": ["nuclear_electricity"], "hydro": ["hydro_electricity"], "wind": ["wind_electricity"],
            "solar": ["solar_electricity"], "bio": ["biofuel_electricity"], "other": ["other_renewable_exc_biofuel_electricity"]}


@api.get("/energy/electricity-mix")
def electricity_mix(back: int = Query(10, ge=1, le=40, description="Years before the latest to compare with")):
    """Each country's electricity generation by source in its latest year and `back` years before, as
    shares (%), with the total in TWh; also the world and each continent (countries added up). For the
    electricity map on the Energy topic page."""
    ids = [i for v in ELEC_MIX.values() for i in v]
    got = rows("""SELECT s.entity_id, s.indicator_id, year(s.period_start) AS y, s.value FROM series s
        JOIN entities e ON e.entity_id = s.entity_id
        WHERE s.indicator_id IN (SELECT unnest(?)) AND s.breakdown = '' AND s.variant = 'central' AND s.status = 'E'
          AND s.value IS NOT NULL AND e.type IN ('country', 'world')
        QUALIFY row_number() OVER (PARTITION BY s.entity_id, s.indicator_id, s.period_start ORDER BY s.source_id) = 1""", [ids])
    kind = {i: k for k, v in ELEC_MIX.items() for i in v}
    by: dict[str, dict[int, dict[str, float]]] = {}
    for r in got:
        d = by.setdefault(r["entity_id"], {}).setdefault(r["y"], {})
        d[kind[r["indicator_id"]]] = d.get(kind[r["indicator_id"]], 0.0) + max(0.0, float(r["value"]))
    cont = {r["member_id"]: (r["group_id"], r["name"]) for r in rows("""SELECT m.member_id, m.group_id, g.short_name AS name
        FROM memberships m JOIN entities g ON g.entity_id = m.group_id WHERE g.type = 'continent' AND m.valid_to IS NULL""")}
    names = {r["entity_id"]: r["short_name"] for r in rows("SELECT entity_id, short_name FROM entities WHERE type IN ('country', 'world', 'continent')")}
    # a group's figures: its countries added up, in years when nearly all of its generation has reported
    groups: dict[str, dict[int, dict[str, float]]] = {}
    for e, years in by.items():
        if e in cont:
            for y, d in years.items():
                g = groups.setdefault(cont[e][0], {}).setdefault(y, {})
                for k, v in d.items():
                    g[k] = g.get(k, 0.0) + v
        if e != "world" and "world" not in by:
            for y, d in years.items():
                g = groups.setdefault("world", {}).setdefault(y, {})
                for k, v in d.items():
                    g[k] = g.get(k, 0.0) + v

    def one(e: str, years: dict[int, dict[str, float]], level: str) -> dict | None:
        full = {y: d for y, d in years.items() if sum(d.values()) > 0 and len(d) >= 5}
        if not full:
            return None
        if level != "country":  # a group's newest year is the newest most of its countries have reported
            tot = {y: sum(d.values()) for y, d in full.items()}
            best = max(tot.values())
            full = {y: d for y, d in full.items() if tot[y] >= 0.9 * best} or full
        y = max(full)
        d = full[y]
        t = sum(d.values())
        b = full.get(y - back) or years.get(y - back)
        tb = sum(b.values()) if b else 0
        share = {k: round(100 * d.get(k, 0) / t, 1) for k in ELEC_MIX}
        return {"id": e, "name": names.get(e, e), "level": level, "year": y, "twh": round(t, 1),
                "share": share, "before_year": y - back if tb else None,
                "before": {k: round(100 * b.get(k, 0) / tb, 1) for k in ELEC_MIX} if tb else None,
                "top": max(share, key=lambda k: share[k])}

    out = []
    for e, years in by.items():
        if e == "world":
            continue
        if (x := one(e, years, "country")):
            out.append(x)
    for g, years in groups.items():
        if g != "world" and (x := one(g, years, "continent")):
            out.append(x)
    w = one("world", by.get("world") or groups.get("world", {}), "world")
    return {"world": w, "rows": out, "kinds": list(ELEC_MIX), "back": back,
            "source": "Energy Institute and Ember, via Our World in Data"}
