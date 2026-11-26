"use client";

// A small map in a ship's or plane's card: where it is now (a dot), the path saved or asked for
// so far (solid), and the line on to where it is going (dashed), fitted to all of them. The same
// country shapes and map detail as the big map (Settings > Map).

import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource } from "maplibre-gl";
import { useEffect, useRef } from "react";
import { addDetail, ONLINE_FONTS, quietMapErrors } from "@/lib/basemap";
import { cssVar } from "@/lib/colors";
import { countryShapes } from "@/lib/geo";
import { useSettings } from "@/lib/settings";

const ORANGE = "#f08c00";

// Every point of the lines and the dot, with longitudes moved next to the dot's so a path across
// 180° (Auckland to Los Angeles) is fitted the short way round.
function boxOf(fc: GeoJSON.FeatureCollection, at: [number, number]): [[number, number], [number, number]] {
  const pts: [number, number][] = [at];
  const add = (c: number[]) => { let lon = c[0]; while (lon - at[0] > 180) lon -= 360; while (at[0] - lon > 180) lon += 360; pts.push([lon, c[1]]); };
  for (const f of fc.features) {
    const g = f.geometry;
    if (g.type === "Point") add(g.coordinates);
    else if (g.type === "LineString") g.coordinates.forEach(add);
    else if (g.type === "MultiLineString") g.coordinates.forEach((l) => l.forEach(add));
  }
  const lons = pts.map((p) => p[0]), lats = pts.map((p) => p[1]);
  return [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]];
}

// Line coordinates moved next to the dot's longitude too, so they draw the short way round.
function near(fc: GeoJSON.FeatureCollection, lon0: number): GeoJSON.FeatureCollection {
  const fix = (c: number[]) => { let lon = c[0]; while (lon - lon0 > 180) lon -= 360; while (lon0 - lon > 180) lon += 360; return [lon, c[1]]; };
  return {
    type: "FeatureCollection",
    features: fc.features.map((f) => {
      const g = f.geometry;
      if (g.type === "Point") return { ...f, geometry: { ...g, coordinates: fix(g.coordinates) } };
      if (g.type === "LineString") return { ...f, geometry: { ...g, coordinates: g.coordinates.map(fix) } };
      if (g.type === "MultiLineString") return { ...f, geometry: { ...g, coordinates: g.coordinates.map((l) => l.map(fix)) } };
      return f;
    }),
  };
}

export default function SpotMap({ lon, lat, lines, label, height = 240 }: {
  lon: number; lat: number; lines: GeoJSON.FeatureCollection | null; label?: string; height?: number;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const ready = useRef(false);
  const settings = useSettings();
  const draw = useRef<() => void>(() => {});

  draw.current = () => {
    const m = map.current;
    if (!m || !ready.current) return;
    const fc = near(lines ?? { type: "FeatureCollection", features: [] }, lon);
    const all: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [...fc.features,
      { type: "Feature", properties: { part: "now", label: label ?? "" }, geometry: { type: "Point", coordinates: [lon, lat] } }] };
    (m.getSource("spot") as GeoJSONSource | undefined)?.setData(all);
    const box = boxOf(fc, [lon, lat]);
    const flat = box[1][0] - box[0][0] < 0.05 && box[1][1] - box[0][1] < 0.05;
    if (flat) m.jumpTo({ center: [lon, lat], zoom: 6 });
    else m.fitBounds(box, { padding: 28, maxZoom: 8, duration: 0 });
  };

  useEffect(() => {
    if (!el.current) return;
    const m = new maplibregl.Map({
      container: el.current,
      style: { version: 8, glyphs: ONLINE_FONTS, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": cssVar("--surface") } }] },
      center: [lon, lat], zoom: 4, maxZoom: 12, dragRotate: false, pitchWithRotate: false, renderWorldCopies: true,
      attributionControl: { compact: true, customAttribution: "Borders: Natural Earth" },
    });
    quietMapErrors(m);
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.current = m;
    m.on("load", async () => {
      const shapes = await countryShapes().catch(() => null);
      if (map.current !== m) return;
      if (shapes) {
        m.addSource("countries", { type: "geojson", data: shapes });
        m.addLayer({ id: "fill", type: "fill", source: "countries", paint: { "fill-color": cssVar("--no-data") } });
        m.addLayer({ id: "line", type: "line", source: "countries", paint: { "line-color": cssVar("--surface"), "line-width": 0.45 } });
      }
      m.addSource("spot", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({ id: "spot-path", type: "line", source: "spot", filter: ["==", ["get", "part"], "path"],
        paint: { "line-color": ORANGE, "line-width": 2.5, "line-opacity": 0.9 }, layout: { "line-cap": "round", "line-join": "round" } });
      m.addLayer({ id: "spot-ahead", type: "line", source: "spot", filter: ["==", ["get", "part"], "ahead"],
        paint: { "line-color": ORANGE, "line-width": 2, "line-dasharray": [2, 2], "line-opacity": 0.8 } });
      m.addLayer({ id: "spot-ends", type: "circle", source: "spot", filter: ["==", ["get", "part"], "end"],
        paint: { "circle-radius": 5, "circle-color": cssVar("--surface"), "circle-stroke-color": ORANGE, "circle-stroke-width": 2.5 } });
      m.addLayer({ id: "spot-now", type: "circle", source: "spot", filter: ["==", ["get", "part"], "now"],
        paint: { "circle-radius": 7, "circle-color": "#1864ab", "circle-stroke-color": "#fff", "circle-stroke-width": 2 } });
      ready.current = true;
      draw.current();
      if (shapes) addDetail(m, settings.base_map ?? "online").catch(() => {});
    });
    return () => { ready.current = false; m.remove(); map.current = null; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { draw.current(); }, [lon, lat, lines, label]);

  return <div ref={el} style={{ height, width: "100%", borderRadius: 6, overflow: "hidden", margin: "6px 0" }} aria-label={`Map of ${label ?? "where it is"}`} />;
}
