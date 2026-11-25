// Map overlays from the warehouse's layers table, and how the map draws each one:
// plate boundaries and faults as lines, volcanoes and earthquakes as dots, each
// with a line of text on hover. Fetched once per page and shared by every map.

import type { CircleLayerSpecification, ExpressionSpecification, FillLayerSpecification, LineLayerSpecification } from "maplibre-gl";
import { get } from "@/lib/api";
import { cssVar } from "@/lib/colors";
import { EVENT_KIND, fightingQuery, lookCloser, SOURCE_NAME } from "@/lib/osint";

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

// fetch: "window" layers come from /geo/<id> for the area in view (rivers, basins, cables and
// pipelines are too big to send whole); "live" ones are asked for the area in view now and
// again while on (planes and ships). fill: drawn as areas (basins).
type Style = {
  paint: () => LineLayerSpecification["paint"] | CircleLayerSpecification["paint"] | FillLayerSpecification["paint"];
  legend: string; swatch: () => string; dot?: boolean; fill?: boolean; fetch?: "window" | "live"; every?: number;
  // what a click on one shows: its card (geo features), the countries on a chokepoint's shores, or a card made
  // from the feature itself with "Look closer" links (located events, military planes)
  click?: "feature" | "chokepoint" | "here";
  timed?: boolean; // asked again when the map's time window changes (the fighting layer)
  once?: boolean; // a "window" layer read once, whatever the view (the front line: one shape)
};
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
  major_cities: {
    legend: "City of a million or more (capitals filled dark)", swatch: () => cssVar("--ink"), dot: true,
    paint: () => ({
      "circle-color": ["case", ["has", "capital"], cssVar("--ink"), cssVar("--surface")], "circle-opacity": 0.85,
      "circle-radius": ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "population"], 0]], 0, 2, 1000, 3.5, 6000, 11],
      "circle-stroke-color": cssVar("--ink"), "circle-stroke-width": 1.1,
    }),
  },
  city_stress: {
    legend: "City stress score, 0 calm (green) to 10 most stressful (red)", swatch: () => "#e8590c", dot: true,
    paint: () => ({
      "circle-color": ["interpolate", ["linear"], ["coalesce", ["get", "score"], 5], 0, "#2f9e44", 3.5, "#94d82d", 5, "#fcc419", 6.5, "#f76707", 10, "#c92a2a"],
      "circle-opacity": 0.9, "circle-radius": zoomWidth(4, 8), "circle-stroke-color": cssVar("--ink"), "circle-stroke-width": 0.6,
    }),
  },
  transit_stations: {
    legend: "Metro and rail station", swatch: () => cssVar("--series-3"), dot: true,
    paint: () => ({
      "circle-color": cssVar("--series-3"), "circle-opacity": 0.85, "circle-radius": zoomWidth(1.2, 3.5),
      "circle-stroke-color": cssVar("--surface"), "circle-stroke-width": 0.4,
    }),
  },
  transit_lines: {
    legend: "Metro and rail line (its own colour where known)", swatch: () => cssVar("--series-3"),
    paint: () => ({
      "line-color": ["case", ["has", "color"], ["get", "color"],
        ["match", ["get", "ci"], 0, cssVar("--series-1"), 1, cssVar("--series-2"), 2, cssVar("--series-3"), 3, cssVar("--series-4"),
          4, cssVar("--series-5"), 5, cssVar("--series-6"), 6, cssVar("--series-7"), cssVar("--series-8")]],
      "line-width": ["interpolate", ["linear"], ["zoom"], 2, 0.6, 8, 2, 13, 4], "line-opacity": 0.9,
    }),
  },
  hospitals: {
    legend: "Hospital, sized by beds (Settings > Places: smallest shown)", swatch: () => cssVar("--div-neg-2"), dot: true,
    paint: () => ({
      "circle-color": cssVar("--div-neg-2"), "circle-opacity": 0.8,
      "circle-radius": ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "beds"], 100]], 0, 1.8, 20, 3, 50, 7],
      "circle-stroke-color": cssVar("--surface"), "circle-stroke-width": 0.6,
    }),
  },
  military_bases: {
    legend: "Military, air or naval base", swatch: () => cssVar("--series-7"), dot: true,
    paint: () => ({
      "circle-color": cssVar("--series-7"), "circle-opacity": 0.85, "circle-radius": zoomWidth(2, 5),
      "circle-stroke-color": cssVar("--ink"), "circle-stroke-width": 0.6,
    }),
  },
  universities: {
    legend: "University, sized by students", swatch: () => cssVar("--series-5"), dot: true,
    paint: () => ({
      "circle-color": cssVar("--series-5"), "circle-opacity": 0.75,
      "circle-radius": ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "students"], 5000]], 0, 2, 100, 3, 300, 8],
      "circle-stroke-color": cssVar("--surface"), "circle-stroke-width": 0.6,
    }),
  },
  storm_tracks: {
    legend: "Tropical storm track (darker red: stronger, category 1 to 5)", swatch: () => cssVar("--div-neg-3"),
    paint: () => ({
      "line-color": ["interpolate", ["linear"], ["coalesce", ["get", "cat"], 0], 0, cssVar("--series-1"), 2, cssVar("--series-6"), 5, cssVar("--div-neg-3")],
      "line-width": ["interpolate", ["linear"], ["coalesce", ["get", "cat"], 0], 0, 0.6, 5, 2.4], "line-opacity": 0.7,
    }),
  },
  storms_active: {
    legend: "Storm active now (NOAA IBTrACS, last days; darker red: stronger)", swatch: () => cssVar("--div-neg-3"),
    paint: () => ({
      "line-color": ["interpolate", ["linear"], ["coalesce", ["get", "cat"], 0], 0, cssVar("--series-1"), 2, cssVar("--series-6"), 5, cssVar("--div-neg-3")],
      "line-width": ["interpolate", ["linear"], ["coalesce", ["get", "cat"], 0], 0, 2, 5, 4], "line-opacity": 0.95,
    }),
  },
  // ---- hazards now and power (parked ideas, map layers)
  fires_now: {
    legend: "Fire seen from space in the last 24 hours (bigger: more fire power)", swatch: () => "#d9480f", dot: true,
    paint: () => ({ "circle-color": "#d9480f", "circle-opacity": 0.75, "circle-stroke-color": "#7a2100", "circle-stroke-width": 0.4,
      "circle-radius": ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "frp"], 1]], 0, 1.6, 10, 3.5, 40, 8, 120, 14] }),
  },
  fires_week: {
    legend: "Fire seen from space in the last 7 days (MODIS; bigger: more fire power)", swatch: () => "#e8590c", dot: true,
    paint: () => ({ "circle-color": "#e8590c", "circle-opacity": 0.6, "circle-stroke-color": "#7a2100", "circle-stroke-width": 0.3,
      "circle-radius": ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "frp"], 1]], 0, 1.4, 10, 3, 40, 7, 120, 12] }),
  },
  heat_now: {
    legend: "Big city forecast to reach 35 °C or more on 2+ of the next 5 days (darker: hotter)", swatch: () => "#c2255c", dot: true,
    paint: () => ({ "circle-color": cssVar("--surface"), "circle-radius": zoomWidth(5, 9),
      "circle-stroke-color": ["interpolate", ["linear"], ["coalesce", ["get", "peak"], 35], 35, "#f783ac", 40, "#c2255c", 45, "#6f0d33"],
      "circle-stroke-width": 3 }),
  },
  coral_alerts: {
    legend: "Reef region under bleaching heat stress (NOAA Coral Reef Watch: watch, warning, alert 1, alert 2)", swatch: () => "#f08c00", fill: true,
    paint: () => ({ "fill-color": ["match", ["get", "level"], 1, "#ffe066", 2, "#f8c56a", 3, "#f08c00", 4, "#c92a2a", "#ced4da"],
      "fill-opacity": ["match", ["get", "level"], 0, 0.12, 0.5], "fill-outline-color": "#7a3b00" }),
  },
  nz_wastewater: {
    legend: "Wastewater test site, sized by people served: red rising, blue falling against the month before", swatch: () => "#c92a2a", dot: true,
    paint: () => ({
      "circle-color": ["case", ["!", ["to-boolean", ["get", "recent"]]], "#adb5bd", ["==", ["get", "change"], null], "#868e96",
        ["interpolate", ["linear"], ["get", "change"], -50, "#1c7ed6", -15, "#a5d8ff", 0, "#f1f3f5", 15, "#ffc9c9", 50, "#c92a2a"]],
      "circle-opacity": 0.9, "circle-stroke-color": "#495057", "circle-stroke-width": 0.8,
      "circle-radius": ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "population"], 1000]], 0, 3, 300, 6, 1200, 14],
    }),
  },
  power_plants: {
    legend: "Power plant, sized by capacity, coloured by fuel", swatch: () => "#2b8a3e", dot: true,
    paint: () => ({
      "circle-color": ["match", ["get", "fuel"], "Hydro", "#1c7ed6", "Geothermal", "#e8590c", "Wind", "#37b24d", "Solar", "#f59f00",
        "Nuclear", "#7048e8", "Coal", "#343a40", "Gas", "#868e96", "Oil", "#5c3d2e", "Biomass", "#82c91e", "Waste", "#a9a9a9", "#adb5bd"],
      "circle-opacity": 0.85, "circle-stroke-color": cssVar("--surface"), "circle-stroke-width": 0.6,
      "circle-radius": ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "mw"], 10]], 0, 1.5, 10, 3, 30, 7, 80, 14],
    }),
  },
  power_links: {
    legend: "Electricity traded between countries in a year (thicker: more; hover for which way)", swatch: () => "#e8590c",
    paint: () => ({ "line-color": "#e8590c", "line-opacity": 0.8,
      "line-width": ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "total"], 0]], 0, 0.8, 100, 3, 200, 7, 300, 12] }),
  },
  railways: {
    legend: "Railway (thicker: main lines)", swatch: () => "#7b2d26", fetch: "window",
    paint: () => ({ "line-color": "#7b2d26", "line-opacity": 0.85,
      "line-width": ["interpolate", ["linear"], ["zoom"], 2, ["match", ["get", "rank"], 1, 1.1, 0.6], 8, ["match", ["get", "rank"], 1, 2.4, 2, 1.6, 1.1]] }),
  },
  power_lines: {
    legend: "Power line (solid: mapped; faint: predicted from night lights)", swatch: () => "#5f3dc4", fetch: "window",
    paint: () => ({ "line-color": "#5f3dc4", "line-width": ["interpolate", ["linear"], ["zoom"], 2, 0.5, 8, 1.6, 12, 2.6],
      "line-opacity": ["case", ["==", ["get", "rank"], 1], 0.85, 0.35] }),
  },
  antarctic_claims: {
    legend: "Antarctic claim (frozen by the 1959 treaty)", swatch: () => cssVar("--series-4"),
    paint: () => ({ "line-color": cssVar("--series-4"), "line-width": zoomWidth(1.2, 2.5), "line-opacity": 0.85, "line-dasharray": [3, 2] }),
  },
  antarctic_stations: {
    legend: "Antarctic research station", swatch: () => cssVar("--series-1"), dot: true,
    paint: () => ({
      "circle-color": cssVar("--series-1"), "circle-opacity": 0.9, "circle-radius": zoomWidth(2.5, 6),
      "circle-stroke-color": cssVar("--surface"), "circle-stroke-width": 0.8,
    }),
  },
  tide_gauges: {
    legend: "Tide gauge: sea rising faster (red) or slower (blue) than 3 mm a year", swatch: () => cssVar("--div-neg-2"), dot: true,
    paint: () => ({
      "circle-color": ["interpolate", ["linear"], ["coalesce", ["get", "trend30"], ["get", "trend"], 0],
        -3, cssVar("--div-pos-3"), 0, cssVar("--div-pos-1"), 3, cssVar("--surface-2"), 6, cssVar("--div-neg-2"), 10, cssVar("--div-neg-3")],
      "circle-radius": zoomWidth(2.5, 6), "circle-opacity": 0.9, "circle-stroke-color": cssVar("--ink-2"), "circle-stroke-width": 0.5,
    }),
  },
  // ---- land, cities and trees (PR 6)
  urban_centres: {
    legend: "City outline (darker: grew more since 1975)", swatch: () => cssVar("--series-5"), fill: true, fetch: "window", click: "feature",
    paint: () => ({ "fill-color": cssVar("--series-5"), "fill-outline-color": cssVar("--series-5"),
      "fill-opacity": ["interpolate", ["linear"], ["coalesce", ["get", "growth"], 0], 0, 0.15, 100, 0.35, 300, 0.6] }),
  },
  street_trees: {
    legend: "Street or park tree (council list; from street level)", swatch: () => "#2d6a4f", dot: true, fetch: "window", click: "feature",
    paint: () => ({ "circle-color": "#2d6a4f", "circle-opacity": 0.8, "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 1.5, 17, 5],
      "circle-stroke-color": cssVar("--surface"), "circle-stroke-width": 0.4 }),
  },
  nz_land_change: {
    legend: "Land cover changed since the survey before (NZ LCDB)", swatch: () => "#c0392b", fill: true, fetch: "window", click: "feature",
    paint: () => ({ "fill-color": ["match", ["get", "to"], [1, 2, 5, 6], "#c0392b", [64], "#e67e22", [71, 68], "#27ae60", [69, 70], "#145a32",
      [40, 41], "#c5d86d", [30, 33], "#af7ac5", "#7f8c8d"], "fill-opacity": 0.6, "fill-outline-color": cssVar("--ink-2") }),
  },
  // ---- transport and trade, rivers, tourism (PR 4)
  rivers: {
    legend: "River, wider for more water (more appear as you zoom in)", swatch: () => cssVar("--series-1"), fetch: "window", click: "feature",
    paint: () => ({ "line-color": cssVar("--series-1"), "line-opacity": 0.75,
      // width by flow order (1 the Amazon, 7 a stream), thicker as you zoom in
      "line-width": ["*", ["interpolate", ["linear"], ["zoom"], 1, 0.8, 6, 1.4],
        ["interpolate", ["linear"], ["coalesce", ["get", "order"], ["get", "rank"], 5], 1, 3.2, 3, 1.8, 5, 0.8, 7, 0.4]] }),
  },
  basins: {
    legend: "River basin (outlined; darker: shared by several countries)", swatch: () => cssVar("--series-1"), fill: true, fetch: "window", click: "feature",
    paint: () => ({ "fill-color": ["case", ["boolean", ["get", "transboundary"], false], cssVar("--series-1"), cssVar("--series-3")],
      "fill-opacity": 0.18, "fill-outline-color": cssVar("--series-1") }),
  },
  eez_lines: {
    legend: "Economic zone limits (200 nautical miles; darker: borders between countries' zones)", swatch: () => "#3b6ea5", fetch: "window",
    paint: () => ({ "line-color": ["case", ["boolean", ["get", "outer"], false], "#5f8fc4", "#2c4f7c"],
      "line-width": zoomWidth(0.8, 1.8), "line-opacity": 0.9 }),
  },
  airspace: {
    legend: "Flight information region (whose air traffic control covers it; each region as you zoom in)", swatch: () => "#6a4fc2", fill: true, fetch: "window",
    paint: () => ({ "fill-color": "#6a4fc2", "fill-opacity": ["case", ["==", ["get", "rank"], 1], 0.05, 0.02], "fill-outline-color": "#6a4fc2" }),
  },
  waterways: {
    legend: "Inland waterway ships use", swatch: () => cssVar("--series-4"), fetch: "window", click: "feature",
    paint: () => ({ "line-color": cssVar("--series-4"), "line-width": ["interpolate", ["linear"], ["zoom"], 1, 1, 6, 2.6], "line-opacity": 0.9 }),
  },
  cables: {
    legend: "Undersea cable (its own colour)", swatch: () => cssVar("--series-6"), fetch: "window", click: "feature",
    paint: () => ({ "line-color": ["coalesce", ["get", "color"], cssVar("--series-6")], "line-width": zoomWidth(1, 2.2), "line-opacity": 0.85 }),
  },
  gas_pipelines: {
    legend: "Gas pipeline (dashed: not built yet)", swatch: () => cssVar("--series-2"), fetch: "window", click: "feature",
    paint: () => ({ "line-color": cssVar("--series-2"), "line-width": zoomWidth(1, 2.4),
      "line-opacity": ["case", ["<=", ["coalesce", ["get", "rank"], 3], 1], 0.95, 0.45] }),
  },
  oil_pipelines: {
    legend: "Oil pipeline", swatch: () => cssVar("--series-7"), fetch: "window", click: "feature",
    paint: () => ({ "line-color": cssVar("--series-7"), "line-width": zoomWidth(1, 2.4),
      "line-opacity": ["case", ["<=", ["coalesce", ["get", "rank"], 3], 1], 0.95, 0.45] }),
  },
  shipping_lanes: {
    legend: "Shipping lane (thicker: busier)", swatch: () => cssVar("--series-1"),
    paint: () => ({ "line-color": cssVar("--series-1"), "line-opacity": 0.55,
      "line-width": ["match", ["get", "rank"], 1, 2.2, 2, 1.2, 0.6] }),
  },
  ports: {
    legend: "Port, sized by ship calls a year", swatch: () => cssVar("--series-1"), dot: true,
    paint: () => ({
      "circle-color": cssVar("--series-1"), "circle-opacity": 0.75,
      "circle-radius": ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "calls"], 0]], 0, 1.8, 50, 4, 150, 10],
      "circle-stroke-color": cssVar("--surface"), "circle-stroke-width": 0.6,
    }),
  },
  port_pressure: {
    legend: "Port, last 4 weeks against normal (red: fewer ships, blue: more; larger: busier)", swatch: () => cssVar("--div-neg-2"), dot: true,
    paint: () => ({
      "circle-color": ["case", ["!=", ["typeof", ["get", "vs_normal"]], "number"], cssVar("--muted"),
        ["interpolate", ["linear"], ["coalesce", ["get", "vs_normal"], 0], -40, cssVar("--div-neg-3"), -15, cssVar("--div-neg-1"), 0, cssVar("--surface-2"), 15, cssVar("--div-pos-1"), 40, cssVar("--div-pos-3")]],
      "circle-opacity": 0.85,
      "circle-radius": ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "weekly"], 0]], 0, 2, 5, 3.5, 15, 7, 40, 12],
      "circle-stroke-color": cssVar("--ink-2"), "circle-stroke-width": 0.5,
    }),
  },
  ports_all: {
    legend: "Port (World Port Index)", swatch: () => cssVar("--muted"), dot: true,
    paint: () => ({
      "circle-color": cssVar("--ink-2"), "circle-opacity": 0.6,
      "circle-radius": ["match", ["get", "size"], "large", 4, "medium", 3, 2],
    }),
  },
  chokepoints: {
    legend: "Shipping chokepoint, sized by ships a day", swatch: () => cssVar("--div-neg-2"), dot: true, click: "chokepoint",
    paint: () => ({
      "circle-color": cssVar("--div-neg-2"), "circle-opacity": 0.8,
      "circle-radius": ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "daily"], 10]], 0, 4, 5, 7, 12, 14],
      "circle-stroke-color": cssVar("--ink"), "circle-stroke-width": 1,
    }),
  },
  airports: {
    legend: "Airport (larger: large airport)", swatch: () => cssVar("--series-5"), dot: true,
    paint: () => ({
      "circle-color": cssVar("--series-5"), "circle-opacity": 0.8,
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 0, ["match", ["get", "size"], "large", 2.5, 1.2], 5, ["match", ["get", "size"], "large", 6, 3]],
      "circle-stroke-color": cssVar("--surface"), "circle-stroke-width": 0.5,
    }),
  },
  cable_landings: {
    legend: "Cable landing point", swatch: () => cssVar("--series-6"), dot: true,
    paint: () => ({ "circle-color": cssVar("--series-6"), "circle-radius": zoomWidth(1.5, 4), "circle-stroke-color": cssVar("--surface"), "circle-stroke-width": 0.5 }),
  },
  lng_terminals: {
    legend: "LNG terminal (hollow: not built yet)", swatch: () => cssVar("--series-2"), dot: true,
    paint: () => ({
      "circle-color": ["case", ["==", ["get", "status"], "operating"], cssVar("--series-2"), cssVar("--surface")],
      "circle-radius": ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "capacity"], 1]], 0, 3, 5, 9],
      "circle-stroke-color": cssVar("--series-2"), "circle-stroke-width": 1.4,
    }),
  },
  heritage_sites: {
    legend: "World Heritage site (red ring: in danger)", swatch: () => cssVar("--series-3"), dot: true,
    paint: () => ({
      "circle-color": ["match", ["get", "type"], "natural", cssVar("--series-3"), "mixed", cssVar("--series-5"), cssVar("--series-6")],
      "circle-radius": zoomWidth(2, 5), "circle-opacity": 0.85,
      "circle-stroke-color": ["case", ["has", "danger"], cssVar("--div-neg-3"), cssVar("--surface")],
      "circle-stroke-width": ["case", ["has", "danger"], 2, 0.5],
    }),
  },
  visited_sites: {
    legend: "Place with a million or more visitors a year", swatch: () => cssVar("--series-4"), dot: true,
    paint: () => ({
      "circle-color": cssVar("--series-4"), "circle-opacity": 0.8,
      "circle-radius": ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "visitors"], 1e6]], 1000, 3, 5000, 9],
      "circle-stroke-color": cssVar("--surface"), "circle-stroke-width": 0.6,
    }),
  },
  live_planes: {
    legend: "Plane in the air now (OpenSky)", swatch: () => cssVar("--series-7"), dot: true, fetch: "live", every: 60,
    paint: () => ({ "circle-color": cssVar("--series-7"), "circle-radius": zoomWidth(1.4, 3.5), "circle-opacity": 0.85 }),
  },
  live_ships: {
    legend: "Ship now (aisstream.io)", swatch: () => cssVar("--series-1"), dot: true, fetch: "live", every: 30,
    paint: () => ({ "circle-color": cssVar("--series-1"), "circle-radius": zoomWidth(1.4, 3.5), "circle-opacity": 0.85,
      "circle-stroke-color": cssVar("--surface"), "circle-stroke-width": 0.4 }),
  },
  // ---- detail from the OSINT communities
  conflict_events: {
    legend: "Fighting and unrest in the time window (UCDP, ACLED): bigger for more deaths; red fighting, purple civilians killed, blue protests",
    swatch: () => "#c92a2a", dot: true, fetch: "window", click: "here", timed: true,
    paint: () => ({
      "circle-color": ["match", ["get", "kind"], ...Object.entries(EVENT_KIND).flatMap(([k, v]) => [k, v.color]), "#868e96"] as unknown as ExpressionSpecification,
      "circle-opacity": ["case", ["==", ["get", "group"], "unrest"], 0.55, 0.75],
      "circle-radius": ["interpolate", ["linear"], ["sqrt", ["coalesce", ["get", "deaths"], 0]], 0, 2.4, 3, 4, 10, 8, 30, 15],
      "circle-stroke-color": cssVar("--surface"), "circle-stroke-width": 0.5,
    }),
  },
  front_line: {
    legend: "Land held by Russia in Ukraine (DeepState, latest day; War trackers has the date slider)", swatch: () => "#c92a2a", fill: true, fetch: "window", once: true,
    paint: () => ({ "fill-color": "#c92a2a", "fill-opacity": 0.22, "fill-outline-color": "#8a1c1c" }),
  },
  live_military: {
    legend: "Military plane now (adsb.lol; only those that broadcast)", swatch: () => "#2b8a3e", dot: true, fetch: "live", every: 60, click: "here",
    paint: () => ({ "circle-color": "#2b8a3e", "circle-radius": zoomWidth(2.4, 5), "circle-opacity": 0.9,
      "circle-stroke-color": cssVar("--ink"), "circle-stroke-width": 0.8 }),
  },
  companies: {
    legend: "Big company head office", swatch: () => cssVar("--series-6"), dot: true,
    paint: () => ({
      "circle-color": cssVar("--series-6"), "circle-opacity": 0.75, "circle-radius": zoomWidth(2.2, 5),
      "circle-stroke-color": cssVar("--surface"), "circle-stroke-width": 0.6,
    }),
  },
};

// Features of a "window" or "live" layer for the area in view.
export function windowData(id: string, b: { west: number; south: number; east: number; north: number }, zoom: number) {
  const r = (v: number) => Math.round(v * 100) / 100;
  const q = `west=${r(b.west)}&south=${r(b.south)}&east=${r(b.east)}&north=${r(b.north)}`;
  const path = id === "live_planes" ? `/live/planes?${q}` : id === "live_ships" ? `/live/ships?${q}`
    : id === "live_military" ? `/live/military-planes?${q}`
    : id === "conflict_events" ? `/osint/events?${q}&${fightingQuery()}&limit=${zoom < 3 ? 2500 : 6000}`
    : id === "front_line" ? "/osint/front/russia_ukraine"
    : `/geo/${encodeURIComponent(id)}?${q}&zoom=${zoom.toFixed(1)}`;
  return get<GeoJSON.FeatureCollection & { error?: string; note?: string; count?: number; capped?: boolean; loaded?: boolean }>(path);
}

const num = (v: unknown, d = 0) => (typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: d }) : "");

// The text shown when the pointer is over one of a layer's features.
export function layerLabel(layer: string, p: Record<string, unknown>): string {
  const esc = (v: unknown) => String(v ?? "").replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`);
  const more = "<br/><span class=\"muted\">Click for what depends on it</span>";
  if (layer === "rivers") return `${p.name ? `<b>${esc(p.name)}</b> (river)` : "<b>River</b>"}${typeof p.flow === "number" ? `<br/>${num(p.flow, p.flow < 10 ? 1 : 0)} m³/s at the end of this stretch` : ""}${typeof p.length === "number" ? ` · ${num(p.length)} km` : ""}`;
  if (layer === "basins") return `<b>${esc(p.name ?? "River basin")}</b><br/>${num(p.area)} km²${typeof p.flow === "number" ? ` · ${num(p.flow)} m³/s` : ""}`
    + `${p.transboundary ? "<br/>Shared by several countries" : ""}<br/><span class="muted">Click for its countries and people</span>`;
  if (layer === "waterways") return `<b>${esc(p.name)}</b> (waterway)${p.cemt ? `<br/>Class ${esc(p.cemt)}` : ""}${p.to ? `<br/>Ships go to ${esc(p.to)}` : ""}`;
  if (layer === "cables") return `<b>${esc(p.name)}</b> (undersea cable)${p.rfs ? `<br/>In service ${esc(p.rfs)}` : ""}${p.planned ? " (planned)" : ""}${more}`;
  if (layer === "gas_pipelines" || layer === "oil_pipelines") return `<b>${esc(p.name)}</b> (${layer === "gas_pipelines" ? "gas" : "oil"} pipeline)`
    + `${p.status ? `<br/>${esc(p.status)}` : ""}${more}`;
  if (layer === "eez_lines") return `<b>${esc(p.name)}</b><br/>${p.outer ? "Outer limit of an economic zone" : esc(p.type || "Border between economic zones")}`
    + `${p.eez1 && p.eez2 ? `<br/>${esc(p.eez1)} | ${esc(p.eez2)}` : ""}${typeof p.km === "number" ? ` · ${num(p.km)} km` : ""}`;
  if (layer === "airspace") return p.kind === "country"
    ? `<b>${esc(p.name)}</b><br/>Covered by its air traffic control${Array.isArray(p.firs) && p.firs.length ? `<br/><span class="muted">${esc((p.firs as string[]).slice(0, 6).join(", "))}${p.firs.length > 6 ? "…" : ""}</span>` : ""}`
    : `<b>${esc(p.name)}</b> (${esc(p.icao)})${p.country ? `<br/>${esc(p.country)}` : ""}<br/><span class="muted">Flight information region or sector (VATSIM)</span>`;
  if (layer === "shipping_lanes") return `<b>${esc(p.name)}</b>`;
  if (layer === "ports") return `<b>${esc(p.name)}</b> (port)${typeof p.calls === "number" ? `<br/>${num(p.calls)} ship calls in ${esc(p.year)}` : ""}`
    + (p.top ? `<br/>Biggest trade: ${esc(p.top)}` : "");
  if (layer === "port_pressure") return `<b>${esc(p.name)}</b> (port)${typeof p.vs_normal === "number" ? `<br/>Last 4 weeks: ${p.vs_normal > 0 ? "+" : ""}${num(p.vs_normal)}% against normal` : "<br/>Too few ships to judge"}`
    + `${typeof p.weekly === "number" ? `<br/>Usually ${num(p.weekly)} ships a week` : ""}${p.as_of ? `<br/><span class="muted">Weeks to ${esc(p.as_of)}</span>` : ""}`;
  if (layer === "ports_all") return `<b>${esc(p.name)}</b> (port)${p.size ? `<br/>Harbour: ${esc(p.size)}` : ""}${typeof p.depth === "number" ? ` · channel ${p.depth} m` : ""}`;
  if (layer === "chokepoints") return `<b>${esc(p.name)}</b>${typeof p.daily === "number" ? `<br/>${num(p.daily, 1)} ships a day${p.year ? ` in ${esc(p.year)}` : ""}` : ""}`
    + "<br/><span class=\"muted\">Click for the countries on its shores</span>";
  if (layer === "airports") return `<b>${esc(p.name)}</b>${p.iata ? ` (${esc(p.iata)})` : ""}${p.city ? `<br/>${esc(p.city)}` : ""}`;
  if (layer === "cable_landings") return `<b>${esc(p.name)}</b> (cable landing)`;
  if (layer === "lng_terminals") return `<b>${esc(p.name)}</b> (LNG ${esc(String(p.facility ?? "").toLowerCase() || "terminal")})`
    + `${p.status ? `<br/>${esc(p.status)}` : ""}${typeof p.capacity === "number" ? ` · ${p.capacity} Mt a year` : ""}`;
  if (layer === "heritage_sites") return `<b>${esc(p.name)}</b><br/>World Heritage (${esc(p.type)}), ${esc(p.year)}${p.danger ? "<br/><b>In danger</b>" : ""}`;
  if (layer === "visited_sites") return `<b>${esc(p.name)}</b><br/>${num(p.visitors)} visitors${p.year ? ` (${esc(p.year)})` : ""}`;
  if (layer === "live_planes") return `<b>${esc(p.callsign ?? p.id)}</b> (${esc(p.country)})${typeof p.altitude_m === "number" ? `<br/>${num(p.altitude_m)} m` : ""}`
    + (typeof p.speed_kmh === "number" ? ` · ${p.speed_kmh} km/h` : "");
  if (layer === "live_ships") return `<b>${esc(p.name ?? `Ship ${p.id}`)}</b>${typeof p.speed_kn === "number" ? `<br/>${p.speed_kn} knots` : ""}`
    + (p.sanctioned ? "<br/><b style=\"color:#c92a2a\">On a sanctions list</b> (OpenSanctions)" : "");
  if (layer === "conflict_events") {
    const k = EVENT_KIND[String(p.kind)];
    return `<b>${esc(k?.label ?? p.kind)}</b> · ${esc(p.day)}<br/>${esc(p.place ?? "")}${p.admin1 && p.admin1 !== p.place ? `, ${esc(p.admin1)}` : ""}`
      + (typeof p.deaths === "number" && p.deaths > 0 ? `<br/>${num(p.deaths)} killed` : "")
      + `<br/><span class="muted">${esc(SOURCE_NAME[String(p.source)] ?? p.source)} · click for more and Look closer links</span>`;
  }
  if (layer === "front_line") return `<b>Held by Russia</b> on ${esc(p.day)}${typeof p.area_km2 === "number" ? `<br/>${num(p.area_km2)} km²` : ""}<br/><span class="muted">DeepStateMap</span>`;
  if (layer === "live_military") return `<b>${esc(p.callsign || p.id)}</b>${p.type ? ` (${esc(p.type)})` : ""}${typeof p.altitude_m === "number" ? `<br/>${num(p.altitude_m)} m` : ""}`
    + (typeof p.speed_kmh === "number" ? ` · ${p.speed_kmh} km/h` : "") + "<br/><span class=\"muted\">Military (adsb.lol)</span>";
  if (layer === "volcanoes") {
    const last = typeof p.last === "number" ? (p.last < 0 ? `${-p.last} BCE` : String(p.last)) : "unknown";
    return `<b>${esc(p.name)}</b> (volcano)<br/>${esc(p.type ?? "")}${p.country ? `, ${esc(p.country)}` : ""}<br/>Last eruption: ${last}`
      + (typeof p.elevation === "number" ? ` · ${Math.round(p.elevation)} m` : "");
  }
  if (layer === "earthquakes") {
    return `<b>Magnitude ${esc(p.mag)}</b> · ${esc(p.date)}<br/>${esc(p.name)}`
      + (typeof p.depth === "number" ? `<br/>Depth ${p.depth} km` : "") + (p.tsunami ? " · tsunami" : "");
  }
  if (layer === "major_cities") {
    const pop = typeof p.population === "number" ? `${(p.population / 1e6).toFixed(p.population >= 1e7 ? 0 : 1)} million people` : "";
    return `<b>${esc(p.name)}</b>${p.capital ? " (capital)" : ""}<br/>${pop}<br/><span class="muted">Click for the city page</span>`;
  }
  if (layer === "city_stress") {
    return `<b>${esc(p.name)}</b>${p.country ? `, ${esc(p.country)}` : ""}<br/>City stress ${typeof p.score === "number" ? p.score.toFixed(1) : "–"} of 10`
      + ` · ${esc(p.rank)} of ${esc(p.of)}${p.parts !== 5 ? ` (${esc(p.parts)} of 5 parts)` : ""}<br/><span class="muted">Click for the city page</span>`;
  }
  if (layer === "storm_tracks") {
    const cat = typeof p.cat === "number" ? (p.cat > 0 ? `category ${p.cat}` : "tropical storm") : "";
    return `<b>${esc(p.name)}</b><br/>${esc(p.basin)} · strongest: ${cat}${typeof p.wind === "number" ? ` (${p.wind} knots)` : ""}${p.land ? "<br/>Reached land" : ""}`;
  }
  if (layer === "fires_now" || layer === "fires_week") return `<b>${num(p.n)} fire${p.n === 1 ? "" : "s"}</b> seen here${p.date ? ` (latest ${esc(p.date)})` : ""}`
    + (typeof p.frp === "number" ? `<br/>Fire power ${num(p.frp)} MW` : "");
  if (layer === "heat_now") return `<b>${esc(p.name)}</b><br/>Forecast high ${esc(p.peak)} °C on ${esc(p.day)}<br/>${esc(p.days)} of the next 5 days at 35 °C or more`;
  if (layer === "coral_alerts") return `<b>${esc(p.name)}</b><br/>Coral bleaching: ${esc(p.label)} (highest in the last 7 days)`;
  if (layer === "nz_wastewater") return `<b>${esc(p.name)}</b>${p.region ? `, ${esc(p.region)}` : ""}<br/>${num(p.value)} virus copies per person per day, week to ${esc(p.week)}`
    + `${typeof p.change === "number" ? `<br/>${p.change > 0 ? "+" : ""}${p.change}% on the month before` : ""}${typeof p.population === "number" ? `<br/>Serves ${num(p.population)} people` : ""}`
    + `${p.recent ? "" : "<br/><span class=\"muted\">No recent samples</span>"}`;
  if (layer === "power_plants") return `<b>${esc(p.name)}</b><br/>${esc(p.fuel)}${typeof p.mw === "number" ? `, ${num(p.mw)} MW` : ""}`
    + `${p.year ? ` · built ${esc(p.year)}` : ""}${p.owner ? `<br/>${esc(p.owner)}` : ""}`;
  if (layer === "power_links") return `<b>${esc(p.from_name)} → ${esc(p.to_name)}</b>, ${esc(p.year)}<br/>${num(p.sent)} GWh sent, `
    + `${num(p.back)} GWh back<br/>Net ${num(p.net)} GWh to ${esc(p.to_name)}`;
  if (layer === "railways") return `<b>Railway</b>${p.rank === 1 ? " (main line)" : ""}`;
  if (layer === "power_lines") return `<b>Power line</b>${p.rank === 1 ? " (mapped)" : " (predicted)"}${p.kv ? `<br/>${esc(p.kv)} kV` : ""}`;
  if (layer === "storms_active") {
    const cat = typeof p.cat === "number" ? (p.cat > 0 ? `category ${p.cat}` : "tropical storm") : "";
    return `<b>${esc(p.name)}</b> (active)<br/>${esc(p.basin)} · strongest so far: ${cat}${typeof p.wind === "number" ? ` (${p.wind} knots)` : ""}`
      + (p.last ? `<br/>Last position ${esc(p.last)} UTC` : "");
  }
  if (layer === "transit_lines") return `<b>${esc(p.name)}</b> (line)`;
  if (layer === "tide_gauges") {
    const t = (v: unknown) => (typeof v === "number" ? `${v > 0 ? "+" : ""}${v.toFixed(1)} mm a year` : "not enough years");
    return `<b>${esc(p.name)}</b> (tide gauge)<br/>${esc(p.from)}-${esc(p.to)}: ${t(p.trend)}<br/>Last 30 years: ${t(p.trend30)}`;
  }
  if (layer === "hospitals") {
    return `<b>${esc(p.name)}</b> (hospital)${typeof p.beds === "number" ? `<br/>${p.beds.toLocaleString()} beds` : "<br/>Beds not given"}`;
  }
  if (layer === "military_bases") {
    return `<b>${esc(p.name)}</b> (${esc(p.type ?? "military base")})${p.operator ? `<br/>Run by ${esc(p.operator)}` : ""}`;
  }
  if (layer === "transit_stations") return `<b>${esc(p.name)}</b> (station)${p.system ? `<br/>${esc(p.system)}` : ""}`;
  if (layer === "universities") {
    return `<b>${esc(p.name)}</b> (university)${typeof p.students === "number" ? `<br/>${Math.round(p.students).toLocaleString()} students` : ""}`;
  }
  if (layer === "companies") {
    const rev = typeof p.revenue === "number" ? `<br/>Revenue ${esc(p.currency)} ${(p.revenue / 1e9).toFixed(1)} billion${p.revenue_year ? ` (${p.revenue_year})` : ""}` : "";
    return `<b>${esc(p.name)}</b> (company)${rev}${p.industry ? `<br/>${esc(p.industry)}` : ""}`;
  }
  if (layer === "antarctic_stations") {
    return `<b>${esc(p.name)}</b> (research station)${p.operator ? `<br/>${esc(p.operator)}` : ""}${p.country ? ` · ${esc(p.country)}` : ""}`
      + (p.opened ? `<br/>Opened ${esc(p.opened)}` : "");
  }
  if (layer === "antarctic_claims") return `<b>${esc(p.name)}</b>${p.overlap ? "<br/>Overlaps another claim" : ""}`;
  if (layer === "points") {
    return `<b>${esc(p.name)}</b>${p.capital ? " (capital)" : ""}${p.text ? `<br/>${esc(p.text)}` : ""}`;
  }
  if (layer === "active_faults") {
    return `<b>${esc(p.name)}</b> (fault)${p.slip ? `<br/>${esc(p.slip)}` : ""}${typeof p.rate === "number" ? ` · ${p.rate} mm a year` : ""}`;
  }
  return `<b>${esc(p.name)}</b>${p.type ? `<br/>${esc(p.type)}` : ""}`;
}

// The card a click on a "here" feature opens: a few lines about it and links to look closer.
export function hereCard(layer: string, p: Record<string, unknown>, at: { lng: number; lat: number }):
  { title: string; lines: string[]; links: { label: string; href: string; hint: string }[] } {
  if (layer === "live_military") {
    const hex = String(p.id ?? "");
    return { title: String(p.callsign || hex || "Military plane"),
      lines: [p.type ? `Type ${p.type}` : "", typeof p.altitude_m === "number" ? `${num(p.altitude_m)} m up` : "",
        typeof p.speed_kmh === "number" ? `${p.speed_kmh} km/h` : "", "Seen by adsb.lol's volunteer receivers. Many military flights switch their transponder off, so this is never the whole picture."].filter(Boolean),
      links: [{ label: "Follow it on adsb.lol", hint: "The plane's track on the volunteer map", href: `https://globe.adsb.lol/?icao=${encodeURIComponent(hex)}` },
        ...lookCloser(at.lat, at.lng).slice(0, 1)] };
  }
  const k = EVENT_KIND[String(p.kind)];
  return {
    title: `${k?.label ?? p.kind} · ${p.day}`,
    lines: [
      [p.place, p.admin1].filter(Boolean).filter((v, i, a) => a.indexOf(v) === i).join(", "),
      typeof p.deaths === "number" ? `${num(p.deaths)} killed${p.subkind ? ` · ${p.subkind}` : ""}` : String(p.subkind ?? ""),
      typeof p.actors === "string" && p.actors ? `Who: ${p.actors}` : "",
      typeof p.note === "string" ? p.note.slice(0, 400) : "",
      `Source: ${SOURCE_NAME[String(p.source)] ?? p.source}`,
    ].filter(Boolean),
    links: lookCloser(at.lat, at.lng, String(p.day ?? "")),
  };
}
