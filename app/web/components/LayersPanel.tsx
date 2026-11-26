"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { CW_LABEL } from "@/components/CrisisWatchCard";
import type { MapMark, MapOutline, RasterTiles } from "@/components/WorldMap";
import { api, type CrisisWatchMonth, type MapEvents } from "@/lib/api";
import { zoneTiles } from "@/lib/climate";
import { cssVar } from "@/lib/colors";
import { countryCentres } from "@/lib/geo";
import { DETAIL_LAYERS, detailsHref, layerApi, type LayerItem } from "@/lib/layerDetails";
import { CAMERA_KIND, CAMERA_SOURCE, cameraFilter, LAYER_STYLE, layerData, mapLayers, type MapLayerInfo } from "@/lib/layers";
import { LAND_COVER } from "@/lib/maplook";
import { PLANE_GROUPS, SHIP_GROUPS } from "@/lib/mapIcons";
import { setShipsAt, usePlaneStatus, useShipStatus, useShipsAt } from "@/lib/ships";
import { setFightingWindow } from "@/lib/osint";
import { CHANGE_LEGEND, changeLayer, spotLayer, waterTiles, WATER_LEGEND, type LayerPoint } from "@/lib/spotting";
import { saveSettings, useSettings } from "@/lib/settings";
import { showCameraWall, useCameraWall } from "@/lib/cameraWall";
import { forecastFields, hasWaves, hasWeather, useRadar, useWeatherStatus, useWeatherStep, weatherRasters } from "@/lib/weather";
import { GROUP_LABEL, KIND_GROUP, kindColor, yl } from "@/lib/long";
import { setMapYear, useMapYear, useWorldIn, useYearEvents, yearMarks } from "@/lib/longYear";
import {
  LAYER_GROUPS, MAP_LAYERS, QUICK_SETS, WINDOWS, wholeYear, windowDates, type Action, type LayerDef, type Panel as PanelState,
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
  const st = useSettings();
  const { map_hospital_beds: minBeds, map_hospitals_unsized: unsized, map_hospitals_all: allHospitals } = st;
  const { lists: hospLists, kinds: hospKinds } = hospitalPicks(st);
  const quakeMin = st.map_quake_min ?? 4.5;
  const [spotted, setSpotted] = useState<LayerPoint[] | null>(null);
  useEffect(() => {
    if (!on("0")) return;
    let live = true;
    spotLayer().then((p) => live && setSpotted(p)).catch(() => live && setSpotted([]));
    return () => { live = false; };
  }, [on("0"), st.spot_min_sure]); // eslint-disable-line react-hooks/exhaustive-deps
  const [start, end] = windowDates(win, year);
  useEffect(() => { if (on("3") || on("*")) setFightingWindow(start, end); }, [start, end, on("3"), on("*")]); // eslint-disable-line react-hooks/exhaustive-deps
  const [cw, setCw] = useState<CrisisWatchMonth | null>(null);
  const [ev, setEv] = useState<MapEvents | null>(null);
  const [centres, setCentres] = useState<Record<string, [number, number]> | null>(null);
  const [counts, setCounts] = useState<LayerCounts>({});
  const pastYear = useMapYear();
  const wx = useWeatherStatus(hasWeather(letters), hasWaves(letters)).status;
  const wxStep = useWeatherStep();
  const rad = useRadar(on("@")).radar;
  const world = useWorldIn(on("y"), pastYear);
  const past = useYearEvents(on("y"), pastYear);
  const pastLabels = useSettings().history_map_labels ?? 10;
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
    const want = MAP_LAYERS.filter((m) => m.timed && !m.made && !LAYER_STYLE[m.id]?.fetch && on(m.letter));
    Promise.all(want.map((m) => layerData(m.id).then((fc) => [m.id, fc] as const).catch(() => null))).then((got) => {
      if (!live) return;
      const out: LayerCounts = {};
      for (const g of got) {
        if (!g) continue;
        const [id, fc] = g;
        const n = fc.features.filter((f) => inWindow(id, f.properties ?? {}, start, end, quakeMin)).length;
        out[id] = `${n} in window`;
      }
      setCounts(out);
    });
    return () => { live = false; };
  }, [letters, start, end, quakeMin]); // eslint-disable-line react-hooks/exhaustive-deps

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
            + (h.place ? `<br/>Placed at ${esc(h.place.name)}` : "<br/>Placed at the country's centre")
            + "<br/><span class=\"muted\">Click for the story, its picture and more news from there</span>" });
      }
    }
    const filters: Record<string, unknown[] | null> = {
      earthquakes: ["all", [">=", ["to-string", ["get", "date"]], start], ["<=", ["to-string", ["get", "date"]], `${end}~`],
        [">=", ["coalesce", ["get", "mag"], 0], quakeMin]],
      storm_tracks: ["all", [">=", ["get", "year"], +start.slice(0, 4)], ["<=", ["get", "year"], +end.slice(0, 4)]],
      // Every hospital from every list, or (Settings > Places) those above a size and, if asked, those with no bed count.
      // Only the lists and likely kinds ticked in the Layers panel (dots from before the lists were split pass the list test).
      hospitals: ["all",
        ...(allHospitals === false ? [["any", [">=", ["coalesce", ["get", "beds"], -1], minBeds ?? 200], unsized ? ["!", ["has", "beds"]] : false]] : []),
        ...(hospLists.length < HOSPITAL_LISTS.length
          ? [["any", ["!", ["has", "found"]], ...hospLists.map((k) => ["in", HOSPITAL_LIST_NAME[k], ["get", "found"]])]] : []),
        ...(hospKinds.length < 3 ? [["in", ["coalesce", ["get", "tier"], "hospital"], ["literal", hospKinds]]] : [])],
      // Ship kinds and plane types switched off with the chips in the Layers panel.
      live_ships: hiddenFilter(st.map_ships_hidden),
      live_planes: hiddenFilter(st.map_planes_hidden),
      live_cameras: cameraFilter(st.map_cameras_hidden),
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
      all.history_world = `${world.count} states, ${past.events.length} events within ${past.window} years of ${yl(pastYear)}`;
      legend.push({ label: `States and empires in ${yl(pastYear)} (one colour per empire)`, color: cssVar("--series-4"), shape: "dot" });
      marks.push(...yearMarks(past.events, pastYear, past.window, pastLabels));
      for (const g of [...new Set(past.events.map((e) => KIND_GROUP[e.kind]))].filter(Boolean)) {
        legend.push({ label: GROUP_LABEL[g], color: kindColor(Object.keys(KIND_GROUP).find((k) => KIND_GROUP[k] === g)!), shape: "dot" });
      }
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
    if (on("Q")) {
      const day = new Date(Date.now() - 2 * 86_400_000).toISOString().slice(0, 10);
      rasters.push({ tiles: `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/GHRSST_L4_MUR_Sea_Surface_Temperature_Anomalies/default/${day}/GoogleMapsCompatible_Level7/{z}/{y}/{x}.png`,
        attribution: "Sea temperature against usual: NASA GIBS, GHRSST MUR", maxzoom: 7, over: true, opacity: 0.7 });
      legend.push({ label: "Sea warmer than usual (red) or cooler (blue)", color: "#e8590c", shape: "dot" });
    }
    if (on("X")) {
      rasters.push({ tiles: "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/GEDI_ISS_L3_Canopy_Height_Mean_RH100_201904-202104/default/default/GoogleMapsCompatible_Level7/{z}/{y}/{x}.png",
        attribution: "Tree height: NASA GEDI (GIBS)", maxzoom: 7, over: true, opacity: 0.8 });
      legend.push({ label: "Tree height (darker green: taller, up to 40 m+)", color: "#1b5e20", shape: "dot" });
    }
    // Worked out here: land change and water from the pictures, and what local AI scans spotted.
    if (on("8")) {
      const lc = changeLayer(st);
      rasters.push({ tiles: lc.tiles, attribution: lc.attribution, maxzoom: lc.maxzoom, over: true, opacity: 0.9 });
      legend.push(...CHANGE_LEGEND.map(([label, c]) => ({ label: `${label} (${lc.from}-${lc.to})`, color: c, shape: "dot" as const })).slice(0, 1),
        ...CHANGE_LEGEND.slice(1).map(([label, c]) => ({ label, color: c, shape: "dot" as const })));
    }
    if (on("9")) {
      rasters.push({ tiles: waterTiles(st.spot_water_show ?? "changes"), attribution: "Water: EC JRC / Google, Global Surface Water 1984-2021",
        maxzoom: 13, over: true, opacity: 0.9 });
      legend.push(...WATER_LEGEND.map(([label, c]) => ({ label, color: c, shape: "dot" as const })));
    }
    if (on("0") && spotted) {
      for (const p of spotted) {
        marks.push({ key: `ai:${p.scan}:${p.id}`, lng: p.lon, lat: p.lat, color: p.kind === "check" ? "#c92a2a" : tagColour(p.tag),
          hollow: p.kind === "check" || (p.mark !== "yes" && p.sure < 0.8), r: 5,
          href: `/spotting?tab=scans&scan=${encodeURIComponent(p.scan)}&item=${encodeURIComponent(p.id)}`,
          label: `<b>${esc(p.kind === "check" ? p.name : p.label)}</b>${p.kind === "check" ? `<br/>${esc(p.label)}` : ""}`
            + `<br/>Model ${Math.round(p.sure * 100)}% sure${p.mark === "yes" ? ", you marked it right" : ""}${p.note ? `<br/>${esc(p.note)}` : ""}`
            + "<br/><span class=\"muted\">Click to see the picture and mark it right or wrong</span>" });
      }
      all.ai_spotted = `${spotted.length} shown`;
      if (spotted.length) legend.push({ label: "Spotted by AI (hollow: less sure, red ring: map place looks wrong)", color: "#862e9c", shape: "ring" });
    }
    // Weather on top: forecast fields for the hour on the weather bar, satellite clouds, rain radar.
    rasters.push(...weatherRasters(letters, wx, wxStep, rad));
    if (wx?.run && (forecastFields(letters).length || letters.includes("^"))) all.wx_temp = all.wx_rain = all.wx_cloud = all.wx_wind = all.wx_pressure = all.wx_windlines = wx.steps.length < wx.all_steps.length
      ? `${wx.steps.length} of ${wx.all_steps.length} forecast hours in` : `next ${wx.days} days, ${wx.model_name}`;
    if (wx?.waves.run && hasWaves(letters)) all.wx_waves = all.wx_swell = wx.waves.steps.length < wx.waves.all_steps.length
      ? `${wx.waves.steps.length} of ${wx.waves.all_steps.length} wave steps in` : `next ${wx.days} days, every 6 hours`;
    return { outlines, marks, filters, legend, counts: all, start, end, cwMonth: cw?.month ?? null, areas: world, rasters,
      watch: on("n") ? ev?.watch ?? [] : [] };
  }, [cw, ev, centres, counts, letters, start, end, minBeds, unsized, world, pastYear, past, pastLabels, spotted, st.spot_change_source, st.spot_change_from, st.spot_change_to, st.spot_water_show, wx, wxStep, rad, st.map_hospital_sources, st.map_hospital_kinds, st.map_ships_hidden, st.map_planes_hidden, st.map_cameras_hidden, quakeMin]); // eslint-disable-line react-hooks/exhaustive-deps
}

const TAG_COLOUR: Record<string, string> = {
  open_pit_mine: "#862e9c", solar_farm: "#f59f00", airport: "#1971c2", port: "#0b7285", dam: "#1c7ed6", greenhouses: "#868e96",
  clearfell: "#e8590c", new_housing: "#c92a2a", industrial: "#495057", pivot_irrigation: "#2b8a3e", burn_scar: "#343a40", oil_gas: "#5c3d2e",
};
const tagColour = (t: string) => TAG_COLOUR[t] ?? "#862e9c";

function inWindow(id: string, p: Record<string, unknown>, start: string, end: string, quakeMin = 0): boolean {
  if (id === "earthquakes") { const d = String(p.date ?? ""); return d >= start && d <= `${end}~` && Number(p.mag ?? 0) >= quakeMin; }
  if (id === "storm_tracks") { const y = Number(p.year); return y >= +start.slice(0, 4) && y <= +end.slice(0, 4); }
  return true;
}

// ----------------------------------------------------------------------------- the panel
const BASE_MAPS: { id: "plain" | "online" | "local"; label: string; gives: string }[] = [
  { id: "plain", label: "Countries only", gives: "No roads, towns or labels under the colours; fastest." },
  { id: "online", label: "Street detail (online)", gives: "Needs the internet; OpenFreeMap tiles." },
  { id: "local", label: "Street detail (this PC)", gives: "Only as far as the map files you made (Settings > Map)." },
];
const LOOKS: { id: "plain" | "relief" | "satellite" | "sharp" | "night" | "landcover"; label: string; gives: string }[] = [
  { id: "plain", label: "Plain", gives: "Just the country colours." },
  { id: "relief", label: "Shaded relief", gives: "Mountains, valleys and sea depths, shaded as if lit from the north-west." },
  { id: "satellite", label: "Satellite (10 m, 2020)", gives: "A cloud-free picture of the whole Earth (Sentinel-2, 2020)." },
  { id: "sharp", label: "Satellite (sharp)", gives: "LINZ aerial photos in New Zealand (down to 7.5 cm; needs your free LINZ key) and Esri World Imagery elsewhere (about 0.5 m, for looking only)." },
  { id: "night", label: "Night lights", gives: "Lights seen from space at night: where people, money and power are." },
  { id: "landcover", label: "Land cover", gives: "What covers the ground at 10 m: trees, grass, crops, built-up land, water (ESA WorldCover)." },
];
// Read from the internet while on (marked "live" in the list).
const LIVE = new Set(["wx_temp", "wx_rain", "wx_cloud", "wx_wind", "wx_pressure", "wx_windlines", "wx_waves", "wx_swell", "air_now", "forecast_skill", "wx_radar", "wx_satellite", "fires_now", "fires_week", "storms_active", "heat_now", "coral_alerts", "smoke", "marine_heat", "live_planes", "live_ships", "live_military", "live_cameras"]);
const ZONE_GROUPS: [string, string][] = [["Tropical", "#1e6eeb"], ["Dry", "#f0a01e"], ["Temperate", "#5abe46"], ["Cold", "#965ac8"], ["Polar", "#aaaaaa"]];
const MADE_SWATCH: Record<string, () => string> = {
  climate_zones: () => "#5abe46", smoke: () => "#b4783c", marine_heat: () => "#e8590c", tree_height: () => "#1b5e20",
  crisiswatch: () => cssVar("--div-neg-3"), events: () => cssVar("--series-7"), news: () => cssVar("--series-4"),
  history_world: () => cssVar("--series-4"), electricity_mix: () => "#2c4f9e",
  land_change: () => "#c92a2a", water_change: () => "#1c7ed6", ai_spotted: () => "#862e9c",
  wx_temp: () => "#f08246", wx_rain: () => "#2878e6", wx_cloud: () => "#b4bcc6", wx_wind: () => "#3c8cc8",
  wx_pressure: () => "#283040", wx_radar: () => "#1fa34a", wx_satellite: () => "#d0d8e0",
  wx_windlines: () => "#1c263a", wx_waves: () => "#3278d2", wx_swell: () => "#6e50c8",
};

export default function LayersPanel({ panel, dispatch, win, onWin, counts, year, onClose, selection = [], names = new Map() }: {
  panel: PanelState; dispatch: (a: Action) => void; win: string; onWin: (w: string) => void; counts: LayerCounts;
  year: number | null; onClose: () => void; selection?: string[]; names?: Map<string, string>;
}) {
  const s = useSettings();
  const [have, setHave] = useState<Map<string, MapLayerInfo> | null>(null);
  const [q, setQ] = useState("");
  const [shut, setShut] = useState<Set<string>>(new Set()); // groups with a layer on that were closed
  const [opened, setOpened] = useState<Set<string>>(new Set()); // groups with nothing on that were opened
  const [waitingOpen, setWaitingOpen] = useState<Set<string>>(new Set());
  const [view, setView] = useState<"layers" | "look">("layers");
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
    if (m.made && m.id.startsWith("wx_")) {
      if (!s.weather_maps) return { ok: false, why: "Switched off in Settings > Climate", source: "" };
      if ((m.id === "wx_waves" || m.id === "wx_swell") && !s.weather_waves) return { ok: false, why: "Waves are switched off in Settings > Climate", source: "" };
      return { ok: true, why: "", source: m.id === "wx_radar" ? "RainViewer, read from the internet every 5 minutes"
        : m.id === "wx_satellite" ? "NASA GIBS (Himawari, GOES), read from the internet every 10 minutes"
        : m.id === "wx_waves" || m.id === "wx_swell" ? "NOAA GFS-Wave, downloaded to this PC every 6 hours while a wave layer is on"
        : s.weather_model === "ecmwf" ? "ECMWF IFS open data, downloaded to this PC twice a day while a forecast layer is on"
        : "NOAA GFS, downloaded to this PC every 6 hours while a forecast layer is on" };
    }
    if (m.made) {
      if (m.id === "crisiswatch") return { ok: true, why: "", source: "Crisis Group, the latest month stored" };
      if (m.id === "events") return { ok: true, why: "", source: "Events from every source, placed on their country" };
      if (m.id === "history_world") return { ok: true, why: "", source: "Seshat Cliopatria borders; events and rulers from Wikidata and NOAA (a refresh loads them)" };
      if (m.id === "climate_zones") return { ok: true, why: "", source: "Beck et al. 2023 (a refresh loads them)" };
      if (m.id === "electricity_mix") return { ok: true, why: "", source: "Our World in Data energy, each place's latest year" };
      if (m.id === "smoke") return { ok: true, why: "", source: "NASA GIBS, read from the internet" };
      if (m.id === "marine_heat") return { ok: true, why: "", source: "NASA GIBS (GHRSST MUR), read from the internet" };
      if (m.id === "tree_height") return { ok: true, why: "", source: "NASA GIBS (GEDI), read from the internet" };
      if (m.id === "land_change") return { ok: true, why: "", source: "Worked out here from the land cover maps (Esri or ESA), read from the internet; kept once worked out" };
      if (m.id === "water_change") return { ok: true, why: "", source: "EC JRC Global Surface Water, read from the internet" };
      if (m.id === "ai_spotted") return { ok: true, why: "", source: "Your area scans with a local model (Spotting page)" };
      return { ok: true, why: "", source: "Your watch words in the news (Settings > Briefing)" };
    }
    if (m.id === "power_links") return { ok: true, why: "", source: "Eurostat electricity trade by partner, the latest year (a refresh loads it)" };
    if (m.id === "city_stress") return { ok: true, why: "", source: "Our score from Numbeo, TomTom and WHO figures (Cities > City stress)" };
    if (m.id === "air_now") return s.weather_maps && s.weather_air ? { ok: true, why: "", source: "Open-Meteo air quality (CAMS), every 3 hours" }
      : { ok: false, why: "Switched off in Settings > Climate", source: "" };
    if (m.id === "forecast_skill") return s.weather_maps && s.weather_skill ? { ok: true, why: "", source: "Our scoring of 8 Open-Meteo models against airport reports (METAR), every 6 hours" }
      : { ok: false, why: "Switched off in Settings > Climate", source: "" };
    if (m.id === "storms_active") return { ok: true, why: "", source: "NOAA IBTrACS, read when turned on (at most hourly)" };
    if (["fires_now", "fires_week", "heat_now", "coral_alerts"].includes(m.id)) return s.hazards_live
      ? { ok: true, why: "", source: m.id === "heat_now" ? "Open-Meteo forecasts, every 6 hours" : m.id === "coral_alerts" ? "NOAA Coral Reef Watch, daily" : "NASA FIRMS, every 3 hours" }
      : { ok: false, why: "Switched off in Settings > Climate", source: "" };
    if (m.id === "live_planes") return s.live_planes ? { ok: true, why: "", source: "OpenSky Network, the area in view, once a minute" }
      : { ok: false, why: "Switched off in Settings > Transport", source: "" };
    if (m.id === "live_military") return s.live_military_planes ? { ok: true, why: "", source: "adsb.lol volunteer receivers, the area in view, once a minute" }
      : { ok: false, why: "Switched off in Settings > Transport", source: "" };
    if (m.id === "live_cameras") return s.live_cameras ? { ok: true, why: "", source: "Road agencies' public cameras (lists kept six hours) and Windy webcams with a free key, the area in view" }
      : { ok: false, why: "Switched off in Settings > Transport", source: "" };
    if (m.id === "conflict_events") return { ok: true, why: "", source: "UCDP and ACLED, the area in view (a refresh loads them; ACLED needs a free account)" };
    if (m.id === "front_line") return { ok: true, why: "", source: "DeepStateMap via GitHub (a refresh loads it)" };
    if (m.id === "live_ships") return s.live_ships ? { ok: true, why: "", source: "aisstream.io, the area in view (needs AISSTREAM_API_KEY)" }
      : { ok: false, why: "Switched off in Settings > Transport", source: "" };
    if (m.id === "night") return { ok: true, why: "", source: "Worked out here from the time and the Sun's position, every minute" };
    if (m.id === "timezones") return { ok: true, why: "", source: "timezone-boundary-builder outlines (a refresh loads them); offsets and local times from your browser's time zone rules" };
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
  const timedOn = onNow.some((m) => m.timed);
  const groupsShown = LAYER_GROUPS.map((g) => {
    const rows = MAP_LAYERS.filter((m) => m.group === g.id && match(m));
    const ready = rows.filter((m) => status(m).ok || panel.layers.includes(m.letter));
    const waiting = rows.filter((m) => !ready.includes(m));
    return { g, rows, ready, waiting, n: rows.filter((m) => panel.layers.includes(m.letter)).length };
  }).filter((x) => x.rows.length);
  const row = (m: LayerDef) => {
    const st = status(m);
    const checked = panel.layers.includes(m.letter);
    const tip = [m.hint ?? have?.get(m.id)?.description ?? "", st.ok ? st.source : st.why].filter(Boolean).join("\n");
    return (
      <div key={m.letter} className={`lp-row${st.ok ? "" : " off"}`} title={tip}>
        <input type="checkbox" checked={checked} disabled={!st.ok && !checked} onChange={(e) => toggle(m.letter, e.target.checked)}
          aria-label={m.label} id={`lp-${panel.id}-${m.letter}`} />
        <i className="lp-swatch" style={{ background: swatch(m) }} />
        <label htmlFor={`lp-${panel.id}-${m.letter}`} className="lp-name">
          {m.label}
          {m.timed && <span className="lp-tag" title="Follows the time window">timed</span>}
          {LIVE.has(m.id) && <span className="lp-tag" title="Read from the internet while it is on">live</span>}
          {LAYER_STYLE[m.id]?.fetch === "window" && m.id !== "night" && <span className="lp-tag" title="Big: read for the area in view as you move">big</span>}
          {!st.ok && <small className="muted">{st.why}</small>}
          {checked && counts[m.id] ? <small className="muted">{counts[m.id]}</small> : null}
        </label>
        {DETAIL_LAYERS.has(m.id) ? <Link className="small lp-details" href={detailsHref(m.id)} title={`${m.label}: counts by country, sizes and every item`}>Details</Link> : <span />}
      </div>
    );
  };
  return (
    <aside className="layers-panel" aria-label="Layers">
      <div className="lp-head">
        <h2>Layers</h2>
        <Link className="small" href="/layers" title="Every layer counted by country, with sizes">All in detail</Link>
        <span className="spacer" />
        <button className="small" onClick={onClose} aria-label="Close the layers panel">Close</button>
      </div>
      <div className="seg lp-tabs" role="tablist">
        <button role="tab" aria-selected={view === "layers"} className={view === "layers" ? "on" : ""} onClick={() => setView("layers")}>Layers</button>
        <button role="tab" aria-selected={view === "look"} className={view === "look" ? "on" : ""} onClick={() => setView("look")}>Map look</button>
      </div>

      {view === "look" ? (
        <>
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
        <p className="caption">{BASE_MAPS.find((b) => b.id === s.base_map)?.gives}</p>
      </div>

          <div className="lp-section">
        <div className="lp-label">Shape</div>
        <div className="lp-look-opts">
          <label className="small"><input type="checkbox" checked={s.plain_map_borders} onChange={(e) => saveSettings({ plain_map_borders: e.target.checked }).catch(() => undefined)} /> Country borders with &quot;None (plain map)&quot;</label>
          <label className="small"><input type="checkbox" checked={s.map_globe} onChange={(e) => saveSettings({ map_globe: e.target.checked }).catch(() => undefined)} /> Globe (drag to spin; the globe button on the map does the same)</label>
          {s.map_globe && (<>
            <label className="small"><input type="checkbox" checked={s.globe_space} onChange={(e) => saveSettings({ globe_space: e.target.checked }).catch(() => undefined)} /> Space look (dark sky, blue glow and land)</label>
            <label className="small"><input type="checkbox" checked={s.globe_grid} onChange={(e) => saveSettings({ globe_grid: e.target.checked }).catch(() => undefined)} /> Grid lines</label>
          </>)}
        </div>
      </div>

          <div className="lp-section">
        <div className="lp-label">Background <span className="muted">under the colours</span></div>
        <div className="lp-base lp-look" role="radiogroup" aria-label="Background">
          {LOOKS.map((b) => (
            <label key={b.id} className={`lp-set${s.map_look === b.id ? " on" : ""}`} title={b.gives}>
              <input type="radio" name={`look-${panel.id}`} checked={s.map_look === b.id} onChange={() => saveSettings({ map_look: b.id }).catch(() => undefined)} />
              {b.label}
            </label>
          ))}
        </div>
        <p className="caption">{LOOKS.find((b) => b.id === s.map_look)?.gives}</p>
        {s.map_look === "relief" && (
          <div className="lp-look-opts">
            <label className="small">Style{" "}
              <select value={s.relief_style} onChange={(e) => saveSettings({ relief_style: e.target.value as typeof s.relief_style }).catch(() => undefined)}>
                <option value="classic">Height colours</option><option value="grey">Grey</option><option value="satellite">Over satellite</option>
              </select>
            </label>
            <label className="small">Shading{" "}
              <input type="range" min={0} max={1} step={0.05} value={s.relief_shading}
                onChange={(e) => saveSettings({ relief_shading: Number(e.target.value) }).catch(() => undefined)} />
            </label>
          </div>
        )}
        {s.map_look === "night" && (
          <div className="lp-look-opts">
            <label className="small">Lights of{" "}
              <select value={s.night_year} onChange={(e) => saveSettings({ night_year: e.target.value as typeof s.night_year }).catch(() => undefined)}>
                <option value="2016">2016 (yearly picture)</option><option value="2012">2012 (yearly picture)</option><option value="latest">Last night (clouds and moonlight show)</option>
              </select>
            </label>
          </div>
        )}
        {s.map_look === "landcover" && (
          <div className="lp-look-opts">
            <label className="small">Year{" "}
              <select value={s.land_cover_year} onChange={(e) => saveSettings({ land_cover_year: e.target.value as typeof s.land_cover_year }).catch(() => undefined)}>
                <option value="2021">2021</option><option value="2020">2020</option>
              </select>
            </label>
            <div className="legend small">{LAND_COVER.map(([n, c]) => <span key={n} className="legend-item"><i style={{ background: c }} />{n}</span>)}</div>
          </div>
        )}
        {s.map_look !== "plain" && (
          <div className="lp-look-opts">
            <label className="small">Country colours{" "}
              <input type="range" min={0} max={1} step={0.05} value={s.map_colours_over}
                onChange={(e) => saveSettings({ map_colours_over: Number(e.target.value) }).catch(() => undefined)} />
            </label>
            <label className="small"><input type="checkbox" checked={s.map_3d} onChange={(e) => saveSettings({ map_3d: e.target.checked }).catch(() => undefined)} /> 3D (tilt with right-drag)</label>
          </div>
        )}
        <p className="caption"><Link href="/settings#maps">Saved copies</Link> make these quick and work offline; <Link href="/shapes">Map shapes</Link> has true size and cartograms; <Link href="/regions">Regions inside a country</Link> maps US states and counties and New Zealand's regions.</p>
      </div>

        </>
      ) : (
        <>
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a layer (hospitals, quakes, cables…)"
            aria-label="Find a layer" className="lp-find" />

          <div className="lp-section">
            <div className="lp-label">On now ({onNow.length}){onNow.length > 1 && <button className="link small" style={{ marginLeft: 8 }} onClick={() => set("")}>All off</button>}</div>
            {onNow.length === 0 ? <p className="caption">None: tick a layer below or pick a quick set.</p> : (
              <div className="chips-row">
                {onNow.map((m) => (
                  <span key={m.letter} className="chip lp-chip">
                    <i className="lp-swatch" style={{ background: swatch(m) }} />{m.label}
                    <button aria-label={`Turn off ${m.label}`} onClick={() => toggle(m.letter, false)}>×</button>
                  </span>
                ))}
              </div>
            )}
          </div>

          {timedOn && (
            <div className="lp-section lp-window">
        <div className="lp-label">Time window for timed layers <span className="muted">{from} to {to}</span></div>
        <div className="seg" role="group" aria-label="Time window">
          {WINDOWS.map((w) => (
            <button key={w.id} className={(win || s.map_window) === w.id ? "on" : ""} aria-pressed={(win || s.map_window) === w.id}
              onClick={() => onWin(w.id === s.map_window ? "" : w.id)}
              title={w.id === "year" ? (year ? `${year}, the year the country colours show` : "Last year (the map shows no country colours, so no colour year)") : undefined}>
              {w.id === "year" && !year ? "Last year" : w.label}</button>
          ))}
        </div>
        {wholeYear(from, to) !== null && (() => {
          const y = wholeYear(from, to)!;
          const now = new Date().getUTCFullYear();
          const goTo = (n: number) => onWin(`${n}-01-01~${n}-12-31`);
          return (
            <div className="row small lp-dates" role="group" aria-label="Year">
              <button className="small" onClick={() => goTo(y - 1)} aria-label="The year before">‹ {y - 1}</button>
              <b>{y}</b>
              <button className="small" onClick={() => goTo(y + 1)} disabled={y >= now} aria-label="The year after">{y + 1} ›</button>
            </div>
          );
        })()}
        <div className="row small lp-dates">
          <label>From <input type="date" value={from} max={to} onChange={(e) => e.target.value && onWin(`${e.target.value}~${to}`)} /></label>
          <label>to <input type="date" value={to} min={from} onChange={(e) => e.target.value && onWin(`${from}~${e.target.value}`)} /></label>
          <button className="small" onClick={play} title="Move this window through the last twelve months">{playing ? "❚❚ Stop" : "▶ Play"}</button>
          {custom && !playing && <button className="link small" onClick={() => onWin("")}>Back to {WINDOWS.find((w) => w.id === s.map_window)?.label}</button>}
        </div>
        <p className="caption">One window for events, news, earthquakes and storms on every map on this page. Older items in the window are fainter.</p>
      </div>
          )}
          {panel.layers.includes("y") && <PastYear />}
          {(panel.layers.includes("S") || panel.layers.includes("F")) && <ShipsTime ships={panel.layers.includes("S")} planes={panel.layers.includes("F")} />}
          {panel.layers.includes("F") && <Kinds title="Planes now, by type" groups={PLANE_GROUPS} href="/live?tab=planes" />}
          {panel.layers.includes("h") && <HospitalPick />}
          {panel.layers.includes("q") && <QuakePick selection={selection} names={names} from={from} to={to} />}
          {panel.layers.includes("-") && <CameraKinds />}

          <div className="lp-section">
            <div className="lp-label">Quick sets</div>
            <div className="chips-row lp-quick">
              {QUICK_SETS.map((qs) => (
                <button key={qs.name} className={`chip${panel.layers === qs.letters ? " on" : ""}`} onClick={() => set(qs.letters)} title={qs.hint}
                  aria-pressed={panel.layers === qs.letters}>{qs.name}</button>
              ))}
              {saved.map(([name, letters]) => (
                <span key={name} className={`chip mine${panel.layers === letters ? " on" : ""}`}
                  title={MAP_LAYERS.filter((m) => letters.includes(m.letter)).map((m) => m.label).join(", ")}>
                  <button className="link" onClick={() => set(letters)}>{name}</button>
                  <button aria-label={`Delete the set ${name}`} onClick={() => dropSet(name)}>×</button>
                </span>
              ))}
              <button className="chip" onClick={saveSet} disabled={!panel.layers} title="Keep the layers on now as a set of your own">+ Save</button>
            </div>
          </div>

          {groupsShown.map(({ g, rows, ready, waiting, n }) => {
            const open = !!words || n > 0 ? !shut.has(g.id) || !!words : opened.has(g.id);
            const flip = () => {
              if (n > 0 || words) setShut((cur) => { const x = new Set(cur); if (x.has(g.id)) x.delete(g.id); else x.add(g.id); return x; });
              else setOpened((cur) => { const x = new Set(cur); if (x.has(g.id)) x.delete(g.id); else x.add(g.id); return x; });
            };
            const showWaiting = waitingOpen.has(g.id) || !!words;
            return (
              <div key={g.id} className="lp-group">
                <button className="lp-group-head" aria-expanded={open} onClick={flip}>
                  <span>{g.label} {open ? "▾" : "▸"}</span><span className="muted small">{n} of {rows.length} on</span>
                </button>
                {open && ready.map(row)}
                {open && waiting.length > 0 && (showWaiting ? waiting.map(row) : (
                  <button className="link small lp-waiting" onClick={() => setWaitingOpen((cur) => new Set(cur).add(g.id))}>
                    {waiting.length} not loaded yet ▸</button>
                ))}
              </div>
            );
          })}
          {words && !groupsShown.length && <p className="caption">No layer matches &quot;{q}&quot;.</p>}

          <p className="caption">
            Hover a layer for where it comes from. The opening map turns on {MAP_LAYERS.filter((m) => s.map_open_layers.includes(m.letter)).map((m) => m.label).join(", ") || "no layers"}:
            {" "}<Link href="/settings#briefing">change in Settings</Link>.
          </p>
        </>
      )}
    </aside>
  );
}

// The World in year layer's own year: a slider over 5,400 years, quick jumps, and Play.
const JUMPS = [-500, 1, 500, 1000, 1300, 1500, 1700, 1800, 1900, 1914, 1939, 2000];
// The lists the Hospitals layer is merged from, as each dot's "found" names them.
// Settings keep the keys (worldmodel_contract.health SOURCES); dots name the lists.
export const HOSPITAL_LISTS = ["wikidata", "osm", "overture", "national"];
const HOSPITAL_LIST_NAME: Record<string, string> = { wikidata: "Wikidata", osm: "OpenStreetMap", overture: "Overture", national: "Official lists" };
const HOSPITAL_KINDS: [string, string, string][] = [
  ["hospital", "Likely hospitals", "Beds of 50 or more, a hospital word in the name, or listed by Wikidata, an official list or with an emergency department"],
  ["unsure", "Not sure", "Called a hospital by OpenStreetMap or Overture with nothing else to go on (often no name)"],
  ["clinic", "Likely clinics", "Fewer than 20 beds, or a clinic, health post, dental, dialysis or office word in the name (诊所, 卫生院, puskesmas...)"],
];

// The lists and likely kinds ticked, from Settings (anything unknown left out).
function hospitalPicks(s: { map_hospital_sources?: string; map_hospital_kinds?: string }) {
  const pick = (v: string | undefined, fallback: string, known: string[]) => (v ?? fallback).split(",").filter((x) => known.includes(x));
  return { lists: pick(s.map_hospital_sources, HOSPITAL_LISTS.join(","), HOSPITAL_LISTS),
           kinds: pick(s.map_hospital_kinds, "hospital", HOSPITAL_KINDS.map((k) => k[0])) };
}

// Hospitals: which lists and which likely kinds the layer shows, on every map (saved in Settings).
function HospitalPick() {
  const { lists, kinds } = hospitalPicks(useSettings());
  const flip = (have: string[], x: string, all: string[]) => all.filter((a) => (a === x ? !have.includes(a) : have.includes(a))).join(",");
  return (
    <div className="lp-section">
      <div className="lp-label">Hospitals: lists shown</div>
      <div className="chips-row">
        {HOSPITAL_LISTS.map((l) => (
          <label key={l} className="small" style={{ marginRight: 10 }}>
            <input type="checkbox" checked={lists.includes(l)} onChange={() => saveSettings({ map_hospital_sources: flip(lists, l, HOSPITAL_LISTS) })} /> {HOSPITAL_LIST_NAME[l]}
          </label>))}
      </div>
      <div className="lp-label">Kinds shown</div>
      <div className="chips-row">
        {HOSPITAL_KINDS.map(([k, label, why]) => (
          <label key={k} className="small" style={{ marginRight: 10 }} title={why}>
            <input type="checkbox" checked={kinds.includes(k)}
              onChange={() => saveSettings({ map_hospital_kinds: flip(kinds, k, HOSPITAL_KINDS.map((x) => x[0])) })} /> {label}
          </label>))}
      </div>
      <p className="caption">A hospital two lists share shows if either is ticked. Solid dots are likely hospitals, pale ones unsure,
        rings likely clinics (only likely hospitals are ticked at first); hover a kind for how it is told. <Link href="/layers/hospitals?tab=sizes">Details</Link> has counts by list.</p>
    </div>
  );
}

// Earthquakes: the smallest magnitude shown on every map (saved in Settings), and for each selected
// country its quakes in the time window, biggest or newest first, with the full list on the layer's page.
const QUAKE_MINS = [3, 4.5, 5, 6, 7];
function QuakePick({ selection, names, from, to }: { selection: string[]; names: Map<string, string>; from: string; to: string }) {
  const min = useSettings().map_quake_min ?? 4.5;
  const [sort, setSort] = useState<"size" | "date">("size");
  const [who, setWho] = useState("");
  const country = selection.includes(who) ? who : selection[0] ?? "";
  const [got, setGot] = useState<{ rows: LayerItem[]; total: number } | null>(null);
  useEffect(() => {
    if (!country) { setGot(null); return; }
    let live = true;
    setGot(null);
    layerApi.items("earthquakes", { country, sort, limit: 15, min_size: min, date_from: from, date_to: to })
      .then((r) => live && setGot(r)).catch(() => live && setGot({ rows: [], total: 0 }));
    return () => { live = false; };
  }, [country, sort, min, from, to]);
  const name = names.get(country) ?? country;
  const full = `/layers/earthquakes?tab=items&country=${encodeURIComponent(country)}&sort=${sort}&min=${min}&from=${from}&to=${to}`;
  return (
    <div className="lp-section">
      <div className="lp-label">Earthquakes: smallest shown</div>
      <div className="seg" role="group" aria-label="Smallest magnitude shown">
        {QUAKE_MINS.map((m) => <button key={m} className={min === m ? "on" : ""} aria-pressed={min === m}
          onClick={() => saveSettings({ map_quake_min: m }).catch(() => undefined)}>{m}+</button>)}
      </div>
      <p className="caption">Below 6 only since 2016; below 4.5 only around New Zealand (GeoNet).</p>
      {!country ? <p className="caption">Pick a country (shift-click it on the map or use the box above) to list its earthquakes.</p> : (
        <>
          <div className="lp-label" style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
            {selection.length > 1
              ? <select value={country} onChange={(e) => setWho(e.target.value)} aria-label="Country">
                  {selection.map((c) => <option key={c} value={c}>{names.get(c) ?? c}</option>)}</select>
              : <span>{name}</span>}
            <span className="muted">{got ? `${got.total.toLocaleString()} of ${min}+ in the window` : "…"}</span>
          </div>
          <div className="seg" role="group" aria-label="Order">
            <button className={sort === "size" ? "on" : ""} aria-pressed={sort === "size"} onClick={() => setSort("size")}>Biggest first</button>
            <button className={sort === "date" ? "on" : ""} aria-pressed={sort === "date"} onClick={() => setSort("date")}>Newest first</button>
          </div>
          {got && got.rows.length > 0 && (
            <table className="small lp-quakes"><tbody>{got.rows.map((r) => (
              <tr key={r.item_id}>
                <td style={{ textAlign: "right" }}><b>{r.size?.toFixed(1)}</b></td>
                <td style={{ whiteSpace: "nowrap" }}>{String(r.fields.date ?? "")}</td>
                <td>{r.url ? <a href={r.url} target="_blank" rel="noreferrer">{placeOf(r.name)}</a> : placeOf(r.name)}</td>
              </tr>))}</tbody></table>
          )}
          {got && got.total === 0 && <p className="caption">None of {min}+ in {name} from {from} to {to}.</p>}
          <Link className="small" href={full}>Full list for {name}{got && got.total > got.rows.length ? ` (all ${got.total.toLocaleString()})` : ""}</Link>
        </>
      )}
    </div>
  );
}
const placeOf = (title: string) => title.replace(/^M\s*[\d.]+\s*-\s*/, "");

function hiddenFilter(hidden?: string): unknown[] | null {
  const off = (hidden ?? "").split(",").filter(Boolean);
  return off.length ? ["!", ["in", ["coalesce", ["get", "group"], "unknown"], ["literal", off]]] : null;
}

// Coloured chips for a layer's kinds; clicking one hides or shows that kind on the map (kept in settings).
// One setting can hold several rows of chips (the Cameras layer's kinds and owners): each row
// changes only its own ids.
type ChipSetting = "map_ships_hidden" | "map_planes_hidden" | "map_cameras_hidden";
function KindChips({ groups, setting, caption = true }: { groups: { id: string; label: string; color?: string; title?: string }[]; setting: ChipSetting; caption?: boolean }) {
  const all = (useSettings()[setting] ?? "").split(",").filter(Boolean);
  const mine = new Set(groups.map((g) => g.id));
  const hidden = all.filter((x) => mine.has(x));
  const save = (v: string[]) => saveSettings({ [setting]: [...all.filter((x) => !mine.has(x)), ...v].join(",") });
  const only = (id: string) => save(groups.map((g) => g.id).filter((x) => x !== id));
  return (
    <>
      <div className="chips-row">
        {groups.map((g) => {
          const off = hidden.includes(g.id);
          return (
            <button key={g.id} className="chip small" aria-pressed={!off} style={{ opacity: off ? 0.45 : 1, textDecoration: off ? "line-through" : undefined }}
              title={`${g.title ? `${g.title}. ` : ""}${off ? "Hidden: click to show. Shift-click to show only this one." : "Click to hide. Shift-click to show only this one."}`}
              onClick={(e) => e.shiftKey ? only(g.id) : save(off ? hidden.filter((x) => x !== g.id) : [...hidden, g.id])}>
              {g.color && <i style={{ background: g.color, display: "inline-block", width: 8, height: 8, borderRadius: 4, marginRight: 4 }} />}{g.label}
            </button>);
        })}
      </div>
      {caption && <p className="caption">Click a kind to hide or show it; shift-click to show only that kind.
        {hidden.length ? <> {hidden.length} hidden. <button className="link small" onClick={() => save([])}>Show all</button></> : null}</p>}
    </>
  );
}

// The Cameras layer: switch kinds of camera, and whose cameras, on and off; the camera wall.
function CameraKinds() {
  const s = useSettings();
  const hidden = (s.map_cameras_hidden ?? "").split(",").filter(Boolean);
  const wall = useCameraWall();
  return (
    <div className="lp-section">
      <div className="lp-label">Cameras</div>
      <div className="caption" style={{ margin: "2px 0" }}>Kind</div>
      <KindChips setting="map_cameras_hidden" caption={false}
        groups={[...Object.entries(CAMERA_KIND).map(([id, k]) => ({ id, label: k.label, color: k.color })),
          { id: "offline", label: "Offline", title: "Cameras their owner marks offline (hollow dots)" }]} />
      <div className="caption" style={{ margin: "4px 0 2px" }}>Whose</div>
      <KindChips setting="map_cameras_hidden" caption={false}
        groups={CAMERA_SOURCE.map((x) => ({ id: x.id, label: x.label, title: x.name }))} />
      <p className="caption">Click to hide or show; shift-click to show only that one.
        {hidden.length ? <> {hidden.length} hidden. <button className="link small" onClick={() => saveSettings({ map_cameras_hidden: "" })}>Show all</button></> : null}
        {" "}Click a camera for its picture; <b>Add to wall</b> on its card (or ctrl-click the dot) puts it on the camera wall, to watch several at once
        {wall.length ? <> ({wall.length} on the wall. <button className="link small" onClick={() => showCameraWall(true)}>Show the wall</button>)</> : null}.</p>
    </div>
  );
}

// Flags beside planes and logos beside airliners once zoomed in (also in Settings > Transport).
function PlaneBadgeToggles() {
  const s = useSettings();
  return (
    <div className="row small" style={{ gap: 12 }}>
      <label title="Each plane's flag (the country that issued its transponder address) beside it when zoomed in">
        <input type="checkbox" checked={s.planes_badges !== false} onChange={(e) => saveSettings({ planes_badges: e.target.checked }).catch(() => undefined)} /> Flags</label>
      <label title="The airline's logo beside airliners when zoomed in, and in the Planes table and card">
        <input type="checkbox" checked={s.planes_logos !== false} onChange={(e) => saveSettings({ planes_logos: e.target.checked }).catch(() => undefined)} /> Airline logos</label>
      <span className="caption">shown when zoomed in</span>
    </div>
  );
}

function Kinds({ title, groups, href }: { title: string; groups: { id: string; label: string; color: string }[]; href: string }) {
  return (
    <div className="lp-section">
      <div className="lp-label">{title} <Link className="small" href={href}>Table</Link></div>
      <KindChips groups={groups} setting="map_planes_hidden" />
      <PlaneBadgeToggles />
      <p className="caption">Shapes point where each is heading. Click one for where it came from and where it is going.</p>
    </div>
  );
}

// The Ships and Planes layers' time: now, or any time since they were first saved (Settings > Transport).
function ShipsTime({ ships, planes }: { ships: boolean; planes: boolean }) {
  const st = useShipStatus(ships);
  const pst = usePlaneStatus(planes);
  const at = useShipsAt();
  const [playing, setPlaying] = useState(false);
  const firsts = [ships ? st?.first : null, planes ? pst?.first : null].filter((x): x is number => typeof x === "number");
  const lasts = [ships ? st?.last : null, planes ? pst?.last : null].filter((x): x is number => typeof x === "number");
  const first = firsts.length ? Math.min(...firsts) : null;
  const last = lasts.length ? Math.max(...lasts) : Math.round(Date.now() / 1000);
  useEffect(() => () => setShipsAt(null), []); // back to now when the layer is turned off
  useEffect(() => {
    if (!playing || !first) return;
    let cur = at ?? first;
    const t = setInterval(() => {
      cur = cur + 3600;
      if (cur >= last) { setPlaying(false); setShipsAt(null); return; }
      setShipsAt(cur);
    }, 1500);
    return () => clearInterval(t);
  }, [playing]); // eslint-disable-line react-hooks/exhaustive-deps
  const fmt = (t: number) => new Date(t * 1000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const size = st ? (st.bytes > 1e9 ? `${(st.bytes / 1e9).toFixed(1)} GB` : `${Math.max(0.1, st.bytes / 1e6).toFixed(1)} MB`) : "";
  return (
    <div className="lp-section">
      <div className="lp-label">{ships && planes ? "Ships and planes" : ships ? "Ships" : "Planes"} {at ? <>at <b>{fmt(at)}</b></> : <b>now</b>}
        {ships && <> <Link className="small" href="/live?tab=ships">Ships table</Link></>}{planes && <> <Link className="small" href="/live?tab=planes">Planes table</Link></>}</div>
      {first && first < last - 1800 ? (
        <>
          <input type="range" min={first} max={last} step={600} value={at ?? last} style={{ width: "100%" }} aria-label="Time the ships show"
            onChange={(e) => { const v = +e.target.value; setShipsAt(v >= last - 600 ? null : v); }} />
          <div className="row small lp-dates">
            <span className="muted">{fmt(first)}</span><span className="spacer" />
            <button className="small" onClick={() => setPlaying(!playing)} title="An hour at a time">{playing ? "❚❚ Stop" : "▶ Play"}</button>
            {at && <button className="link small" onClick={() => { setPlaying(false); setShipsAt(null); }}>Now</button>}
          </div>
        </>
      ) : <p className="caption">The time slider appears once {ships ? "ships" : "planes"} have been saved for a while.</p>}
      {planes && pst && (
        <p className="caption">{pst.collecting
          ? <>Saving planes as the map gets them: {(pst.planes ?? 0).toLocaleString()} planes, {pst.days} day{pst.days === 1 ? "" : "s"},{" "}
            {pst.bytes > 1e9 ? `${(pst.bytes / 1e9).toFixed(1)} GB` : `${Math.max(0.1, pst.bytes / 1e6).toFixed(1)} MB`} (kept {pst.keep_days} days).
            {pst.world_every_minutes ? ` The whole world is asked every ${pst.world_every_minutes} minutes.` : ""}{pst.world_note ? ` ${pst.world_note}` : ""}</>
          : <>Planes are not being saved; turn on Save planes in <Link href="/settings#transport">Settings</Link>.</>}</p>
      )}
      {ships && <KindChips groups={SHIP_GROUPS} setting="map_ships_hidden" />}
      {ships && <p className="caption">
        {st?.collecting
          ? <>Saving ships for {st.area}{st.world_every_hours ? `, and the whole world for 10 minutes every ${st.world_every_hours} hours` : ""}:
            {" "}{(st.ships ?? 0).toLocaleString()} ships, {st.days} day{st.days === 1 ? "" : "s"}, {size} (kept {st.keep_days} days).{st.world_note ? ` ${st.world_note}` : ""}</>
          : <>Ships are not being saved: only the area in view, while the layer is on. Turn on Collect ships in <Link href="/settings#transport">Settings</Link>.</>}
        {st?.error ? <> <b>{st.error}</b></> : null}
        {" "}Red-ringed ships are on a sanctions list. Click a ship for where it has been and where it is going.
      </p>}
    </div>
  );
}

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
