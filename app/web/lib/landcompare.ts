// Land cover side by side: the pieces the Land page's "Compare countries" tab is built from.
//
// The shares come from ESA's yearly 300 m land cover maps as FAOSTAT adds them up by country
// (lc_*_pct). The map picture is ESA WorldCover at 10 m (the Map's Land cover look), read
// tile by tile and redrawn so only the kinds of cover picked show, in the bar's colours.

import * as maplibregl from "maplibre-gl";
import { COVER_COLOURS } from "@/lib/land";

export { COVER_COLOURS };

// Bar order, bottom to top (forest at the foot like most land charts, water on top).
export const COVER_ORDER = ["trees", "crops", "grass", "shrub", "bare", "snow", "built", "water"] as const;
export type CoverId = (typeof COVER_ORDER)[number];

// ESA WorldCover classes: value -> colour in the published pictures (as in contract land.py WORLDCOVER).
export const WORLDCOVER_PALETTE: [number, [number, number, number]][] = [
  [10, [0x00, 0x64, 0x00]], [20, [0xff, 0xbb, 0x22]], [30, [0xff, 0xff, 0x4c]], [40, [0xf0, 0x96, 0xff]],
  [50, [0xfa, 0x00, 0x00]], [60, [0xb4, 0xb4, 0xb4]], [70, [0xf0, 0xf0, 0xf0]], [80, [0x00, 0x64, 0xc8]],
  [90, [0x00, 0x96, 0xa0]], [95, [0x00, 0xcf, 0x75]], [100, [0xfa, 0xe6, 0xa0]],
];

// Which WorldCover classes make up each of the bar's kinds of cover. The two maps class land a
// little differently (CCI puts flooded shrubs and sparse plants with shrubs; WorldCover has
// "bare or sparse" as one class), so the picture is a guide to where, not a second count.
export const COVER_TO_WORLDCOVER: Record<CoverId, number[]> = {
  trees: [10, 95], crops: [40], grass: [30], shrub: [20, 90, 100], bare: [60], snow: [70], built: [50], water: [80],
};
const CLASS_TO_COVER = new Map<number, CoverId>(
  (Object.entries(COVER_TO_WORLDCOVER) as [CoverId, number[]][]).flatMap(([c, vs]) => vs.map((v) => [v, c] as [number, CoverId])));

const hex = (h: string): [number, number, number] => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];

// The WorldCover class a pixel's colour stands for: the nearest palette colour, if close enough
// (tiles drawn smaller than 10 m can blend neighbouring colours a little).
export function classOf(r: number, g: number, b: number): number | null {
  let best: number | null = null;
  let bestD = 40 * 40 * 3;
  for (const [v, [pr, pg, pb]] of WORLDCOVER_PALETTE) {
    const d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2;
    if (d < bestD) { bestD = d; best = v; }
  }
  return best;
}

// Redraws a tile's pixels in place: the kinds picked in their bar colour, the rest see-through.
// `show` is "all" or a list of kinds.
export function recolour(px: Uint8ClampedArray, show: "all" | CoverId[]): void {
  const keep = show === "all" ? null : new Set(show);
  const cache = new Map<number, [number, number, number] | null>();
  for (let i = 0; i < px.length; i += 4) {
    if (px[i + 3] === 0) continue;
    const key = (px[i] << 16) | (px[i + 1] << 8) | px[i + 2];
    let out = cache.get(key);
    if (out === undefined) {
      const v = classOf(px[i], px[i + 1], px[i + 2]);
      const c = v === null ? undefined : CLASS_TO_COVER.get(v);
      out = c && (!keep || keep.has(c)) ? hex(COVER_COLOURS[c]) : null;
      cache.set(key, out);
    }
    if (out) { px[i] = out[0]; px[i + 1] = out[1]; px[i + 2] = out[2]; px[i + 3] = 255; } else px[i + 3] = 0;
  }
}

// A map tile source that reads WorldCover tiles and recolours them: the source's tile address is
// lcpick://<kinds or all>@<the real address with {z}/{x}/{y}>.
// A tile the app's server has no saved copy of and can't fetch comes back as a see-through
// picture marked X-Tile-Missing; that, an empty answer or one that isn't a picture is drawn
// see-through instead of failing to decode, and counted so the page can say the pictures didn't come.
let added = false;
let blank: ImageBitmap | null = null;
const blankTile = async () => (blank ??= await createImageBitmap(new ImageData(1, 1)));
export const tileCount = { ok: 0, missing: 0 };
const listeners = new Set<() => void>();
export function onTileCount(f: () => void): () => void { listeners.add(f); return () => { listeners.delete(f); }; }
const counted = (ok: boolean) => { if (ok) tileCount.ok++; else tileCount.missing++; listeners.forEach((f) => f()); };

export function addCoverProtocol(): void {
  if (added || typeof window === "undefined") return;
  added = true;
  maplibregl.addProtocol("lcpick", async (params, abort) => {
    const rest = params.url.slice("lcpick://".length);
    const at = rest.indexOf("@");
    const which = rest.slice(0, at);
    const url = rest.slice(at + 1);
    const r = await fetch(url, { signal: abort.signal });
    if (!r.ok) throw new Error(`land cover tile: ${r.status}`);
    const body = await r.blob();
    if (r.status === 204 || r.headers.get("x-tile-missing") || !body.size || !(r.headers.get("content-type") ?? "image/").startsWith("image/")) {
      counted(false);
      return { data: await blankTile() };
    }
    let bmp: ImageBitmap;
    try { bmp = await createImageBitmap(body); } catch { counted(false); return { data: await blankTile() }; }
    counted(true);
    const canvas = new OffscreenCanvas(bmp.width, bmp.height);
    const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
    ctx.drawImage(bmp, 0, 0);
    const img = ctx.getImageData(0, 0, bmp.width, bmp.height);
    recolour(img.data, which === "all" ? "all" : (which.split(",") as CoverId[]));
    ctx.putImageData(img, 0, 0);
    return { data: await createImageBitmap(canvas) };
  });
}

// ---------------------------------------------------------------------------- outlines
type Ring = number[][];
type Poly = Ring[];
export const polysOf = (g: GeoJSON.Geometry | null | undefined): Poly[] =>
  !g ? [] : g.type === "Polygon" ? [g.coordinates as Poly] : g.type === "MultiPolygon" ? (g.coordinates as Poly[]) : [];

const bbox = (ring: Ring) => {
  let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
  for (const [x, y] of ring) { w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y); }
  return [w, s, e, n] as [number, number, number, number];
};

// The box to fit a country's panel to: its main pieces of land (each at least a fifth the size of
// the biggest, or close to it and not tiny, like Tasmania; so far-off islands and territories don't
// shrink the country to a dot), moved east across 180° when they straddle it (Russia, Fiji).
export function fitBox(polys: Poly[]): [[number, number], [number, number]] | null {
  if (!polys.length) return null;
  const boxes = polys.map((p) => bbox(p[0]));
  const size = (b: number[]) => (b[2] - b[0]) * (b[3] - b[1]);
  const biggest = Math.max(...boxes.map(size));
  const big = boxes.find((b) => size(b) === biggest)!;
  const near = (b: number[]) => b[0] <= big[2] + 10 && b[2] >= big[0] - 10 && b[1] <= big[3] + 10 && b[3] >= big[1] - 10;
  let main = boxes.filter((b) => size(b) >= biggest * 0.2 || (near(b) && size(b) >= biggest * 0.005));
  const span = (bs: number[][]) => Math.max(...bs.map((b) => b[2])) - Math.min(...bs.map((b) => b[0]));
  if (span(main) > 180) main = main.map((b) => (b[2] < 0 ? [b[0] + 360, b[1], b[2] + 360, b[3]] : b) as [number, number, number, number]);
  return [[Math.min(...main.map((b) => b[0])), Math.min(...main.map((b) => b[1]))],
    [Math.max(...main.map((b) => b[2])), Math.max(...main.map((b) => b[3]))]];
}

// Everything but the country, to lay over the picture so only the country's own land shows.
export function maskOf(polys: Poly[]): GeoJSON.Feature {
  return { type: "Feature", properties: {}, geometry: { type: "Polygon",
    coordinates: [[[-180, -86], [180, -86], [180, 86], [-180, 86], [-180, -86]], ...polys.map((p) => p[0])] } };
}

// Zooms that put every panel at the same scale in km at its centre: Mercator draws land
// 1/cos(latitude) times bigger away from the equator, so each panel's zoom is set from the
// smallest fitting scale across panels.
export function sameScaleZooms(fits: { zoom: number; lat: number }[]): number[] {
  if (!fits.length) return [];
  const RAD = Math.PI / 180;
  const k = Math.min(...fits.map((f) => 2 ** f.zoom / Math.cos(f.lat * RAD)));
  return fits.map((f) => Math.log2(k * Math.cos(f.lat * RAD)));
}

// ---------------------------------------------------------------------------- the bar
export type Seg = { id: CoverId; share: number; y0: number; y1: number; labelY: number };

// The bar's pieces, top to bottom in pixels, and where each label goes: beside the middle of its
// piece, pushed apart so no two labels overlap (`gap` px), and kept inside the bar's height.
export function barLayout(shares: Partial<Record<CoverId, number>>, height: number, gap = 20): Seg[] {
  const parts = [...COVER_ORDER].reverse().filter((id) => (shares[id] ?? 0) > 0);
  const total = parts.reduce((a, id) => a + (shares[id] ?? 0), 0) || 1;
  let y = 0;
  const segs: Seg[] = parts.map((id) => {
    const h = ((shares[id] ?? 0) / total) * height;
    const s = { id, share: shares[id] ?? 0, y0: y, y1: y + h, labelY: y + h / 2 };
    y += h;
    return s;
  });
  const top = gap / 2, bottom = height - gap / 2;
  for (let i = 0; i < segs.length; i++) segs[i].labelY = Math.max(segs[i].labelY, i ? segs[i - 1].labelY + gap : top);
  for (let i = segs.length - 1; i >= 0; i--) segs[i].labelY = Math.min(segs[i].labelY, i < segs.length - 1 ? segs[i + 1].labelY - gap : bottom);
  return segs;
}

export const pct = (v: number) => (v >= 10 ? v.toFixed(0) : v >= 1 ? v.toFixed(1) : v.toFixed(2)) + "%";
