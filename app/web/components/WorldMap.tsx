"use client";

import * as maplibregl from "maplibre-gl";
import type { ExpressionSpecification, GeoJSONSource } from "maplibre-gl";
import { useEffect, useMemo, useRef } from "react";
import { cssVar, divergingRamp, sequentialRamp } from "@/lib/colors";
import { compact, formatValue } from "@/lib/format";
import type { CameraBus } from "@/lib/camera";
import { countryShapes } from "@/lib/geo";

// MapLibre's worker file, copied into public/ on npm install (scripts/copy-maplibre-worker.mjs).
if (typeof window !== "undefined") maplibregl.setWorkerUrl(`/maplibre/maplibre-gl-worker.mjs?v=${maplibregl.getVersion()}`);

type Value = { entity_id: string; value: number; status: string };
type Props = {
  values: Value[];
  unit: string;
  decimals: number;
  diverging: boolean;
  onPick: (iso3: string) => void;
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
}: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const onLoad = useRef<(() => void)[]>([]); // work waiting for the country layers
  const geo = useRef<GeoJSON.FeatureCollection | null>(null);
  const pick = useRef(onPick);
  pick.current = onPick;
  const hover = useRef(onHover);
  hover.current = onHover;

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
      const p = f.properties as { name: string; value?: number; status?: string; label?: string };
      popup.setLngLat(e.lngLat)
        .setHTML(`<b>${p.name}</b><br/>${p.label ?? "no data"}${p.status === "P" ? " (projection)" : ""}`)
        .addTo(m);
    });
    m.on("mouseleave", "fill", () => {
      if (hovered !== undefined) m.setFeatureState({ source: "countries", id: hovered }, { hover: false });
      hovered = undefined;
      hover.current?.(null);
      m.getCanvas().style.cursor = "";
      popup.remove();
    });
    m.on("click", "fill", (e) => {
      const iso = e.features?.[0]?.properties?.iso3;
      if (iso) pick.current(iso);
    });
    return () => {
      ro.disconnect();
      m.remove();
    };
  }, []);

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

  return (
    <div className={fill ? "map-fill" : undefined}>
      <div className="map-wrap"><div ref={el} className="map" /></div>
      <Legend scale={scale} unit={unit} />
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
