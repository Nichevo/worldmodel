// Map detail under the colours: water, roads, rail, buildings and place names, faint at
// world view and clearer as you zoom in (the country colours fade so the detail shows).
// Settings > Map picks where it comes from:
//   online  OpenFreeMap's free vector tiles (OpenMapTiles layout; nothing stored here)
//   local   the map files made on this PC (Protomaps layout): world.pmtiles plus a
//           full-detail file per chosen country, served by the app's server
//   plain   just the country shapes, as before

import * as maplibregl from "maplibre-gl";
import type { ExpressionSpecification, LayerSpecification } from "maplibre-gl";
import { Protocol } from "pmtiles";
import { get } from "@/lib/api";
import { cssVar } from "@/lib/colors";
import { refreshFill } from "@/lib/maplook";

export type BaseMap = "online" | "local" | "plain";
export type BaseMapFile = { name: string; region: string; bytes: number; made: string | null; build: string | null; maxzoom: number | null };
export type BaseMapJob = { state: "idle" | "running" | "done" | "failed"; step?: string; error?: string; started?: string; finished?: string };
export type BaseMapStatus = {
  files: BaseMapFile[]; fonts: boolean; tool: boolean; job: BaseMapJob; regions: string[];
  world_zoom: number; region_zoom: number; base_map: BaseMap;
};
export type BaseMapEstimate = {
  build: string; items: { name: string; region: string; maxzoom: number; bytes: number | null }[];
  bytes: number; size: string; fits: boolean; why: string | null;
};

const ONLINE_TILES = "https://tiles.openfreemap.org/planet";
const ONLINE_FONTS = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf";
const LOCAL_FONTS = "/api/v1/basemap/fonts/{fontstack}/{range}.pbf";
const FONT = ["Noto Sans Regular"];
export const DETAIL_PREFIX = "bm-";

let protocolAdded = false;
function addProtocol() {
  if (protocolAdded) return;
  const p = new Protocol();
  maplibregl.addProtocol("pmtiles", p.tile);
  protocolAdded = true;
}

let status: Promise<BaseMapStatus> | null = null;
export function baseMapStatus(fresh = false): Promise<BaseMapStatus> {
  if (fresh || !status) status = get<BaseMapStatus>("/basemap").catch((e) => { status = null; throw e; });
  return status;
}

// The country colours fade as you zoom in, so the detail under them shows.
export const FADED_FILL: ExpressionSpecification = ["interpolate", ["linear"], ["zoom"], 3, 0.92, 6, 0.6, 9, 0.35, 13, 0.2];

const name: ExpressionSpecification = ["coalesce", ["get", "name:en"], ["get", "name_en"], ["get", "name"]];
const width = (stops: [number, number][]): ExpressionSpecification =>
  ["interpolate", ["exponential", 1.6], ["zoom"], ...stops.flat()] as ExpressionSpecification;

function label(id: string, source: string, layer: string, filter: ExpressionSpecification, minzoom: number, size: [number, number]): LayerSpecification {
  return {
    id, type: "symbol", source, "source-layer": layer, filter, minzoom,
    layout: { "text-field": name, "text-font": FONT, "text-size": ["interpolate", ["linear"], ["zoom"], minzoom, size[0], minzoom + 6, size[1]],
      "text-max-width": 8, "text-padding": 4 },
    paint: { "text-color": cssVar("--ink"), "text-halo-color": cssVar("--surface"), "text-halo-width": 1.4, "text-opacity": 0.9 },
  };
}

// OpenMapTiles layout (OpenFreeMap).
function onlineLayers(src: string): { under: LayerSpecification[]; over: LayerSpecification[] } {
  const p = DETAIL_PREFIX + src;
  const road = (cls: string[], minzoom: number, color: string, w: [number, number][]): LayerSpecification => ({
    id: `${p}-road-${cls[0]}`, type: "line", source: src, "source-layer": "transportation", minzoom,
    filter: ["in", ["get", "class"], ["literal", cls]],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": cssVar(color), "line-width": width(w), "line-opacity": 0.85 },
  });
  return {
    under: [
      { id: `${p}-water`, type: "fill", source: src, "source-layer": "water", paint: { "fill-color": cssVar("--map-water"), "fill-opacity": 0.9 } },
      { id: `${p}-waterway`, type: "line", source: src, "source-layer": "waterway", minzoom: 8,
        paint: { "line-color": cssVar("--map-water"), "line-width": width([[8, 0.5], [14, 2]]) } },
      { id: `${p}-building`, type: "fill", source: src, "source-layer": "building", minzoom: 13,
        paint: { "fill-color": cssVar("--map-building"), "fill-opacity": 0.7 } },
      road(["minor", "service"], 12, "--map-road", [[12, 0.4], [16, 4]]),
      road(["secondary", "tertiary"], 9, "--map-road", [[9, 0.4], [16, 6]]),
      road(["primary", "trunk"], 6, "--map-road-major", [[6, 0.4], [16, 8]]),
      road(["motorway"], 5, "--map-road-major", [[5, 0.6], [16, 10]]),
      { id: `${p}-rail`, type: "line", source: src, "source-layer": "transportation", minzoom: 6,
        filter: ["in", ["get", "class"], ["literal", ["rail", "transit"]]],
        paint: { "line-color": cssVar("--map-rail"), "line-width": width([[6, 0.6], [16, 3]]), "line-dasharray": [3, 2] } },
    ],
    over: [
      label(`${p}-label-road`, src, "transportation_name", ["has", "name"], 13, [10, 13]),
      label(`${p}-label-village`, src, "place", ["in", ["get", "class"], ["literal", ["village", "suburb", "neighbourhood"]]], 11, [10, 13]),
      label(`${p}-label-town`, src, "place", ["==", ["get", "class"], "town"], 7, [10, 14]),
      label(`${p}-label-city`, src, "place", ["==", ["get", "class"], "city"], 4, [11, 17]),
    ],
  };
}

// Protomaps layout (the local files).
function localLayers(src: string): { under: LayerSpecification[]; over: LayerSpecification[] } {
  const p = DETAIL_PREFIX + src;
  const road = (kinds: string[], minzoom: number, color: string, w: [number, number][]): LayerSpecification => ({
    id: `${p}-road-${kinds[0]}`, type: "line", source: src, "source-layer": "roads", minzoom,
    filter: ["in", ["get", "kind"], ["literal", kinds]],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": cssVar(color), "line-width": width(w), "line-opacity": 0.85 },
  });
  const rail = (layer: string): LayerSpecification => ({
    id: `${p}-rail-${layer}`, type: "line", source: src, "source-layer": layer, minzoom: 6,
    filter: ["==", ["get", "kind"], "rail"],
    paint: { "line-color": cssVar("--map-rail"), "line-width": width([[6, 0.6], [16, 3]]), "line-dasharray": [3, 2] },
  });
  const place = (id: string, filter: ExpressionSpecification, minzoom: number, size: [number, number]) =>
    label(`${p}-label-${id}`, src, "places", ["all", ["==", ["get", "kind"], "locality"], filter], minzoom, size);
  const rank: ExpressionSpecification = ["coalesce", ["get", "population_rank"], 0];
  return {
    under: [
      { id: `${p}-water`, type: "fill", source: src, "source-layer": "water", filter: ["==", ["geometry-type"], "Polygon"],
        paint: { "fill-color": cssVar("--map-water"), "fill-opacity": 0.9 } },
      { id: `${p}-waterway`, type: "line", source: src, "source-layer": "water", minzoom: 8, filter: ["==", ["geometry-type"], "LineString"],
        paint: { "line-color": cssVar("--map-water"), "line-width": width([[8, 0.5], [14, 2]]) } },
      { id: `${p}-building`, type: "fill", source: src, "source-layer": "buildings", minzoom: 13,
        paint: { "fill-color": cssVar("--map-building"), "fill-opacity": 0.7 } },
      road(["minor_road", "other"], 12, "--map-road", [[12, 0.4], [16, 4]]),
      road(["medium_road"], 9, "--map-road", [[9, 0.4], [16, 6]]),
      road(["major_road"], 6, "--map-road-major", [[6, 0.4], [16, 8]]),
      road(["highway"], 5, "--map-road-major", [[5, 0.6], [16, 10]]),
      rail("roads"), rail("transit"),
    ],
    over: [
      label(`${p}-label-road`, src, "roads", ["has", "name"], 13, [10, 13]),
      place("small", ["<", rank, 9], 10, [10, 13]),
      place("town", ["all", [">=", rank, 9], ["<", rank, 12]], 6, [10, 14]),
      place("city", [">=", rank, 12], 3, [11, 17]),
    ],
  };
}

// Take the detail off a map (when the setting changes).
export function removeDetail(m: maplibregl.Map) {
  for (const l of m.getStyle()?.layers ?? []) if (l.id.startsWith(DETAIL_PREFIX)) m.removeLayer(l.id);
  for (const s of Object.keys(m.getStyle()?.sources ?? {})) if (s.startsWith("detail-")) m.removeSource(s);
  refreshFill(m, { detail: false });
}

// Put the detail on a map whose country layers ("fill", "line") are already there.
// Returns the attribution to show, or null when there is no detail (plain, or no files).
export async function addDetail(m: maplibregl.Map, mode: BaseMap): Promise<string | null> {
  removeDetail(m);
  if (mode === "plain") return null;
  let sources: { id: string; spec: maplibregl.SourceSpecification; layers: ReturnType<typeof onlineLayers> }[] = [];
  if (mode === "online") {
    sources = [{ id: "detail-online", spec: { type: "vector", url: ONLINE_TILES }, layers: onlineLayers("detail-online") }];
    m.setGlyphs(ONLINE_FONTS);
  } else {
    const st = await baseMapStatus().catch(() => null);
    if (!st || !st.files.length) return null;
    addProtocol();
    const origin = typeof location !== "undefined" ? location.origin : "";
    sources = st.files.map((f) => {
      const id = `detail-${f.region.toLowerCase()}`;
      return { id, spec: { type: "vector", url: `pmtiles://${origin}/api/v1/basemap/files/${encodeURIComponent(f.name)}`,
        attribution: "Map detail: <a href=\"https://protomaps.com\">Protomaps</a> © <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a>" } as maplibregl.SourceSpecification,
        layers: localLayers(id) };
    });
    if (st.fonts) m.setGlyphs(LOCAL_FONTS);
    else sources.forEach((s) => { s.layers.over = []; }); // no fonts yet: no place names
  }
  if (!m.getLayer("line")) return null; // the map went away meanwhile
  for (const s of sources) {
    if (!m.getSource(s.id)) m.addSource(s.id, s.spec);
    for (const l of s.layers.under) m.addLayer(l, "line");
  }
  for (const s of sources) for (const l of s.layers.over) m.addLayer(l);
  refreshFill(m, { detail: true });
  return mode === "online" ? "Map detail: OpenFreeMap, © OpenMapTiles, © OpenStreetMap contributors"
    : "Map detail: Protomaps, © OpenStreetMap contributors";
}

// How far in a map may zoom: further with detail to show.
export const maxZoomFor = (mode: BaseMap, files = 0) => (mode === "online" || (mode === "local" && files > 0) ? 16 : 7);
