// Then and now (Spotting page): which pictures of a place there are, the before and after slider's
// tile addresses, What changed? (Ask AI with both pictures), and Landsat timelapses since 1984.

import { get, send } from "@/lib/api";
import { openAsk, toast, type AskPart } from "@/lib/ai";
import { aerialTiles, ESRI_NOW } from "@/lib/maplook";

export type Survey = { layer: string; title: string; year_from: number | null; year_to: number | null; gsd: number | null;
  kind: "urban" | "rural" | "historical" | "satellite" | "other"; region: string };
export type Dates = { lon: number; lat: number; nz: boolean; linz: Survey[]; linz_list: { state: string; error: string | null; built?: string | null };
  linz_key: boolean; eox: string[]; places: Record<string, number[]> };
export type WaybackVersion = { release: number; date: string };

// One picture the slider can show.
export type Source = { id: string; kind: "linz" | "eox" | "esri" | "wayback"; label: string; year: number; ai: boolean;
  tiles: string; maxzoom: number; attribution: string; release?: number; date?: string };

const origin = () => (typeof location !== "undefined" ? location.origin : "");
const WAYBACK = "https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/WMTS/1.0.0/default028mm/MapServer/tile/{release}/{z}/{y}/{x}";
const ESRI_NOTE = "Esri World Imagery (for looking only)";

export const placeDates = (lon: number, lat: number) => get<Dates>("/thennow/dates", { lon: lon.toFixed(5), lat: lat.toFixed(5) });
export const waybackVersions = (lon: number, lat: number) =>
  get<{ versions: WaybackVersion[]; error: string | null }>("/thennow/wayback", { lon: lon.toFixed(5), lat: lat.toFixed(5) });

const years = (s: Survey) => (s.year_from && s.year_to && s.year_to !== s.year_from ? `${s.year_from}-${s.year_to}` : `${s.year_to ?? s.year_from ?? "?"}`);
const detail = (m: number | null) => (m == null ? "" : m >= 1 ? `${m} m` : `${Math.round(m * 100)} cm`);

export function sources(d: Dates | null, wayback: WaybackVersion[]): Source[] {
  const out: Source[] = [];
  for (const s of d?.linz ?? []) {
    out.push({ id: `linz:${s.layer}`, kind: "linz", label: `${years(s)} · LINZ ${s.kind === "satellite" ? "satellite" : s.kind === "historical" ? "historical photo" : "aerial"} ${detail(s.gsd)} (${s.title.replace(/\s*\(.*\)$/, "")})`,
      year: s.year_to ?? s.year_from ?? 0, ai: true, tiles: aerialTiles(s.layer), maxzoom: 21, attribution: "Aerial photos: Toitū Te Whenua LINZ (CC BY 4.0)" });
  }
  out.push({ id: "esri:now", kind: "esri", label: `Now · ${ESRI_NOTE}`, year: new Date().getFullYear(), ai: false, tiles: ESRI_NOW, maxzoom: 19,
    attribution: "Esri World Imagery (Maxar, Earthstar Geographics and others)" });
  for (const w of wayback) {
    out.push({ id: `wayback:${w.date}`, kind: "wayback", label: `${w.date} · Esri version (looking only)`, year: +w.date.slice(0, 4), ai: false,
      tiles: WAYBACK.replace("{release}", String(w.release)), maxzoom: 19, attribution: `Esri World Imagery Wayback, ${w.date}`, release: w.release, date: w.date });
  }
  for (const y of d?.eox ?? []) {
    out.push({ id: `eox:${y}`, kind: "eox", label: `${y} · Sentinel-2 10 m (EOX)`, year: +y, ai: true, tiles: `${origin()}/api/v1/tiles/satyears/{z}/{x}/{y}?t=${y}`,
      maxzoom: 15, attribution: `Sentinel-2 cloudless ${y} by EOX (Copernicus Sentinel data)` });
  }
  return out;
}

// The first pair to show: the oldest and newest sharp LINZ photos in New Zealand, else EOX 2016 and Esri now.
export function defaultPair(list: Source[], d: Dates | null): [string, string] {
  const sharp = (d?.linz ?? []).filter((s) => (s.gsd ?? 9) <= 0.5 && s.kind !== "satellite");
  if (sharp.length >= 2) {
    const modern = sharp.filter((s) => (s.year_to ?? 0) >= 1990);
    const before = (modern.length >= 2 ? modern : sharp).at(-1)!;
    return [`linz:${before.layer}`, `linz:${sharp[0].layer}`];
  }
  return [list.find((s) => s.id === "eox:2016") ? "eox:2016" : list.at(-1)?.id ?? "eox:2016", "esri:now"];
}

// "What changed?": both pictures side by side (Esri's swapped for LINZ or EOX by the server), where it
// is and the map's places nearby, to the Ask AI box.
export async function askWhatChanged(lon: number, lat: number, zoom: number, a: Source, b: Source, model?: string | null) {
  toast("Getting both pictures…");
  type Pair = { picture: string; km: number; notes: string[]; before: { label: string }; after: { label: string };
    country: { name: string } | null; nearby: { layer_id: string; name: string; category: string | null; km: number }[] };
  let p: Pair;
  const src = (s: Source) => (s.kind === "wayback" ? `wayback:${s.date}` : s.id);
  try {
    p = await get<Pair>("/thennow/pair", { lon: lon.toFixed(5), lat: lat.toFixed(5), zoom: Math.round(zoom), a: src(a), b: src(b) });
  } catch (e) {
    toast(`No pictures: ${String((e as Error).message || e).replace(/^\d+: /, "")}`);
    return;
  }
  const where = `${Math.abs(lat).toFixed(4)}°${lat < 0 ? "S" : "N"} ${Math.abs(lon).toFixed(4)}°${lon < 0 ? "W" : "E"}${p.country ? `, ${p.country.name}` : ""}`;
  const parts: AskPart[] = [
    { key: "where", kind: "page", label: "The two pictures", text: `Two pictures of the same place side by side, about ${p.km} km across each, north up, centred at ${where}. `
      + `LEFT (before): ${p.before.label}. RIGHT (after): ${p.after.label}.${p.notes.length ? ` ${p.notes.join(". ")}.` : ""}` },
  ];
  if (p.nearby.length) {
    parts.push({ key: "nearby", kind: "data", label: "Places on the app's map within the picture",
      text: p.nearby.map((n) => `${n.name} (${n.layer_id.replace(/_/g, " ")}${n.category ? `, ${n.category}` : ""}), ${n.km} km from the centre`).join("\n") });
  }
  openAsk({
    title: `What changed? ${where}`,
    parts,
    question: "What changed between the left (before) and right (after) pictures? Describe new or removed buildings, roads, "
      + "subdivisions, farms, forest, water and coast, roughly how much of the picture each covers, and how sure you are. "
      + "Say if the pictures differ only in season, light or detail.",
    picture: async () => p.picture,
    pictureTitle: "the two pictures",
    model: model ?? undefined,
    search: false,
  });
}

export const pairDownload = (lon: number, lat: number, zoom: number, a: Source, b: Source) => {
  const src = (s: Source) => (s.kind === "wayback" ? `wayback:${s.date}` : s.id);
  return `/api/v1/thennow/pair.jpg?lon=${lon.toFixed(5)}&lat=${lat.toFixed(5)}&zoom=${Math.round(zoom)}&a=${encodeURIComponent(src(a))}&b=${encodeURIComponent(src(b))}`;
};

// ----------------------------------------------------------------------------- timelapses
export type TimelapseYear = { year: number; scene?: string; date?: string; cloud?: number; platform?: string;
  water?: number; green?: number; built?: number; seen?: number; missing?: string };
export type Timelapse = { id: string; name: string; bbox: number[]; km: number[]; zoom: number; summers: boolean; created: string;
  state: "queued" | "running" | "done" | "error" | "stopped"; years: TimelapseYear[]; done: number; total: number; error?: string; attribution: string };
export const timelapses = () => get<{ running: string | null; timelapses: Timelapse[] }>("/thennow/timelapse");
export const makeTimelapse = (bbox: number[], name: string, summers: boolean) => send<Timelapse>("POST", "/thennow/timelapse", { bbox, name, summers });
export const deleteTimelapse = (id: string) => send<{ ok: boolean }>("DELETE", `/thennow/timelapse/${id}`);
export const frameUrl = (id: string, year: number) => `/api/v1/thennow/timelapse/${id}/${year}.jpg`;

// Places to try, with their boxes (west, south, east, north).
export const TIMELAPSE_PLACES: [string, number[]][] = [
  ["Lake Pukaki and Tekapo", [170.05, -44.20, 170.60, -43.80]], ["Rolleston", [172.33, -43.66, 172.50, -43.57]],
  ["Auckland's edge (Pukekohe to Drury)", [174.85, -37.25, 175.05, -37.08]], ["Franz Josef Glacier", [170.10, -43.52, 170.30, -43.40]],
  ["Dubai", [55.05, 24.95, 55.45, 25.30]], ["Las Vegas", [-115.35, 35.95, -114.95, 36.35]], ["Aral Sea (north)", [60.4, 45.8, 61.8, 46.8]],
];
