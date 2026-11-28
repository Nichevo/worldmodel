"use client";

// Land > Top crops: every country, US state or county, or New Zealand region coloured by the crop
// grown on the most land there (as on "top crop by county" maps), with a legend of those crops and
// how many places each leads. Hover for a place's top three; pick a crop to see where it is grown
// (shaded by its share of each place's crop land); click a place for its crops over the years.

import Link from "next/link";
import * as maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";
import EChart from "@/components/EChart";
import { api, type CropLevel, type CropPlace, type CropTop, type CropWhere } from "@/lib/api";
import { quietMapErrors } from "@/lib/basemap";
import { cssVar } from "@/lib/colors";
import { compact } from "@/lib/format";
import { countryShapes } from "@/lib/geo";
import { linesOption } from "@/lib/land";

const ACRES_PER_HA = 2.4710538;
const SHAPES: Record<string, () => Promise<GeoJSON.FeatureCollection>> = {
  world: () => countryShapes().then((fc) => ({ ...fc, features: fc.features.map((f) => ({ ...f, properties: { ...f.properties,
    id: (f.properties as { iso3?: string })?.iso3 } })) })),
  us_state: () => api.regionShapes("USA"),
  us_county: () => api.regionShapes("USA", "county"),
  nz_region: () => api.regionShapes("NZL"),
};
const VIEW: Record<string, { center: [number, number]; zoom: number }> = {
  world: { center: [160, 15], zoom: 0.9 }, us_state: { center: [-97, 39], zoom: 2.6 }, us_county: { center: [-97, 39], zoom: 2.6 },
  nz_region: { center: [173, -41], zoom: 3.9 },
};

function ha(v: number, us: boolean): string {
  return us ? `${compact(v * ACRES_PER_HA)} acres (${compact(v)} ha)` : `${compact(v)} ha`;
}
const pct = (v: number | null | undefined) => (v == null ? "" : `${v >= 10 ? v.toFixed(0) : v.toFixed(1)}%`);

type Hover = { x: number; y: number; id: string; name: string };

function CropMap({ level, shapes, fill, onHover, onPick, picked }: {
  level: string; shapes: GeoJSON.FeatureCollection | null; fill: Record<string, { c: string; o: number }>;
  onHover: (h: Hover | null) => void; onPick: (id: string) => void; picked: string | null;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const hover = useRef(onHover);
  hover.current = onHover;
  const pick = useRef(onPick);
  pick.current = onPick;

  useEffect(() => {
    if (!el.current) return;
    const m = new maplibregl.Map({
      container: el.current,
      style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": cssVar("--surface") } }] },
      center: VIEW.world.center, zoom: VIEW.world.zoom, minZoom: 0, dragRotate: false, pitchWithRotate: false, renderWorldCopies: true,
      attributionControl: false,
    });
    quietMapErrors(m);
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.current = m;
    m.on("load", () => {
      m.addSource("places", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({ id: "fill", type: "fill", source: "places", paint: {
        "fill-color": ["coalesce", ["get", "c"], cssVar("--no-data")] as maplibregl.ExpressionSpecification,
        "fill-opacity": ["coalesce", ["get", "o"], 0.9] as maplibregl.ExpressionSpecification } });
      m.addLayer({ id: "line", type: "line", source: "places", paint: { "line-color": cssVar("--surface"), "line-width": 0.5 } });
      m.addLayer({ id: "picked", type: "line", source: "places", filter: ["==", ["get", "id"], ""], paint: { "line-color": cssVar("--ink"), "line-width": 2 } });
      m.on("mousemove", "fill", (e) => {
        const p = e.features?.[0]?.properties as { id?: string; name?: string } | undefined;
        if (!p?.id) return;
        m.getCanvas().style.cursor = "pointer";
        hover.current({ x: e.point.x, y: e.point.y, id: p.id, name: p.name ?? p.id });
      });
      m.on("mouseleave", "fill", () => { m.getCanvas().style.cursor = ""; hover.current(null); });
      m.on("click", "fill", (e) => { const id = (e.features?.[0]?.properties as { id?: string } | undefined)?.id; if (id) pick.current(id); });
      setReady(true);
    });
    return () => { setReady(false); m.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const v = VIEW[level] ?? VIEW.world;
    m.jumpTo({ center: v.center, zoom: v.zoom });
  }, [level, ready]);

  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !shapes) return;
    const data: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: shapes.features.map((f) => {
      const id = String((f.properties as { id?: string })?.id ?? f.id ?? "");
      const got = fill[id];
      return { ...f, properties: { ...f.properties, id, ...(got ? { c: got.c, o: got.o } : {}) } };
    }) };
    (m.getSource("places") as maplibregl.GeoJSONSource).setData(data);
    m.setPaintProperty("line", "line-width", shapes.features.length > 400 ? 0.15 : 0.5);
  }, [shapes, fill, ready]);

  useEffect(() => {
    if (map.current && ready) map.current.setFilter("picked", ["==", ["get", "id"], picked ?? ""]);
  }, [picked, ready]);

  return <div ref={el} style={{ height: 520, borderRadius: 10, overflow: "hidden" }} aria-label="Map of the top crop in each place" />;
}

export default function TopCrops() {
  const [levels, setLevels] = useState<CropLevel[] | null>(null);
  const [level, setLevel] = useState("world");
  const [year, setYear] = useState<number | null>(null);
  const [top, setTop] = useState<CropTop | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [shapes, setShapes] = useState<GeoJSON.FeatureCollection | null>(null);
  const [crop, setCrop] = useState<string | null>(null);
  const [where, setWhere] = useState<CropWhere | null>(null);
  const [hover, setHover] = useState<Hover | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [place, setPlace] = useState<CropPlace | null>(null);
  const [filter, setFilter] = useState("");
  const us = level.startsWith("us_");

  useEffect(() => { api.cropLevels().then((l) => { setLevels(l); if (l.length && !l.some((x) => x.level === "world")) setLevel(l[0].level); })
    .catch(() => setLevels([])); }, []);
  useEffect(() => {
    let live = true;
    setTop(null); setErr(null);
    api.cropTop(level, year).then((t) => live && setTop(t)).catch((e) => live && setErr(String(e)));
    return () => { live = false; };
  }, [level, year]);
  useEffect(() => {
    let live = true;
    setShapes(null);
    (SHAPES[level] ?? SHAPES.world)().then((s) => live && setShapes(s)).catch(() => live && setShapes({ type: "FeatureCollection", features: [] }));
    return () => { live = false; };
  }, [level]);
  useEffect(() => {
    if (!crop) { setWhere(null); return; }
    let live = true;
    api.cropWhere(crop, level, top?.year).then((w) => live && setWhere(w)).catch(() => live && setWhere(null));
    return () => { live = false; };
  }, [crop, level, top?.year]);
  useEffect(() => {
    if (!picked) { setPlace(null); return; }
    let live = true;
    api.cropPlace(picked).then((p) => live && setPlace(p)).catch(() => live && setPlace(null));
    return () => { live = false; };
  }, [picked]);

  const colourOf = useMemo(() => Object.fromEntries((top?.crops ?? []).map((c) => [c.id, c.color])), [top]);
  const nameOf = useMemo(() => Object.fromEntries((top?.crops ?? []).map((c) => [c.id, c.name])), [top]);
  const byId = useMemo(() => Object.fromEntries((top?.places ?? []).map((p) => [p.id, p])), [top]);
  const fill = useMemo(() => {
    const out: Record<string, { c: string; o: number }> = {};
    if (where && crop) {
      const shares = Object.values(where.values).map((v) => v.share ?? 0);
      const most = Math.max(1, ...shares);
      for (const [id, v] of Object.entries(where.values)) out[id] = { c: where.color, o: 0.15 + 0.85 * Math.min(1, (v.share ?? 0) / most) };
    } else {
      for (const p of top?.places ?? []) if (p.top[0]) out[p.id] = { c: colourOf[p.top[0].crop] ?? "#999", o: 0.92 };
    }
    return out;
  }, [top, where, crop, colourOf]);
  const leaders = (top?.crops ?? []).filter((c) => c.top_in > 0);
  const rows = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return (top?.places ?? []).filter((p) => !f || p.name.toLowerCase().includes(f) || p.top.some((t, i) => i < 2 && (nameOf[t.crop] ?? t.crop).toLowerCase().includes(f)))
      .sort((a, b) => b.total_ha - a.total_ha);
  }, [top, filter, nameOf]);
  const lvl = levels?.find((l) => l.level === level);

  if (levels && !levels.length) {
    return <div className="card"><p>No crop figures yet. They come with <code>.\refresh.bat</code>: FAOSTAT gives every country&apos;s crops; US states and
      counties need a free <code>NASS_API_KEY</code> (Settings &gt; Keys, from <a href="https://quickstats.nass.usda.gov/api" target="_blank" rel="noreferrer">USDA Quick Stats</a>);
      New Zealand&apos;s regions come from Stats NZ with <code>STATSNZ_API_KEY</code>. See <Link href="/data">Data status</Link>.</p></div>;
  }
  const h = hover ? byId[hover.id] : null;
  const hw = hover && where ? where.values[hover.id] : null;
  return (
    <div className="grid">
      <div className="chips-row small">
        <span className="seg" role="group" aria-label="Places">
          {(levels ?? []).map((l) => (
            <button key={l.level} className={l.level === level ? "on" : ""} aria-pressed={l.level === level}
              onClick={() => { setLevel(l.level); setYear(null); setPicked(null); setCrop(null); }}>{l.label}</button>))}
        </span>
        {top && top.years.length > 1 && (
          <label>Year{" "}
            <select value={top.year ?? ""} onChange={(e) => setYear(Number(e.target.value))}>
              {[...top.years].reverse().map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </label>)}
        {top && (
          <label>Where is{" "}
            <select value={crop ?? ""} onChange={(e) => setCrop(e.target.value || null)}>
              <option value="">(top crop in each place)</option>
              {[...top.crops].sort((a, b) => b.ha - a.ha).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>{" "}grown?
          </label>)}
        {crop && <button onClick={() => setCrop(null)}>Back to top crops</button>}
      </div>
      {err && <p className="muted">Could not load the crop figures ({err}).</p>}
      <div className="card" style={{ position: "relative" }}>
        <h3 style={{ marginTop: 0 }}>{crop && where ? `Where ${where.name.toLowerCase()} is grown` : `Top crop in each ${{ world: "country", us_state: "state", us_county: "county", nz_region: "region" }[level] ?? "place"} by land`}
          {top?.year ? `, ${top.year}` : ""}</h3>
        <CropMap level={level} shapes={shapes} fill={fill} onHover={setHover} onPick={setPicked} picked={picked} />
        {hover && (
          <div className="small" style={{ position: "absolute", left: Math.min(hover.x + 28, 9999), top: hover.y + 70, pointerEvents: "none", zIndex: 2,
            background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, padding: "6px 9px", boxShadow: "0 2px 6px rgba(0,0,0,.15)", maxWidth: 320 }}>
            <b>{hover.name}</b>
            {hw && where && <div>{where.name}: {ha(hw.ha, us)}, {pct(hw.share)} of crop land (#{hw.rank} crop here)</div>}
            {h ? h.top.slice(0, 3).map((t, i) => (
              <div key={t.crop}><i style={{ display: "inline-block", width: 9, height: 9, borderRadius: 2, background: colourOf[t.crop], marginRight: 5 }} />
                {i + 1}. {nameOf[t.crop] ?? t.crop}: {ha(t.ha, us)} ({pct(t.share)})</div>))
              : <div className="muted">no crop figures</div>}
          </div>)}
        {!crop && leaders.length > 0 && (
          <div className="swatches small" style={{ marginTop: 8 }}>
            {leaders.map((c) => (
              <button key={c.id} className="legend-item link" style={{ color: "inherit" }} title={`Show where ${c.name.toLowerCase()} is grown`} onClick={() => setCrop(c.id)}>
                <i style={{ background: c.color }} />{c.name} <span className="muted">({c.top_in})</span></button>))}
            <span className="legend-item"><i style={{ background: "var(--no-data)" }} />no figures</span>
          </div>)}
        {crop && where && <p className="small muted" style={{ marginBottom: 0 }}>Darker where {where.name.toLowerCase()} takes a bigger share of the place&apos;s crop land;
          {" "}grown in {Object.keys(where.values).length.toLocaleString()} of {top?.places.length.toLocaleString()} places.</p>}
        {top && <p className="caption">{top.source}. {top.note} Numbers in brackets: places where the crop leads. Click a place for its crops over the years.</p>}
      </div>
      {picked && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>{byId[picked]?.name ?? picked}: crops by land <button className="link small" onClick={() => setPicked(null)}>close</button></h3>
          {byId[picked] && (
            <table className="small"><tbody>{byId[picked].top.map((t) => (
              <tr key={t.crop}><td><i style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: colourOf[t.crop], marginRight: 6 }} />{nameOf[t.crop] ?? t.crop}</td>
                <td className="num">{ha(t.ha, us)}</td><td className="num muted">{pct(t.share)}</td>
                <td style={{ width: 160 }}><div style={{ height: 8, width: `${t.share ?? 0}%`, background: colourOf[t.crop], borderRadius: 3 }} /></td></tr>))}</tbody></table>)}
          {place && place.years.length > 1 && (
            <EChart label="Crops by land over the years" height={300} option={() => linesOption(place.crops.slice(0, 6).map((c) => ({
              label: c.name, color: c.color, pts: Object.entries(c.ha).map(([y, v]) => [Number(y), v] as [number, number]) })), ["ha"])} />)}
          {!picked.startsWith("US-") && !picked.startsWith("NZ-") && <p className="small"><Link href={`/entity/${picked}`}>Country page</Link></p>}
        </div>)}
      {top && top.places.length > 0 && (
        <div className="card">
          <div className="chips-row small"><h3 style={{ margin: 0 }}>{lvl?.label ?? top.label} by crop land</h3>
            <input type="search" placeholder="Filter by place or crop" value={filter} onChange={(e) => setFilter(e.target.value)} /></div>
          <div className="table-wrap" style={{ maxHeight: 480, overflow: "auto" }}>
            <table className="small">
              <thead><tr><th>Place</th><th>Top crop</th><th className="num">Share</th><th>Next</th><th className="num">Crop land</th></tr></thead>
              <tbody>{rows.slice(0, 400).map((p) => (
                <tr key={p.id} className={p.id === picked ? "on" : ""}>
                  <td><button className="link" onClick={() => setPicked(p.id)}>{p.name}</button></td>
                  <td><i style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: colourOf[p.top[0]?.crop], marginRight: 6 }} />{nameOf[p.top[0]?.crop] ?? ""}</td>
                  <td className="num">{pct(p.top[0]?.share)}</td>
                  <td className="muted">{p.top[1] ? `${nameOf[p.top[1].crop] ?? p.top[1].crop} (${pct(p.top[1].share)})` : ""}</td>
                  <td className="num">{ha(p.total_ha, us)}</td></tr>))}</tbody>
            </table>
          </div>
          {rows.length > 400 && <p className="small muted">The 400 with the most crop land of {rows.length.toLocaleString()}; filter to find others.</p>}
        </div>)}
    </div>
  );
}
