"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { CW_LABEL } from "@/components/CrisisWatchCard";
import type { MapMark, MapOutline, RasterTiles } from "@/components/WorldMap";
import { api, type CrisisWatchMonth, type MapEvents } from "@/lib/api";
import { zoneTiles } from "@/lib/climate";
import { cssVar } from "@/lib/colors";
import { countryCentres } from "@/lib/geo";
import { LAYER_STYLE, layerData, mapLayers, type MapLayerInfo } from "@/lib/layers";
import { saveSettings, useSettings } from "@/lib/settings";
import { yl } from "@/lib/long";
import { setMapYear, useMapYear, useWorldIn } from "@/lib/longYear";
import {
  LAYER_GROUPS, MAP_LAYERS, QUICK_SETS, WINDOWS, windowDates, type Action, type LayerDef, type Panel as PanelState,
} from "@/lib/workspace";

// ----------------------------------------------------------------------------- what the app's own layers draw
// Colours per kind of event, from the app's palette (names of CSS variables).
const GROUP_COLOR: Record<string, string> = {
  conflict: "--div-neg-3", hazard: "--series-2", politics: "--series-7", economy: "--series-6", news: "--series-4", other: "--muted",
};
export const GROUP_NAME: Record<string, string> = {
  conflict: "Conflict, coups and unrest", hazard: "Disasters and hazards", politics: "Politics and elections", economy: "Economy", other: "Other",
};
// CrisisWatch outlines sit over the country colours (mostly blue), so they use colours that stand out
// from blue: red for worse, orange for an alert, green for better.
const CW_OUTLINE: Record<string, string> = {
  deteriorated: "--div-neg-3", risk_alert: "--series-2", improved: "--series-3", resolution_opportunity: "--series-6",
};
const esc = (v: unknown) => String(v ?? "").replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`);
const color = (group: string) => cssVar(GROUP_COLOR[group] ?? "--muted") || "#888";

let cwLatest: Promise<CrisisWatchMonth> | null = null;
const eventsCache = new Map<string, Promise<MapEvents>>();

// Several markers in one country spread round its centre, so they don't sit on each other.
function spread(c: [number, number], i: number): [number, number] {
  if (i === 0) return c;
  const ring = Math.ceil(Math.sqrt(i));
  const a = i * 2.399963; // the golden angle
  return [c[0] + Math.cos(a) * 0.9 * ring, c[1] + Math.sin(a) * 0.7 * ring];
}

export type LayerCounts = Record<string, string>;

// Outlines, markers, filters, legend and counts for a map panel's layers in a time window.
export function useMapMarks(letters: string, win: string, year: number | null) {
  const on = (l: string) => letters.includes(l);
  const { map_hospital_beds: minBeds, map_hospitals_unsized: unsized } = useSettings();
  const [start, end] = windowDates(win, year);
  const [cw, setCw] = useState<CrisisWatchMonth | null>(null);
  const [ev, setEv] = useState<MapEvents | null>(null);
  const [centres, setCentres] = useState<Record<string, [number, number]> | null>(null);
  const [counts, setCounts] = useState<LayerCounts>({});
  const pastYear = useMapYear();
  const world = useWorldIn(on("y"), pastYear);
  useEffect(() => {
    if (!on("w")) return;
    cwLatest ??= api.crisiswatch().catch((e) => { cwLatest = null; throw e; });
    cwLatest.then(setCw).catch(() => setCw(null));
  }, [on("w")]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!on("e") && !on("n")) return;
    let live = true;
    const key = `${start}~${end}`;
    if (!eventsCache.has(key)) {
      const p = api.mapEvents(start, end);
      p.catch(() => eventsCache.delete(key));
      eventsCache.set(key, p);
    }
    eventsCache.get(key)!.then((d) => live && setEv(d)).catch(() => live && setEv(null));
    countryCentres().then((c) => live && setCentres(c)).catch(() => {});
    return () => { live = false; };
  }, [start, end, on("e"), on("n")]); // eslint-disable-line react-hooks/exhaustive-deps
  // Counts in the window for earthquakes and storms, from their layers.
  useEffect(() => {
    let live = true;
    const want = MAP_LAYERS.filter((m) => m.timed && !m.made && on(m.letter));
    Promise.all(want.map((m) => layerData(m.id).then((fc) => [m.id, fc] as const).catch(() => null))).then((got) => {
      if (!live) return;
      const out: LayerCounts = {};
      for (const g of got) {
        if (!g) continue;
        const [id, fc] = g;
        const n = fc.features.filter((f) => inWindow(id, f.properties ?? {}, start, end)).length;
        out[id] = `${n} in window`;
      }
      setCounts(out);
    });
    return () => { live = false; };
  }, [letters, start, end]); // eslint-disable-line react-hooks/exhaustive-deps

  return useMemo(() => {
    const outlines: MapOutline[] = on("w") && cw?.month
      ? cw.rows.filter((r) => r.subkind !== "unchanged").map((r) => ({
          entity: r.entity_id, color: cssVar(CW_OUTLINE[r.subkind] ?? "--muted"),
          label: `CrisisWatch ${cw.month}: <b>${esc(CW_LABEL[r.subkind] ?? r.subkind)}</b>${r.place ? ` (${esc(r.place)})` : ""}` }))
      : [];
    const marks: MapMark[] = [];
    const used = new Map<string, number>();
    const span = Math.max(1, (Date.parse(end) - Date.parse(start)) / 86_400_000);
    const fade = (d: string) => 0.4 + 0.6 * Math.max(0, Math.min(1, 1 - (Date.parse(end) - Date.parse(d)) / 86_400_000 / span));
    const at = (entity: string): [number, number] | null => {
      const c = centres?.[entity];
      if (!c) return null;
      const i = used.get(entity) ?? 0;
      used.set(entity, i + 1);
      return spread(c, i);
    };
    if (ev && on("e")) {
      for (const e of ev.events) {
        const p = at(e.entity_id);
        if (!p) continue;
        const r = e.deaths ? Math.min(11, 4 + Math.log10(e.deaths + 1) * 1.6) : 5;
        marks.push({ key: `e:${e.event_id}:${e.entity_id}`, lng: p[0], lat: p[1], color: color(e.group), r, opacity: fade(e.start_date),
          href: e.url ?? `/events?entity=${e.entity_id}`,
          label: `<b>${esc(e.title)}</b><br/>${esc(e.entity_name ?? e.entity_id)} · ${esc(e.start_date)}${e.place ? `<br/>${esc(e.place)}` : ""}`
            + (e.deaths ? `<br/>${Math.round(e.deaths).toLocaleString()} deaths` : "") });
      }
    }
    if (ev && on("n")) {
      for (const h of ev.watch) {
        const p: [number, number] | null = h.place ? [h.place.lon, h.place.lat] : at(h.entity_id);
        if (!p) continue;
        marks.push({ key: h.key, lng: p[0], lat: p[1], color: color(h.group === "news" ? "news" : h.group), hollow: !h.confirmed, r: 5.5,
          opacity: fade(h.date), href: h.url ?? undefined,
          label: `<b>${esc(h.headline)}</b><br/>${esc(h.date)} · "${esc(h.word)}" · ${esc(h.outlets.join(", "))}`
            + `<br/>${h.confirmed ? `Confirmed: ${esc(h.confirmed_by ?? "a dataset has it")}` : "Reported in the news, not yet confirmed by a dataset"}`
            + (h.place ? `<br/>Placed at ${esc(h.place.name)}` : "<br/>Placed at the country's centre") });
      }
    }
    const filters: Record<string, unknown[] | null> = {
      earthquakes: ["all", [">=", ["to-string", ["get", "date"]], start], ["<=", ["to-string", ["get", "date"]], `${end}~`]],
      storm_tracks: ["all", [">=", ["get", "year"], +start.slice(0, 4)], ["<=", ["get", "year"], +end.slice(0, 4)]],
      // Hospitals above the size in Settings > Places (and, if asked, those with no bed count).
      hospitals: ["any", [">=", ["coalesce", ["get", "beds"], -1], minBeds ?? 200], unsized ? ["!", ["has", "beds"]] : false],
    };
    const legend: { label: string; color: string; shape: "dot" | "ring" | "outline" }[] = [];
    if (on("w") && outlines.length) {
      legend.push({ label: `CrisisWatch ${cw?.month}: worse`, color: cssVar(CW_OUTLINE.deteriorated), shape: "outline" },
        { label: "alert", color: cssVar(CW_OUTLINE.risk_alert), shape: "outline" }, { label: "better", color: cssVar(CW_OUTLINE.improved), shape: "outline" });
    }
    if (on("e")) {
      const groups = [...new Set((ev?.events ?? []).map((e) => e.group))];
      for (const g of groups) legend.push({ label: GROUP_NAME[g] ?? g, color: color(g), shape: "dot" });
    }
    if (on("n") && ev?.watch.length) legend.push({ label: "Reported in the news (hollow until confirmed)", color: color("news"), shape: "ring" });
    const all: LayerCounts = { ...counts };
    if (cw?.month) all.crisiswatch = `${cw.rows.filter((r) => r.subkind !== "unchanged").length} changed, ${cw.month}`;
    if (ev) { all.events = `${ev.events.length} in window`; all.news = `${ev.watch.length} in window`; }
    if (world) {
      all.history_world = `${world.count} states in ${yl(pastYear)}`;
      legend.push({ label: `States and empires in ${yl(pastYear)} (one colour per empire)`, color: cssVar("--series-4"), shape: "dot" });
    }
    // Picture layers over the country colours: climate zones (this app's tiles) and smoke (NASA).
    const rasters: RasterTiles[] = [];
    if (on("k")) {
      rasters.push({ tiles: zoneTiles("1991-2020", "historical", true), attribution: "Climate zones: Beck et al. 2023", maxzoom: 6, over: true, opacity: 0.75 });
      legend.push(...ZONE_GROUPS.map(([label, c]) => ({ label, color: c, shape: "dot" as const })));
    }
    if (on("x")) {
      const day = new Date(Date.now() - 2 * 86_400_000).toISOString().slice(0, 10);
      rasters.push({ tiles: `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Combined_Value_Added_AOD/default/${day}/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png`,
        attribution: "Smoke and dust: NASA GIBS", maxzoom: 6, over: true, opacity: 0.7 });
    }
    return { outlines, marks, filters, legend, counts: all, start, end, cwMonth: cw?.month ?? null, areas: world, rasters };
  }, [cw, ev, centres, counts, letters, start, end, minBeds, unsized, world, pastYear]); // eslint-disable-line react-hooks/exhaustive-deps
}

function inWindow(id: string, p: Record<string, unknown>, start: string, end: string): boolean {
  if (id === "earthquakes") { const d = String(p.date ?? ""); return d >= start && d <= `${end}~`; }
  if (id === "storm_tracks") { const y = Number(p.year); return y >= +start.slice(0, 4) && y <= +end.slice(0, 4); }
  return true;
}

// ----------------------------------------------------------------------------- the panel
const BASE_MAPS: { id: "plain" | "online" | "local"; label: string; gives: string }[] = [
  { id: "plain", label: "Countries only", gives: "No roads, towns or labels under the colours; fastest." },
  { id: "online", label: "Street detail (online)", gives: "Needs the internet; OpenFreeMap tiles." },
  { id: "local", label: "Street detail (this PC)", gives: "Only as far as the map files you made (Settings > Map)." },
];
const ZONE_GROUPS: [string, string][] = [["Tropical", "#1e6eeb"], ["Dry", "#f0a01e"], ["Temperate", "#5abe46"], ["Cold", "#965ac8"], ["Polar", "#aaaaaa"]];
const MADE_SWATCH: Record<string, () => string> = {
  climate_zones: () => "#5abe46", smoke: () => "#b4783c",
  crisiswatch: () => cssVar("--div-neg-3"), events: () => cssVar("--series-7"), news: () => cssVar("--series-4"),
  history_world: () => cssVar("--series-4"),
};

export default function LayersPanel({ panel, dispatch, win, onWin, counts, year, onClose }: {
  panel: PanelState; dispatch: (a: Action) => void; win: string; onWin: (w: string) => void; counts: LayerCounts;
  year: number | null; onClose: () => void;
}) {
  const s = useSettings();
  const [have, setHave] = useState<Map<string, MapLayerInfo> | null>(null);
  const [q, setQ] = useState("");
  const [shut, setShut] = useState<Set<string>>(new Set(["earth", "transport", "polar"]));
  const [playing, setPlaying] = useState(false);
  const [from, to] = windowDates(win || s.map_window, year);
  useEffect(() => { mapLayers().then((l) => setHave(new Map(l.map((x) => [x.layer_id, x])))).catch(() => setHave(new Map())); }, []);
  const set = (letters: string) => dispatch({ type: "panel", id: panel.id, patch: { layers: letters } });
  const toggle = (letter: string, on: boolean) => set(MAP_LAYERS.map((m) => m.letter).filter((l) => (l === letter ? on : panel.layers.includes(l))).join(""));
  // Play: a window of the chosen length moved through the last twelve months, a step every second and a half.
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);
  const play = () => {
    if (playing) { if (timer.current) clearInterval(timer.current); setPlaying(false); return; }
    const len = Math.max(7, Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000));
    let t = Date.now() - 365 * 86_400_000;
    const iso = (ms: number) => new Date(ms).toISOString().slice(0, 10);
    setPlaying(true);
    const step = () => {
      const end = Math.min(Date.now(), t + len * 86_400_000);
      onWin(`${iso(t)}~${iso(end)}`);
      if (end >= Date.now()) { if (timer.current) clearInterval(timer.current); setPlaying(false); }
      t += Math.max(7, Math.round(len / 2)) * 86_400_000;
    };
    step();
    timer.current = setInterval(step, 1500);
  };
  const status = (m: LayerDef): { ok: boolean; why: string; source: string } => {
    if (m.made) {
      if (m.id === "crisiswatch") return { ok: true, why: "", source: "Crisis Group, the latest month stored" };
      if (m.id === "events") return { ok: true, why: "", source: "Events from every source, placed on their country" };
      if (m.id === "history_world") return { ok: true, why: "", source: "Seshat Cliopatria borders (a refresh loads them)" };
      if (m.id === "climate_zones") return { ok: true, why: "", source: "Beck et al. 2023 (a refresh loads them)" };
      if (m.id === "smoke") return { ok: true, why: "", source: "NASA GIBS, read from the internet" };
      return { ok: true, why: "", source: "Your watch words in the news (Settings > Briefing)" };
    }
    if (m.id === "storms_active") return { ok: true, why: "", source: "NOAA IBTrACS, read when turned on (at most hourly)" };
    if (m.id === "live_planes") return s.live_planes ? { ok: true, why: "", source: "OpenSky Network, the area in view, once a minute" }
      : { ok: false, why: "Switched off in Settings > Transport", source: "" };
    if (m.id === "live_ships") return s.live_ships ? { ok: true, why: "", source: "aisstream.io, the area in view (needs AISSTREAM_API_KEY)" }
      : { ok: false, why: "Switched off in Settings > Transport", source: "" };
    if (LAYER_STYLE[m.id]?.fetch === "window") return { ok: true, why: "", source: "Read for the area in view (a refresh loads them)" };
    const info = have?.get(m.id);
    if (!have) return { ok: true, why: "", source: "" };
    if (!info) return { ok: false, why: "Not loaded yet: a refresh fetches it", source: "" };
    return { ok: true, why: "", source: `${info.source_name ?? info.source_id} · ${info.feature_count.toLocaleString()}` };
  };
  const words = q.trim().toLowerCase();
  const match = (m: LayerDef) => !words || `${m.label} ${m.hint ?? ""} ${have?.get(m.id)?.description ?? ""}`.toLowerCase().includes(words);
  const onNow = MAP_LAYERS.filter((m) => panel.layers.includes(m.letter));
  const saved = Object.entries(s.map_layer_sets ?? {});
  const saveSet = () => {
    const name = window.prompt("Name this set of layers", "")?.trim();
    if (!name) return;
    saveSettings({ map_layer_sets: { ...(s.map_layer_sets ?? {}), [name]: panel.layers } }).catch(() => undefined);
  };
  const dropSet = (name: string) => {
    const { [name]: _gone, ...rest } = s.map_layer_sets ?? {};
    saveSettings({ map_layer_sets: rest }).catch(() => undefined);
  };
  const swatch = (m: LayerDef) => (m.made ? MADE_SWATCH[m.id]?.() : LAYER_STYLE[m.id]?.swatch()) ?? cssVar("--muted");
  const custom = /~/.test(win);
  return (
    <aside className="layers-panel" aria-label="Layers">
      <div className="lp-head">
        <h2>Layers</h2>
        <span className="spacer" />
        <button className="small" onClick={onClose} aria-label="Close the layers panel">Close</button>
      </div>

      <div className="lp-section">
        <div className="lp-label">On now ({onNow.length})</div>
        {onNow.length === 0 && <p className="caption">None: tick a layer below or pick a quick set.</p>}
        <div className="chips-row">
          {onNow.map((m) => (
            <span key={m.letter} className="chip lp-chip">
              <i className="lp-swatch" style={{ background: swatch(m) }} />{m.label}
              <button aria-label={`Turn off ${m.label}`} onClick={() => toggle(m.letter, false)}>×</button>
            </span>
          ))}
          {onNow.length > 1 && <button className="link small" onClick={() => set("")}>All off</button>}
        </div>
      </div>

      <div className="lp-section">
        <div className="lp-label">Quick sets</div>
        <div className="lp-sets">
          {QUICK_SETS.map((qs) => (
            <button key={qs.name} className={`lp-set${panel.layers === qs.letters ? " on" : ""}`} onClick={() => set(qs.letters)} title={qs.hint}>
              <b>{qs.name}</b><span className="muted">{qs.hint}</span>
            </button>
          ))}
          {saved.map(([name, letters]) => (
            <span key={name} className={`lp-set mine${panel.layers === letters ? " on" : ""}`}>
              <button className="link" onClick={() => set(letters)}><b>{name}</b></button>
              <span className="muted">{MAP_LAYERS.filter((m) => letters.includes(m.letter)).map((m) => m.label).join(", ")}</span>
              <button className="x" aria-label={`Delete the set ${name}`} onClick={() => dropSet(name)}>×</button>
            </span>
          ))}
          <button className="lp-set" onClick={saveSet} disabled={!panel.layers} title="Keep the layers on now as a set of your own">
            <b>+ Save current set</b><span className="muted">Name it, use it on any map</span>
          </button>
        </div>
      </div>

      <label className="lp-section lp-label">Find a layer
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="quakes, cities, CrisisWatch…" />
      </label>

      <div className="lp-section">
        <div className="lp-label">Base map <span className="muted">pick one</span></div>
        <div className="lp-base" role="radiogroup" aria-label="Base map">
          {BASE_MAPS.map((b) => (
            <label key={b.id} className={`lp-set${s.base_map === b.id ? " on" : ""}`} title={b.gives}>
              <input type="radio" name={`base-${panel.id}`} checked={s.base_map === b.id} onChange={() => saveSettings({ base_map: b.id }).catch(() => undefined)} />
              {b.label}
            </label>
          ))}
        </div>
        <p className="caption">{BASE_MAPS.find((b) => b.id === s.base_map)?.gives} Satellite, night lights and relief come with the maps PR.</p>
      </div>

      {LAYER_GROUPS.map((g) => {
        const rows = MAP_LAYERS.filter((m) => m.group === g.id && match(m));
        if (!rows.length) return null;
        const open = !!words || !shut.has(g.id);
        const n = rows.filter((m) => panel.layers.includes(m.letter)).length;
        return (
          <div key={g.id} className="lp-group">
            <button className="lp-group-head" aria-expanded={open}
              onClick={() => setShut((cur) => { const x = new Set(cur); if (x.has(g.id)) x.delete(g.id); else x.add(g.id); return x; })}>
              {g.label} <span className="muted small">{n} of {rows.length} on {open ? "▾" : "▸"}</span>
            </button>
            {open && rows.map((m) => {
              const st = status(m);
              const checked = panel.layers.includes(m.letter);
              return (
                <label key={m.letter} className={`lp-row${st.ok ? "" : " off"}`} title={m.hint ?? have?.get(m.id)?.description ?? ""}>
                  <input type="checkbox" checked={checked} disabled={!st.ok && !checked} onChange={(e) => toggle(m.letter, e.target.checked)} />
                  <i className="lp-swatch" style={{ background: swatch(m) }} />
                  <span>
                    {m.label}{m.timed && <span className="lp-tag">timed</span>}
                    <small className="muted">{st.ok ? st.source : st.why}</small>
                  </span>
                  <span className="muted small lp-count">{checked ? counts[m.id] ?? "" : ""}</span>
                </label>
              );
            })}
          </div>
        );
      })}

      {panel.layers.includes("y") && <PastYear />}

      <div className="lp-section lp-window">
        <div className="lp-label">Time window for timed layers <span className="muted">{from} to {to}</span></div>
        <div className="seg" role="group" aria-label="Time window">
          {WINDOWS.map((w) => (
            <button key={w.id} className={(win || s.map_window) === w.id ? "on" : ""} aria-pressed={(win || s.map_window) === w.id}
              onClick={() => onWin(w.id === s.map_window ? "" : w.id)} disabled={w.id === "year" && !year}
              title={w.id === "year" ? "The year the country colours show" : undefined}>{w.label}</button>
          ))}
        </div>
        <div className="row small lp-dates">
          <label>From <input type="date" value={from} max={to} onChange={(e) => e.target.value && onWin(`${e.target.value}~${to}`)} /></label>
          <label>to <input type="date" value={to} min={from} onChange={(e) => e.target.value && onWin(`${from}~${e.target.value}`)} /></label>
          <button className="small" onClick={play} title="Move this window through the last twelve months">{playing ? "❚❚ Stop" : "▶ Play"}</button>
          {custom && !playing && <button className="link small" onClick={() => onWin("")}>Back to {WINDOWS.find((w) => w.id === s.map_window)?.label}</button>}
        </div>
        <p className="caption">One window for events, news, earthquakes and storms on every map on this page. Older items in the window are fainter.</p>
      </div>
      <p className="caption">
        Greyed layers say why. The opening map turns on {MAP_LAYERS.filter((m) => s.map_open_layers.includes(m.letter)).map((m) => m.label).join(", ") || "no layers"}:
        {" "}<Link href="/settings#briefing">change in Settings</Link>.
      </p>
    </aside>
  );
}

// The World in year layer's own year: a slider over 5,400 years, quick jumps, and Play.
const JUMPS = [-500, 1, 500, 1000, 1300, 1500, 1700, 1800, 1900, 1914, 1939, 2000];
function PastYear() {
  const y = useMapYear();
  const [playing, setPlaying] = useState(false);
  const [text, setText] = useState(String(y));
  useEffect(() => setText(String(y)), [y]);
  useEffect(() => {
    if (!playing) return;
    let cur = y;
    const t = setInterval(() => {
      cur = Math.min(2024, cur + 10);
      setMapYear(cur);
      if (cur >= 2024) setPlaying(false);
    }, 1200);
    return () => clearInterval(t);
  }, [playing]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="lp-section">
      <div className="lp-label">World in year <b>{yl(y)}</b></div>
      <input type="range" min={-3400} max={2024} value={y} onChange={(e) => setMapYear(+e.target.value)} style={{ width: "100%" }} aria-label="Year for the World in year layer" />
      <div className="row small lp-dates">
        <label>Year <input type="number" value={text} min={-3400} max={2024} style={{ width: 80 }}
          onChange={(e) => setText(e.target.value)} onBlur={() => Number.isFinite(+text) && setMapYear(+text)}
          onKeyDown={(e) => { if (e.key === "Enter" && Number.isFinite(+text)) setMapYear(+text); }} /></label>
        <button className="small" onClick={() => setPlaying(!playing)} title="Ten years at a time">{playing ? "❚❚ Stop" : "▶ Play"}</button>
      </div>
      <div className="row small" style={{ flexWrap: "wrap", gap: 4 }}>
        {JUMPS.map((j) => <button key={j} className="link small" onClick={() => setMapYear(j)}>{yl(j)}</button>)}
      </div>
      <p className="caption">Negative years are BC. Its own year, apart from the country colours&apos; year; pairs well with
        &quot;None (plain map)&quot;. Grey land had no state recorded that year. Hover a state for its name and years;
        empires&apos; cards are on <Link href="/long?tab=empires">Long history</Link>.</p>
    </div>
  );
}
