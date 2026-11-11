// What sits under the country colours (Settings > Maps, and the Layers panel's Background):
//   plain      nothing: the page colour, as before
//   relief     heights and sea depths, coloured and hill-shaded in the browser from AWS Terrain
//              Tiles (classic colours, grey shading only, or shading over the satellite picture)
//   satellite  Sentinel-2 cloudless by EOX
//   night      night lights (NASA Black Marble 2016 or 2012, or last night's VIIRS picture)
// Tiles come through the app's server, which serves the copies saved on this PC and fetches
// the rest online ("Saved copies first"), or straight from the sites ("Always online").
// With a picture on, the country colours turn see-through (Settings > Maps > colours over
// pictures) and countries without a figure are left clear so the picture shows.

import type * as maplibregl from "maplibre-gl";
import type { ExpressionSpecification } from "maplibre-gl";
import type { Settings } from "@/lib/api";

export type Look = Pick<Settings, "map_look" | "relief_style" | "relief_shading" | "map_colours_over" | "night_year" | "map_3d" | "map_3d_exaggeration" | "map_tiles">;

const ONLINE: Record<string, string> = {
  relief: "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
  satellite: "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{z}/{y}/{x}.jpg",
  night: "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{layer}/default/{t}/GoogleMapsCompatible_Level8/{z}/{y}/{x}.png",
};
export const ATTRIBUTION: Record<string, string> = {
  relief: "Heights: <a href=\"https://registry.opendata.aws/terrain-tiles/\">AWS Terrain Tiles</a> (SRTM, GMTED, ETOPO1)",
  satellite: "<a href=\"https://s2maps.eu\">Sentinel-2 cloudless 2020</a> by EOX (Copernicus Sentinel data 2020)",
  night: "Night lights: NASA Earth Observatory Black Marble, VIIRS (<a href=\"https://earthdata.nasa.gov/gibs\">NASA GIBS</a>)",
};
const MAXZOOM: Record<string, number> = { relief: 15, satellite: 15, night: 8 };
export const LOOK_PREFIX = "look-";

const yesterday = () => new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);

export function tileUrl(set: "relief" | "satellite" | "night", look: Pick<Look, "map_tiles" | "night_year">): string {
  if (look.map_tiles === "online") {
    if (set !== "night") return ONLINE[set];
    const [layer, t] = look.night_year === "latest" ? ["VIIRS_SNPP_DayNightBand_ENCC", yesterday()] : ["VIIRS_Black_Marble", `${look.night_year}-01-01`];
    return ONLINE.night.replace("{layer}", layer).replace("{t}", t);
  }
  const origin = typeof location !== "undefined" ? location.origin : "";
  return `${origin}/api/v1/tiles/${set}/{z}/{x}/{y}${set === "night" ? `?t=${look.night_year}` : ""}`;
}

// Height colours: sea depths in blues, then lowland green through brown to snow.
const RELIEF_COLOURS: ExpressionSpecification = ["interpolate", ["linear"], ["elevation"],
  -8000, "#0d2b4c", -5000, "#1b4a78", -2500, "#2f6ea3", -500, "#6aa6cf", -50, "#a8d1e7", -1, "#c4e2ef",
  0, "#6f9f63", 150, "#8fb878", 500, "#c7cf94", 1000, "#d9c48f", 1600, "#c49a6a", 2400, "#a07756", 3400, "#9a918a", 4800, "#f4f4f4"];
const GREY_COLOURS: ExpressionSpecification = ["interpolate", ["linear"], ["elevation"],
  -6000, "#a7b8c6", -1, "#d6e1ea", 0, "#ecebe6", 3000, "#f4f3ef"];

// Per map: whether a picture is under the colours (so the colours fade and blanks clear).
const state = new WeakMap<maplibregl.Map, { picture: boolean; over: number; detail: boolean }>();

// The country fill's opacity, from whether map detail and a picture are on.
export function refreshFill(m: maplibregl.Map, change: Partial<{ picture: boolean; over: number; detail: boolean }> = {}) {
  const st = { picture: false, over: 0.55, detail: false, ...state.get(m), ...change };
  state.set(m, st);
  if (!m.getLayer("fill")) return;
  // The map detail's water would cover the sea in the picture: clear while a picture is on.
  for (const l of m.getStyle()?.layers ?? []) if (l.id.startsWith("bm-") && l.id.endsWith("-water")) m.setPaintProperty(l.id, "fill-opacity", st.picture ? 0 : 0.9);
  const hasValue: ExpressionSpecification = ["==", ["typeof", ["get", "value"]], "number"];
  const k = st.picture ? st.over : 1;
  const stops: [number, number][] = st.detail ? [[3, 0.92], [6, 0.6], [9, 0.35], [13, 0.2]] : [[3, 1], [13, 1]];
  if (!st.picture && !st.detail) { m.setPaintProperty("fill", "fill-opacity", 1); return; }
  const expr = ["interpolate", ["linear"], ["zoom"],
    ...stops.flatMap(([z, o]) => [z, st.picture ? ["case", hasValue, o * k, 0] : o])] as unknown as ExpressionSpecification;
  m.setPaintProperty("fill", "fill-opacity", expr);
}

export function removeLook(m: maplibregl.Map) {
  if (m.getTerrain?.()) m.setTerrain(null);
  for (const l of m.getStyle()?.layers ?? []) if (l.id.startsWith(LOOK_PREFIX)) m.removeLayer(l.id);
  for (const s of Object.keys(m.getStyle()?.sources ?? {})) if (s.startsWith(LOOK_PREFIX)) m.removeSource(s);
  if (m.getLayer("bg")) m.setPaintProperty("bg", "background-color", getComputedStyle(document.documentElement).getPropertyValue("--surface").trim() || "#fff");
  refreshFill(m, { picture: false });
}

// Put the chosen picture under the country layers ("fill" must be there). Returns its attribution.
export function addLook(m: maplibregl.Map, look: Look): string | null {
  removeLook(m);
  if (!m.getLayer("fill") || look.map_look === "plain") {
    if (m.getPitch() > 0 && !look.map_3d) m.easeTo({ pitch: 0 });
    return null;
  }
  const before = "fill";
  const raster = (set: "satellite" | "night", id: string, opacity = 1) => {
    m.addSource(id, { type: "raster", tiles: [tileUrl(set, look)], tileSize: 256, maxzoom: MAXZOOM[set], attribution: ATTRIBUTION[set] });
    m.addLayer({ id, type: "raster", source: id, paint: { "raster-opacity": opacity } }, before);
  };
  const dem = (id: string) => m.addSource(id, { type: "raster-dem", tiles: [tileUrl("relief", look)], tileSize: 256, maxzoom: MAXZOOM.relief,
    encoding: "terrarium", attribution: ATTRIBUTION.relief });
  const attributions: string[] = [];
  if (look.map_look === "night") {
    m.setPaintProperty("bg", "background-color", "#05070d");
    raster("night", `${LOOK_PREFIX}night`);
    attributions.push("Night lights: NASA Black Marble / VIIRS");
  }
  if (look.map_look === "satellite" || (look.map_look === "relief" && look.relief_style === "satellite")) {
    raster("satellite", `${LOOK_PREFIX}satellite`);
    attributions.push("Satellite: Sentinel-2 cloudless by EOX");
  }
  if (look.map_look === "relief") {
    dem(`${LOOK_PREFIX}dem`);
    if (look.relief_style !== "satellite") {
      m.addLayer({ id: `${LOOK_PREFIX}colour`, type: "color-relief", source: `${LOOK_PREFIX}dem`,
        paint: { "color-relief-color": look.relief_style === "grey" ? GREY_COLOURS : RELIEF_COLOURS } }, before);
    }
    m.addLayer({ id: `${LOOK_PREFIX}shade`, type: "hillshade", source: `${LOOK_PREFIX}dem`,
      paint: { "hillshade-exaggeration": look.relief_shading, "hillshade-illumination-direction": 315,
        "hillshade-shadow-color": "#2b2a33", "hillshade-highlight-color": "#ffffff", "hillshade-accent-color": "#3d3a45" } }, before);
    attributions.push("Relief: AWS Terrain Tiles");
  }
  if (look.map_3d) {
    dem(`${LOOK_PREFIX}terrain`);
    m.setTerrain({ source: `${LOOK_PREFIX}terrain`, exaggeration: look.map_3d_exaggeration });
    m.setMaxPitch(70);
    if (m.getPitch() < 20) m.easeTo({ pitch: 50 });
  } else if (m.getPitch() > 0) m.easeTo({ pitch: 0 });
  m.setMaxZoom(Math.max(m.getMaxZoom(), look.map_look === "night" ? 8 : 12));
  refreshFill(m, { picture: true, over: look.map_colours_over });
  return attributions.join(" · ");
}
