// Map overlays from the warehouse's layers table, and how the map draws each one:
// plate boundaries and faults as lines, volcanoes and earthquakes as dots, each
// with a line of text on hover. Fetched once per page and shared by every map.

import type { CircleLayerSpecification, ExpressionSpecification, LineLayerSpecification } from "maplibre-gl";
import { get } from "@/lib/api";
import { cssVar } from "@/lib/colors";

export type MapLayerInfo = {
  layer_id: string; name: string; description: string; kind: "line" | "point"; feature_count: number;
  source_id: string; source_name: string | null;
};

let listed: Promise<MapLayerInfo[]> | null = null;
export function mapLayers(): Promise<MapLayerInfo[]> {
  listed ??= get<MapLayerInfo[]>("/layers").catch((e) => { listed = null; throw e; });
  return listed;
}

const features = new Map<string, Promise<GeoJSON.FeatureCollection>>();
export function layerData(id: string): Promise<GeoJSON.FeatureCollection> {
  if (!features.has(id)) {
    features.set(id, get<GeoJSON.FeatureCollection>(`/layers/${encodeURIComponent(id)}`)
      .catch((e) => { features.delete(id); throw e; }));
  }
  return features.get(id)!;
}

type Style = { paint: () => LineLayerSpecification["paint"] | CircleLayerSpecification["paint"]; legend: string; swatch: () => string; dot?: boolean };
const zoomWidth = (w0: number, w5: number): ExpressionSpecification => ["interpolate", ["linear"], ["zoom"], 0, w0, 5, w5];

export const LAYER_STYLE: Record<string, Style> = {
  plate_boundaries: {
    legend: "Plate boundary", swatch: () => cssVar("--series-7"),
    paint: () => ({ "line-color": cssVar("--series-7"), "line-width": zoomWidth(1.2, 2.5), "line-opacity": 0.9 }),
  },
  active_faults: {
    legend: "Active fault", swatch: () => cssVar("--div-neg-2"),
    paint: () => ({ "line-color": cssVar("--div-neg-2"), "line-width": zoomWidth(0.5, 1.6), "line-opacity": 0.8 }),
  },
  volcanoes: {
    legend: "Volcano (darker: erupted since 1900)", swatch: () => cssVar("--series-2"), dot: true,
    paint: () => ({
      "circle-color": cssVar("--series-2"), "circle-radius": zoomWidth(2.5, 6),
      "circle-opacity": ["case", [">=", ["coalesce", ["get", "last"], -99999], 1900], 0.95, 0.4],
      "circle-stroke-color": cssVar("--surface"), "circle-stroke-width": 0.6,
    }),
  },
  earthquakes: {
    legend: "Earthquake, sized by magnitude (6 to 9+)", swatch: () => cssVar("--series-8"), dot: true,
    paint: () => ({
      "circle-color": cssVar("--series-8"), "circle-opacity": 0.4,
      "circle-radius": ["interpolate", ["linear"], ["coalesce", ["get", "mag"], 6], 6, 2, 7, 3.5, 8, 7, 9, 12],
      "circle-stroke-color": cssVar("--series-8"), "circle-stroke-width": 0.6, "circle-stroke-opacity": 0.8,
    }),
  },
};

// The text shown when the pointer is over one of a layer's features.
export function layerLabel(layer: string, p: Record<string, unknown>): string {
  const esc = (v: unknown) => String(v ?? "").replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`);
  if (layer === "volcanoes") {
    const last = typeof p.last === "number" ? (p.last < 0 ? `${-p.last} BCE` : String(p.last)) : "unknown";
    return `<b>${esc(p.name)}</b> (volcano)<br/>${esc(p.type ?? "")}${p.country ? `, ${esc(p.country)}` : ""}<br/>Last eruption: ${last}`
      + (typeof p.elevation === "number" ? ` · ${Math.round(p.elevation)} m` : "");
  }
  if (layer === "earthquakes") {
    return `<b>Magnitude ${esc(p.mag)}</b> · ${esc(p.date)}<br/>${esc(p.name)}`
      + (typeof p.depth === "number" ? `<br/>Depth ${p.depth} km` : "") + (p.tsunami ? " · tsunami" : "");
  }
  if (layer === "active_faults") {
    return `<b>${esc(p.name)}</b> (fault)${p.slip ? `<br/>${esc(p.slip)}` : ""}${typeof p.rate === "number" ? ` · ${p.rate} mm a year` : ""}`;
  }
  return `<b>${esc(p.name)}</b>${p.type ? `<br/>${esc(p.type)}` : ""}`;
}
