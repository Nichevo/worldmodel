"use client";

// Land cover side by side: each country's outline beside a stacked bar of its land cover (ESA's
// satellite maps as FAOSTAT adds them up). Pick a kind of cover in any bar and every map shows
// where that cover is (ESA WorldCover pictures, recoloured on this PC); "All" shows every kind.

import * as maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";
import CardAsk from "@/components/CardAsk";
import CountryChoice from "@/components/CountryChoice";
import { quietMapErrors } from "@/lib/basemap";
import { openAsk } from "@/lib/ai";
import { api, type LandCover } from "@/lib/api";
import { cssVar } from "@/lib/colors";
import { countryShapes } from "@/lib/geo";
import {
  addCoverProtocol, barLayout, onTileCount, tileCount, COVER_COLOURS, COVER_ORDER, type CoverId, fitBox, maskOf, pct, polysOf, sameScaleZooms,
} from "@/lib/landcompare";
import { entityColors, entityVar } from "@/lib/look";
import { windowData } from "@/lib/layers";
import { tileUrl } from "@/lib/maplook";
import { useSettings } from "@/lib/settings";

export type Show = null | "all" | CoverId;
const LABELS: Record<CoverId, string> = { trees: "Tree cover", crops: "Cropland", grass: "Grassland", shrub: "Shrubs and sparse plants",
  bare: "Bare land", snow: "Snow and ice", built: "Built-up land", water: "Inland water" };
const SHORT: Record<CoverId, string> = { trees: "trees", crops: "crops", grass: "grass", shrub: "shrubs", bare: "bare", snow: "snow",
  built: "built-up", water: "water" };
const MAP_H = 340;
const BAR_H = 300;

type Fit = { zoom: number; lat: number; centre: [number, number] };

export default function LandCompare({ initial, onChange }: { initial: string[]; onChange?: (ids: string[]) => void }) {
  const [ids, setIds] = useState<string[]>(initial.length ? initial : ["NZL", "AUS"]);
  const [covers, setCovers] = useState<Record<string, LandCover | null>>({});
  const [shapes, setShapes] = useState<Record<string, GeoJSON.Geometry>>({});
  const [show, setShow] = useState<Show>(null);
  const [year, setYear] = useState<number | null>(null);
  const [same, setSame] = useState(false);
  const [rivers, setRivers] = useState(false);
  const [fits, setFits] = useState<Record<string, Fit>>({});
  const [adding, setAdding] = useState("");
  const [tilesMissing, setTilesMissing] = useState(false);
  useEffect(() => onTileCount(() => setTilesMissing(tileCount.missing > 0 && tileCount.ok === 0)), []);

  useEffect(() => { onChange?.(ids); }, [ids]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    for (const id of ids) if (!(id in covers)) api.landCover(id).then((c) => setCovers((o) => ({ ...o, [id]: c }))).catch(() => setCovers((o) => ({ ...o, [id]: null })));
  }, [ids, covers]);
  useEffect(() => {
    countryShapes().then((fc) => {
      const out: Record<string, GeoJSON.Geometry> = {};
      const size = (g: GeoJSON.Geometry) => JSON.stringify(g).length;
      for (const f of fc.features) {
        const iso = (f.properties as { iso3?: string } | null)?.iso3;
        // Some territories share their country's code: keep the biggest shape.
        if (iso && f.geometry && (!out[iso] || size(f.geometry) > size(out[iso]))) out[iso] = f.geometry;
      }
      setShapes(out);
    }).catch(() => setShapes({}));
  }, []);

  const years = useMemo(() => [...new Set(ids.flatMap((id) => covers[id]?.parts.flatMap((p) => p.points.map((x) => x[0])) ?? []))].sort((a, b) => a - b), [ids, covers]);
  const y = year ?? years.at(-1) ?? null;
  const shareOf = (id: string): Partial<Record<CoverId, number>> => {
    const out: Partial<Record<CoverId, number>> = {};
    for (const p of covers[id]?.parts ?? []) {
      const pt = p.points.find((x) => x[0] === y) ?? null;
      if (pt) out[p.id as CoverId] = pt[1];
    }
    return out;
  };
  const colours = entityColors(ids);
  const zooms = useMemo(() => {
    if (!same || ids.some((id) => !fits[id])) return null;
    const z = sameScaleZooms(ids.map((id) => fits[id]));
    return Object.fromEntries(ids.map((id, i) => [id, z[i]]));
  }, [same, ids, fits]);

  const remove = (id: string) => setIds((v) => v.filter((x) => x !== id));
  const add = (id: string) => { if (id && !ids.includes(id) && ids.length < 4) setIds((v) => [...v, id]); setAdding(""); };
  const name = (id: string) => covers[id]?.name ?? id;
  const askText = () => ["Kind\t" + ids.map(name).join("\t"),
    ...COVER_ORDER.map((c) => `${LABELS[c]}\t${ids.map((id) => shareOf(id)[c]?.toFixed(2) ?? "").join("\t")}`)].join("\n");

  return (
    <>
      <div className="card">
        <div className="card-head"><h3>Land cover side by side{y ? `, ${y}` : ""}</h3>
          <CardAsk onAsk={() => openAsk({ title: `Land cover: ${ids.map(name).join(", ")}`, parts: [{ key: "lc", kind: "data", label: `Share of land and inland water, ${y}`, text: askText() }] })} /></div>
        <div className="chips-row small" role="group" aria-label="Countries">
          {ids.map((id, i) => (
            <span key={id} className="chip-btn lc-chip" style={{ borderColor: entityVar(id, i) }}>{name(id)}
              {ids.length > 1 && <button className="link" aria-label={`Remove ${name(id)}`} onClick={() => remove(id)}>×</button>}</span>))}
          {ids.length < 4 && <CountryChoice value={adding} onChange={add} label="Add a country" />}
          {years.length > 1 && <select value={y ?? ""} onChange={(e) => setYear(+e.target.value)} aria-label="Year">
            {[...years].reverse().map((v) => <option key={v} value={v}>{v}</option>)}</select>}
          <label className="small"><input type="checkbox" checked={same} onChange={(e) => setSame(e.target.checked)} /> Same scale</label>
          <label className="small"><input type="checkbox" checked={rivers} onChange={(e) => setRivers(e.target.checked)} /> Rivers</label>
        </div>
        <div className="chips-row small" role="group" aria-label="Show on the maps">
          <span className="muted">Show on the maps:</span>
          <button className={show === null ? "on" : ""} onClick={() => setShow(null)}>Outline only</button>
          <button className={show === "all" ? "on" : ""} onClick={() => setShow("all")}>All kinds</button>
          {COVER_ORDER.map((c) => (
            <button key={c} className={show === c ? "on" : ""} onClick={() => setShow(show === c ? null : c)}>
              <i className="lc-key" style={{ background: COVER_COLOURS[c] }} />{LABELS[c]}</button>))}
        </div>
      </div>
      <div className="lc-grid">
        {ids.map((id, i) => (
          <div key={id} className="card lc-panel">
            <div className="lc-name" style={{ background: entityVar(id, i) }}>{name(id)}</div>
            <div className="lc-body">
              <CoverMap geometry={shapes[id]} colour={colours[i]} show={show} rivers={rivers} zoom={zooms?.[id] ?? null}
                onFit={(f) => setFits((o) => (o[id]?.zoom === f.zoom ? o : { ...o, [id]: f }))} />
              {covers[id] === undefined ? <p className="muted small lc-bar-col">Loading…</p>
                : !covers[id]?.parts.length ? <p className="muted small lc-bar-col">No land cover figures for {name(id)} yet (FAOSTAT, with <code>.\refresh.bat</code>).</p>
                  : <CoverBar shares={shareOf(id)} show={show} pick={(c) => setShow(show === c ? null : c)} />}
            </div>
          </div>))}
      </div>
      {show !== null && tilesMissing && <p className="notice small">The land cover pictures didn&apos;t come: there are no saved copies on this PC and
        Terrascope (ESA WorldCover&apos;s map service) didn&apos;t answer. The bars and table still hold. Try again later, or save an area&apos;s
        Land cover pictures in Settings &gt; Maps.</p>}
      {ids.length > 1 && <CompareTable ids={ids} names={ids.map(name)} shares={ids.map(shareOf)} show={show} pick={(c) => setShow(show === c ? null : c)} />}
      <p className="caption">Bars: share of land and inland water in each kind of cover, from ESA&apos;s yearly 300 m satellite maps as FAOSTAT adds them up
        by country (coastal water and tidal flats left out). Borders: Natural Earth. Maps: ESA WorldCover at 10 m for {useSettings().land_cover_year === "2020" ? 2020 : 2021} (CC BY 4.0), the
        same picture as the Map&apos;s Land cover look, recoloured to match the bars. The two sort land a little differently (WorldCover counts sparse plants as bare;
        flooded shrubs and moss go with shrubs here), and small patches such as towns fade when zoomed out, so zoom in to see them. Same scale draws every
        country at the same km per pixel at its centre. Rivers: HydroRIVERS, down to 1 m³/s as you zoom in (the Map&apos;s Rivers layer; needs Settings &gt; Rivers and river basins on and a refresh).</p>
    </>
  );
}

function CoverBar({ shares, show, pick }: { shares: Partial<Record<CoverId, number>>; show: Show; pick: (c: CoverId) => void }) {
  const segs = barLayout(shares, BAR_H);
  const dim = (c: CoverId) => show !== null && show !== "all" && show !== c;
  return (
    <div className="lc-bar-col">
      <svg width={168} height={BAR_H + 4} role="img" aria-label={segs.map((s) => `${LABELS[s.id]} ${pct(s.share)}`).join(", ")}>
        <rect x={1} y={1} width={44} height={BAR_H + 2} rx={8} fill="none" stroke="var(--border)" />
        {segs.map((s) => (
          <g key={s.id} style={{ cursor: "pointer" }} onClick={() => pick(s.id)} opacity={dim(s.id) ? 0.3 : 1}>
            <title>{`${LABELS[s.id]}: ${pct(s.share)}`}</title>
            <rect x={2} y={2 + s.y0} width={42} height={Math.max(0.5, s.y1 - s.y0)} fill={COVER_COLOURS[s.id]} />
            <path d={`M46 ${2 + (s.y0 + s.y1) / 2} L54 ${2 + s.labelY}`} stroke="var(--muted)" fill="none" />
            <rect x={56} y={s.labelY - 5} width={10} height={10} rx={2} fill={COVER_COLOURS[s.id]} />
            <text x={70} y={s.labelY + 5} fontSize={14} fontWeight={show === s.id ? 800 : 600} fill="var(--ink)">{pct(s.share)}
              <tspan dx={4} fontSize={10.5} fontWeight={400} fill="var(--muted)">{SHORT[s.id]}</tspan></text>
          </g>))}
      </svg>
    </div>
  );
}

function CompareTable({ ids, names, shares, show, pick }: { ids: string[]; names: string[]; shares: Partial<Record<CoverId, number>>[]; show: Show; pick: (c: CoverId) => void }) {
  return (
    <div className="card">
      <div className="card-head"><span className="small ink-2">Share of land, by kind of cover</span></div>
      <table className="small lc-table">
        <thead><tr><th />{names.map((n, i) => <th key={ids[i]} className="num">{n}</th>)}</tr></thead>
        <tbody>{[...COVER_ORDER].reverse().map((c) => {
          const vals = shares.map((s) => s[c] ?? null);
          const top = Math.max(...vals.map((v) => v ?? -1));
          return (
            <tr key={c} className={show === c ? "on" : ""} onClick={() => pick(c)} style={{ cursor: "pointer" }}>
              <td><i className="lc-key" style={{ background: COVER_COLOURS[c] }} />{LABELS[c]}</td>
              {vals.map((v, i) => <td key={ids[i]} className="num" style={{ fontWeight: v !== null && v === top && ids.length > 1 ? 700 : 400 }}>{v === null ? "–" : pct(v)}</td>)}
            </tr>);
        })}</tbody>
      </table>
    </div>
  );
}

// One country's outline on a plain background, with the land cover picked drawn inside it.
function CoverMap({ geometry, colour, show, rivers, zoom, onFit }: { geometry?: GeoJSON.Geometry; colour: string; show: Show; rivers: boolean; zoom: number | null;
  onFit: (f: Fit) => void }) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const fit = useRef<Fit | null>(null);
  const settings = useSettings();
  const tiles = tileUrl("landcover", { map_tiles: settings.map_tiles, night_year: settings.night_year, land_cover_year: settings.land_cover_year });

  useEffect(() => {
    if (!el.current || !geometry) return;
    addCoverProtocol();
    const polys = polysOf(geometry);
    const box = fitBox(polys);
    const bg = cssVar("--no-data");
    const m = new maplibregl.Map({
      container: el.current,
      style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": bg } }] },
      bounds: box ?? undefined, fitBoundsOptions: { padding: 16 },
      maxZoom: 12, scrollZoom: false, dragRotate: false, pitchWithRotate: false, renderWorldCopies: true,
      attributionControl: false, // the caption below names Natural Earth and ESA WorldCover
    });
    quietMapErrors(m);
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.current = m;
    m.on("load", () => {
      m.resize(); // the box may have changed size since the map was made
      if (box) m.fitBounds(box, { padding: 16, animate: false });
      m.addSource("mask", { type: "geojson", data: maskOf(polys) });
      m.addSource("country", { type: "geojson", data: { type: "Feature", properties: {}, geometry } });
      m.addLayer({ id: "land", type: "fill", source: "country", paint: { "fill-color": cssVar("--surface"), "fill-opacity": 1 } });
      m.addLayer({ id: "mask", type: "fill", source: "mask", paint: { "fill-color": bg, "fill-opacity": 1 } });
      m.addLayer({ id: "outline", type: "line", source: "country", paint: { "line-color": colour, "line-width": 2.2 } });
      const c = m.getCenter();
      fit.current = { zoom: m.getZoom(), lat: c.lat, centre: [c.lng, c.lat] };
      onFit(fit.current);
      setReady(true);
    });
    return () => { setReady(false); m.remove(); map.current = null; };
  }, [geometry]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    if (m.getLayer("cover")) m.removeLayer("cover");
    if (m.getSource("cover")) m.removeSource("cover");
    if (show === null) return;
    m.addSource("cover", { type: "raster", tiles: [`lcpick://${show}@${tiles}`], tileSize: 256, maxzoom: 14 });
    m.addLayer({ id: "cover", type: "raster", source: "cover", paint: { "raster-resampling": "nearest", "raster-fade-duration": 0 } }, "mask");
  }, [show, ready, tiles]);

  useEffect(() => { if (map.current && ready) map.current.setPaintProperty("outline", "line-color", colour); }, [colour, ready]);

  // Rivers (HydroRIVERS, as on the Map's Rivers layer) for the area in view, under the mask so
  // only the country's own rivers show; asked again after each move with the detail for the zoom.
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const empty: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
    if (!m.getSource("rivers")) {
      m.addSource("rivers", { type: "geojson", data: empty });
      m.addLayer({ id: "rivers", type: "line", source: "rivers", layout: { visibility: "none" },
        paint: { "line-color": "#2e86c1", "line-opacity": 0.85,
          "line-width": ["interpolate", ["linear"], ["coalesce", ["get", "rank"], 5], 1, 2.4, 3, 1.2, 5, 0.5] } }, "mask");
    }
    m.setLayoutProperty("rivers", "visibility", rivers ? "visible" : "none");
    if (!rivers) return;
    let live = true;
    const load = () => {
      const b = m.getBounds();
      windowData("rivers", { west: b.getWest(), south: b.getSouth(), east: b.getEast(), north: b.getNorth() }, m.getZoom())
        .then((fc) => { if (live) (m.getSource("rivers") as maplibregl.GeoJSONSource | undefined)?.setData(fc.features ? fc : empty); })
        .catch(() => undefined);
    };
    load();
    m.on("moveend", load);
    return () => { live = false; m.off("moveend", load); };
  }, [rivers, ready]);

  useEffect(() => {
    const m = map.current;
    const f = fit.current;
    if (!m || !ready || !f) return;
    m.jumpTo({ center: f.centre, zoom: zoom ?? f.zoom });
  }, [zoom, ready]);

  if (!geometry) return <div className="lc-map muted small">No outline for this one.</div>;
  return <div ref={el} className="lc-map" style={{ height: MAP_H }} />;
}
