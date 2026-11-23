"use client";

// Land cover maps year by year (Land > Land cover maps): ESA's 300 m maps every year 1992-2020
// and Esri's 10 m maps every year from 2017, with a year slider; "What changed" colours only the
// land whose cover differs between two years. Below, a country's land that moved from one kind
// of cover to another between the two years, worked out from ESA's maps.

import * as maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";
import CardAsk from "@/components/CardAsk";
import CountryChoice from "@/components/CountryChoice";
import { openAsk } from "@/lib/ai";
import { cssVar } from "@/lib/colors";
import { compact } from "@/lib/format";
import { countryShapes } from "@/lib/geo";
import { COVER_COLOURS } from "@/lib/land";
import { fitBox, maskOf, polysOf } from "@/lib/landcompare";
import {
  addChangeProtocol, coverChange, type CoverChange, LEGEND, MAXZOOM, SOURCE_CREDIT, SOURCE_LABEL, tilesOf, YEARS, type YearSource,
} from "@/lib/landyears";
import { entityColors } from "@/lib/look";

const KIND_LABEL: Record<string, string> = { trees: "Trees", crops: "Cropland", grass: "Grassland", shrub: "Shrubs", bare: "Bare or sparse",
  snow: "Snow and ice", built: "Built-up", water: "Water" };

export default function LandYears({ entity, pick }: { entity: string; pick: (id: string) => void }) {
  const [source, setSource] = useState<YearSource>("lcyears");
  const [view, setView] = useState<"year" | "change">("year");
  const [year, setYear] = useState(2020);
  const [from, setFrom] = useState(1992);
  const [shapes, setShapes] = useState<Record<string, GeoJSON.Geometry>>({});
  const years = YEARS[source];
  const y = Math.min(Math.max(year, years[0]), years[years.length - 1]);
  const y0 = Math.min(Math.max(from, years[0]), y - 1);

  useEffect(() => {
    countryShapes().then((fc) => {
      const out: Record<string, GeoJSON.Geometry> = {};
      const size = (g: GeoJSON.Geometry) => JSON.stringify(g).length;
      for (const f of fc.features) {
        const iso = (f.properties as { iso3?: string } | null)?.iso3;
        if (iso && f.geometry && (!out[iso] || size(f.geometry) > size(out[iso]))) out[iso] = f.geometry;
      }
      setShapes(out);
    }).catch(() => setShapes({}));
  }, []);

  const tiles = view === "year" ? tilesOf(source, y) : `lcchange://${tilesOf(source, y0)}|${tilesOf(source, y)}`;
  const switchSource = (s: YearSource) => {
    setSource(s);
    if (s === "lc10") { setYear(2024); setFrom(2017); } else { setYear(2020); setFrom(1992); }
  };

  return (
    <>
      <div className="card">
        <div className="chips-row small" style={{ gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <CountryChoice value={entity} onChange={pick} />
          <span className="seg" role="group" aria-label="Map">
            {(["lcyears", "lc10"] as YearSource[]).map((s) => (
              <button key={s} type="button" className={source === s ? "on" : ""} aria-pressed={source === s} onClick={() => switchSource(s)}>{SOURCE_LABEL[s]}</button>))}
          </span>
          <span className="seg" role="group" aria-label="View">
            <button type="button" className={view === "year" ? "on" : ""} aria-pressed={view === "year"} onClick={() => setView("year")}>Each year</button>
            <button type="button" className={view === "change" ? "on" : ""} aria-pressed={view === "change"} onClick={() => setView("change")}>What changed</button>
          </span>
        </div>
        <div className="chips-row small" style={{ gap: 10, alignItems: "center", marginTop: 8 }}>
          {view === "change" && (
            <label htmlFor="lcy-from">From <select id="lcy-from" value={y0} onChange={(e) => setFrom(Number(e.target.value))}>
              {years.filter((v) => v < y).map((v) => <option key={v} value={v}>{v}</option>)}</select></label>)}
          <label htmlFor="lcy-year" style={{ display: "flex", alignItems: "center", gap: 8, flex: "1 1 260px" }}>
            {view === "change" ? "to" : "Year"}
            <input id="lcy-year" type="range" min={years[0] + (view === "change" ? 1 : 0)} max={years[years.length - 1]} value={y}
              onChange={(e) => setYear(Number(e.target.value))} style={{ flex: 1 }} />
            <b className="num">{y}</b>
          </label>
        </div>
        <YearsMap geometry={shapes[entity]} tiles={tiles} maxzoom={MAXZOOM[source]} colour={entityColors([entity])[0] || cssVar("--ink")} />
        <div className="swatches small" style={{ marginTop: 6 }}>
          {LEGEND[source].map(([n, c]) => <span key={n} className="legend-item"><i style={{ background: c, outline: "1px solid var(--border)" }} />{n}</span>)}
          {view === "change" && <span className="legend-item"><i style={{ background: "rgba(150,150,150,0.4)" }} />Same in both years</span>}
        </div>
        <p className="caption">
          {view === "change"
            ? `Land whose cover in ${y} differs from ${y0}, in its ${y} colour; land that stayed the same is faint grey. `
            : ""}
          {SOURCE_CREDIT[source]}. {source === "lcyears"
            ? "300 m pixels: good for forests, farms and big towns, too coarse for a suburb. Saved copies (Settings > Maps) make the slider quick."
            : "10 m pixels, sharp enough for a town. Esri's maps can call the same land differently from year to year (clouds, season), so small changes are often noise."}
          {" "}Zoom in with the scroll wheel; the rest of the world is shaded.
        </p>
      </div>
      <ChangeTable entity={entity} y0={source === "lcyears" ? y0 : 1992} y1={source === "lcyears" ? y : 2020} />
    </>
  );
}

function YearsMap({ geometry, tiles, maxzoom, colour }: { geometry?: GeoJSON.Geometry; tiles: string; maxzoom: number; colour: string }) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!el.current) return;
    addChangeProtocol();
    const m = new maplibregl.Map({
      container: el.current,
      style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": cssVar("--no-data") } }] },
      center: [174, -41], zoom: 3, maxZoom: 14, dragRotate: false, pitchWithRotate: false, renderWorldCopies: true, attributionControl: false,
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.current = m;
    m.on("load", () => {
      m.resize();
      m.addSource("mask", { type: "geojson", data: maskOf([]) });
      m.addSource("country", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({ id: "mask", type: "fill", source: "mask", paint: { "fill-color": cssVar("--surface"), "fill-opacity": 0.65 } });
      m.addLayer({ id: "outline", type: "line", source: "country", paint: { "line-color": colour, "line-width": 1.8 } });
      setReady(true);
    });
    return () => { setReady(false); m.remove(); map.current = null; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !geometry) return;
    const polys = polysOf(geometry);
    (m.getSource("mask") as maplibregl.GeoJSONSource).setData(maskOf(polys));
    (m.getSource("country") as maplibregl.GeoJSONSource).setData({ type: "Feature", properties: {}, geometry });
    m.setPaintProperty("outline", "line-color", colour);
    const box = fitBox(polys);
    if (box) m.fitBounds(box, { padding: 20, animate: false });
  }, [geometry, ready, colour]);

  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    if (m.getLayer("cover")) m.removeLayer("cover");
    if (m.getSource("cover")) m.removeSource("cover");
    m.addSource("cover", { type: "raster", tiles: [tiles], tileSize: 256, maxzoom });
    m.addLayer({ id: "cover", type: "raster", source: "cover", paint: { "raster-resampling": "nearest", "raster-fade-duration": 0 } }, "mask");
  }, [tiles, maxzoom, ready]);

  return <div ref={el} style={{ height: 420, borderRadius: 10, overflow: "hidden", marginTop: 8 }} />;
}

function ChangeTable({ entity, y0, y1 }: { entity: string; y0: number; y1: number }) {
  const [d, setD] = useState<CoverChange | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asked, setAsked] = useState<string | null>(null);
  const key = `${entity}|${y0}|${y1}`;
  useEffect(() => { setD(null); setError(null); }, [key]);
  const run = () => {
    setAsked(key); setError(null);
    coverChange(entity, y0, y1).then(setD).catch((e) => setError(String(e.message || e).replace(/^\d+: /, "")));
  };
  const rows = useMemo(() => (d ? d.kinds.filter((k) => d.totals[k].from + d.totals[k].to > 0) : []), [d]);
  const ha = (v: number) => `${compact(v)} ha`;
  const text = () => (d ? [`Land cover change,${entity},${y0} to ${y1}`, "From,To,Hectares",
    ...d.changes.map((c) => `${c.from},${c.to},${c.ha}`)].join("\n") : "");

  return (
    <div className="card">
      <div className="title-row">
        <h3>What turned into what, {y0} to {y1}</h3>
        {d && <CardAsk onAsk={() => openAsk({ title: `Land cover change in ${entity}, ${y0} to ${y1}`, entity,
          parts: [{ key: "data", kind: "data", label: "Changes (ESA CCI, hectares)", text: text() }] })} />}
      </div>
      {!d && asked !== key && <p className="small">Works out, from ESA&apos;s maps, how much of the country moved from each kind of cover to another.
        {" "}<button type="button" onClick={run}>Work it out</button></p>}
      {!d && asked === key && !error && <p className="small muted">Reading the two years&apos; maps… (up to a minute the first time)</p>}
      {error && <p className="small error">{error}</p>}
      {d && (
        <div className="grid two">
          <div style={{ minWidth: 0 }}>
            <table className="summary-table small">
              <thead><tr><th>Kind of cover</th><th className="num">{y0}</th><th className="num">{y1}</th><th className="num">Change</th></tr></thead>
              <tbody>{rows.map((k) => {
                const t = d.totals[k];
                const ch = t.to - t.from;
                return (
                  <tr key={k}><td><span className="legend-item"><i style={{ background: COVER_COLOURS[k] }} />{KIND_LABEL[k] ?? k}</span></td>
                    <td className="num">{ha(t.from)}</td><td className="num">{ha(t.to)}</td>
                    <td className="num" style={{ color: ch > 0 ? "var(--good, inherit)" : ch < 0 ? "var(--bad, inherit)" : undefined }}>
                      {ch > 0 ? "+" : ch < 0 ? "−" : ""}{ha(Math.abs(ch))}{t.from ? ` (${ch >= 0 ? "+" : "−"}${Math.abs((ch / t.from) * 100).toFixed(1)}%)` : ""}</td></tr>);
              })}</tbody>
            </table>
          </div>
          <div style={{ minWidth: 0 }}>
            <table className="summary-table small">
              <thead><tr><th>From → to</th><th className="num">Hectares</th></tr></thead>
              <tbody>{d.changes.slice(0, 12).map((c) => (
                <tr key={`${c.from}-${c.to}`}><td>{KIND_LABEL[c.from] ?? c.from} → {KIND_LABEL[c.to] ?? c.to}</td><td className="num">{c.ha.toLocaleString()}</td></tr>))}</tbody>
            </table>
          </div>
        </div>
      )}
      {d && <p className="caption">Read from ESA CCI / C3S maps at about {d.pixel_km} km a pixel ({d.tiles} pictures each year{d.missing ? `, ${d.missing} missing` : ""}).
        Totals are close to FAOSTAT&apos;s land cover shares, which come from the same maps; small changes between years are within the maps&apos; error.</p>}
    </div>
  );
}
