// Symbols for the map's place layers (an anchor in each port's dot, a plane in each airport's, a
// cross in each hospital's ...) and, as a choice, drawing those places about their real size once
// zoomed in close. The dots keep their busy-ness sizing (ship calls, beds, students, capacity):
// with symbols on, a dot is only made big enough to hold its symbol once zoomed in a little, and
// with real size on it grows with the map, in metres, over the site.
// Settings: map_place_icons (default on) and map_real_size (default off).
import type { ExpressionSpecification, LayerSpecification, Map as MlMap, SymbolLayerSpecification } from "maplibre-gl";
import { cssVar } from "@/lib/colors";

type Expr = ExpressionSpecification;
const E = (x: unknown) => x as Expr;

// Symbols drawn white on a 48 x 48 grid: filled shapes (fill) and lines (stroke, 4 wide).
type Glyph = { fill?: string[]; stroke?: string[] };
const GLYPHS: Record<string, Glyph> = {
  // an anchor: ring, shank, stock, curved arms with points
  "wm-p-anchor": {
    stroke: ["M24 14 L24 43", "M14 19 L34 19", "M9 30 C10 38 17 43 24 43 C31 43 38 38 39 30"],
    fill: ["M24 3 A6 6 0 1 1 23.99 3 Z M24 7 A2.3 2.3 0 1 0 24.01 7 Z", "M4 32 L9 25 L14 32 Z", "M34 32 L39 25 L44 32 Z"],
  },
  // a plane seen from above, nose up and to the right (the airport sign)
  "wm-p-plane": {
    fill: ["M24 2 C26 2 27 5 27 8 L27 18 L45 28 L45 32 L27 26 L27 37 L33 42 L33 45 L24 43 L15 45 L15 42 L21 37 L21 26 L3 32 L3 28 L21 18 L21 8 C21 5 22 2 24 2 Z"],
  },
  // a cross
  "wm-p-cross": { fill: ["M18 4 H30 V18 H44 V30 H30 V44 H18 V30 H4 V18 H18 Z"] },
  // a mortarboard
  "wm-p-cap": {
    fill: ["M24 7 L47 18 L24 29 L1 18 Z", "M11 24 L24 30.5 L37 24 L37 35 C37 40 11 40 11 35 Z"],
    stroke: ["M42 20 L42 33"],
  },
  // a five-pointed star
  "wm-p-star": { fill: ["M24 2 L29.8 17.2 L46 17.8 L33.3 27.9 L37.8 43.5 L24 34.5 L10.2 43.5 L14.7 27.9 L2 17.8 L18.2 17.2 Z"] },
  // a lightning bolt
  "wm-p-bolt": { fill: ["M29 2 L9 27 L22 27 L17 46 L39 19 L26 19 Z"] },
};
const SIZE = 48; // canvas pixels; added at pixelRatio 2, so 24 screen pixels at icon-size 1
const ICON_PX = 24;

export function ensurePlaceIcons(m: MlMap) {
  for (const [id, gl] of Object.entries(GLYPHS)) {
    if (m.hasImage(id)) continue;
    const c = document.createElement("canvas");
    c.width = SIZE;
    c.height = SIZE;
    const g = c.getContext("2d");
    if (!g) continue;
    g.fillStyle = "#fff";
    g.strokeStyle = "#fff";
    g.lineWidth = 4;
    g.lineCap = "round";
    for (const d of gl.fill ?? []) g.fill(new Path2D(d), "evenodd");
    for (const d of gl.stroke ?? []) g.stroke(new Path2D(d));
    const img = g.getImageData(0, 0, SIZE, SIZE);
    m.addImage(id, { width: SIZE, height: SIZE, data: new Uint8Array(img.data.buffer) }, { sdf: true, pixelRatio: 2 });
  }
}

// Each place layer: its symbol, the zoom its symbols start at (busy layers later, so the world
// view isn't a carpet of them), its dot radius in pixels at a zoom (the busy-ness sizing the
// layer has always had), its colour, and roughly how wide the place is in metres (a radius).
export type PlaceLook = {
  icon: string; rotate?: number; from: number; label: string;
  busy: (z: number) => unknown; color: () => unknown;
  metres?: unknown; size_note?: string; // how the real size is estimated (Settings and the Layers panel)
};
const lerp = (z: number, z0: number, a: number, z1: number, b: number) => a + (b - a) * Math.min(1, Math.max(0, (z - z0) / (z1 - z0)));
const hospitalBusy = ["*", ["match", ["get", "tier"], "clinic", 0.75, 1],
  ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "beds"], 100]], 0, 1.8, 20, 3, 50, 7]];

export const PLACE_LOOK: Record<string, PlaceLook> = {
  ports: {
    icon: "wm-p-anchor", from: 3, label: "Ports",
    busy: () => ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "calls"], 0]], 0, 1.8, 50, 4, 150, 10],
    color: () => cssVar("--series-1"),
    metres: ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "calls"], 0]], 0, 300, 50, 1500, 150, 4000],
    size_note: "ports from their ship calls (a busy port about 8 km across)",
  },
  port_pressure: {
    icon: "wm-p-anchor", from: 3, label: "Ports against normal",
    busy: () => ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "weekly"], 0]], 0, 2, 5, 3.5, 15, 7, 40, 12],
    color: () => cssVar("--ink-2"),
    metres: ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "weekly"], 0]], 0, 300, 15, 1500, 40, 4000],
  },
  ports_all: {
    icon: "wm-p-anchor", from: 5, label: "Every port",
    busy: () => ["match", ["get", "size"], "large", 4, "medium", 3, 2],
    color: () => cssVar("--ink-2"),
    metres: ["match", ["get", "size"], "large", 2500, "medium", 1200, "small", 600, 300],
    size_note: "the World Port Index harbour size",
  },
  airports: {
    icon: "wm-p-plane", rotate: 45, from: 3, label: "Airports",
    busy: (z) => ["match", ["get", "size"], "large", lerp(z, 0, 2.5, 5, 6), lerp(z, 0, 1.2, 5, 3)],
    color: () => cssVar("--series-5"),
    // the site is about as wide as its longest runway (a typical one where it isn't known)
    metres: ["*", 0.55, ["coalesce", ["get", "runway_m"], ["match", ["get", "size"], "large", 3200, 2000]]],
    size_note: "airports from their longest runway",
  },
  hospitals: {
    icon: "wm-p-cross", from: 6, label: "Hospitals",
    busy: () => hospitalBusy,
    color: () => cssVar("--div-neg-2"),
    // about 150 m² of grounds a bed (buildings, car parks), at least 40 m across a clinic
    metres: ["max", 20, ["sqrt", ["/", ["*", ["coalesce", ["get", "beds"], ["match", ["get", "tier"], "clinic", 10, 100]], 150], Math.PI]]],
    size_note: "hospitals from their beds",
  },
  universities: {
    icon: "wm-p-cap", from: 5, label: "Universities",
    busy: () => ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "students"], 5000]], 0, 2, 100, 3, 300, 8],
    color: () => cssVar("--series-5"),
    // about 20 m² of campus a student
    metres: ["sqrt", ["/", ["*", ["coalesce", ["get", "students"], 5000], 20], Math.PI]],
    size_note: "universities from their students",
  },
  military_bases: {
    icon: "wm-p-star", from: 4, label: "Military bases",
    busy: (z) => lerp(z, 0, 2, 5, 5),
    color: () => cssVar("--series-7"),
  },
  power_plants: {
    icon: "wm-p-bolt", from: 6, label: "Power plants",
    busy: () => ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "mw"], 10]], 0, 1.5, 10, 3, 30, 7, 80, 14],
    color: () => ["match", ["get", "fuel"], "Hydro", "#1c7ed6", "Geothermal", "#e8590c", "Wind", "#37b24d", "Solar", "#f59f00",
      "Nuclear", "#7048e8", "Coal", "#343a40", "Gas", "#868e96", "Oil", "#5c3d2e", "Biomass", "#82c91e", "Waste", "#a9a9a9", "#adb5bd"],
  },
};

const BADGE = 8;      // smallest dot radius that holds a readable symbol (pixels)
const ICON_MAX = 26;  // symbols stop growing here, however big the dot
export const REAL_FROM = 11; // real sizes are drawn from this zoom (a city) inward
const STOPS = Array.from({ length: 23 }, (_, i) => i); // every whole zoom: MapLibre interpolates between
const M_PER_PX = 78271.517; // metres a screen pixel at zoom 0 at the equator (512-pixel world)

export type PlaceOpts = { icons: boolean; real: boolean };

// The dot's radius at zoom z: the busy-ness size, at least a badge once symbols show, and at least
// the place's real size (metres turned into pixels at its latitude; the wm_k property is 1/cos(lat)).
function radiusAt(p: PlaceLook, z: number, o: PlaceOpts): unknown {
  const parts: unknown[] = [p.busy(z)];
  if (o.icons && z >= p.from) parts.push(BADGE);
  if (o.real && p.metres && z >= REAL_FROM - 1) parts.push(["/", ["*", p.metres, ["coalesce", ["get", "wm_k"], 1], 2 ** z], M_PER_PX]);
  return parts.length === 1 ? parts[0] : ["max", ...parts];
}
const byZoom = (f: (z: number) => unknown): Expr => E(["interpolate", ["linear"], ["zoom"], ...STOPS.flatMap((z) => [z, f(z)])]);

export const placeRadius = (id: string, o: PlaceOpts) => byZoom((z) => radiusAt(PLACE_LOOK[id], z, o));

// The symbol layer drawn over a place layer's dots (id: its layer id plus "-icon").
export function placeIconSpec(id: string, lid: string, o: PlaceOpts): SymbolLayerSpecification {
  const p = PLACE_LOOK[id];
  const size = byZoom((z) => z < p.from ? 0.3 : ["/", ["min", ICON_MAX, ["*", 1.35, radiusAt(p, z, o)]], ICON_PX]);
  const real = o.real && p.metres;
  const clinic = ["==", ["get", "tier"], "clinic"];
  const white = ["case", clinic, p.color(), "#ffffff"], halo = ["case", clinic, 1.2, 0];
  return {
    id: `${lid}-icon`, type: "symbol", source: lid, minzoom: p.from,
    layout: { "icon-image": p.icon, "icon-size": size, "icon-rotate": p.rotate ?? 0, "icon-rotation-alignment": "viewport",
      "icon-allow-overlap": true, "icon-ignore-placement": true },
    paint: {
      // white in a solid dot; in the dot's colour (with a white edge) over a pale real-size area or a clinic's ring
      "icon-color": E(real ? ["step", ["zoom"], white, REAL_FROM, p.color()] : white),
      "icon-halo-color": "#ffffff",
      "icon-halo-width": E(real ? ["step", ["zoom"], halo, REAL_FROM, 1.2] : halo),
    },
  };
}

// Paint for the dots that real size changes: once drawn at real size they turn pale with a solid edge,
// so the streets and buildings under them still show.
function realPaint(id: string, base: Record<string, unknown>, o: PlaceOpts): Record<string, unknown> {
  const p = PLACE_LOOK[id];
  if (!o.real || !p.metres) return {};
  return {
    "circle-opacity": ["interpolate", ["linear"], ["zoom"], REAL_FROM - 1, base["circle-opacity"] ?? 1, REAL_FROM, 0.22],
    "circle-stroke-color": ["step", ["zoom"], base["circle-stroke-color"] ?? "#ffffff", REAL_FROM, p.color()],
    "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], REAL_FROM - 1, base["circle-stroke-width"] ?? 0, REAL_FROM, 1.6],
    "circle-pitch-alignment": "map",
  };
}

// The dot layer's paint with symbols and real size applied (for the Self check, and the map).
export function placePaint(id: string, base: Record<string, unknown>, o: PlaceOpts): Record<string, unknown> {
  if (!o.icons && !o.real) return base;
  return { ...base, "circle-radius": placeRadius(id, o), ...realPaint(id, base, o) };
}

// The specs the Self check validates: the dots with both choices on (as <lid>-place), and the symbols.
export function placeSpecs(id: string, lid: string, dots: LayerSpecification): LayerSpecification[] {
  const o = { icons: true, real: true };
  const base = (dots as { paint?: Record<string, unknown> }).paint ?? {};
  return [{ ...dots, id: `${lid}-place`, paint: placePaint(id, base, o) } as LayerSpecification, placeIconSpec(id, lid, o)];
}

// Applies the choices to a place layer already on the map (and again whenever they change).
export function applyPlaceLook(m: MlMap, id: string, lid: string, base: Record<string, unknown>, o: PlaceOpts) {
  if (!PLACE_LOOK[id] || !m.getLayer(lid)) return;
  const paint = placePaint(id, base, o);
  for (const k of ["circle-radius", "circle-opacity", "circle-stroke-color", "circle-stroke-width", "circle-pitch-alignment"]) {
    m.setPaintProperty(lid, k as "circle-radius", (paint[k] ?? (k === "circle-pitch-alignment" ? "viewport" : base[k])) as never);
  }
  const iid = `${lid}-icon`;
  if (m.getLayer(iid)) m.removeLayer(iid);
  if (!o.icons) return;
  ensurePlaceIcons(m);
  const above = m.getStyle().layers.findIndex((l) => l.id === lid);
  const next = m.getStyle().layers[above + 1]?.id;
  m.addLayer(placeIconSpec(id, lid, o), next);
  const f = m.getFilter(lid);
  if (f) m.setFilter(iid, f);
}

// 1/cos(latitude) on each point (as wm_k), so a size in metres can be turned into pixels.
export function withLatScale<T extends GeoJSON.FeatureCollection>(fc: T): T {
  for (const f of fc.features) {
    if (f.geometry?.type !== "Point" || !f.properties || "wm_k" in f.properties) continue;
    const lat = (f.geometry.coordinates[1] ?? 0) * Math.PI / 180;
    f.properties.wm_k = Math.round(1000 / Math.max(0.05, Math.cos(lat))) / 1000;
  }
  return fc;
}
