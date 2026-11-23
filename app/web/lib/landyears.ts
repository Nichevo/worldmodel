// Land cover year by year: ESA's 300 m maps (1992-2020) and Esri's 10 m maps (2017 on), drawn
// by the app's tile route (saved copies first), and a "what changed" picture made in the browser
// from two years' tiles: land whose colour changed shows in its new colour, the rest faint grey.
import * as maplibregl from "maplibre-gl";
import { get } from "@/lib/api";

export type YearSource = "lcyears" | "lc10";
export const YEARS: Record<YearSource, number[]> = {
  lcyears: Array.from({ length: 29 }, (_, i) => 1992 + i),
  lc10: Array.from({ length: 9 }, (_, i) => 2017 + i),
};
export const SOURCE_LABEL: Record<YearSource, string> = { lcyears: "ESA, 300 m (1992–2020)", lc10: "Esri, 10 m (2017–2025)" };
export const SOURCE_CREDIT: Record<YearSource, string> = {
  lcyears: "ESA Climate Change Initiative and Copernicus C3S land cover, 300 m, via Microsoft Planetary Computer",
  lc10: "Esri Land Cover 10 m (Impact Observatory, Microsoft and Esri), CC BY 4.0",
};
export const MAXZOOM: Record<YearSource, number> = { lcyears: 9, lc10: 14 };

// What each map's colours mean (grouped for ESA, whose 37 classes would make a long legend).
export const LEGEND: Record<YearSource, [string, string][]> = {
  lcyears: [["Trees", "#006400"], ["Trees, open or mixed", "#788200"], ["Shrubs", "#966400"], ["Grassland", "#ffb432"],
    ["Cropland", "#ffff64"], ["Irrigated cropland", "#aaf0f0"], ["Flooded plants", "#00dc82"], ["Sparse plants", "#ffebaf"],
    ["Bare", "#fff5d7"], ["Built-up", "#c31400"], ["Water", "#0046c8"], ["Snow and ice", "#ffffff"]],
  lc10: [["Trees", "#397d49"], ["Rangeland", "#e3e2c3"], ["Crops", "#e49635"], ["Built area", "#c4281b"],
    ["Bare ground", "#a59b8f"], ["Flooded plants", "#7a87c6"], ["Water", "#419bdf"], ["Snow and ice", "#a8ebff"], ["Clouds", "#616161"]],
};

export const tilesOf = (set: YearSource, year: number) =>
  `${typeof location !== "undefined" ? location.origin : ""}/api/v1/tiles/${set}/{z}/{x}/{y}?t=${year}`;

let added = false;
let blank: ImageBitmap | null = null;
const blankTile = async () => (blank ??= await createImageBitmap(new ImageData(1, 1)));

async function bitmap(url: string, signal: AbortSignal): Promise<ImageBitmap | null> {
  const r = await fetch(url, { signal });
  if (!r.ok || r.headers.get("x-tile-missing")) return null;
  const body = await r.blob();
  if (!body.size || !(r.headers.get("content-type") ?? "image/").startsWith("image/")) return null;
  try { return await createImageBitmap(body); } catch { return null; }
}

// Pixels of b that differ from a in colour (both drawn) keep b's colour; unchanged land is a
// faint grey so the place stays readable; the sea and missing pixels stay see-through.
export function changed(a: Uint8ClampedArray, b: Uint8ClampedArray, grey = 150): void {
  for (let i = 0; i < b.length; i += 4) {
    if (b[i + 3] === 0 || a[i + 3] === 0) { b[i + 3] = 0; continue; }
    const d = Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]);
    if (d > 45) { b[i + 3] = 255; continue; }
    b[i] = grey; b[i + 1] = grey; b[i + 2] = grey; b[i + 3] = 50;
  }
}

// lcchange://<first year's tile address>|<second year's tile address>
export function addChangeProtocol(): void {
  if (added || typeof window === "undefined") return;
  added = true;
  maplibregl.addProtocol("lcchange", async (params, abort) => {
    const [ua, ub] = params.url.slice("lcchange://".length).split("|");
    const [a, b] = await Promise.all([bitmap(ua, abort.signal), bitmap(ub, abort.signal)]);
    if (!a || !b) return { data: await blankTile() };
    const size = b.width;
    const ca = new OffscreenCanvas(size, size), cb = new OffscreenCanvas(size, size);
    const xa = ca.getContext("2d", { willReadFrequently: true })!, xb = cb.getContext("2d", { willReadFrequently: true })!;
    xa.imageSmoothingEnabled = false;
    xa.drawImage(a, 0, 0, size, size);
    xb.drawImage(b, 0, 0);
    const ia = xa.getImageData(0, 0, size, size), ib = xb.getImageData(0, 0, size, size);
    changed(ia.data, ib.data);
    xb.putImageData(ib, 0, 0);
    return { data: await createImageBitmap(cb) };
  });
}

export type CoverChange = { entity: string; y0: string; y1: string; zoom: number; pixel_km: number; tiles: number; missing: number;
  kinds: string[]; totals: Record<string, { from: number; to: number }>; changes: { from: string; to: string; ha: number }[] };
export const coverChange = (entity: string, y0: number, y1: number) =>
  get<CoverChange>("/land/cover-change", { entity, y0: String(y0), y1: String(y1) });
