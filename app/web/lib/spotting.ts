// Spotting: layers the app works out itself from the satellite pictures and land cover maps
// (map layers 8 Land change, 9 Water gained and lost, 0 Spotted by AI), the Spotting page,
// and "What is here?" (Ask the picture) on any map.

import { get, send, type Settings } from "@/lib/api";
import { openAsk, toast, type AskPart } from "@/lib/ai";

export type ChangeKind = { id: string; label: string; colour: string; hint: string };
export type WaterClass = { code: number; label: string; colour: string; group: string; draw: string };
export type ScanTag = { id: string; label: string; looks: string; colour: string; ticked?: boolean; needs_before?: boolean };
export type SpotTerms = {
  changes: ChangeKind[]; water: WaterClass[]; tags: ScanTag[]; checkable: Record<string, string>;
  sources: Record<string, { label: string; years: [number, number]; maxzoom: number }>; water_attribution: string;
  aerial_tags: ScanTag[]; // New Zealand aerial photo scans
};

let terms: Promise<SpotTerms> | null = null;
export function spotTerms(): Promise<SpotTerms> {
  terms ??= get<SpotTerms>("/spot/terms").catch((e) => { terms = null; throw e; });
  return terms;
}

// The colours here match worldmodel_contract.spotting, so legends can show before the terms load.
export const CHANGE_LEGEND: [string, string][] = [
  ["Built on", "#c92a2a"], ["New bare ground (mines, quarries)", "#862e9c"], ["Trees cleared", "#e8590c"],
  ["New farmland", "#f2c200"], ["Trees grown", "#2b8a3e"], ["Became water", "#1c7ed6"], ["Water became land", "#a0522d"],
];
export const WATER_LEGEND: [string, string][] = [
  ["New water", "#1c7ed6"], ["New seasonal water", "#74c0fc"], ["Water gone", "#c92a2a"], ["Seasonal water gone", "#ffa8a8"],
  ["Now all year", "#3b5bdb"], ["Now only seasonal", "#f59f00"],
];

const origin = () => (typeof location !== "undefined" ? location.origin : "");
export const changeTiles = (src: string, from: number, to: number, kinds?: string) =>
  `${origin()}/api/v1/spot/change/${src}/{z}/{x}/{y}?from=${from}&to=${to}${kinds ? `&kinds=${kinds}` : ""}`;
export const waterTiles = (show: "changes" | "all") => `${origin()}/api/v1/spot/water/{z}/{x}/{y}?show=${show}`;

export function changeLayer(s: Pick<Settings, "spot_change_source" | "spot_change_from" | "spot_change_to">) {
  const src = s.spot_change_source ?? "lc10";
  const [lo, hi] = src === "lcyears" ? [1992, 2020] : [2017, 2025];
  const from = Math.max(lo, Math.min(hi - 1, s.spot_change_from ?? lo));
  const to = Math.max(from + 1, Math.min(hi, s.spot_change_to ?? hi));
  return {
    tiles: changeTiles(src, from, to), maxzoom: src === "lcyears" ? 9 : 14, from, to, src,
    attribution: src === "lcyears" ? "Land change worked out from ESA CCI land cover (Planetary Computer)"
      : "Land change worked out from Esri Land Cover 10 m (Impact Observatory, Microsoft, Esri)",
  };
}

// ----------------------------------------------------------------------------- area summaries
export type SummaryReq = { kind: "land" | "water"; src?: string; from?: number; to?: number; entity?: string | null;
  bbox?: number[] | null; detail?: "quick" | "fine" };
export type HotSpot = { lon: number; lat: number; ha: number; main: string; z: number; x: number; y: number };
export type Summary = SummaryReq & { name: string; zoom: number; squares: number; read: number; missing: number; pixel_m: number;
  ha: Record<string, number>; hot_spots: HotSpot[]; worked_out: string };
export type SummaryJob = { state: "idle" | "running" | "done" | "error"; key?: string; done?: number; total?: number; step?: string; error?: string; req?: SummaryReq };
export const summaries = () => get<{ job: SummaryJob; saved: Record<string, Summary> }>("/spot/summary");
export const startSummary = (r: SummaryReq) => send<{ job: SummaryJob; saved: Record<string, Summary> }>("POST", "/spot/summary", r);
export function summaryKey(r: SummaryReq): string {
  const area = r.entity || (r.bbox ?? []).map((v) => v.toFixed(2)).join(",");
  return r.kind === "water" ? `water|${area}|${r.detail ?? "quick"}` : `land|${r.src}|${r.from}|${r.to}|${area}|${r.detail ?? "quick"}`;
}

// ----------------------------------------------------------------------------- models and scans
export type VisionModels = { models: { name: string; size: number | null; parameters?: string }[]; ask: string | null; scan: string | null; error: string | null };
export const visionModels = () => get<VisionModels>("/spot/models");

export type Scan = {
  id: string; name: string; mode: "scan" | "check"; entity: string | null; bbox: number[] | null; tags: string[]; layers: string[];
  model: string; created: string; state: "queued" | "running" | "paused" | "done" | "stopped" | "error"; total: number; done: number;
  skipped: number; found: number; errors: number; seconds: number; error?: string; last_error?: string; note?: string; finished?: string;
  picture?: "aerial"; layer?: string; before?: string | null; layer_title?: string; before_title?: string | null;
};
export type HitRate = { tag: string; label: string; found: number; yes: number; no: number; right_pct: number | null };
export type Found = {
  id: string; tag?: string; sure: number; where?: string; note: string; lon: number; lat: number; z?: number; x?: number; y?: number;
  country?: string | null; mark: "yes" | "no" | null; count?: number;
  layer?: string; item_id?: string; name?: string; category?: string | null; verdict?: "yes" | "no" | "unsure";
};
export type LayerPoint = { scan: string; id: string; kind: "tag" | "check"; tag: string; label: string; sure: number; note: string;
  lon: number; lat: number; mark: string | null; name?: string };

export const scans = () => get<{ running: string | null; scans: Scan[]; hit_rates: HitRate[] }>("/spot/scans");
export type ScanReq = { mode: "scan" | "check"; entity?: string | null; bbox?: number[] | null; tags?: string[]; layers?: string[]; model?: string; name?: string;
  picture?: "satellite" | "aerial"; layer?: string; before?: string | null; layer_title?: string; before_title?: string | null };
export type TownCount = { town: string; squares: number; counts: Record<string, number> };
export const scanTowns = (id: string) => get<TownCount[]>(`/spot/scans/${id}/towns`);
export const estimateScan = (r: ScanReq) => send<{ count: number; minutes: number; note: string }>("POST", "/spot/scans/estimate", r);
export const createScan = (r: ScanReq) => send<Scan>("POST", "/spot/scans", r);
export const scanAction = (id: string, action: "pause" | "resume" | "stop") => send<Scan>("POST", `/spot/scans/${id}/${action}`);
export const deleteScan = (id: string) => send<{ ok: boolean }>("DELETE", `/spot/scans/${id}`);
export const scanFound = (id: string) => get<Found[]>(`/spot/scans/${id}/found`);
export const markFound = (scan: string, item: string, mark: "yes" | "no" | null) =>
  send<Found>("POST", `/spot/scans/${scan}/found/${encodeURIComponent(item)}/mark`, { mark });
export const foundPicture = (scan: string, f: Found) =>
  `/api/v1/spot/scans/${scan}/pictures/${f.layer ? f.id : `${f.z}-${f.x}-${f.y}`}.jpg`;
export const spotLayer = () => get<LayerPoint[]>("/spot/layer");

// ----------------------------------------------------------------------------- Ask the picture
export type Here = {
  lon: number; lat: number; km: number; zoom: number; picture: string; country: { id: string; name: string } | null;
  cover: { label: string; share: number }[];
  nearby: { layer_id: string; name: string; category: string | null; size: number | null; km: number }[];
};

const fmtLat = (lat: number, lon: number) =>
  `${Math.abs(lat).toFixed(4)}°${lat < 0 ? "S" : "N"} ${Math.abs(lon).toFixed(4)}°${lon < 0 ? "W" : "E"}`;

// Opens the Ask AI box about a place: its satellite picture (for models that see), and as text
// where it is, what covers the ground and the map's places nearby.
export async function askHere(lon: number, lat: number, zoom = 15, question?: string): Promise<void> {
  toast("Getting the satellite picture…");
  let h: Here;
  let models: VisionModels | null = null;
  try {
    [h, models] = await Promise.all([get<Here>("/spot/here", { lon: lon.toFixed(5), lat: lat.toFixed(5), zoom }),
      visionModels().catch(() => null)]);
  } catch (e) {
    toast(`No picture: ${String((e as Error).message || e).replace(/^\d+: /, "")}`);
    return;
  }
  const where = `${fmtLat(h.lat, h.lon)}${h.country ? `, ${h.country.name}` : ", at sea or outside any country"}`;
  const parts: AskPart[] = [
    { key: "where", kind: "page", label: "Where the picture is",
      text: `Centre: ${where}. The picture is about ${h.km} km across, north up, from the Sentinel-2 cloud-free mosaic of 2020 `
        + "(10 m pixels, so single cars, small boats and most single houses are too small to see)." },
  ];
  if (h.cover.length) {
    parts.push({ key: "cover", kind: "data", label: "Land cover in the picture (ESA WorldCover)",
      text: h.cover.map((c) => `${c.label}: ${c.share}%`).join("\n") });
  }
  if (h.nearby.length) {
    parts.push({ key: "nearby", kind: "data", label: "Places on the app's map within the picture",
      text: h.nearby.map((n) => `${n.name} (${n.layer_id.replace(/_/g, " ")}${n.category ? `, ${n.category}` : ""}), ${n.km} km from the centre`).join("\n") });
  }
  openAsk({
    title: `What is here? ${where}`,
    parts,
    question: question ?? "What can you see in this satellite picture? Describe the main features (land use, settlements, industry, "
      + "infrastructure, water) and anything unusual, and say how sure you are. Use the listed places to name what you see where they match.",
    picture: async () => h.picture,
    pictureTitle: "the satellite picture",
    model: models?.ask ?? undefined,
    search: false,
  });
}
