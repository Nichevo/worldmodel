// The real grounds of a place, coloured from the map detail itself (Settings > Map page, "Site
// outlines from the map"): with the Airports layer on, every airport's grounds as the map draws
// them get a tint and an edge in the layer's colour; likewise hospital and university grounds and
// military land. Ports have no "port" area in either map layout, so their grounds are worked out:
// the industrial land within about a kilometre of a port dot in view.
// Both map layouts are read: OpenMapTiles (online, "class") and Protomaps (local files, "kind").
// Needs map detail (online or local files): with "Countries only" there is nothing to read.
import type { ExpressionSpecification, GeoJSONSource, LayerSpecification, Map as MlMap } from "maplibre-gl";
import { DETAIL_PREFIX } from "@/lib/basemap";
import { PLACE_LOOK } from "@/lib/placeIcons";

const kindIs = (kinds: string[]): ExpressionSpecification =>
  ["all", ["==", ["geometry-type"], "Polygon"], ["in", ["coalesce", ["get", "class"], ["get", "kind"], ""], ["literal", kinds]]];

// Each place layer's grounds in the map detail: the kinds, and the detail layers they are in.
export const SITE_KINDS: Record<string, { kinds: string[]; layers: string[] }> = {
  airports: { kinds: ["aerodrome"], layers: ["aeroway", "landuse"] },
  hospitals: { kinds: ["hospital"], layers: ["landuse"] },
  universities: { kinds: ["university", "college"], layers: ["landuse"] },
  military_bases: { kinds: ["military", "naval_base"], layers: ["landuse"] },
};
export const PORT_LAYERS = ["ports", "port_pressure", "ports_all"];
const PORT_LAND = ["industrial", "port", "harbour"];
export const SITE_FROM = 10; // grounds are drawn from about a region's zoom inward
const PORT_FROM = 11;
const NEAR_KM = 1;
const PREFIX = `${DETAIL_PREFIX}site-`; // removed with the map detail (its source goes too)

const colour = (id: string) => PLACE_LOOK[id]?.color() as string;

function detailSources(m: MlMap) {
  return Object.keys(m.getStyle()?.sources ?? {}).filter((s) => s.startsWith("detail-"));
}

// The specs for one place layer's grounds in one map detail source (also for the Self check).
export function siteSpecs(id: string, src: string, color: string): LayerSpecification[] {
  const k = SITE_KINDS[id];
  return k.layers.flatMap((sl) => [
    { id: `${PREFIX}${id}-${src}-${sl}-fill`, type: "fill", source: src, "source-layer": sl, minzoom: SITE_FROM, filter: kindIs(k.kinds),
      paint: { "fill-color": color, "fill-opacity": ["interpolate", ["linear"], ["zoom"], SITE_FROM, 0, SITE_FROM + 1, 0.22] } },
    { id: `${PREFIX}${id}-${src}-${sl}-line`, type: "line", source: src, "source-layer": sl, minzoom: SITE_FROM, filter: kindIs(k.kinds),
      paint: { "line-color": color, "line-width": ["interpolate", ["linear"], ["zoom"], SITE_FROM, 0.6, 15, 2.2],
        "line-opacity": ["interpolate", ["linear"], ["zoom"], SITE_FROM, 0, SITE_FROM + 1, 0.9] } },
  ] as LayerSpecification[]);
}
// Solid, in a pale mix of the colour, under the roads and buildings: the pieces cut from the
// tiles overlap a little at tile edges, and a see-through tint would show the overlaps darker.
// Port land in a warm amber, not the Ports layer's blue, which next to the sea read as more water.
export const PORT_LAND_COLOUR = "#e0902f";
export const portSpec = (color: string): LayerSpecification => ({
  id: `${PREFIX}ports`, type: "fill", source: `${PREFIX}ports`, minzoom: PORT_FROM,
  paint: { "fill-color": pale(color, 0.42), "fill-opacity": 1, "fill-antialias": false },
});
function pale(c: string, k = 0.3): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(c.trim());
  if (!m) return c;
  const n = parseInt(m[1], 16), mix = (v: number) => Math.round(v * k + 0xf4 * (1 - k));
  return `rgb(${mix(n >> 16)}, ${mix((n >> 8) & 255)}, ${mix(n & 255)})`;
}
// Just over the map detail's water, under its roads and buildings.
const underRoads = (m: MlMap) => m.getStyle().layers.find((l) => l.id.startsWith(DETAIL_PREFIX) && !l.id.startsWith(`${DETAIL_PREFIX}site-`)
  && !l.id.startsWith(`${DETAIL_PREFIX}landuse-`) && !/-water(way)?$/.test(l.id))?.id ?? before(m);

const before = (m: MlMap) => (m.getLayer("line") ? "line" : undefined);

// Puts the grounds of the place layers that are on (on: their ids) on the map, and takes the
// rest off. Call when the layers, the setting or the map detail change.
export function syncSiteOutlines(m: MlMap, on: string[], enabled: boolean) {
  if (!m.getStyle()) return;
  const want = new Set<string>();
  const srcs = detailSources(m);
  if (enabled) {
    for (const id of on) {
      if (!SITE_KINDS[id]) continue;
      for (const src of srcs) for (const spec of siteSpecs(id, src, colour(id))) {
        want.add(spec.id);
        if (!m.getLayer(spec.id)) m.addLayer(spec, before(m));
      }
    }
  }
  const ports = enabled && srcs.length > 0 && on.some((id) => PORT_LAYERS.includes(id));
  if (ports) want.add(`${PREFIX}ports`);
  for (const l of m.getStyle().layers) if (l.id.startsWith(PREFIX) && !want.has(l.id)) m.removeLayer(l.id);
  if (!ports) {
    if (m.getSource(`${PREFIX}ports`)) m.removeSource(`${PREFIX}ports`);
    return;
  }
  if (!m.getSource(`${PREFIX}ports`)) m.addSource(`${PREFIX}ports`, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  if (!m.getLayer(`${PREFIX}ports`)) m.addLayer(portSpec(PORT_LAND_COLOUR), underRoads(m));
  findPortLand(m, on.filter((id) => PORT_LAYERS.includes(id)));
}

type Ring = GeoJSON.Position[];
function polygons(g: GeoJSON.Geometry): Ring[][] {
  if (g.type === "Polygon") return [g.coordinates];
  if (g.type === "MultiPolygon") return g.coordinates;
  return [];
}

// Industrial land near a port dot (by its bounding box, widened by NEAR_KM), from the detail tiles
// loaded for the view. Pieces cut at tile edges are kept as they come; drawn as a tint only, so
// the cuts don't show.
export function portLand(points: GeoJSON.Position[], land: GeoJSON.Feature[]): GeoJSON.Feature[] {
  const out: GeoJSON.Feature[] = [];
  const seen = new Set<string>();
  for (const f of land) {
    for (const poly of polygons(f.geometry)) {
      const ring = poly[0];
      if (!ring?.length) continue;
      let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
      for (const [x, y] of ring) { w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y); }
      const dy = NEAR_KM / 111, dx = dy / Math.max(0.05, Math.cos(((s + n) / 2) * Math.PI / 180));
      if (!points.some(([x, y]) => x >= w - dx && x <= e + dx && y >= s - dy && y <= n + dy)) continue;
      const key = ring.slice(0, 4).map(([x, y]) => `${x.toFixed(5)},${y.toFixed(5)}`).join(";") + ring.length;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: poly } });
    }
  }
  return out;
}

function findPortLand(m: MlMap, layers: string[]) {
  const src = m.getSource(`${PREFIX}ports`) as GeoJSONSource | undefined;
  if (!src) return;
  if (m.getZoom() < PORT_FROM - 0.5) { src.setData({ type: "FeatureCollection", features: [] }); return; }
  const b = m.getBounds();
  const points: GeoJSON.Position[] = [];
  for (const id of layers) {
    if (!m.getSource(`ov-${id}`)) continue;
    for (const f of m.querySourceFeatures(`ov-${id}`)) {
      if (f.geometry.type !== "Point") continue;
      const [x, y] = f.geometry.coordinates;
      if (b.contains([x, y])) points.push([x, y]);
    }
  }
  const land: GeoJSON.Feature[] = [];
  if (points.length) {
    for (const s of detailSources(m)) {
      land.push(...m.querySourceFeatures(s, { sourceLayer: "landuse", filter: kindIs(PORT_LAND) }) as GeoJSON.Feature[]);
    }
  }
  src.setData({ type: "FeatureCollection", features: portLand(points, land) });
}

// Ports' grounds follow the view (the detail tiles loaded change as the map moves).
export function watchPortLand(m: MlMap, layers: () => string[]) {
  let t: ReturnType<typeof setTimeout> | null = null;
  const run = () => {
    if (t) clearTimeout(t);
    t = setTimeout(() => { if (m.getSource(`${PREFIX}ports`)) findPortLand(m, layers().filter((id) => PORT_LAYERS.includes(id))); }, 300);
  };
  m.on("moveend", run);
  m.on("idle", () => { if (m.getSource(`${PREFIX}ports`)) run(); });
  return () => { m.off("moveend", run); if (t) clearTimeout(t); };
}

// ------------------------------------------------------------------ Land use (from the map)
// The map layer "Land use (from the map)": the land use and land cover areas the map detail
// already holds, each kind in its own colour (homes, shops and offices, industry ...). Kinds
// can be hidden in the Layers panel (setting map_landuse_hidden).
export const LAND_USE: { id: string; label: string; color: string; kinds: string[] }[] = [
  { id: "homes", label: "Homes", color: "#f2c14e", kinds: ["residential", "garages"] },
  { id: "shops", label: "Shops and offices", color: "#e8590c", kinds: ["commercial", "retail"] },
  { id: "industry", label: "Industry and ports", color: "#8d6e63", kinds: ["industrial", "port", "harbour", "quarry", "landfill", "brownfield"] },
  { id: "schools", label: "Schools and universities", color: "#9c36b5", kinds: ["school", "kindergarten", "college", "university", "library"] },
  { id: "health", label: "Hospitals", color: "#e03131", kinds: ["hospital"] },
  { id: "parks", label: "Parks and reserves", color: "#2f9e44", kinds: ["park", "national_park", "nature_reserve", "protected_area", "garden", "dog_park"] },
  { id: "sport", label: "Sport and play", color: "#94d82d", kinds: ["pitch", "stadium", "track", "sports_centre", "playground", "golf_course", "theme_park", "zoo"] },
  { id: "farms", label: "Farms", color: "#d4b483", kinds: ["farmland", "farm", "farmyard", "orchard", "vineyard", "allotments", "meadow"] },
  { id: "forest", label: "Forest", color: "#1b5e20", kinds: ["wood", "forest"] },
  { id: "grass", label: "Grass and scrub", color: "#a9d18e", kinds: ["grass", "grassland", "scrub", "heath"] },
  { id: "wet", label: "Wetland", color: "#4dabf7", kinds: ["wetland", "marsh", "swamp", "bog"] },
  { id: "bare", label: "Sand, rock and ice", color: "#ced4da", kinds: ["sand", "beach", "rock", "bare_rock", "scree", "glacier", "ice"] },
  { id: "cemetery", label: "Cemeteries", color: "#6c757d", kinds: ["cemetery", "grave_yard"] },
  { id: "military", label: "Military", color: "#5f3dc4", kinds: ["military", "naval_base"] },
  { id: "transport", label: "Airports and railway land", color: "#495057", kinds: ["aerodrome", "railway", "bus_station", "pier"] },
];
export const LANDUSE_LAYER = "map_landuse";
// OpenMapTiles: landuse, landcover, park, aeroway; Protomaps: landuse, landcover, natural.
const LANDUSE_SOURCE_LAYERS = ["landcover", "landuse", "park", "natural", "aeroway"];
const LU = `${DETAIL_PREFIX}landuse-`;
const kindOf: ExpressionSpecification = ["coalesce", ["get", "class"], ["get", "kind"], ["get", "subclass"], ""];

export function landUseSpecs(src: string, hidden: string[]): LayerSpecification[] {
  const shown = LAND_USE.filter((u) => !hidden.includes(u.id));
  const kinds = shown.flatMap((u) => u.kinds);
  const color = ["match", kindOf, ...shown.flatMap((u) => [u.kinds, u.color]), "#adb5bd"] as unknown as ExpressionSpecification;
  const filter: ExpressionSpecification = ["all", ["==", ["geometry-type"], "Polygon"], ["in", kindOf, ["literal", kinds.length ? kinds : ["-"]]]];
  return LANDUSE_SOURCE_LAYERS.flatMap((sl) => [
    { id: `${LU}${src}-${sl}-fill`, type: "fill", source: src, "source-layer": sl, filter,
      paint: { "fill-color": color, "fill-opacity": ["interpolate", ["linear"], ["zoom"], 4, 0.25, 10, 0.4, 15, 0.45] } },
    { id: `${LU}${src}-${sl}-line`, type: "line", source: src, "source-layer": sl, minzoom: 12, filter,
      paint: { "line-color": color, "line-width": 0.8, "line-opacity": 0.7 } },
  ] as LayerSpecification[]);
}

// Puts the land use layer on (or takes it off), under the place layers and borders.
export function syncLandUse(m: MlMap, on: boolean, hidden: string[]) {
  if (!m.getStyle()) return;
  for (const l of m.getStyle().layers) if (l.id.startsWith(LU)) m.removeLayer(l.id);
  if (!on) return;
  // under the site outlines when they are on, else just under the borders
  const site = m.getStyle().layers.find((l) => l.id.startsWith(PREFIX))?.id;
  for (const src of detailSources(m)) for (const spec of landUseSpecs(src, hidden)) m.addLayer(spec, site ?? before(m));
}
