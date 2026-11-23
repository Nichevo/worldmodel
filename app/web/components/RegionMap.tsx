"use client";

// The regions inside a country or state, coloured by one figure: seven classes at quantiles
// (as on the world map), the region's name and value on hover, a click to pick it. No base map:
// the outlines alone, so it works offline. Fitted to the regions, with the Pacific kept in view
// for places that straddle 180° (Alaska's Aleutians).

import * as maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";
import { makeScale } from "@/components/WorldMap";
import { cssVar } from "@/lib/colors";
import { formatValue } from "@/lib/format";
import { short } from "@/lib/sectors";
import { fitBox, polysOf } from "@/lib/landcompare";

type Box = [[number, number], [number, number]];

// Every region's own main land (so Hawaii counts as much as Texas), across 180° when one of them
// straddles it (Alaska's Aleutians, New Zealand's Chatham Islands): then the rest move east too.
function unionBox(boxes: Box[]): Box | null {
  if (!boxes.length) return null;
  const east = boxes.some((b) => b[1][0] > 180);
  const bs = east ? boxes.map((b) => (b[1][0] < 0 ? [[b[0][0] + 360, b[0][1]], [b[1][0] + 360, b[1][1]]] as Box : b)) : boxes;
  return [[Math.min(...bs.map((b) => b[0][0])), Math.min(...bs.map((b) => b[0][1]))], [Math.max(...bs.map((b) => b[1][0])), Math.max(...bs.map((b) => b[1][1]))]];
}

type Props = {
  shapes: GeoJSON.FeatureCollection | null;
  values: Record<string, number | null | undefined>;
  unit: string;
  decimals: number;
  selected?: string | null;
  onPick?: (id: string) => void;
  height?: number;
};

export default function RegionMap({ shapes, values, unit, decimals, selected, onPick, height = 380 }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [hover, setHover] = useState<{ x: number; y: number; name: string; v: number | null | undefined } | null>(null);
  const pick = useRef(onPick);
  pick.current = onPick;
  const nums = useMemo(() => Object.values(values).filter((v): v is number => typeof v === "number"), [values]);
  const diverging = nums.some((v) => v < 0) && nums.some((v) => v > 0);
  const scale = useMemo(() => makeScale(nums, diverging), [nums, diverging]);

  useEffect(() => {
    if (!el.current) return;
    const m = new maplibregl.Map({
      container: el.current,
      style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": cssVar("--surface") } }] },
      center: [-100, 40], zoom: 2, dragRotate: false, pitchWithRotate: false, renderWorldCopies: true, attributionControl: false,
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.current = m;
    m.on("load", () => {
      m.addSource("regions", { type: "geojson", data: { type: "FeatureCollection", features: [] }, promoteId: "id" });
      m.addLayer({ id: "fill", type: "fill", source: "regions", paint: { "fill-color": cssVar("--no-data"), "fill-opacity": 0.92 } });
      m.addLayer({ id: "line", type: "line", source: "regions", paint: { "line-color": cssVar("--surface"), "line-width": 0.6 } });
      m.addLayer({ id: "picked", type: "line", source: "regions", filter: ["==", ["get", "id"], ""],
        paint: { "line-color": cssVar("--ink"), "line-width": 2 } });
      m.on("mousemove", "fill", (e) => {
        const f = e.features?.[0];
        if (!f) return;
        m.getCanvas().style.cursor = "pointer";
        const p = f.properties as { name: string; value?: number };
        setHover({ x: e.point.x, y: e.point.y, name: p.name, v: p.value });
      });
      m.on("mouseleave", "fill", () => { m.getCanvas().style.cursor = ""; setHover(null); });
      m.on("click", "fill", (e) => { const id = (e.features?.[0]?.properties as { id?: string } | undefined)?.id; if (id) pick.current?.(id); });
      setReady(true);
    });
    return () => { setReady(false); m.remove(); map.current = null; };
  }, []);

  // Outlines: fitted once per set of shapes.
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !shapes) return;
    const box = unionBox(shapes.features.map((f) => fitBox(polysOf(f.geometry))).filter((b): b is Box => !!b));
    if (box) m.fitBounds(box, { padding: 16, animate: false });
  }, [shapes, ready]);

  // Values and colours.
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !shapes) return;
    const data: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: shapes.features.map((f) => {
      const id = String((f.properties as { id?: string })?.id ?? f.id);
      const v = values[id];
      return { ...f, properties: { ...f.properties, id, ...(typeof v === "number" ? { value: v } : {}) } };
    }) };
    (m.getSource("regions") as maplibregl.GeoJSONSource).setData(data);
    const steps: (number | string)[] = [scale.colors[0] ?? cssVar("--no-data")];
    scale.breaks.forEach((b, i) => steps.push(b, scale.colors[i + 1]));
    m.setPaintProperty("fill", "fill-color", scale.breaks.length
      ? ["case", ["has", "value"], ["step", ["get", "value"], ...steps], cssVar("--no-data")] as unknown as maplibregl.ExpressionSpecification
      : ["case", ["has", "value"], steps[0], cssVar("--no-data")] as maplibregl.ExpressionSpecification);
    m.setPaintProperty("line", "line-width", shapes.features.length > 400 ? 0.2 : 0.6);
  }, [shapes, values, scale, ready]);

  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    m.setFilter("picked", ["==", ["get", "id"], selected ?? ""]);
  }, [selected, ready]);

  const fmt = (v: number) => formatValue(v, unit, decimals);
  const leg = (v: number) => (Math.abs(v) >= 10000 ? short(v) : fmt(v));
  return (
    <div style={{ position: "relative" }}>
      <div ref={el} style={{ height, borderRadius: 10, overflow: "hidden" }} aria-label="Map of the regions" />
      {hover && (
        <div className="small" style={{ position: "absolute", left: Math.min(hover.x + 12, 9999), top: hover.y + 12, pointerEvents: "none",
          background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, padding: "4px 8px", boxShadow: "0 2px 6px rgba(0,0,0,.15)" }}>
          <b>{hover.name}</b><br />{hover.v == null ? "no figure" : `${fmt(hover.v)} ${unit}`}
        </div>
      )}
      {scale.breaks.length > 0 && (
        <div className="swatches small" style={{ marginTop: 6 }}>
          {scale.colors.map((c, i) => (
            <span key={c + i} className="legend-item"><i style={{ background: c }} />
              {i === 0 ? `under ${leg(scale.breaks[0])}` : i === scale.colors.length - 1 ? `${leg(scale.breaks[i - 1])} and over`
                : `${leg(scale.breaks[i - 1])}–${leg(scale.breaks[i])}`}</span>))}
          <span className="legend-item"><i style={{ background: "var(--no-data)" }} />no figure</span>
        </div>
      )}
    </div>
  );
}
