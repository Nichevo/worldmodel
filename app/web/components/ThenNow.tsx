"use client";

// Then and now: two dated pictures of the same place, wiped with a slider, side by side or
// flicking between them, and "What changed?" asking the local AI with both pictures.

import * as maplibregl from "maplibre-gl";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { quietMapErrors } from "@/lib/basemap";
import { useSettings } from "@/lib/settings";
import { changeTiles } from "@/lib/spotting";
import { askWhatChanged, type Dates, defaultPair, pairDownload, placeDates, type Source, sources, waybackVersions,
  type WaybackVersion } from "@/lib/thennow";

type Mode = "slider" | "side" | "flicker";
const PLACES: [string, number, number, number][] = [
  ["Rolleston", 172.38, -43.595, 15], ["Christchurch red zone", 172.70, -43.51, 15], ["Auckland, Hobsonville", 174.66, -36.79, 15],
  ["Tauranga port", 176.18, -37.65, 14], ["Queenstown, Frankton", 168.73, -45.02, 15], ["Dubai Marina", 55.14, 25.08, 14],
];

function rasterStyle(s: Source | undefined): maplibregl.StyleSpecification {
  return {
    version: 8, sources: s ? { pic: { type: "raster", tiles: [s.tiles], tileSize: 256, maxzoom: s.maxzoom, attribution: s.attribution } } : {},
    layers: [{ id: "bg", type: "background", paint: { "background-color": "#20262c" } }, ...(s ? [{ id: "pic", type: "raster" as const, source: "pic" }] : [])],
  };
}

export default function ThenNow({ start, onTimelapse, model }: {
  start?: { lon: number; lat: number; zoom: number }; onTimelapse: (bbox: number[], name: string) => void; model?: string | null;
}) {
  const s = useSettings();
  const wrap = useRef<HTMLDivElement>(null);
  const elA = useRef<HTMLDivElement>(null);
  const elB = useRef<HTMLDivElement>(null);
  const maps = useRef<{ a: maplibregl.Map | null; b: maplibregl.Map | null }>({ a: null, b: null });
  const [centre, setCentre] = useState(start ?? { lon: 172.38, lat: -43.595, zoom: 15 });
  const [dates, setDates] = useState<Dates | null>(null);
  const [wayback, setWayback] = useState<WaybackVersion[]>([]);
  const [wbNote, setWbNote] = useState<string | null>(null);
  const [pick, setPick] = useState<[string, string] | null>(null);
  const [mode, setMode] = useState<Mode>("slider");
  const [pos, setPos] = useState(50);
  const [flickOn, setFlickOn] = useState(true);
  const [change, setChange] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const list = useMemo(() => sources(dates, wayback), [dates, wayback]);
  const a = list.find((x) => x.id === pick?.[0]);
  const b = list.find((x) => x.id === pick?.[1]);

  // two maps, one over the other, moving together
  useEffect(() => {
    if (!elA.current || !elB.current) return;
    const opts = { center: [centre.lon, centre.lat] as [number, number], zoom: centre.zoom, maxZoom: 20, dragRotate: false, pitchWithRotate: false, attributionControl: false as const };
    const ma = new maplibregl.Map({ container: elA.current, style: rasterStyle(undefined), ...opts });
    const mb = new maplibregl.Map({ container: elB.current, style: rasterStyle(undefined), ...opts });
    quietMapErrors(ma);
    quietMapErrors(mb);
    mb.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    mb.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    let syncing = false;
    const follow = (from: maplibregl.Map, to: maplibregl.Map) => () => {
      if (syncing) return;
      syncing = true;
      to.jumpTo({ center: from.getCenter(), zoom: from.getZoom() });
      syncing = false;
    };
    ma.on("move", follow(ma, mb));
    mb.on("move", follow(mb, ma));
    let t: ReturnType<typeof setTimeout> | undefined;
    const moved = () => {
      clearTimeout(t);
      t = setTimeout(() => { const c = mb.getCenter(); setCentre({ lon: c.lng, lat: c.lat, zoom: mb.getZoom() }); }, 700);
    };
    mb.on("moveend", moved);
    ma.on("moveend", moved);
    maps.current = { a: ma, b: mb };
    return () => { clearTimeout(t); ma.remove(); mb.remove(); maps.current = { a: null, b: null }; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // what pictures there are here (again when the map moves somewhere else)
  const lastAsk = useRef<string>("");
  useEffect(() => {
    const key = `${centre.lon.toFixed(3)},${centre.lat.toFixed(3)}`;
    if (key === lastAsk.current) return;
    lastAsk.current = key;
    placeDates(centre.lon, centre.lat).then((d) => { setDates(d); setErr(null); }).catch((e) => setErr(String(e.message || e)));
    if (centre.zoom >= 11) {
      setWbNote("Looking up Esri's older versions…");
      waybackVersions(centre.lon, centre.lat).then((w) => { setWayback(w.versions); setWbNote(w.error); }).catch(() => setWbNote("Esri's older versions could not be read."));
    } else { setWayback([]); setWbNote("Zoom in to list Esri's older versions here."); }
  }, [centre]);

  // keep the picked pair while it is still on offer here, else pick again
  useEffect(() => {
    if (!dates) return;
    const ids = new Set(list.map((x) => x.id));
    if (!pick || !ids.has(pick[0]) || !ids.has(pick[1])) setPick(defaultPair(list, dates));
  }, [dates, list]); // eslint-disable-line react-hooks/exhaustive-deps

  // the pictures on each map, and the land change layer over both if asked
  useEffect(() => {
    const { a: ma, b: mb } = maps.current;
    if (!ma || !mb) return;
    const put = (m: maplibregl.Map, src: Source | undefined) => {
      const set = () => {
        if (m.getLayer("change")) m.removeLayer("change");
        if (m.getSource("change")) m.removeSource("change");
        if (m.getLayer("pic")) m.removeLayer("pic");
        if (m.getSource("pic")) m.removeSource("pic");
        if (src) {
          m.addSource("pic", { type: "raster", tiles: [src.tiles], tileSize: 256, maxzoom: src.maxzoom, attribution: src.attribution });
          m.addLayer({ id: "pic", type: "raster", source: "pic" });
        }
        if (change && a && b) {
          const y0 = Math.max(2017, Math.min(2024, Math.min(a.year, b.year))), y1 = Math.max(y0 + 1, Math.min(2025, Math.max(a.year, b.year)));
          m.addSource("change", { type: "raster", tiles: [changeTiles("lc10", y0, y1)], tileSize: 256, maxzoom: 14 });
          m.addLayer({ id: "change", type: "raster", source: "change", paint: { "raster-opacity": 0.75 } });
        }
      };
      if (m.isStyleLoaded()) set(); else m.once("load", set);
    };
    put(ma, a);
    put(mb, b);
  }, [a?.id, b?.id, change]); // eslint-disable-line react-hooks/exhaustive-deps

  // side by side needs the maps resized
  useEffect(() => { setTimeout(() => { maps.current.a?.resize(); maps.current.b?.resize(); }, 50); }, [mode]);
  useEffect(() => {
    if (mode !== "flicker") return;
    const t = setInterval(() => setFlickOn((v) => !v), 900);
    return () => clearInterval(t);
  }, [mode]);

  const drag = (e: React.PointerEvent) => {
    const box = wrap.current?.getBoundingClientRect();
    if (!box) return;
    const move = (ev: PointerEvent) => setPos(Math.max(0, Math.min(100, ((ev.clientX - box.left) / box.width) * 100)));
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    e.preventDefault();
  };
  const fly = (lon: number, lat: number, zoom: number) => maps.current.b?.flyTo({ center: [lon, lat], zoom });
  const viewBox = (): number[] | null => {
    const m = maps.current.b;
    if (!m) return null;
    const bb = m.getBounds();
    return [bb.getWest(), bb.getSouth(), bb.getEast(), bb.getNorth()].map((v) => Math.round(v * 1000) / 1000);
  };
  const linzCount = dates?.linz.length ?? 0;
  const side = mode === "side";
  const aStyle: React.CSSProperties = side ? { position: "absolute", left: 0, top: 0, width: "calc(50% - 2px)", height: "100%" }
    : { position: "absolute", inset: 0, zIndex: 2, clipPath: mode === "slider" ? `inset(0 ${100 - pos}% 0 0)` : undefined,
      visibility: mode === "flicker" && !flickOn ? "hidden" : "visible" };
  const bStyle: React.CSSProperties = side ? { position: "absolute", right: 0, top: 0, width: "calc(50% - 2px)", height: "100%" } : { position: "absolute", inset: 0 };
  const choice = (i: 0 | 1) => (
    <select value={pick?.[i] ?? ""} onChange={(e) => setPick((p) => (i === 0 ? [e.target.value, p?.[1] ?? ""] : [p?.[0] ?? "", e.target.value]))}
      aria-label={i === 0 ? "Before" : "After"} style={{ maxWidth: 380 }}>
      {linzCount > 0 && <optgroup label="LINZ aerial photos (New Zealand)">{list.filter((x) => x.kind === "linz").map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</optgroup>}
      <optgroup label="Esri World Imagery (looking only)">{list.filter((x) => x.kind === "esri" || x.kind === "wayback").map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</optgroup>
      <optgroup label="Sentinel-2 cloudless, 10 m">{list.filter((x) => x.kind === "eox").map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</optgroup>
    </select>
  );
  return (
    <div className="card">
      <div className="chips-row small">
        <span className="muted">Go to</span>
        {PLACES.map(([n, lo, la, z]) => <button key={n} className="link small" style={{ marginRight: 8 }} onClick={() => fly(lo, la, z)}>{n}</button>)}
      </div>
      <div className="chips-row small">
        <span className="seg" role="group" aria-label="How to compare">
          {([["slider", "Slider"], ["side", "Side by side"], ["flicker", "Flicker"]] as const).map(([v, t]) => (
            <button key={v} className={mode === v ? "on" : ""} aria-pressed={mode === v} onClick={() => setMode(v)}>{t}</button>))}
        </span>
        <label>Before {choice(0)}</label>
        <label>After {choice(1)}</label>
      </div>
      <p className="small muted" style={{ margin: "4px 0" }}>
        {dates ? <>{list.length} pictures here: {linzCount ? `${linzCount} LINZ surveys (${[...new Set(dates.linz.map((x) => x.year_to))].filter(Boolean).slice(-1)[0]} to ${dates.linz[0].year_to})` : dates.nz ? "no LINZ surveys listed here" : "outside New Zealand, so no LINZ photos"}
          {wayback.length ? `, ${wayback.length} Esri versions where this spot changed` : ""}, {dates.eox.length} Sentinel-2 years.</> : "Finding the pictures of this place…"}
        {wbNote && <> {wbNote}</>}
        {dates?.linz_list.state === "running" && " Reading LINZ's list of surveys for the first time (about half a minute)…"}
        {dates?.linz_list.error && <span className="warn-text"> {dates.linz_list.error}</span>}
      </p>
      {dates?.nz && !dates.linz_key && (
        <p className="small warn-text">LINZ&apos;s aerial photos need a free key: add LINZ_BASEMAPS_API_KEY under <Link href="/data">Data status</Link> &gt; Keys you can add. Until then the LINZ pictures stay blank.</p>)}
      {err && <p className="small warn-text">{err}</p>}
      <div ref={wrap} style={{ position: "relative", height: 560, borderRadius: 6, overflow: "hidden", background: "#20262c" }}>
        <div ref={elA} style={aStyle} />
        <div ref={elB} style={bStyle} />
        {mode === "slider" && (
          <div onPointerDown={drag} role="slider" aria-label="Before and after" aria-valuenow={Math.round(pos)} aria-valuemin={0} aria-valuemax={100} tabIndex={0}
            onKeyDown={(e) => { if (e.key === "ArrowLeft") setPos((p) => Math.max(0, p - 5)); if (e.key === "ArrowRight") setPos((p) => Math.min(100, p + 5)); }}
            style={{ position: "absolute", top: 0, bottom: 0, left: `calc(${pos}% - 14px)`, width: 28, zIndex: 3, cursor: "ew-resize", display: "flex", justifyContent: "center" }}>
            <div style={{ width: 3, background: "#fff", boxShadow: "0 0 4px rgba(0,0,0,.6)" }} />
            <div style={{ position: "absolute", top: "50%", width: 28, height: 28, marginTop: -14, borderRadius: 14, background: "#fff", boxShadow: "0 0 4px rgba(0,0,0,.5)",
              display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13 }}>⇔</div>
          </div>)}
        <span style={{ position: "absolute", left: 8, top: 8, zIndex: 4, background: "rgba(0,0,0,.6)", color: "#fff", padding: "2px 6px", borderRadius: 4, fontSize: 12 }}>
          Before: {a?.label.split(" · ")[0] ?? "…"}</span>
        <span style={{ position: "absolute", right: side ? 8 : 48, top: 8, zIndex: 4, background: "rgba(0,0,0,.6)", color: "#fff", padding: "2px 6px", borderRadius: 4, fontSize: 12 }}>
          After: {b?.label.split(" · ")[0] ?? "…"}</span>
      </div>
      <div className="chips-row small" style={{ marginTop: 8 }}>
        <button disabled={!a || !b || s.ai_enabled === false} onClick={() => a && b && void askWhatChanged(centre.lon, centre.lat, Math.min(19, Math.round(centre.zoom) + 1), a, b, model)}>
          What changed? Ask AI</button>
        <label><input type="checkbox" checked={change} onChange={(e) => setChange(e.target.checked)} /> Land change layer on top</label>
        <button className="link small" onClick={() => { const bb = viewBox(); if (bb) onTimelapse(bb, `Near ${centre.lat.toFixed(2)}, ${centre.lon.toFixed(2)}`); }}>Timelapse here</button>
        {a && b && <a className="small" href={pairDownload(centre.lon, centre.lat, Math.min(19, Math.round(centre.zoom) + 1), a, b)}>Save both pictures</a>}
      </div>
      <p className="caption">Drag the map to move both pictures; drag the white handle to wipe between them. LINZ&apos;s photos go back to the 1930s in places
        (black and white before the 1980s) and down to 5-7.5 cm in cities. Esri&apos;s pictures are shown straight from Esri for looking only: What changed? and
        Save both pictures use the nearest LINZ survey (New Zealand) or Sentinel-2 year instead, and say so. Dates are the year of the survey or version;
        an Esri version can hold a picture taken earlier. The land change layer is Esri&apos;s 10 m land cover change between the two years (2017 to 2025 only).</p>
    </div>
  );
}
