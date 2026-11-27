"""Your predictions, crowd forecasts and the Outlook page."""

from __future__ import annotations

import csv
import io
import re
from typing import Literal

from fastapi import Body, HTTPException, Query
from fastapi.responses import Response
import httpx

from worldmodel_contract import crowd as crowd_terms
from worldmodel_contract.schema import EVENT_KINDS
from worldmodel_api import ai, attention, core, crowd, outlook, predictions, releases, userdata
from worldmodel_api.core import _build_id, api, rows, split
from worldmodel_api.routes.basics import _wiki_facts, wiki_target


# ----------------------------------------------------------------------------- Predictions (your log, scorecard, base rates, watchlist)
def _pred_check() -> None:
    """Settle what the app can see, at most once per build (cheap, but every page asks)."""
    b = _build_id()
    if _pred_state.get("build") != b:
        _pred_state["build"] = b
        try:
            predictions.check(rows)
        except Exception:  # noqa: BLE001 - a bad entry never breaks the page
            pass


_pred_state: dict = {}


@api.get("/predictions")
def predictions_list(who: str | None = None, category: str | None = None, entity: str | None = None,
                     indicator: str | None = None, state: str | None = None):
    """Your log: every prediction with its state (open, due, settled) and score. Outcomes the app can
    see (an indicator's figure for the year, a crowd question's resolution) are filled in first."""
    _pred_check()
    items = predictions.listing({"who": who, "category": category, "entity": entity, "indicator": indicator, "state": state})
    everyone = predictions.items()
    return {"items": items, "who": sorted({p["who"] for p in everyone}), "categories": sorted({p["category"] for p in everyone if p.get("category")})}


@api.post("/predictions")
def predictions_add(p: dict = Body(..., examples=[{"question": "NZ inflation in 2026", "kind": "number", "value": 2.4, "low": 2,
                                                   "high": 3, "due": "2027-04-30", "indicator": "inflation", "entity": "NZL", "year": 2026}])):
    """Add a prediction: {question, kind (binary, number or date), who_kind (you, expert, app, crowd), who, link, made, due,
    chance | value, low, high, unit | date_call, window_days, category, tags, why, indicator, entity, year, crowd_key}."""
    try:
        return predictions.save(p)
    except ValueError as e:
        raise HTTPException(422, str(e))


@api.put("/predictions/{pred_id}")
def predictions_edit(pred_id: str, p: dict = Body(...)):
    try:
        return predictions.save(p, pred_id)
    except KeyError:
        raise HTTPException(404, f"no prediction {pred_id}")
    except ValueError as e:
        raise HTTPException(422, str(e))


@api.delete("/predictions/{pred_id}")
def predictions_delete(pred_id: str):
    if not predictions.delete(pred_id):
        raise HTTPException(404, f"no prediction {pred_id}")
    return {"deleted": pred_id}


@api.post("/predictions/{pred_id}/outcome")
def predictions_outcome(pred_id: str, body: dict = Body(..., examples=[{"actual": True}])):
    """How it turned out: {actual: true/false, a number or a date; null clears it}."""
    try:
        p = predictions.set_outcome(pred_id, body.get("actual"))
        return {**p, "score": predictions.score(p)}
    except KeyError:
        raise HTTPException(404, f"no prediction {pred_id}")
    except ValueError as e:
        raise HTTPException(422, str(e))


@api.get("/predictions/export.csv")
def predictions_csv():
    buf = io.StringIO()
    cols = ["id", "question", "kind", "who_kind", "who", "made", "due", "chance", "value", "low", "high", "unit", "date_call",
            "category", "indicator", "entity", "year", "crowd_key", "link", "why", "state", "outcome", "hit", "brier", "miss"]
    w = csv.writer(buf)
    w.writerow(cols)
    for p in predictions.listing():
        sc = p.get("score") or {}
        w.writerow([p.get(c) if c not in ("outcome", "hit", "brier", "miss") else
                    ((p.get("outcome") or {}).get("actual") if c == "outcome" else sc.get(c)) for c in cols])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=predictions.csv"})


@api.get("/predictions/scorecard")
def predictions_scorecard(category: str | None = None, entity: str | None = None, since: str | None = None):
    """One row per forecaster (you, experts, the app, each crowd site, your Metaculus accounts): hit rate,
    Brier score, typical miss, and calibration in tenths."""
    _pred_check()
    days = int(userdata.settings().get("crowd_score_days", 7))
    return {"score_days": days, "rows": predictions.scorecard(rows, category=category, entity=entity, since=since, score_days=days)}


@api.get("/predictions/due")
def predictions_due(days: int = Query(30, ge=1, le=365)):
    _pred_check()
    return predictions.due_soon(days)


@api.post("/predictions/draft")
def predictions_draft(body: dict = Body(..., examples=[{"url": "https://example.org/article"}])):
    """Draft an expert's prediction from a web page (or pasted text) with your local AI, for you to check."""
    s = userdata.settings()
    if not s.get("ai_enabled", True):
        raise HTTPException(422, "Local AI is off (Settings: Local AI)")
    text, url = (body.get("text") or "").strip(), (body.get("url") or "").strip()
    if url and not text:
        if not re.match(r"https?://", url):
            raise HTTPException(422, "Paste a link starting with http:// or https://")
        try:
            with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "worldmodel (personal research)"}) as c:
                r = c.get(url)
                r.raise_for_status()
                text = predictions.page_text(r.text)
        except httpx.HTTPError as e:
            raise HTTPException(422, f"Could not read that page ({e.__class__.__name__}); paste its text instead")
    if len(text) < 80:
        raise HTTPException(422, "Not enough text to find a prediction in")
    model = ai.default_model(s, ai.models(s))
    if not model:
        raise HTTPException(422, "No local AI model is installed (Settings: Local AI)")
    try:
        with httpx.Client(timeout=300) as c:
            r = c.post(f"{ai.ollama_url(s)}/api/chat", json={"model": model, "stream": False, "format": "json",
                       "messages": [{"role": "user", "content": predictions.DRAFT_PROMPT.format(url=url or "pasted text", text=text[:12000])}],
                       "options": {"temperature": 0, "num_ctx": s["ai_context_tokens"]}})
            r.raise_for_status()
            answer = (r.json().get("message") or {}).get("content") or ""
    except httpx.HTTPError as e:
        raise HTTPException(502, f"The local AI did not answer ({e.__class__.__name__})")
    try:
        d = predictions.parse_draft(answer)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if url:
        d["link"] = url
    d["model"] = model
    return d


@api.get("/predictions/base-rates")
def base_rates_presets():
    return {"presets": predictions.PRESETS,
            "event_kinds": [{"kind": k, "label": v} for k, v in EVENT_KINDS.items() if k not in ("holiday", "user", "crisiswatch")]}


@api.get("/predictions/base-rate")
def base_rate(preset: str | None = None, event: str | None = None, indicator: str | None = None, if_op: str | None = None,
              if_value: float | None = None, then_op: str | None = None, then_value: float | None = None,
              within: int | None = Query(None, ge=1, le=50), entity: str | None = None, group: str | None = None,
              start: int = Query(1960, ge=1800, le=2030)):
    """How often something has happened before: a preset, or your own: an event kind per country-year
    (event=coup), or an indicator rule (indicator, if_op/if_value, then_op/then_value, within years)."""
    kind = "event" if event else "rule" if indicator else None
    if not (preset or kind):
        raise HTTPException(400, "give a preset, an event or an indicator")
    try:
        return predictions.base_rate(rows, preset, kind=kind, event=event, indicator=indicator, if_op=if_op, if_value=if_value,
                                     then_op=then_op, then_value=then_value, within=within, entity=entity, group=group, start=start)
    except KeyError:
        raise HTTPException(404, f"no preset {preset}")
    except (ValueError, TypeError) as e:
        raise HTTPException(422, f"Not enough to work out a base rate: {e}")


@api.get("/watchlist")
def watchlist_get():
    s = userdata.settings()
    return {"on": bool(s.get("watchlist_on", True)), "items": predictions.check_watch(rows, s.get("crowd_move_points", 10))}


@api.post("/watchlist")
def watchlist_add(w: dict = Body(..., examples=[{"kind": "indicator", "indicator": "inflation", "entity": "NZL", "op": "above", "threshold": 3}])):
    """Watch an indicator crossing a line, a crowd question moving, or an IMF forecast being revised."""
    try:
        return predictions.add_watch(w)
    except ValueError as e:
        raise HTTPException(422, str(e))


@api.delete("/watchlist/{watch_id}")
def watchlist_delete(watch_id: str):
    if not predictions.delete_watch(watch_id):
        raise HTTPException(404, f"no watch {watch_id}")
    return {"deleted": watch_id}


# ----------------------------------------------------------------------------- Crowd forecasts
@api.get("/crowd")
def crowd_list(site: str | None = None, category: str | None = None, country: str | None = None,
               status: str | None = "open", q: str | None = None, indicator: str | None = None, followed: bool = False,
               hidden: bool = False, sort: Literal["busy", "closing", "newest", "moved", "resolved"] = "busy",
               days: int = Query(7, ge=1, le=90), limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    """Crowd questions matched to countries, indicators and categories, each with its chance now and how far
    it moved over `days` days. status: open, closed, resolved (or empty for all)."""
    f = crowd_terms.load_follow()
    out = crowd.questions(rows, site=site, category=category, country=country, status=status or None, q=q, indicator=indicator,
                          follow=f["follow"], hide=f["hide"], only_followed=followed, show_hidden=hidden, sort=sort, days=days,
                          limit=limit, offset=offset)
    out["categories"] = crowd_terms.CATEGORIES
    out["sites"] = crowd_terms.SITES
    out["loaded"] = crowd.has_data(rows)
    return out


@api.get("/crowd/question")
def crowd_question(key: str):
    """One question: its record, chance over time (the site's own history and the app's saves), your
    Metaculus forecasts, comments, the same question on other sites, and events in its countries."""
    rec = crowd.question(rows, key)
    if rec is None:
        raise HTTPException(404, f"no question {key}")
    f = crowd_terms.load_follow()
    rec["followed"], rec["hidden"] = key in f["follow"], key in f["hide"]
    rec["predictions"] = [p for p in predictions.listing() if p.get("crowd_key") == key]
    return rec


@api.post("/crowd/follow")
def crowd_follow(body: dict = Body(..., examples=[{"key": "metaculus:123", "follow": True}])):
    """Follow or hide a question: {key, follow: bool} or {key, hide: bool}. Followed questions get their full
    history and comments read at the next refresh."""
    key = str(body.get("key") or "")
    if not re.fullmatch(r"(polymarket|metaculus|manifold):[\w-]{1,80}", key):
        raise HTTPException(422, "key is <site>:<id>")
    f = crowd_terms.load_follow()
    for name in ("follow", "hide"):
        if name in body:
            lst = [k for k in f[name] if k != key]
            if body[name]:
                lst.append(key)
            f[name] = lst
    crowd_terms.save_follow(f)
    return f


@api.get("/crowd/moves")
def crowd_moves(days: int = Query(7, ge=1, le=90), points: float | None = Query(None, ge=1, le=100), country: str | None = None):
    s = userdata.settings()
    f = crowd_terms.load_follow()
    return crowd.moves(rows, days=days, min_points=points or s.get("crowd_move_points", 10), countries=split(country) or None,
                       hide=f["hide"], limit=60)


@api.get("/crowd/events")
def crowd_events():
    """Events against predictions: did the crowd see resolved questions coming, and how early."""
    return crowd.events_vs(rows, int(userdata.settings().get("crowd_score_days", 7)))


@api.get("/crowd/country/{entity_id}")
def crowd_country(entity_id: str):
    """A country page's "What the crowd expects" card: its busiest open questions and ViEWS conflict forecasts."""
    out = crowd.country(rows, entity_id, hide=crowd_terms.load_follow()["hide"])
    out["pundits"] = crowd.pundit_country(rows, entity_id)
    return out


@api.get("/crowd/pundits")
def crowd_pundits(country: str | None = None, q: str | None = None, min_graded: int = Query(10, ge=0, le=10000),
                  sort: Literal["accuracy", "graded", "rank", "name", "pending"] = "accuracy", limit: int = Query(200, ge=1, le=2000)):
    """Pundits: named forecasters on Prediction Archive (pages saved by hand) with their hit rates, their open
    calls on your key countries (Settings > Discover) or on `country`, and calls graded lately."""
    s = userdata.settings()
    keys = [k for k in (s.get("discover_key_countries") or "").split(",") if k] or ["NZL", "AUS", "GBR", "USA"]
    return crowd.pundits(rows, countries=keys, country=country, q=q, min_graded=min_graded, sort=sort, limit=limit)


@api.get("/crowd/pundits/{predictor_id}")
def crowd_pundit(predictor_id: str):
    """One forecaster on Prediction Archive and every call of theirs held."""
    got = crowd.pundit(rows, predictor_id)
    if got is None:
        raise HTTPException(404, f"no forecaster {predictor_id}")
    return got


@api.get("/crowd/conflict")
def crowd_conflict():
    """ViEWS conflict forecasts by country for the next 12 months."""
    return crowd.conflict_map(rows)


# ----------------------------------------------------------------------------- Outlook
def _wh_version() -> str:
    o = core.warehouse.current()
    return f"{o.path}:{o.mtime}"


def _set(name: str, default=True) -> bool:
    return bool(userdata.settings().get(name, default))


@api.get("/outlook/recession")
def outlook_recession(entities: str | None = None):
    """The chance a recession starts within a year, for each country asked (default: the key countries),
    with its history, its recessions and what drives the latest reading."""
    ents = split(entities) or list(outlook.KEY)
    got = outlook.recession_odds(rows, ents, _wh_version())
    names = {r["entity_id"]: r["name"] for r in rows("SELECT entity_id, coalesce(short_name, name) AS name FROM entities")}
    for c in got["countries"]:
        c["name"] = names.get(c["entity"], c["entity"])
    return got


@api.get("/outlook/recession/all")
def outlook_recession_all():
    """Every country with a reading now, highest odds first (no histories)."""
    ents = [r["e"] for r in rows("SELECT DISTINCT entity_id AS e FROM series WHERE indicator_id = 'gdp_growth_q'")]
    got = outlook.recession_odds(rows, ents, _wh_version(), history_from=9999)
    names = {r["entity_id"]: r["name"] for r in rows("SELECT entity_id, coalesce(short_name, name) AS name FROM entities")}
    out = [{"entity": c["entity"], "name": names.get(c["entity"], c["entity"]), "odds": c["odds"], "month": c["month"],
            "model": c["model"], "in_recession": c["in_recession"]} for c in got["countries"] if c["odds"] is not None]
    return {"countries": sorted(out, key=lambda c: -c["odds"]), "models": got["models"]}


@api.get("/outlook/nowcast/{entity_id}")
def outlook_nowcast(entity_id: str):
    """This quarter's growth estimated before the official figure, with the method's track record."""
    return outlook.nowcast(rows, entity_id, _wh_version())


@api.get("/outlook/calendar")
def outlook_calendar(countries: str | None = None, days_back: int = 7, days_ahead: int = 42):
    """Data releases and rate decisions coming up (and the last week's), with the app's nowcast where it has one."""
    return releases.calendar(_set("calendar_live"), split(countries) or list(outlook.KEY), days_back, days_ahead,
                             nowcasts=outlook.remembered())


def _article(entity_id: str) -> str | None:
    t = wiki_target(entity_id)
    if not t or t.get("type") not in ("country", "historical_country"):
        return None
    return t.get("article") or t["name"]


@api.get("/attention/top")
def attention_top():
    """Countries among Wikipedia's most-read articles yesterday, and the key countries' own views."""
    on = _set("attention_on")
    countries = rows("SELECT entity_id, name, coalesce(short_name, name) AS short FROM entities WHERE type = 'country' AND valid_to IS NULL")
    facts = _wiki_facts([c["entity_id"] for c in countries])
    titles = {(facts.get(c["entity_id"], {}).get("article") or c["name"]): c["entity_id"] for c in countries}
    got = attention.top(titles, on)
    names = {c["entity_id"]: c["short"] for c in countries}
    for c in got["countries"]:
        c["name"] = names.get(c["entity"], c["entity"])
    key = []
    for e in outlook.KEY:
        a = _article(e)
        if a:
            r = attention.country(e, a, on)
            key.append({"entity": e, "name": names.get(e, e), **{k: r.get(k) for k in ("latest", "usual", "week_avg", "ratio", "spikes", "note")},
                        "points": r.get("points", [])[-30:]})
    return {**got, "key": key}


@api.get("/attention/{entity_id}")
def attention_country(entity_id: str):
    """How many people read the country's Wikipedia article each day over the last 90 days, and its spikes."""
    a = _article(entity_id)
    if not a:
        return {"entity": entity_id, "points": [], "note": "No Wikipedia article for this kind of place."}
    return attention.country(entity_id, a, _set("attention_on"))


# ----------------------------------------------------------------------------- forecast scores (back-tests and the running record)
def _scores():
    from worldmodel_api import forecast_scores as fs

    if fs.SCORES.q is None:
        fs.SCORES.configure(rows, _build_id, _wh_version, userdata.settings)
    return fs


@api.get("/forecast-scores")
def forecast_scores_part(part: str = Query("disease", description="disease, stat:<indicator>, nowcast, recession or live")):
    """How good the app's forecasts have been: each made again from the past with only the figures there were
    then (a rolling-origin back-test) and scored against what came and against simple baselines; or, for
    `live`, the forecasts saved after each refresh scored as their figures come in. Worked out in the
    background after each new build: {status: working} until ready, then {status: ready, result}."""
    fs = _scores()
    if part.startswith("stat:"):
        ind = part[5:]
        if not re.fullmatch(r"[a-z0-9_]{1,80}", ind) or not rows("SELECT 1 FROM indicators WHERE indicator_id = ?", [ind]):
            raise HTTPException(404, f"no indicator {ind}")
    elif part not in ("disease", "nowcast", "recession", "live"):
        raise HTTPException(422, "part must be disease, stat:<indicator>, nowcast, recession or live")
    return fs.SCORES.ask(part)


@api.get("/forecast-scores/state")
def forecast_scores_state():
    """Which parts of the scores are ready for this build, which is being worked out and which wait."""
    fs = _scores()
    return {**fs.SCORES.state(), "defaults": list(fs.PARTS_DEFAULT), "stat_default": list(fs.STAT_DEFAULT),
            "horizons": fs.HORIZONS, "horizon_unit": fs.HORIZON_UNIT, "baselines": fs.BASE_NAMES}
