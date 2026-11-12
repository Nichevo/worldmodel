"use client";

import * as maplibregl from "maplibre-gl";
import type { ExpressionSpecification, GeoJSONSource } from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { sparklineSvg } from "@/lib/charts";
import { cssVar, divergingRamp, sequentialRamp } from "@/lib/colors";
import { compact, formatValue } from "@/lib/format";
import type { CameraBus } from "@/lib/camera";
import { arc, countryCentres, countryShapes } from "@/lib/geo";
import { get } from "@/lib/api";
import { LAYER_STYLE, layerData, layerLabel, windowData } from "@/lib/layers";
import { addDetail, baseMapStatus, maxZoomFor, removeDetail } from "@/lib/basemap";
import { addLook, removeLook } from "@/lib/maplook";
import { useSettings } from "@/lib/settings";

// MapLibre's worker file, copied into public/ on npm install (scripts/copy-maplibre-worker.mjs).
if (typeof window !== "undefined") maplibregl.setWorkerUrl(`/maplibre/maplibre-gl-worker.mjs?v=${maplibregl.getVersion()}`);

type Value = { entity_id: string; value: number; status: string };
export type PickEvent = { shift: boolean; double: boolean; lngLat: [number, number] };
// React content drawn on the map at a place, moving with it (popups).
export type Overlay = { key: string; lng: number; lat: number; node: React.ReactNode };
// Every country's values over the years, for a trend line in the hover tooltip.
export type Spark = { years: number[]; rows: Record<string, (number | null)[]>; upTo: number };
type Props = {
  values: Value[];
  unit: string;
  decimals: number;
  diverging: boolean;
  // A click on a country. With doubleClick, a single click waits a moment so a
  // double click can be told apart (and the map no longer zooms on double click).
  onPick: (iso3: string, e: PickEvent) => void;
  doubleClick?: boolean;
  overlays?: Overlay[];
  spark?: Spark | null;
  onMap?: (m: maplibregl.Map | null) => void; // for pictures of the map
  selected?: string[];
  fill?: boolean; // fill the parent's height instead of the fixed page height
  scale?: Scale; // a colour scale shared with other maps; default: this map's own
  hovered?: string | null; // a country hovered in a linked panel
  onHover?: (iso3: string | null) => void;
  camera?: { bus: CameraBus; id: string; group: string } | null; // linked map position
  layers?: string[]; // overlays to draw over the countries (ids in the layers table)
  points?: MapPoint[]; // places to mark (cities on the Cities page), sized by size
  fitPoints?: boolean; // zoom to the points whenever they change
  pointsTop?: number; // the size drawn biggest (default the biggest point): fixed over years, so growth shows
  // A click on a city dot (the points, or the "Major cities" layer); default: open the city's page.
  onCity?: (cityId: string) => void;
  lines?: MapLine[]; // routes between countries (trade on the Sectors page), width by value
  layerFilter?: Record<string, unknown[] | null>; // a MapLibre filter per overlay (storm tracks by year)
  // Picture tiles under the countries (sea temperatures on the Climate page), and boxes drawn on top.
  // over: drawn above the country colours (climate zones, smoke) rather than under them; several may be given.
  raster?: RasterTiles | RasterTiles[] | null;
  boxes?: { name: string; west: number; south: number; east: number; north: number }[];
  // Countries outlined in a colour (CrisisWatch's month), with a line for the hover text.
  outlines?: MapOutline[];
  // Markers at places (events, news), solid or hollow, with hover text; a click opens href.
  marks?: MapMark[];
  // Extra legend entries for outlines and markers.
  legend?: { label: string; color: string; shape: "dot" | "ring" | "outline" }[];
  hideScale?: boolean; // colours stand for categories, so the number legend would mislead
  // Shapes drawn over the countries (borders of past states on the Long history page): each
  // feature's properties give color, opacity (0-1), label (hover HTML), sort (higher on top), key.
  areas?: { key: string; data: GeoJSON.FeatureCollection } | null;
  onArea?: (key: string) => void; // a click on one of the areas
  // Routes as dated stops joined by straight lines (voyages), with a dot at each stop.
  paths?: MapPath[];
  pictures?: boolean; // relief, satellite or night lights under the colours when chosen (Settings > Maps); off for small maps
};

export type RasterTiles = { tiles: string; attribution: string; maxzoom?: number; over?: boolean; opacity?: number };

export type MapPath = { key: string; color: string; label: string; stops: { lng: number; lat: number; label: string }[] };

export type MapOutline = { entity: string; color: string; label: string };
export type MapMark = { key: string; lng: number; lat: number; color: string; hollow?: boolean; r?: number; opacity?: number; label: string; href?: string };

export type MapLine = { from: string; to: string; value: number; text?: string };

export type MapPoint = { id: string; name: string; lng: number; lat: number; size: number; text?: string; capital?: boolean; color?: string };

export type Scale = { breaks: number[]; colors: string[] };

// Seven classes at quantiles of this year's values; a diverging indicator gets
// three classes each side of zero (red below, blue above) so the sign reads at a glance.
export function makeScale(values: number[], diverging: boolean): Scale {
  const sorted = [...values].sort((a, b) => a - b);
  const q = (p: number) => sorted[Math.min(sorted.length - 1, Math.max(0, Math.floor(p * (sorted.length - 1))))];
  if (!sorted.length) return { breaks: [], colors: [] };
  if (diverging) {
    const neg = sorted.filter((v) => v < 0);
    const pos = sorted.filter((v) => v > 0);
    const at = (arr: number[], p: number) => arr.length ? arr[Math.floor(p * (arr.length - 1))] : 0;
    const ramp = divergingRamp();
    const breaks = [at(neg, 0.33), at(neg, 0.67), 0, at(pos, 0.33), at(pos, 0.67)];
    return strictlyIncreasing(breaks, [...ramp.slice(0, 3), ...ramp.slice(4)]);
  }
  return strictlyIncreasing([1, 2, 3, 4, 5, 6].map((i) => q(i / 7)), sequentialRamp());
}

// MapLibre's step expression needs strictly increasing stops; drop repeats
// (few distinct values, or no values on one side of zero) with their colours.
function strictlyIncreasing(breaks: number[], colors: string[]): Scale {
  const out: Scale = { breaks: [], colors: [colors[0]] };
  breaks.forEach((b, i) => {
    if (!out.breaks.length || b > out.breaks[out.breaks.length - 1]) {
      out.breaks.push(b);
      out.colors.push(colors[i + 1]);
    }
  });
  return out;
}

function colorExpression(scale: Scale): ExpressionSpecification | string {
  if (!scale.breaks.length) return scale.colors[0] ?? cssVar("--no-data");
  const steps: (number | string)[] = [scale.colors[0]];
  scale.breaks.forEach((b, i) => steps.push(b, scale.colors[i + 1]));
  return ["case", ["has", "value"], ["step", ["get", "value"], ...steps] as unknown as ExpressionSpecification,
    cssVar("--no-data")] as ExpressionSpecification;
}

export default function WorldMap({
  values, unit, decimals, diverging, onPick, selected = [], fill = false, scale: shared, hovered = null, onHover, camera = null,
  doubleClick = false, overlays = [], spark = null, onMap, layers = [], points, fitPoints = false, pointsTop, onCity, lines, layerFilter,
  raster = null, boxes = [], outlines, marks, legend = [], hideScale = false, areas = null, onArea, paths,
  pictures = true,
}: Props) {
  const areaPick = useRef(onArea);
  areaPick.current = onArea;
  // A clicked river, basin, cable, pipeline or chokepoint: its card and the countries that rely on it.
  const [info, setInfo] = useState<FeatureInfo | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const featurePick = useRef<(layer: string, p: Record<string, unknown>) => void>(() => {});
  featurePick.current = (layer, p) => {
    const st = LAYER_STYLE[layer];
    if (st?.click === "chokepoint") {
      setInfo({ layer, title: String(p.name ?? "Chokepoint"), loading: true });
      get<{ countries: { id: string; name: string }[]; note?: string }>(`/depends/chokepoints/${encodeURIComponent(String(p.name ?? ""))}`)
        .then((d) => setInfo({ layer, title: String(p.name), countries: d.countries, lines: [d.note ?? ""] }))
        .catch(() => setInfo(null));
      return;
    }
    setInfo({ layer, title: String(p.name ?? "…"), loading: true });
    get<GeoCard>(`/geo/${layer}/${encodeURIComponent(String(p.id ?? ""))}`).then((d) => setInfo(cardOf(layer, d))).catch(() => setInfo(null));
  };
  const outlineText = useRef<Map<string, string>>(new Map());
  outlineText.current = new Map((outlines ?? []).map((o) => [o.entity, o.label]));
  const cityPick = useRef(onCity);
  cityPick.current = onCity;
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const onLoad = useRef<(() => void)[]>([]); // work waiting for the country layers
  const geo = useRef<GeoJSON.FeatureCollection | null>(null);
  const pick = useRef(onPick);
  pick.current = onPick;
  const settings = useSettings();
  const { base_map: baseMap, map_centre: mapCentre } = settings;
  const look = {
    map_look: pictures ? settings.map_look : "plain", relief_style: settings.relief_style, relief_shading: settings.relief_shading,
    map_colours_over: settings.map_colours_over, night_year: settings.night_year, land_cover_year: settings.land_cover_year, map_3d: pictures && settings.map_3d,
    map_3d_exaggeration: settings.map_3d_exaggeration, map_tiles: settings.map_tiles,
  } as const;
  const lookKey = JSON.stringify(look);
  const hover = useRef(onHover);
  hover.current = onHover;
  const dbl = useRef(doubleClick);
  dbl.current = doubleClick;
  const sparkRef = useRef(spark);
  sparkRef.current = spark;

  const own = useMemo(() => makeScale(values.map((v) => v.value), diverging), [values, diverging]);
  const scale = shared ?? own;
  const byIso = useMemo(() => new Map(values.map((v) => [v.entity_id, v])), [values]);

  useEffect(() => {
    if (!el.current) return;
    const m = new maplibregl.Map({
      container: el.current,
      style: {
        version: 8,
        sources: {},
        layers: [{ id: "bg", type: "background", paint: { "background-color": cssVar("--surface") } }],
      },
      // Fit the inhabited world to whatever size the map's box is: Europe and Africa in the
      // middle, or the Pacific (the same span moved half way round, New Zealand near the middle).
      bounds: mapCentre === "atlantic" ? [[-170, -56], [180, 78]] : [[10, -56], [360, 78]],
      minZoom: -1, // small boxes (half-width cards, phones) can still show the whole world
      maxZoom: 7,
      attributionControl: { compact: true, customAttribution: "Borders: Natural Earth" },
      renderWorldCopies: true, // drag round the globe without running off the edge
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.current = m;
    onMap?.(m);
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 });

    m.on("load", async () => {
      geo.current = await countryShapes();
      m.addSource("countries", { type: "geojson", data: geo.current!, promoteId: "iso3" });
      m.addLayer({ id: "fill", type: "fill", source: "countries", paint: { "fill-color": cssVar("--no-data") } });
      m.addLayer({
        id: "line", type: "line", source: "countries",
        paint: { "line-color": cssVar("--surface"), "line-width": 0.6 },
      });
      m.addLayer({
        id: "hover", type: "line", source: "countries",
        paint: {
          "line-color": cssVar("--ink"),
          "line-width": ["case", ["any", ["boolean", ["feature-state", "hover"], false], ["boolean", ["feature-state", "linked"], false]], 1.5, 0],
        },
      });
      m.addLayer({
        id: "selected", type: "line", source: "countries", filter: ["in", ["get", "iso3"], ["literal", []]],
        paint: { "line-color": cssVar("--ink"), "line-width": 2.2 },
      });
      if (map.current !== m) return; // removed while the shapes loaded
      onLoad.current.splice(0).forEach((f) => {
        try { f(); } catch (e) { console.warn("map update skipped", e); }
      });
    });
    // MapLibre only tracks window resizes; panels resize on their own.
    const ro = new ResizeObserver(() => m.resize());
    ro.observe(el.current);

    // The overlay feature under the pointer, if any (a few pixels' slack for thin lines and small dots).
    const overlayAt = (pt: maplibregl.Point) => {
      const ids = [...Object.keys(LAYER_STYLE), "points", "lines", "marks", "paths", "pathstops", "areas"].map((k) => `ov-${k}`).filter((id) => m.getLayer(id));
      if (!ids.length) return null;
      const f = m.queryRenderedFeatures([[pt.x - 4, pt.y - 4], [pt.x + 4, pt.y + 4]], { layers: ids })[0];
      if (f && ["ov-lines", "ov-marks", "ov-paths", "ov-pathstops", "ov-areas"].includes(f.layer.id)) return String((f.properties as { label?: string }).label || "") || null;
      return f ? layerLabel(f.layer.id.slice(3), f.properties as Record<string, unknown>) : null;
    };
    // The city dot under the pointer, if any: its city id.
    const cityAt = (pt: maplibregl.Point): string | null => {
      const ids = ["ov-points", "ov-major_cities"].filter((id) => m.getLayer(id));
      if (!ids.length) return null;
      const f = m.queryRenderedFeatures([[pt.x - 4, pt.y - 4], [pt.x + 4, pt.y + 4]], { layers: ids })[0];
      const id = f?.properties?.city;
      return typeof id === "string" ? id : null;
    };
    m.on("click", (e) => {
      const clickable = Object.entries(LAYER_STYLE).filter(([, st]) => st.click).map(([k]) => `ov-${k}`).filter((id) => m.getLayer(id));
      if (clickable.length) {
        const f = m.queryRenderedFeatures([[e.point.x - 4, e.point.y - 4], [e.point.x + 4, e.point.y + 4]], { layers: clickable })[0];
        if (f) { featurePick.current(f.layer.id.slice(3), f.properties as Record<string, unknown>); return; }
      }
      if (m.getLayer("ov-marks")) {
        const f = m.queryRenderedFeatures([[e.point.x - 4, e.point.y - 4], [e.point.x + 4, e.point.y + 4]], { layers: ["ov-marks"] })[0];
        const href = f?.properties?.href;
        if (typeof href === "string" && href) {
          if (/^https?:/.test(href)) window.open(href, "_blank", "noopener");
          else window.location.assign(href);
          return;
        }
      }
      if (m.getLayer("ov-areas") && areaPick.current) {
        const f = m.queryRenderedFeatures(e.point, { layers: ["ov-areas"] })[0];
        const key = f?.properties?.key;
        if (typeof key === "string" && key) { areaPick.current(key); return; }
      }
      const id = cityAt(e.point);
      if (!id) return;
      if (cityPick.current) cityPick.current(id);
      else window.location.assign(`/city/${encodeURIComponent(id)}`);
    });
    let onOverlay = false;
    m.on("mousemove", (e) => {
      const label = overlayAt(e.point);
      if (label) {
        onOverlay = true;
        popup.setLngLat(e.lngLat).setHTML(label).addTo(m);
      } else if (onOverlay) {
        onOverlay = false;
        if (!m.queryRenderedFeatures(e.point, { layers: ["fill"] }).length) popup.remove();
      }
    });

    let hovered: string | number | undefined;
    m.on("mousemove", "fill", (e) => {
      const f = e.features?.[0];
      if (!f || overlayAt(e.point)) { if (f && cityAt(e.point)) m.getCanvas().style.cursor = "pointer"; return; }
      if (f.id !== hovered) hover.current?.(f.id === undefined ? null : String(f.id));
      if (hovered !== undefined) m.setFeatureState({ source: "countries", id: hovered }, { hover: false });
      hovered = f.id;
      if (hovered !== undefined) m.setFeatureState({ source: "countries", id: hovered }, { hover: true });
      m.getCanvas().style.cursor = "pointer";
      const p = f.properties as { name: string; iso3: string; value?: number; status?: string; label?: string };
      const sp = sparkRef.current;
      const line = sp && sp.rows[p.iso3] ? sparklineSvg(sp.years, sp.rows[p.iso3], sp.upTo, cssVar("--series-1")) : "";
      popup.setLngLat(e.lngLat)
        .setHTML(`<b>${p.name}</b><br/>${p.label ?? "no data"}${p.status === "P" ? " (projection)" : ""}${line}`
          + (outlineText.current.get(p.iso3) ? `<br/>${outlineText.current.get(p.iso3)}` : ""))
        .addTo(m);
    });
    m.on("mouseleave", "fill", () => {
      if (hovered !== undefined) m.setFeatureState({ source: "countries", id: hovered }, { hover: false });
      hovered = undefined;
      hover.current?.(null);
      m.getCanvas().style.cursor = "";
      popup.remove();
    });
    let pending: ReturnType<typeof setTimeout> | undefined;
    m.on("click", "fill", (e) => {
      const iso = e.features?.[0]?.properties?.iso3;
      if (!iso || cityAt(e.point)) return;
      const ev: PickEvent = { shift: e.originalEvent.shiftKey, double: false, lngLat: [e.lngLat.lng, e.lngLat.lat] };
      if (!dbl.current || ev.shift) return pick.current(iso, ev);
      clearTimeout(pending);
      pending = setTimeout(() => pick.current(iso, ev), 250);
    });
    m.on("dblclick", "fill", (e) => {
      const iso = e.features?.[0]?.properties?.iso3;
      if (!iso || !dbl.current) return;
      clearTimeout(pending);
      e.preventDefault(); // no zoom: the double click opens a popup instead
      pick.current(iso, { shift: false, double: true, lngLat: [e.lngLat.lng, e.lngLat.lat] });
    });
    return () => {
      clearTimeout(pending);
      ro.disconnect();
      onMap?.(null);
      // Work queued for this map must not run on the next one (React mounts twice in development).
      onLoad.current = [];
      if (map.current === m) map.current = null;
      m.remove();
    };
  }, []);

  // Settings arrive after the map is made: open on the chosen centre (unless the map fits its own points).
  const firstCentre = useRef(mapCentre);
  useEffect(() => {
    const m = map.current;
    if (!m || fitPoints || mapCentre === firstCentre.current) return; // the map was made with this centre
    firstCentre.current = mapCentre;
    m.fitBounds(mapCentre === "atlantic" ? [[-170, -56], [180, 78]] : [[10, -56], [360, 78]], { duration: 0 });
  }, [mapCentre, fitPoints]);

  // Popups: each overlay gets a MapLibre marker whose element React draws into.
  const [els, setEls] = useState<Map<string, HTMLDivElement>>(new Map());
  const markers = useRef(new Map<string, maplibregl.Marker>());
  const overlayKey = overlays.map((o) => `${o.key}@${o.lng.toFixed(3)},${o.lat.toFixed(3)}`).join("|");
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const want = new Map(overlays.map((o) => [o.key, o]));
    let changed = false;
    for (const [key, mk] of markers.current) {
      if (!want.has(key)) { mk.remove(); markers.current.delete(key); changed = true; }
    }
    for (const o of overlays) {
      const have = markers.current.get(o.key);
      if (have) { have.setLngLat([o.lng, o.lat]); continue; }
      const el = document.createElement("div");
      el.className = "map-overlay";
      // Keep clicks, drags and scrolling inside the popup away from the map.
      for (const t of ["mousedown", "pointerdown", "click", "dblclick", "wheel", "touchstart"]) el.addEventListener(t, (e) => e.stopPropagation());
      // Open towards the middle of the map, so the card is not cut off at an edge.
      const pt = m.project([o.lng, o.lat]);
      const box = m.getContainer();
      const v = pt.y < box.clientHeight / 2 ? "top" : "bottom";
      const h = pt.x < box.clientWidth / 3 ? "-left" : pt.x > (box.clientWidth * 2) / 3 ? "-right" : "";
      const anchor = `${v}${h}` as maplibregl.PositionAnchor;
      markers.current.set(o.key, new maplibregl.Marker({ element: el, anchor, offset: [0, v === "top" ? 6 : -6] }).setLngLat([o.lng, o.lat]).addTo(m));
      changed = true;
    }
    if (changed) setEls(new Map([...markers.current].map(([k, mk]) => [k, mk.getElement() as HTMLDivElement])));
  }, [overlayKey]);
  useEffect(() => () => { markers.current.forEach((mk) => mk.remove()); markers.current.clear(); }, []);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const apply = () => {
      if (!geo.current || !m.getSource("countries")) return;
      const data: GeoJSON.FeatureCollection = {
        ...geo.current,
        features: geo.current.features.map((f) => {
          const v = byIso.get(f.properties?.iso3);
          const props = { ...f.properties } as Record<string, unknown>;
          if (v) {
            props.value = v.value;
            props.status = v.status;
            props.label = formatValue(v.value, unit, decimals);
          }
          return { ...f, properties: props };
        }),
      };
      (m.getSource("countries") as GeoJSONSource).setData(data);
      m.setPaintProperty("fill", "fill-color", colorExpression(scale));
    };
    if (m.getSource("countries")) apply();
    else onLoad.current.push(apply);
  }, [byIso, scale, unit, decimals]);

  // Map detail under the colours (Settings > Map): online tiles, the local map files, or none.
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    let gone = false;
    const apply = () => {
      const files = baseMap === "local" ? baseMapStatus().then((st) => st.files.length).catch(() => 0) : Promise.resolve(0);
      files.then((n) => {
        if (gone || map.current !== m) return;
        m.setMaxZoom(maxZoomFor(baseMap, n));
        addDetail(m, baseMap).catch((e) => console.warn("map detail skipped", e));
      });
    };
    if (m.getSource("countries")) apply();
    else onLoad.current.push(apply);
    return () => { gone = true; if (map.current === m && m.getLayer("fill")) removeDetail(m); };
  }, [baseMap]);

  // Relief, satellite or night lights under the colours (Settings > Maps, or the Layers panel's Background).
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const apply = () => {
      try { addLook(m, look); } catch (e) { console.warn("map background skipped", e); }
    };
    if (m.getSource("countries")) apply();
    else onLoad.current.push(apply);
    return () => { if (map.current === m && m.getLayer("fill")) removeLook(m); };
  }, [lookKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Picture tiles under the countries, and outlined boxes over them.
  const rasterList = raster ? (Array.isArray(raster) ? raster : [raster]) : [];
  const rasterKey = rasterList.map((r) => `${r.tiles}|${r.over ? 1 : 0}|${r.opacity ?? ""}`).join(",");
  const boxesKey = JSON.stringify(boxes);
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const apply = () => {
      for (const l of m.getStyle().layers ?? []) if (l.id.startsWith("wm-raster")) m.removeLayer(l.id);
      for (const id of Object.keys(m.getStyle().sources ?? {})) if (id.startsWith("wm-raster")) m.removeSource(id);
      rasterList.forEach((r, i) => {
        const id = `wm-raster${i}`;
        m.addSource(id, { type: "raster", tiles: [r.tiles], tileSize: 256, maxzoom: r.maxzoom ?? 7, attribution: r.attribution });
        m.addLayer({ id, type: "raster", source: id, paint: { "raster-opacity": r.opacity ?? 0.95 } }, r.over && m.getLayer("line") ? "line" : "fill");
      });
      for (const id of ["boxes-line", "boxes-label"]) if (m.getLayer(id)) m.removeLayer(id);
      if (m.getSource("boxes")) m.removeSource("boxes");
      if (boxes.length) {
        m.addSource("boxes", { type: "geojson", data: { type: "FeatureCollection", features: boxes.map((b) => ({
          type: "Feature", properties: { name: b.name },
          geometry: { type: "Polygon", coordinates: [[[b.west, b.south], [b.east, b.south], [b.east, b.north], [b.west, b.north], [b.west, b.south]]] } })) } });
        m.addLayer({ id: "boxes-line", type: "line", source: "boxes", paint: { "line-color": cssVar("--ink"), "line-width": 1.5, "line-dasharray": [3, 2] } });
        m.addLayer({ id: "boxes-label", type: "symbol", source: "boxes", layout: { "text-field": ["get", "name"], "text-size": 11, "text-anchor": "bottom", "text-offset": [0, -1] },
          paint: { "text-color": cssVar("--ink"), "text-halo-color": cssVar("--surface"), "text-halo-width": 1.5 } });
      }
    };
    if (m.getSource("countries")) apply();
    else onLoad.current.push(apply);
  }, [rasterKey, boxesKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Filters on overlays (kept for layers still loading).
  const filters = useRef<Record<string, unknown[] | null>>({});
  const filterKey = JSON.stringify(layerFilter ?? {});
  useEffect(() => {
    filters.current = layerFilter ?? {};
    const m = map.current;
    if (!m) return;
    for (const [id, f] of Object.entries(filters.current)) {
      if (m.getLayer(`ov-${id}`)) m.setFilter(`ov-${id}`, (f ?? null) as maplibregl.FilterSpecification | null);
    }
  }, [filterKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Overlays: add the ones asked for (fetched once per page), remove the rest. Window layers
  // are asked for again when the view stops moving; live ones also every so often.
  const layersKey = layers.join(",");
  const dynamic = useRef<Record<string, () => void>>({}); // id -> stop following the view
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    let live = true;
    const addLayer = (id: string, lid: string) => {
      const style = LAYER_STYLE[id];
      // Areas go just over the country colours; lines under the dots; all under the hover and selection outlines.
      const before = style.fill ? "line" : style.dot ? "hover"
        : (["ov-volcanoes", "ov-earthquakes", "ov-major_cities", "ov-points"].find((x) => m.getLayer(x)) ?? "hover");
      m.addLayer(style.fill
        ? { id: lid, type: "fill", source: lid, paint: style.paint() as maplibregl.FillLayerSpecification["paint"] }
        : style.dot
          ? { id: lid, type: "circle", source: lid, paint: style.paint() as maplibregl.CircleLayerSpecification["paint"] }
          : { id: lid, type: "line", source: lid, paint: style.paint() as maplibregl.LineLayerSpecification["paint"],
              layout: { "line-cap": "round", "line-join": "round" } }, before);
      const f = filters.current[id];
      if (f) m.setFilter(lid, f as maplibregl.FilterSpecification);
    };
    const follow = (id: string, lid: string) => {
      const style = LAYER_STYLE[id];
      let timer: ReturnType<typeof setTimeout> | null = null;
      let asked = 0;
      const load = () => {
        const b = m.getBounds();
        const n = ++asked;
        windowData(id, { west: b.getWest(), south: b.getSouth(), east: b.getEast(), north: b.getNorth() }, m.getZoom()).then((fc) => {
          if (!live || n !== asked) return;
          (m.getSource(lid) as GeoJSONSource | undefined)?.setData(fc);
          const note = fc.error ?? (style.fetch === "live" ? `${LAYER_STYLE[id].legend}: ${fc.features.length.toLocaleString()} in view` : "");
          setNotes((cur) => ({ ...cur, [id]: note }));
        }).catch((e) => setNotes((cur) => ({ ...cur, [id]: `${LAYER_STYLE[id].legend}: ${String(e?.message ?? e)}` })));
      };
      const soon = () => { if (timer) clearTimeout(timer); timer = setTimeout(load, 450); };
      m.on("moveend", soon);
      const every = style.fetch === "live" ? setInterval(load, (style.every ?? 60) * 1000) : null;
      load();
      dynamic.current[id] = () => {
        m.off("moveend", soon);
        if (timer) clearTimeout(timer);
        if (every) clearInterval(every);
        setNotes((cur) => { const { [id]: _gone, ...rest } = cur; return rest; });
      };
    };
    const apply = () => {
      const want = new Set(layersKey ? layersKey.split(",") : []);
      for (const id of Object.keys(LAYER_STYLE)) {
        const lid = `ov-${id}`;
        if (!want.has(id)) {
          dynamic.current[id]?.();
          delete dynamic.current[id];
          if (m.getLayer(lid)) m.removeLayer(lid);
          if (m.getSource(lid)) m.removeSource(lid);
          continue;
        }
        if (m.getLayer(lid)) continue;
        if (LAYER_STYLE[id].fetch) {
          m.addSource(lid, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
          addLayer(id, lid);
          follow(id, lid);
          continue;
        }
        layerData(id).then((data) => {
          if (!live || m.getLayer(lid) || !m.getStyle()) return;
          if (!m.getSource(lid)) m.addSource(lid, { type: "geojson", data });
          addLayer(id, lid);
        }).catch(() => {});
      }
    };
    if (m.getLayer("hover")) apply();
    else onLoad.current.push(apply);
    return () => { live = false; };
  }, [layersKey]);
  useEffect(() => () => { Object.values(dynamic.current).forEach((stop) => stop()); }, []);

  // The countries that rely on the clicked feature, outlined.
  const dependsKey = info?.countries?.map((c) => c.id).join(",") ?? "";
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const apply = () => {
      const ids = dependsKey ? dependsKey.split(",") : [];
      const filter: maplibregl.FilterSpecification = ["in", ["get", "iso3"], ["literal", ids]];
      if (!m.getLayer("ov-depends")) {
        m.addLayer({ id: "ov-depends", type: "line", source: "countries", filter, layout: { "line-join": "round" },
          paint: { "line-color": cssVar("--series-2"), "line-width": 2.6 } });
      } else m.setFilter("ov-depends", filter);
    };
    if (m.getSource("countries")) apply();
    else onLoad.current.push(apply);
  }, [dependsKey]);

  // Places to mark: a dot each, sized by its size (square root, so area follows it).
  const pointsKey = points ? points.map((p) => `${p.id}:${p.size}:${p.color ?? ""}`).join(",") : null;
  useEffect(() => {
    const m = map.current;
    if (!m || pointsKey === null) return;
    const apply = () => {
      const pts = points ?? [];
      const top = pointsTop ?? Math.max(1, ...pts.map((p) => p.size));
      const data: GeoJSON.FeatureCollection = {
        type: "FeatureCollection",
        features: [...pts].sort((a, b) => b.size - a.size).map((p) => ({
          type: "Feature", geometry: { type: "Point", coordinates: [p.lng, p.lat] },
          properties: { city: p.id, name: p.name, text: p.text ?? "", r: 2.5 + 11 * Math.sqrt(Math.max(0, p.size) / top),
            capital: p.capital ? 1 : 0, color: p.color ?? cssVar("--series-1") },
        })),
      };
      const src = m.getSource("ov-points") as GeoJSONSource | undefined;
      if (src) src.setData(data);
      else {
        m.addSource("ov-points", { type: "geojson", data });
        m.addLayer({ id: "ov-points", type: "circle", source: "ov-points", paint: {
          "circle-color": ["get", "color"], "circle-opacity": 0.75, "circle-radius": ["get", "r"],
          "circle-stroke-color": ["case", ["==", ["get", "capital"], 1], cssVar("--ink"), cssVar("--surface")],
          "circle-stroke-width": ["case", ["==", ["get", "capital"], 1], 1.6, 0.8],
        } });
      }
      if (fitPoints && pts.length) {
        // Kept inside what the map can show: a point at the South Pole (Antarctic stations)
        // plus the padding would be below -90 and stop the page.
        const ok = pts.filter((p) => Number.isFinite(p.lng) && Number.isFinite(p.lat));
        const lngs = ok.map((p) => p.lng), lats = ok.map((p) => p.lat);
        const pad = ok.length === 1 ? 2 : 0.5;
        const lat = (v: number) => Math.max(-85, Math.min(85, v)), lng = (v: number) => Math.max(-180, Math.min(180, v));
        if (ok.length) m.fitBounds([[lng(Math.min(...lngs) - pad), lat(Math.min(...lats) - pad)], [lng(Math.max(...lngs) + pad), lat(Math.max(...lats) + pad)]],
          { padding: 30, maxZoom: 6, duration: 0 });
      }
    };
    if (m.getLayer("hover")) apply();
    else onLoad.current.push(apply);
  }, [pointsKey, fitPoints, pointsTop]);

  // Routes between countries: curved lines from each exporter to its buyer, wider for more.
  const linesKey = lines ? lines.map((l) => `${l.from}>${l.to}:${l.value}`).join(",") : null;
  useEffect(() => {
    const m = map.current;
    if (!m || linesKey === null) return;
    let live = true;
    const apply = () => countryCentres().then((c) => {
      if (!live || !map.current) return;
      const ls = (lines ?? []).filter((l) => c[l.from] && c[l.to]);
      const top = Math.max(1, ...ls.map((l) => l.value));
      const data: GeoJSON.FeatureCollection = {
        type: "FeatureCollection",
        features: [...ls].sort((a, b) => a.value - b.value).map((l) => ({
          type: "Feature", geometry: { type: "LineString", coordinates: arc(c[l.from], c[l.to]) },
          properties: { w: 0.8 + 7 * Math.sqrt(l.value / top), label: l.text ?? "" },
        })),
      };
      const src = m.getSource("ov-lines") as GeoJSONSource | undefined;
      if (src) src.setData(data);
      else {
        m.addSource("ov-lines", { type: "geojson", data });
        m.addLayer({ id: "ov-lines", type: "line", source: "ov-lines", layout: { "line-cap": "round" }, paint: {
          "line-color": cssVar("--accent") || cssVar("--series-1"), "line-opacity": 0.55, "line-width": ["get", "w"],
        } }, m.getLayer("hover") ? "hover" : undefined);
      }
    });
    if (m.getLayer("hover")) apply();
    else onLoad.current.push(apply);
    return () => { live = false; };
  }, [linesKey]);

  // Countries outlined in a colour: a line layer over the country shapes, coloured per country.
  const outlinesKey = outlines ? outlines.map((o) => `${o.entity}:${o.color}`).join(",") : null;
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const apply = () => {
      const list = outlines ?? [];
      if (!list.length) {
        if (m.getLayer("ov-outline")) m.removeLayer("ov-outline");
        return;
      }
      const color = ["match", ["get", "iso3"], ...list.flatMap((o) => [o.entity, o.color]), "rgba(0,0,0,0)"] as unknown as ExpressionSpecification;
      const filter = ["in", ["get", "iso3"], ["literal", list.map((o) => o.entity)]] as maplibregl.FilterSpecification;
      if (!m.getLayer("ov-outline")) {
        m.addLayer({ id: "ov-outline", type: "line", source: "countries", filter, layout: { "line-join": "round" },
          paint: { "line-color": color, "line-width": ["interpolate", ["linear"], ["zoom"], 0, 1.6, 5, 3] } }, "hover");
      } else {
        m.setFilter("ov-outline", filter);
        m.setPaintProperty("ov-outline", "line-color", color);
      }
    };
    if (m.getLayer("hover")) apply();
    else onLoad.current.push(apply);
  }, [outlinesKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Markers: solid dots, or rings for things only reported so far; older ones fainter.
  const marksKey = marks ? marks.map((k) => `${k.key}:${k.color}:${k.hollow ? 1 : 0}:${k.opacity ?? 1}`).join(",") : null;
  useEffect(() => {
    const m = map.current;
    if (!m || marksKey === null) return;
    const apply = () => {
      const data: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: (marks ?? []).map((k) => ({
        type: "Feature", geometry: { type: "Point", coordinates: [k.lng, k.lat] },
        properties: { color: k.color, hollow: k.hollow ? 1 : 0, r: k.r ?? 5, o: k.opacity ?? 1, label: k.label, href: k.href ?? "" } })) };
      const src = m.getSource("ov-marks") as GeoJSONSource | undefined;
      if (src) { src.setData(data); return; }
      m.addSource("ov-marks", { type: "geojson", data });
      m.addLayer({ id: "ov-marks", type: "circle", source: "ov-marks", paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 0, ["*", ["get", "r"], 0.8], 5, ["*", ["get", "r"], 1.5]],
        "circle-color": ["get", "color"], "circle-opacity": ["case", ["==", ["get", "hollow"], 1], 0, ["*", 0.85, ["get", "o"]]],
        "circle-stroke-color": ["case", ["==", ["get", "hollow"], 1], ["get", "color"], cssVar("--surface")],
        "circle-stroke-width": ["case", ["==", ["get", "hollow"], 1], 2, 1], "circle-stroke-opacity": ["get", "o"],
      } }, "hover");
    };
    if (m.getLayer("hover")) apply();
    else onLoad.current.push(apply);
  }, [marksKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Shapes of past states over the countries, under the outlines and dots.
  const areasKey = areas?.key ?? null;
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const apply = () => {
      const data = areas?.data ?? { type: "FeatureCollection" as const, features: [] };
      const src = m.getSource("ov-areas") as GeoJSONSource | undefined;
      if (src) { src.setData(data); return; }
      if (!areas) return;
      m.addSource("ov-areas", { type: "geojson", data });
      m.addLayer({ id: "ov-areas", type: "fill", source: "ov-areas", layout: { "fill-sort-key": ["coalesce", ["get", "sort"], 0] },
        paint: { "fill-color": ["get", "color"], "fill-opacity": ["coalesce", ["get", "opacity"], 0.6] } }, "line");
      m.addLayer({ id: "ov-areas-line", type: "line", source: "ov-areas",
        paint: { "line-color": cssVar("--ink"), "line-width": 0.6, "line-opacity": 0.55 } }, "hover");
    };
    if (m.getLayer("hover")) apply();
    else onLoad.current.push(apply);
  }, [areasKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const pathsKey = paths ? paths.map((p) => `${p.key}:${p.stops.length}:${p.color}`).join(",") : null;
  useEffect(() => {
    const m = map.current;
    if (!m || pathsKey === null) return;
    const apply = () => {
      const list = paths ?? [];
      // Lines that cross the date line are drawn the short way round (MapLibre wraps longitudes past 180).
      const unwrap = (stops: { lng: number; lat: number }[]) => {
        const out: [number, number][] = [];
        for (const s of stops) {
          let x = s.lng;
          if (out.length) {
            const prev = out[out.length - 1][0];
            while (x - prev > 180) x -= 360;
            while (prev - x > 180) x += 360;
          }
          out.push([x, s.lat]);
        }
        return out;
      };
      const lines: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: list.map((p) => ({
        type: "Feature", geometry: { type: "LineString", coordinates: unwrap(p.stops) }, properties: { color: p.color, label: p.label } })) };
      const stops: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: list.flatMap((p) => p.stops.map((s) => ({
        type: "Feature" as const, geometry: { type: "Point" as const, coordinates: [s.lng, s.lat] }, properties: { color: p.color, label: s.label } }))) };
      const a = m.getSource("ov-paths") as GeoJSONSource | undefined;
      if (a) { a.setData(lines); (m.getSource("ov-pathstops") as GeoJSONSource).setData(stops); return; }
      m.addSource("ov-paths", { type: "geojson", data: lines });
      m.addSource("ov-pathstops", { type: "geojson", data: stops });
      m.addLayer({ id: "ov-paths", type: "line", source: "ov-paths", layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": ["get", "color"], "line-width": 2, "line-dasharray": [2, 1.5] } }, "hover");
      m.addLayer({ id: "ov-pathstops", type: "circle", source: "ov-pathstops", paint: {
        "circle-radius": 3.5, "circle-color": ["get", "color"], "circle-stroke-color": cssVar("--surface"), "circle-stroke-width": 1 } });
    };
    if (m.getLayer("hover")) apply();
    else onLoad.current.push(apply);
  }, [pathsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Outline the country hovered in a linked panel.
  useEffect(() => {
    const m = map.current;
    if (!m || !hovered) return;
    const id = hovered;
    const apply = () => m.setFeatureState({ source: "countries", id }, { linked: true });
    const clear = () => { if (m.getSource("countries")) m.setFeatureState({ source: "countries", id }, { linked: false }); };
    if (m.getSource("countries")) apply();
    else onLoad.current.push(apply);
    return clear;
  }, [hovered]);

  // Follow and lead the other maps in the group.
  const camKey = camera ? `${camera.id}|${camera.group}` : "";
  useEffect(() => {
    const m = map.current;
    if (!m || !camera) return;
    const { bus, id, group } = camera;
    const unsubscribe = bus.subscribe(id, group, (c) => m.jumpTo(c));
    const start = bus.last.get(group);
    if (start) m.jumpTo(start);
    const onMove = () => {
      const c = m.getCenter();
      bus.publish(id, group, { center: [c.lng, c.lat], zoom: m.getZoom() });
    };
    m.on("move", onMove);
    return () => {
      unsubscribe();
      m.off("move", onMove);
    };
  }, [camKey]);

  const selectedKey = selected.join(",");
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const apply = () => m.getLayer("selected") && m.setFilter("selected", ["in", ["get", "iso3"], ["literal", selectedKey ? selectedKey.split(",") : []]]);
    if (m.getLayer("selected")) apply();
    else onLoad.current.push(apply);
  }, [selectedKey]);

  useEffect(() => { const z = map.current?.doubleClickZoom; if (z) { if (doubleClick) z.disable(); else z.enable(); } }, [doubleClick]);

  return (
    <div className={fill ? "map-fill" : undefined}>
      <div className="map-wrap"><div ref={el} className="map" />
        {info && (
          <div className="map-info" role="dialog" aria-label={info.title}>
            <div className="row"><b>{info.title}</b><span className="spacer" />
              <button className="link small" onClick={() => setInfo(null)} aria-label="Close">×</button></div>
            {info.loading ? <p className="small muted">Loading…</p> : (
              <>
                {(info.lines ?? []).filter(Boolean).map((l) => <p key={l} className="small" style={{ margin: "2px 0" }}>{l}</p>)}
                {info.split?.length ? (
                  <table className="small"><thead><tr><th>Country</th><th>Of the basin</th><th>Of the country</th><th>People (rough)</th></tr></thead>
                    <tbody>{info.split.map((x) => (
                      <tr key={x.id}><td><a href={`/entity/${x.id}`}>{x.name}</a></td><td>{pct(x.share)}</td><td>{pct(x.of_country)}</td>
                        <td>{x.people != null ? compact(x.people) : "…"}</td></tr>))}</tbody></table>
                ) : info.countries?.length ? (
                  <p className="small" style={{ margin: "4px 0" }}>{info.layer === "chokepoints" ? "On its shores" : "Countries it reaches"} (outlined):{" "}
                    {info.countries.map((c, i) => <span key={c.id}>{i ? ", " : ""}<a href={`/entity/${c.id}`}>{c.name}</a></span>)}</p>
                ) : null}
              </>
            )}
          </div>
        )}
      </div>
      {Object.values(notes).some(Boolean) && <p className="caption">{Object.values(notes).filter(Boolean).join(" · ")}</p>}
      {!hideScale && <Legend scale={scale} unit={unit} />}
      {(layers.length > 0 || legend.length > 0) && (
        <div className="legend overlays" aria-label="Map layers">
          {legend.map((l) => (
            <span key={l.label} className="step">
              <i className={l.shape === "dot" ? "dot" : l.shape === "ring" ? "dot ring" : "outline"}
                style={l.shape === "dot" ? { background: l.color } : { borderColor: l.color }} />
              {l.label}
            </span>
          ))}
          {layers.filter((id) => LAYER_STYLE[id]).map((id) => (
            <span key={id} className="step">
              <i className={LAYER_STYLE[id].dot ? "dot" : "line"} style={{ background: LAYER_STYLE[id].swatch() }} />
              {LAYER_STYLE[id].legend}
            </span>
          ))}
        </div>
      )}
      {overlays.map((o) => { const target = els.get(o.key); return target ? createPortal(o.node, target, o.key) : null; })}
    </div>
  );
}

function Legend({ scale, unit }: { scale: Scale; unit: string }) {
  if (!scale.colors.length) return null;
  const labels = ["", ...scale.breaks.map((b) => compact(b))];
  return (
    <div className="legend" aria-label="Map legend">
      {scale.colors.slice(0, scale.breaks.length + 1).map((c, i) => (
        <div className="step" key={i}>
          <div className="bar" style={{ background: c }} />
          <span>{i === 0 ? "" : `${labels[i]}`}</span>
        </div>
      ))}
      <span className="muted" style={{ marginLeft: 8 }}>{unit === "percent" ? "%" : unit}</span>
      <span className="nodata"><span /> no data</span>
    </div>
  );
}

type GeoCard = {
  layer: string; id: string; name: string | null; props: Record<string, unknown>; countries: { id: string; name: string }[];
  split?: { id: string; name: string; share: number; of_country: number | null; people: number | null }[]; people?: number | null;
};
type FeatureInfo = {
  layer: string; title: string; loading?: boolean; lines?: string[]; countries?: { id: string; name: string }[];
  split?: GeoCard["split"];
};
const pct = (v: number | null | undefined) => (typeof v === "number" ? `${(v * 100).toFixed(v < 0.1 ? 1 : 0)}%` : "…");
const n0 = (v: unknown) => (typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 0 }) : null);

// A clicked feature's card: a few lines about it, and its countries.
function cardOf(layer: string, d: GeoCard): FeatureInfo {
  const p = d.props ?? {};
  const lines: string[] = [];
  if (layer === "basins") {
    lines.push(`${n0(p.area)} km² of land drains to it${typeof p.flow === "number" ? `; about ${n0(p.flow)} m³ of water a second leaves it` : ""}.`);
    if (d.people) lines.push(`Roughly ${compact(d.people)} people live in it (each country's people shared by the share of its land in the basin).`);
    if (p.transboundary) lines.push("Shared by several countries: what one does upstream, the next one feels.");
    if (p.endorheic) lines.push("Drains to an inland lake or sea, not the ocean.");
  } else if (layer === "cables") {
    if (p.rfs) lines.push(`In service from ${p.rfs}${p.planned ? " (planned)" : ""}.`);
    if (p.length) lines.push(`Length ${p.length}.`);
    if (p.owners) lines.push(`Owners: ${p.owners}.`);
  } else if (layer === "gas_pipelines" || layer === "oil_pipelines") {
    if (p.status) lines.push(`Status: ${p.status}${p.start ? `, from ${p.start}` : ""}.`);
    if (typeof p.capacity === "number") lines.push(`Capacity ${p.capacity} ${p.capacity_unit ?? (layer === "gas_pipelines" ? "bcm a year" : "")}.`);
    if (typeof p.length_km === "number") lines.push(`${n0(p.length_km)} km long.`);
    if (p.owner) lines.push(`Owner: ${p.owner}.`);
  } else if (layer === "rivers") {
    if (typeof p.flow === "number") lines.push(`About ${n0(p.flow)} m³ of water a second where this stretch ends; ${n0(p.length)} km of river in this order.`);
  } else if (layer === "waterways") {
    if (p.to) lines.push(`Ships use it as far as ${p.to}.`);
    if (p.cemt) lines.push(`European class ${p.cemt} (V and up take big barges and push convoys).`);
    if (p.source) lines.push(`From ${p.source}.`);
  }
  const title = d.name ?? (layer === "rivers" ? "River" : layer === "basins" ? "River basin" : "Feature");
  return { layer, title, lines, countries: d.countries, split: d.split };
}
