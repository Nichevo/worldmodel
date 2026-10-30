"use client";

import * as maplibregl from "maplibre-gl";
import type { ExpressionSpecification, GeoJSONSource } from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { sparklineSvg } from "@/lib/charts";
import { cssVar, divergingRamp, sequentialRamp } from "@/lib/colors";
import { compact, formatValue } from "@/lib/format";
import type { CameraBus } from "@/lib/camera";
import { countryShapes } from "@/lib/geo";

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
};

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
  doubleClick = false, overlays = [], spark = null, onMap,
}: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const onLoad = useRef<(() => void)[]>([]); // work waiting for the country layers
  const geo = useRef<GeoJSON.FeatureCollection | null>(null);
  const pick = useRef(onPick);
  pick.current = onPick;
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
      // Fit the inhabited world to whatever size the map's box is.
      bounds: [[-170, -56], [180, 78]],
      minZoom: 0.5,
      maxZoom: 7,
      attributionControl: { compact: true, customAttribution: "Borders: Natural Earth" },
      renderWorldCopies: false,
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
      onLoad.current.splice(0).forEach((f) => f());
    });
    // MapLibre only tracks window resizes; panels resize on their own.
    const ro = new ResizeObserver(() => m.resize());
    ro.observe(el.current);

    let hovered: string | number | undefined;
    m.on("mousemove", "fill", (e) => {
      const f = e.features?.[0];
      if (!f) return;
      if (f.id !== hovered) hover.current?.(f.id === undefined ? null : String(f.id));
      if (hovered !== undefined) m.setFeatureState({ source: "countries", id: hovered }, { hover: false });
      hovered = f.id;
      if (hovered !== undefined) m.setFeatureState({ source: "countries", id: hovered }, { hover: true });
      m.getCanvas().style.cursor = "pointer";
      const p = f.properties as { name: string; iso3: string; value?: number; status?: string; label?: string };
      const sp = sparkRef.current;
      const line = sp && sp.rows[p.iso3] ? sparklineSvg(sp.years, sp.rows[p.iso3], sp.upTo, cssVar("--series-1")) : "";
      popup.setLngLat(e.lngLat)
        .setHTML(`<b>${p.name}</b><br/>${p.label ?? "no data"}${p.status === "P" ? " (projection)" : ""}${line}`)
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
      if (!iso) return;
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
      m.remove();
    };
  }, []);

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
    const apply = () => m.setFilter("selected", ["in", ["get", "iso3"], ["literal", selectedKey ? selectedKey.split(",") : []]]);
    if (m.getLayer("selected")) apply();
    else onLoad.current.push(apply);
  }, [selectedKey]);

  useEffect(() => { const z = map.current?.doubleClickZoom; if (z) { if (doubleClick) z.disable(); else z.enable(); } }, [doubleClick]);

  return (
    <div className={fill ? "map-fill" : undefined}>
      <div className="map-wrap"><div ref={el} className="map" /></div>
      <Legend scale={scale} unit={unit} />
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
