// The world map as a globe (the Globe button on the map, or Settings > Maps > Globe).
// MapLibre draws every layer on the globe itself, so country colours, overlays, pictures
// (relief, satellite, night lights) and 3D all keep working; only the projection changes.
// The space look puts the globe in a dark sky with a blue glow, blue land and a dark sea,
// and grid lines (every 15 degrees) help show which way the globe is turned.

import * as maplibregl from "maplibre-gl";
import type { ExpressionSpecification } from "maplibre-gl";
import { cssVar } from "@/lib/colors";
import { refreshSea } from "@/lib/maplook";

export type GlobeLook = { globe: boolean; space: boolean; grid: boolean };

// The space look's colours: land with no figure, the sea, borders and grid lines.
export const SPACE = { land: "#1537d6", sea: "#06102a", border: "rgba(170, 195, 255, 0.55)", grid: "rgba(150, 180, 255, 0.28)" };

const GRID = "globe-grid";

// Lines of latitude every 15 degrees (to 75) and longitude every 15 degrees, as short steps so they curve.
function gridLines(): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];
  for (let lat = -75; lat <= 75; lat += 15) {
    const coords: [number, number][] = [];
    for (let lng = -180; lng <= 180; lng += 3) coords.push([lng, lat]);
    features.push({ type: "Feature", properties: { kind: lat === 0 ? "equator" : "lat" }, geometry: { type: "LineString", coordinates: coords } });
  }
  for (let lng = -180; lng < 180; lng += 15) {
    const coords: [number, number][] = [];
    for (let lat = -84; lat <= 84; lat += 3) coords.push([lng, lat]);
    features.push({ type: "Feature", properties: { kind: "lng" }, geometry: { type: "LineString", coordinates: coords } });
  }
  return { type: "FeatureCollection", features };
}

// The globe's size on screen. MapLibre keeps the scale at the centre's latitude the same as the
// flat map's, so its sphere is worldSize / 2 pi / cos(latitude) pixels across the middle; seen
// from the camera (which sits cameraToCenterDistance above the map's centre), the edge of the
// globe shows a little smaller than that.
const latCos = (m: maplibregl.Map) => Math.max(0.09, Math.cos((Math.min(85, Math.abs(m.getCenter().lat)) * Math.PI) / 180));
const cameraDistance = (m: maplibregl.Map) => {
  const fov = m.getVerticalFieldOfView() || 36.8699;
  return (0.5 * (m.getContainer().clientHeight || 500)) / Math.tan(((fov / 2) * Math.PI) / 180);
};
function globeRadius(m: maplibregl.Map): number {
  const R = (512 * 2 ** m.getZoom()) / (2 * Math.PI) / latCos(m);
  const d = cameraDistance(m);
  return (d * R) / Math.sqrt(d * d + 2 * d * R);
}

// The zoom at which the whole globe fits the map's height, with a little room for the glow.
export function wholeGlobeZoom(m: maplibregl.Map): number {
  const r = 0.43 * (m.getContainer().clientHeight || 500);
  const d = cameraDistance(m);
  const R = (r * r + r * Math.sqrt(r * r + d * d)) / d; // the sphere that shows r pixels across
  return Math.log2((R * 2 * Math.PI * latCos(m)) / 512);
}

// The glow round the globe in the space look: a ring drawn behind the map (the sky outside the
// globe is see-through), kept to the globe's size as you zoom. Hidden while the map is tilted,
// when the globe's middle is no longer the middle of the map.
const halos = new WeakSet<maplibregl.Map>();
function haloFollows(m: maplibregl.Map) {
  if (halos.has(m)) return;
  halos.add(m);
  const put = () => {
    const c = m.getContainer();
    if (!c.classList.contains("globe-space")) return;
    c.style.setProperty("--globe-r", `${Math.round(globeRadius(m))}px`);
    c.classList.toggle("globe-tilted", m.getPitch() > 3);
  };
  m.on("move", put);
  m.on("resize", put);
  put();
}

/** The no-figure colour for countries on this map. */
export function noDataColour(look: GlobeLook): string {
  return look.globe && look.space ? SPACE.land : cssVar("--no-data");
}

// Switch the map between flat and globe, with the space look and grid lines when chosen.
// "fill" and "line" (the country layers) must be on the map.
// fit: show the whole globe on turning to it; flatBounds: the world to show on turning back to flat.
export function applyGlobe(m: maplibregl.Map, look: GlobeLook, opts: { fit?: boolean; flatBounds?: maplibregl.LngLatBoundsLike } = {}) {
  const was = m.getProjection()?.type === "globe";
  m.setProjection({ type: look.globe ? "globe" : "mercator" });
  const space = look.globe && look.space;
  m.getContainer().classList.toggle("globe-space", space);
  m.getContainer().classList.toggle("globe-on", look.globe);
  // The glow round the globe fades out as you zoom in close.
  m.setSky(look.globe ? {
    "sky-color": space ? SPACE.sea : cssVar("--surface"),
    "horizon-color": space ? "#1d3f9a" : cssVar("--surface"),
    "sky-horizon-blend": 0.6,
    "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 1, 5, 1, 8, 0] as unknown as ExpressionSpecification,
  } : undefined as unknown as maplibregl.SkySpecification);
  // Without the space look the sea takes the map's water colour, so the globe's edge shows against the page.
  refreshSea(m, space ? SPACE.sea : look.globe ? cssVar("--map-water") : null);
  if (space) haloFollows(m);
  m.getContainer().style.setProperty("--globe-r", `${Math.round(globeRadius(m))}px`);
  if (m.getLayer("line")) m.setPaintProperty("line", "line-color", space ? SPACE.border : cssVar("--surface"));
  if (m.getLayer(GRID)) m.removeLayer(GRID);
  if (m.getSource(GRID)) m.removeSource(GRID);
  if (look.globe && look.grid) {
    m.addSource(GRID, { type: "geojson", data: gridLines() });
    // Just over the country colours, under the borders and everything else.
    m.addLayer({ id: GRID, type: "line", source: GRID,
      paint: { "line-color": space ? SPACE.grid : cssVar("--muted"), "line-width": ["match", ["get", "kind"], "equator", 1, 0.6],
        "line-opacity": space ? 1 : 0.35 } }, m.getLayer("line") ? "line" : undefined);
  }
  // Turning to the globe from a zoomed-out flat map: show the whole globe, filling the map's height.
  if (opts.fit && look.globe && !was) {
    const z = wholeGlobeZoom(m);
    if (m.getZoom() < z + 0.3) m.easeTo({ zoom: z, duration: 600 });
  }
  // ...and back to flat from the whole globe: the whole world again, as the flat map opens.
  if (opts.flatBounds && !look.globe && was && m.getZoom() < wholeGlobeZoom(m) + 0.5) m.fitBounds(opts.flatBounds, { duration: 0 });
}

// The Globe / Flat button under the zoom buttons. get says whether the globe is on now; set changes it.
export function addGlobeButton(m: maplibregl.Map, get: () => boolean, set: (on: boolean) => void): (on: boolean) => void {
  const box = document.createElement("div");
  box.className = "maplibregl-ctrl maplibregl-ctrl-group";
  const b = document.createElement("button");
  b.type = "button";
  b.className = "globe-btn";
  b.innerHTML = '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><circle cx="10" cy="10" r="7.2" fill="none" stroke="currentColor" stroke-width="1.5"/>'
    + '<ellipse cx="10" cy="10" rx="3.2" ry="7.2" fill="none" stroke="currentColor" stroke-width="1.2"/>'
    + '<path d="M3 10 H17 M4.2 6.2 H15.8 M4.2 13.8 H15.8" stroke="currentColor" stroke-width="1.1" fill="none"/></svg>';
  const show = (on: boolean) => {
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", String(on));
    b.title = on ? "Globe on: click for the flat map (drag to spin the globe)" : "Show the world as a globe";
    b.setAttribute("aria-label", on ? "Flat map" : "Globe");
  };
  show(get());
  b.onclick = () => set(!get());
  box.appendChild(b);
  m.addControl({ onAdd: () => box, onRemove: () => box.remove() }, "top-right");
  return show;
}
