"use client";

// The pieces under a World-in-year map: what to mark (kinds, years either side, names,
// rulers), the detail of a clicked event, the rulers of the biggest states that year and
// the list of events in those years.

import { useEffect, useMemo, useState } from "react";
import { api, type LongEvent, type LongStateRulers, type Wikipedia } from "@/lib/api";
import { hueColor, KIND_WORD, kindColor, MAP_GROUPS, mapKinds, yl } from "@/lib/long";
import { saveSettings, useSettings } from "@/lib/settings";

export function YearEventTools() {
  const s = useSettings();
  const groups = new Set((s.history_map_groups ?? "war,built,belief,city").split(",").filter(Boolean));
  const toggle = (id: string) => {
    const next = new Set(groups);
    if (next.has(id)) next.delete(id); else next.add(id);
    saveSettings({ history_map_groups: MAP_GROUPS.map((g) => g.id).filter((g) => next.has(g)).join(",") }).catch(() => {});
  };
  return (
    <div className="long-tools">
      <span className="small muted">Show:</span>
      {MAP_GROUPS.map((g) => (
        <button key={g.id} className={`chip kind small${groups.has(g.id) ? "" : " off"}`} aria-pressed={groups.has(g.id)} onClick={() => toggle(g.id)}
          style={{ borderLeftColor: kindColor(mapKinds(g.id)[0]) }} title={groups.has(g.id) ? "Shown: click to hide" : "Hidden: click to show"}>
          <i style={{ background: kindColor(mapKinds(g.id)[0]) }} /> {g.label}
        </button>
      ))}
      <label className="small">Years either side <select value={s.history_map_window ?? 25}
        onChange={(e) => saveSettings({ history_map_window: +e.target.value }).catch(() => {})}>
        {[10, 25, 50, 100].map((w) => <option key={w} value={w}>±{w}</option>)}
      </select></label>
      <label className="small">Names on <select value={s.history_map_labels ?? 10}
        onChange={(e) => saveSettings({ history_map_labels: +e.target.value }).catch(() => {})}>
        {[0, 5, 10, 20].map((n) => <option key={n} value={n}>{n ? `the ${n} best known` : "none"}</option>)}
      </select></label>
      <label className="small"><input type="checkbox" checked={s.history_map_rulers ?? true}
        onChange={(e) => saveSettings({ history_map_rulers: e.target.checked }).catch(() => {})} /> Rulers</label>
    </div>
  );
}

// Is a point inside a state's shape? (for "held by" under a clicked event)
function inside(g: GeoJSON.Geometry, x: number, y: number): boolean {
  const polys = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
  const ring = (r: number[][]) => {
    let c = false;
    for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
      const [xi, yi] = r[i], [xj, yj] = r[j];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / ((yj - yi) || 1e-12) + xi) c = !c;
    }
    return c;
  };
  return polys.some((p) => ring(p[0] as number[][]) && !p.slice(1).some((h) => ring(h as number[][])));
}

export function heldBy(areas: GeoJSON.FeatureCollection | undefined, e: LongEvent): string | null {
  if (!areas || e.lat === null || e.lon === null) return null;
  const f = areas.features.find((f) => f.geometry && inside(f.geometry, e.lon!, e.lat!));
  if (!f) return null;
  const p = f.properties ?? {};
  return p.whole && p.whole !== p.name ? `${p.name} (part of ${p.whole})` : String(p.name ?? "");
}

export function EventDetail({ e, year, held, onClose }: { e: LongEvent; year: number; held: string | null; onClose: () => void }) {
  const [wiki, setWiki] = useState<Wikipedia | null>(null);
  useEffect(() => {
    setWiki(null);
    if (!e.url?.startsWith("https://en.wikipedia.org/wiki/")) return;
    let live = true;
    api.longEventWikipedia(e.url).then((w) => live && setWiki(w)).catch(() => {});
    return () => { live = false; };
  }, [e.url]);
  const intro = wiki?.page?.extract ? wiki.page.extract.split(/\n/)[0] : null;
  return (
    <div className="long-event-detail">
      <div className="card-head">
        <span className="small" style={{ color: kindColor(e.kind) }}><i className="dot" style={{ background: kindColor(e.kind) }} /> {KIND_WORD[e.kind] ?? e.kind}</span>
        <button className="link small" onClick={onClose} aria-label="Close">Close</button>
      </div>
      <h4>{e.title}</h4>
      <p className="small muted">{e.when}{e.month && e.day && !e.about ? ` (${e.day} ${new Date(2000, e.month - 1, 1).toLocaleString("en", { month: "long" })})` : ""}
        {e.place ? ` · ${e.place}` : ""}{e.year !== year ? ` · ${Math.abs(e.year - year)} years ${e.year > year ? "after" : "before"} ${yl(year)}` : ""}</p>
      {held && <p className="small">Held by: {held} (on the {yl(year)} borders)</p>}
      {e.deaths ? <p className="small">Deaths: about {Math.round(e.deaths).toLocaleString("en")} (Wikidata)</p> : null}
      {e.note && <p className="small">{e.note}</p>}
      {intro && <p className="small">{intro.length > 600 ? `${intro.slice(0, 597)}…` : intro}</p>}
      {wiki?.message && !intro && <p className="small muted">{wiki.message}</p>}
      <p className="small">
        {e.url && <a href={e.url} target="_blank" rel="noreferrer">{e.url.includes("wikipedia.org") ? "Wikipedia" : "Wikidata"}</a>}
        <span className="muted"> · {e.source_id === "typed_in" ? "typed in from the usual textbook dates" : e.source_id === "noaa_hazel" ? "NOAA" : "Wikidata"}
          {e.links ? `, articles in ${e.links} Wikipedias` : ""}</span>
      </p>
    </div>
  );
}

export function RulersStrip({ year }: { year: number }) {
  const s = useSettings();
  const on = s.history_map_rulers ?? true;
  const most = s.history_map_rulers_most ?? 6;
  const [rows, setRows] = useState<LongStateRulers[] | null>(null);
  useEffect(() => {
    if (!on) return;
    let live = true;
    const t = setTimeout(() => api.longRulers(year, most).then((r) => live && setRows(r)).catch(() => live && setRows([])), 250);
    return () => { live = false; clearTimeout(t); };
  }, [on, year, most]);
  if (!on || rows === null) return null;
  return (
    <div className="long-rulers small">
      <span className="muted">Rulers in {yl(year)}:</span>
      {rows.length ? rows.map((r) => (
        <span key={r.state} className="long-ruler" title={`${r.rulers[0].post ?? "Ruler"}, ${r.rulers[0].when}`}>
          <i className="dot" style={{ background: hueColor(r.hue) }} />
          {r.rulers[0].url ? <a href={r.rulers[0].url} target="_blank" rel="noreferrer">{r.rulers[0].name}</a> : r.rulers[0].name}
          <span className="muted">, {r.state}</span>
        </span>
      )) : <span className="muted">none known for the biggest states this year (Wikidata has rulers with articles in 25+ Wikipedias, after a refresh)</span>}
    </div>
  );
}

export function YearEventList({ events, pick, picked }: { events: LongEvent[]; pick: (e: LongEvent) => void; picked: string | null }) {
  const [open, setOpen] = useState(false);
  const list = useMemo(() => [...events].sort((a, b) => a.year - b.year), [events]);
  if (!list.length) return null;
  const shown = open ? list : list.slice(0, 12);
  return (
    <div className="long-year-list">
      <b className="small">In these years</b>
      <ul className="long-events small">
        {shown.map((e) => (
          <li key={e.event_id} className={picked === e.event_id ? "on" : ""}>
            <span className="muted tabular">{e.about ? "c. " : ""}{yl(e.year)}</span>{" "}
            <i className="dot" style={{ background: kindColor(e.kind) }} />{" "}
            <button className="link" onClick={() => pick(e)}>{e.title}</button>
            {e.lat === null ? <span className="muted"> (no place known)</span> : null}
          </li>
        ))}
      </ul>
      {list.length > 12 && <button className="link small" onClick={() => setOpen(!open)}>{open ? "Fewer" : `All ${list.length}`}</button>}
    </div>
  );
}
