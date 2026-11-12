"use client";

import type * as maplibregl from "maplibre-gl";
import type { GeoJSONSource } from "maplibre-gl";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import AskButton from "@/components/AskButton";
import CountryChoice from "@/components/CountryChoice";
import EChart from "@/components/EChart";
import IndicatorSelect from "@/components/IndicatorSelect";
import WorldMap, { makeScale } from "@/components/WorldMap";
import { api, get, type Indicator } from "@/lib/api";
import { cssVar } from "@/lib/colors";
import { compact, formatValue } from "@/lib/format";
import { countryCentres, countryShapes } from "@/lib/geo";
import { logHistory } from "@/lib/history";
import { useSettings } from "@/lib/settings";
import { areaKm2, dorling, EE_H, EE_W, eeOutline, eePath, equalEarth, mercatorStretch, moveTo, polygons } from "@/lib/shapes";

// Map shapes: how big countries really are. True size (drag a country over another), the
// Equal Earth map (every country at its real area), cartograms (countries as circles or
// squares sized by a figure, with Play over the years), and totals told in countries.

type Tab = "true" | "equal" | "cartogram" | "sizes";
const TABS: [Tab, string][] = [["true", "True size"], ["equal", "Equal-area map"], ["cartogram", "Cartogram"], ["sizes", "Size in countries"]];
const INTRO: Record<Tab, string> = {
  true: "The usual web map (Mercator) stretches shapes more the further they are from the equator: Greenland looks as big as Africa but is a fourteenth of its size. Pick countries and drag them about; each keeps its real size, so it grows on this map as it moves towards a pole and shrinks towards the equator.",
  equal: "The Equal Earth projection keeps every country at its real area, at the cost of bending shapes near the edges. Colour it by any figure.",
  cartogram: "Each country as a circle or square sized by a figure, placed near where it is, nudged apart so none overlap. Play runs through the years.",
  sizes: "A world total told in countries: each step's growth set beside the country whose whole economy (or people, or emissions) is about that size, and how many New Zealands it makes.",
};
// strong, fixed colours so the moved shapes stand out over the base map in light and dark themes
const GHOST_COLOURS = ["#c62828", "#1f4fa8", "#d98a00", "#2e7d32", "#7b2f94", "#00838f"];
type Ghost = { id: string; name: string; at: [number, number] };
const START: Ghost[] = [{ id: "NZL", name: "New Zealand", at: [-2, 54] }, { id: "GRL", name: "Greenland", at: [20, 4] }];

function ShapesView() {
  const router = useRouter();
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "true");
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  useEffect(() => {
    api.indicators().then(setIndicators).catch(() => undefined);
    logHistory({ kind: "page", title: "Map shapes", url: "/shapes", detail: "page" });
  }, []);
  const go = (t: Tab) => { setTab(t); router.replace(`/shapes?tab=${t}`, { scroll: false }); };
  return (
    <div className="grid sector-page">
      <div className="title-row"><h1>Map shapes</h1>
        <AskButton title={`Map shapes: ${TABS.find((t) => t[0] === tab)?.[1]}`} parts={() => [
          { key: "description", kind: "description", label: "What this tab shows", text: INTRO[tab] }]} /></div>
      <div className="seg" role="tablist">
        {TABS.map(([t, label]) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => go(t)}>{label}</button>)}
      </div>
      <p className="ink-2" style={{ marginTop: 0, maxWidth: 860 }}>{INTRO[tab]}</p>
      {tab === "true" && <TrueSize />}
      {tab === "equal" && <EqualArea indicators={indicators} />}
      {tab === "cartogram" && <Cartogram indicators={indicators} />}
      {tab === "sizes" && <Sizes indicators={indicators} />}
    </div>
  );
}

// ---------------------------------------------------------------------------- true size
function TrueSize() {
  const [map, setMap] = useState<maplibregl.Map | null>(null);
  const [ghosts, setGhosts] = useState<Ghost[]>(START);
  const [pick, setPick] = useState("AUS");
  const [shapes, setShapes] = useState<Record<string, { polys: number[][][][]; centre: [number, number]; area: number; name: string }>>({});
  const ghostsRef = useRef(ghosts);
  ghostsRef.current = ghosts;
  useEffect(() => {
    Promise.all([countryShapes(), countryCentres()]).then(([fc, cs]) => {
      const out: typeof shapes = {};
      for (const f of fc.features) {
        const p = f.properties as { iso3?: string; name?: string } | null;
        if (!p?.iso3 || !cs[p.iso3]) continue;
        const polys = polygons(f.geometry);
        const area = areaKm2(polys);
        // Some territories share their country's code (Ashmore and Cartier Islands are AUS):
        // keep the biggest shape, so adding Australia adds Australia.
        if (out[p.iso3] && out[p.iso3].area >= area) continue;
        out[p.iso3] = { polys, centre: cs[p.iso3], area, name: p.name ?? p.iso3 };
      }
      setShapes(out);
    });
  }, []);
  const data = useMemo((): GeoJSON.FeatureCollection => ({
    type: "FeatureCollection",
    features: ghosts.filter((g) => shapes[g.id]).map((g, i) => ({
      type: "Feature", id: i, properties: { i, color: GHOST_COLOURS[i % GHOST_COLOURS.length], label: g.name },
      geometry: { type: "MultiPolygon", coordinates: moveTo(shapes[g.id].polys, shapes[g.id].centre, g.at) },
    })),
  }), [ghosts, shapes]);
  useEffect(() => {
    if (!map) return;
    const put = () => {
      const src = map.getSource("ts") as GeoJSONSource | undefined;
      if (src) { src.setData(data); for (const l of ["ts-fill", "ts-casing", "ts-line"]) if (map.getLayer(l)) map.moveLayer(l); return; }
      map.addSource("ts", { type: "geojson", data });
      map.addLayer({ id: "ts-fill", type: "fill", source: "ts", paint: { "fill-color": ["get", "color"], "fill-opacity": 0.62 } });
      map.addLayer({ id: "ts-casing", type: "line", source: "ts", paint: { "line-color": "#111", "line-width": 4, "line-opacity": 0.55 } });
      map.addLayer({ id: "ts-line", type: "line", source: "ts", paint: { "line-color": ["get", "color"], "line-width": 2.2 } });
    };
    // Once the shapes are on the map, new data goes straight in: waiting for the map to be
    // "loaded" or "idle" again could wait for ever while base map tiles are slow or offline.
    // Base map tiles that never arrive (offline, blocked) must not hold the shapes back, so check the style itself.
    // The countries must be drawn first, or they would cover the shapes.
    const ready = () => !!map.getSource("ts") || !!map.getLayer("selected");
    if (ready()) { put(); return; }
    const t = setInterval(() => { if (ready()) { clearInterval(t); put(); } }, 250);
    return () => clearInterval(t);
  }, [map, data]);
  useEffect(() => { // dragging a shape
    if (!map) return;
    let drag: { i: number; start: maplibregl.LngLat; from: [number, number] } | null = null;
    const down = (e: maplibregl.MapMouseEvent) => {
      if (!map.getLayer("ts-fill")) return;
      const f = map.queryRenderedFeatures(e.point, { layers: ["ts-fill"] })[0];
      if (!f) return;
      e.preventDefault();
      const i = Number(f.properties?.i);
      drag = { i, start: e.lngLat, from: ghostsRef.current[i].at };
      map.dragPan.disable();
      map.getCanvas().style.cursor = "grabbing";
    };
    const move = (e: maplibregl.MapMouseEvent) => {
      if (!drag) {
        const over = map.getLayer("ts-fill") && map.queryRenderedFeatures(e.point, { layers: ["ts-fill"] }).length;
        map.getCanvas().style.cursor = over ? "grab" : "";
        return;
      }
      const d = drag;
      const at: [number, number] = [d.from[0] + (e.lngLat.lng - d.start.lng), Math.max(-80, Math.min(80, d.from[1] + (e.lngLat.lat - d.start.lat)))];
      setGhosts((gs) => gs.map((g, k) => (k === d.i ? { ...g, at } : g)));
    };
    const up = () => { if (drag) { drag = null; map.dragPan.enable(); map.getCanvas().style.cursor = ""; } };
    map.on("mousedown", down);
    map.on("mousemove", move);
    map.on("mouseup", up);
    return () => { map.off("mousedown", down); map.off("mousemove", move); map.off("mouseup", up); };
  }, [map]);
  const add = () => {
    const s = shapes[pick];
    if (!s || ghosts.some((g) => g.id === pick)) return;
    const c = map?.getCenter();
    setGhosts([...ghosts, { id: pick, name: s.name, at: c ? [c.lng, c.lat] : s.centre }]);
  };
  return (
    <>
      <div className="chips-row" style={{ gap: 10, flexWrap: "wrap", alignItems: "end", marginBottom: 8 }}>
        <CountryChoice value={pick} onChange={setPick} label="Add a country" />
        <button onClick={add}>Add to the map</button>
        <button className="link" onClick={() => setGhosts(ghosts.map((g) => ({ ...g, at: shapes[g.id]?.centre ?? g.at })))}>Put them back home</button>
        <button className="link" onClick={() => setGhosts([])}>Clear</button>
      </div>
      <div className="card"><div className="map-box">
        <WorldMap fill values={[]} unit="" decimals={0} diverging={false} onPick={() => undefined} onMap={setMap} hideScale />
      </div></div>
      <table className="summary-table" style={{ marginTop: 10 }}>
        <thead><tr><th>Country</th><th className="num">Real area</th><th className="num">Now at latitude</th><th className="num">Looks this many times its size at the equator</th><th /></tr></thead>
        <tbody>
          {ghosts.map((g, i) => (
            <tr key={g.id}>
              <td><span className="swatch" style={{ background: GHOST_COLOURS[i % GHOST_COLOURS.length] }} /> {g.name}</td>
              <td className="num">{shapes[g.id] ? `${compact(shapes[g.id].area)} km²` : "–"}</td>
              <td className="num">{g.at[1].toFixed(0)}°</td>
              <td className="num">{mercatorStretch(g.at[1]).toFixed(1)}×</td>
              <td><button className="link" onClick={() => setGhosts(ghosts.filter((_, k) => k !== i))}>Remove</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="caption">Drag a coloured shape to move it. Areas are worked out from Natural Earth&apos;s borders on a round Earth.</p>
    </>
  );
}

// ---------------------------------------------------------------------------- equal area
function useYearValues(indicator: string, year: number) {
  const [values, setValues] = useState<Record<string, number>>({});
  useEffect(() => {
    if (!indicator) return;
    api.map(indicator, year).then((rows) => setValues(Object.fromEntries(rows.map((r) => [r.entity_id, r.value])))).catch(() => setValues({}));
  }, [indicator, year]);
  return values;
}

// The longitude in the middle of the flat maps: starts from Settings (Pacific or Atlantic), changeable here.
const CENTRES: [string, number][] = [["Pacific", 150], ["New Zealand", 175], ["Americas", -90], ["Atlantic", 0], ["Europe and Africa", 20], ["Asia", 100]];
function useCentre(): [number, React.ReactNode] {
  const { map_centre } = useSettings();
  const [centre, setCentre] = useState<number | null>(null);
  const c = centre ?? (map_centre === "atlantic" ? 0 : 150);
  const named = CENTRES.find(([, v]) => v === c);
  const picker = (
    <label className="small" title="The longitude in the middle of the map">Centre on{" "}
      <select value={named ? String(c) : "own"} onChange={(e) => e.target.value !== "own" && setCentre(Number(e.target.value))}>
        {CENTRES.map(([n, v]) => <option key={n} value={v}>{n}</option>)}
        {!named && <option value="own">{c > 0 ? `${c}° E` : c < 0 ? `${-c}° W` : "0°"}</option>}
      </select>{" "}
      <input type="range" min={-180} max={180} step={5} value={c} onChange={(e) => setCentre(Number(e.target.value))} style={{ width: 110, verticalAlign: "middle" }} aria-label="Centre longitude" />
    </label>
  );
  return [c, picker];
}

function usePaths(width: number, centre: number) {
  const [paths, setPaths] = useState<{ id: string; name: string; d: string; c: [number, number] }[]>([]);
  useEffect(() => {
    const scale = width / EE_W;
    Promise.all([countryShapes(), countryCentres()]).then(([fc, cs]) => setPaths(Object.values(fc.features.flatMap((f) => {
      const p = f.properties as { iso3?: string; name?: string } | null;
      if (!p?.iso3) return [];
      const c = cs[p.iso3] ?? [0, 0];
      const [x, y] = equalEarth(c[0], c[1], centre);
      return [{ id: p.iso3, name: p.name ?? p.iso3, d: eePath(polygons(f.geometry), centre, scale, width / 2, (EE_H * scale) / 2), c: [width / 2 + x * scale, (EE_H * scale) / 2 + y * scale] as [number, number] }];
    }).reduce((acc, p) => { // territories that share a code (Ashmore and Cartier Islands are AUS) join their country
      if (acc[p.id]) acc[p.id] = { ...acc[p.id], d: acc[p.id].d + p.d };
      else acc[p.id] = p;
      return acc;
    }, {} as Record<string, { id: string; name: string; d: string; c: [number, number] }>))));
  }, [width, centre]);
  return paths;
}

const W = 1000;
const MAX_R = 80; // the biggest bubble on the cartogram

function EqualArea({ indicators }: { indicators: Indicator[] }) {
  const [centre, centrePicker] = useCentre();
  const [indicator, setIndicator] = useState("pop_density");
  const [year, setYear] = useState(new Date().getFullYear() - 2);
  const values = useYearValues(indicator, year);
  const paths = usePaths(W, centre);
  const ind = indicators.find((i) => i.indicator_id === indicator);
  useEffect(() => { // the latest year with figures (estimates, not projections)
    get<{ years: number[]; last_estimate_year: number | null }>("/map/range", { indicator })
      .then((r) => { const y = r.last_estimate_year ?? r.years[r.years.length - 1]; if (y) setYear(y); }).catch(() => undefined);
  }, [indicator]);
  const scale = useMemo(() => makeScale(Object.values(values), false), [values]);
  const colour = (v: number | undefined) => {
    if (v === undefined) return cssVar("--no-data");
    let k = 0;
    while (k < scale.breaks.length && v >= scale.breaks[k]) k++;
    return scale.colors[k];
  };
  const H = EE_H * (W / EE_W);
  return (
    <>
      <div className="chips-row" style={{ gap: 10, flexWrap: "wrap", alignItems: "end", marginBottom: 8 }}>
        <label className="small">Colour by <IndicatorSelect indicators={indicators} value={indicator} onChange={setIndicator} /></label>
        <label className="small">Year <input type="number" value={year} min={1950} max={2100} onChange={(e) => setYear(Number(e.target.value))} style={{ width: 80 }} /></label>
        {centrePicker}
      </div>
      <div className="card">
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Equal-area world map">
          <defs><clipPath id="ee-clip"><path d={eeOutline(W / EE_W, W / 2, H / 2)} /></clipPath></defs>
          <path d={eeOutline(W / EE_W, W / 2, H / 2)} fill={cssVar("--map-water") || "#dfe9f2"} />
          <g clipPath="url(#ee-clip)">
            {paths.map((p) => (
              <path key={p.id} d={p.d} fill={colour(values[p.id])} stroke={cssVar("--surface")} strokeWidth={0.4}>
                <title>{p.name}: {values[p.id] !== undefined ? formatValue(values[p.id], ind?.unit ?? "", ind?.decimals ?? 1) : "no figure"}</title>
              </path>
            ))}
          </g>
        </svg>
        <p className="caption">{ind?.name ?? indicator}, {year}. Equal Earth projection (Šavrič, Patterson and Jenny, 2018), centred on {CENTRES.find(([, v]) => v === centre)?.[0] ?? (centre > 0 ? `${centre}° E` : centre < 0 ? `${-centre}° W` : "Greenwich")}.</p>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------- cartogram
type Range = { years: number[]; last_estimate_year: number | null; rows: Record<string, (number | null)[]> };

// Countries as circles (or squares) sized by a figure, sitting where the country is on the map, pushed
// apart so none overlap. One scale for every year by default, so growth shows as circles growing.
// Hover a country for its line through the years (projections dashed); the strip under the map adds
// them all up and is where the year is chosen.
function Cartogram({ indicators }: { indicators: Indicator[] }) {
  const router = useRouter();
  const [centre, centrePicker] = useCentre();
  const [indicator, setIndicator] = useState("pop_total");
  const [year, setYear] = useState(new Date().getFullYear() - 1);
  const [shape, setShape] = useState<"circle" | "square">("circle");
  const [land, setLand] = useState(true);
  const [fixed, setFixed] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [range, setRange] = useState<Range | null>(null);
  const [continents, setContinents] = useState<Record<string, string>>({});
  const [tip, setTip] = useState<{ id: string; x: number; y: number; w: number } | null>(null);
  const paths = usePaths(W, centre);
  const ind = indicators.find((i) => i.indicator_id === indicator);
  useEffect(() => {
    api.memberships({ type: "continent" }).then((ms) => setContinents(Object.fromEntries(ms.map((m) => [m.member_id, m.group_name])))).catch(() => undefined);
  }, []);
  useEffect(() => {
    let on = true;
    get<Range>("/map/range", { indicator }).then((r) => {
      if (!on) return;
      setRange(r);
      if (r.years.length) setYear((y) => Math.min(Math.max(y, r.years[0]), r.years[r.years.length - 1]));
    }).catch(() => on && setRange({ years: [], last_estimate_year: null, rows: {} }));
    return () => { on = false; };
  }, [indicator]);
  const years = range?.years ?? [];
  const yi = years.indexOf(year);
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => setYear((y) => { const i = years.indexOf(y); if (i < 0 || i >= years.length - 1) { setPlaying(false); return y; } return years[i + 1]; }), 450);
    return () => clearInterval(t);
  }, [playing, years]);
  const values = useMemo(() => {
    const out: Record<string, number> = {};
    if (range && yi >= 0) for (const [id, vs] of Object.entries(range.rows)) { const v = vs[yi]; if (v !== null && v > 0) out[id] = v; }
    return out;
  }, [range, yi]);
  const H = EE_H * (W / EE_W);
  // Size the bubbles so that together they cover about a fifth of the map, whatever the figure:
  // with "same scale" that is in the year with the biggest total, so other years are smaller.
  // The biggest bubble is held to MAX_R so one giant (or a figure where every country is near the top) can't fill the map.
  const ids = useMemo(() => new Set(paths.map((p) => p.id)), [paths]);
  const shareOf = (vals: number[]) => {
    const tot = vals.reduce((s, v) => s + v, 0), big = Math.max(0, ...vals);
    if (tot <= 0 || big <= 0) return null;
    const k = Math.min(Math.sqrt((0.2 * W * H) / (Math.PI * tot)), MAX_R / Math.sqrt(big)); // radius = k * sqrt(value)
    return { k, top: big };
  };
  const fixedScale = useMemo(() => {
    if (!range) return null;
    let best: { k: number; top: number } | null = null;
    range.years.forEach((_, i) => {
      const vals = Object.entries(range.rows).filter(([id]) => ids.has(id)).map(([, vs]) => vs[i]).filter((v): v is number => v !== null && v > 0);
      const s = shareOf(vals);
      if (s && (!best || s.k < best.k)) best = s;
    });
    return best;
  }, [range, ids]); // eslint-disable-line react-hooks/exhaustive-deps
  const bubbles = useMemo(() => {
    const items = paths.filter((p) => values[p.id] > 0).map((p) => ({ id: p.id, x: p.c[0], y: p.c[1], value: values[p.id] }));
    const s = fixed && fixedScale ? fixedScale : shareOf(items.map((i) => i.value));
    if (!s) return [];
    return dorling(items, s.k * Math.sqrt(s.top), 120, [W, H], s.top);
  }, [paths, values, fixed, fixedScale, H]); // eslint-disable-line react-hooks/exhaustive-deps
  const groups = [...new Set(Object.values(continents))].sort();
  const colourOf = (id: string) => cssVar(`--series-${(groups.indexOf(continents[id]) % 7) + 1}`) || "#888";
  const names = Object.fromEntries(paths.map((p) => [p.id, p.name]));
  const fmt = (v: number) => formatValue(v, ind?.unit ?? "", ind?.decimals ?? 1);
  const short = (v: number) => (ind?.unit === "people" || indicator === "pop_total" ? (v >= 1e9 ? `${(v / 1e9).toFixed(2)} bn` : v >= 1e6 ? `${Math.round(v / 1e6)} m` : `${Math.round(v / 1e3)} k`) : compact(v));
  const projFrom = range?.last_estimate_year ?? null;
  const isProj = (y: number) => projFrom !== null && y > projFrom;
  const totals = years.map((_, i) => Object.values(range?.rows ?? {}).reduce((s, vs) => s + (vs[i] ?? 0), 0));
  const sum = ind?.agg_method === "sum" || indicator.startsWith("pop_total") || ind?.unit === "people";
  const line = (vs: (number | null)[], w: number, h: number, from = 0, to = years.length - 1) => {
    const max = Math.max(1e-9, ...vs.filter((v): v is number => v !== null));
    const x = (i: number) => (years.length > 1 ? ((years[i] - years[0]) / (years[years.length - 1] - years[0])) * w : 0);
    let d = "", pen = false;
    for (let i = from; i <= to; i++) { const v = vs[i]; if (v === null) { pen = false; continue; } d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${(h - (v / max) * (h - 4)).toFixed(1)}`; pen = true; }
    return { d, x };
  };
  const cut = projFrom !== null ? years.findIndex((y) => y > projFrom) : -1;
  const spark = (vs: (number | null)[], w: number, h: number) => {
    const past = line(vs, w, h, 0, cut > 0 ? cut - 1 : years.length - 1), fut = cut > 0 ? line(vs, w, h, cut - 1) : null;
    return (
      <>
        <path d={past.d} fill="none" stroke={cssVar("--ink-2")} strokeWidth={1.5} />
        {fut && <path d={fut.d} fill="none" stroke={cssVar("--ink-2")} strokeWidth={1.2} strokeDasharray="4 3" />}
        {yi >= 0 && <line x1={past.x(yi)} x2={past.x(yi)} y1={0} y2={h} stroke="#b5891b" strokeWidth={2} />}
      </>
    );
  };
  const pickYear = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const f = (e.clientX - r.left) / r.width;
    const y = Math.round(years[0] + f * (years[years.length - 1] - years[0]));
    setPlaying(false);
    setYear(years.reduce((b, v) => (Math.abs(v - y) < Math.abs(b - y) ? v : b), years[0]));
  };
  return (
    <>
      <div className="chips-row" style={{ gap: 10, flexWrap: "wrap", alignItems: "end", marginBottom: 8 }}>
        <label className="small">Size by <IndicatorSelect indicators={indicators} value={indicator} onChange={setIndicator} /></label>
        <div className="seg" role="group" aria-label="Shape">
          {(["circle", "square"] as const).map((v) => <button key={v} className={shape === v ? "on" : ""} aria-pressed={shape === v} onClick={() => setShape(v)}>{v === "circle" ? "Circles" : "Squares"}</button>)}
        </div>
        <label className="small"><input type="checkbox" checked={land} onChange={(e) => setLand(e.target.checked)} /> Map underneath</label>
        {centrePicker}
        <label className="small" title="Same for every year: circles grow as the figure grows. Off: bubbles are scaled to fit each year on its own."><input type="checkbox" checked={fixed} onChange={(e) => setFixed(e.target.checked)} /> Same scale every year</label>
        <button onClick={() => { if (yi >= years.length - 1) setYear(years[0]); setPlaying(!playing); }}>{playing ? "Pause" : "Play"}</button>
      </div>
      <div className="card" style={{ position: "relative" }} onMouseLeave={() => setTip(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`Cartogram of ${ind?.name ?? indicator}`} style={{ display: "block" }}>
          <path d={eeOutline(W / EE_W, W / 2, H / 2)} fill={land ? cssVar("--surface-2") || "#f3f1ec" : "none"} stroke={cssVar("--line")} />
          {land && paths.map((p) => <path key={p.id} d={p.d} fill={cssVar("--map-land") || "#dcd8cf"} stroke={cssVar("--surface")} strokeWidth={0.4} opacity={0.8} />)}
          {bubbles.map((b) => {
            const s = b.r * 1.772; // a square with the circle's area
            const col = colourOf(b.id);
            const name = names[b.id] ?? b.id;
            const fs = Math.min(15, b.r / 3.2);
            return (
              <g key={b.id} className="carto-b" style={{ transform: `translate(${b.x}px, ${b.y}px)` }} onClick={() => router.push(`/entity/${b.id}`)}
                onMouseMove={(e) => { const r = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect(); setTip({ id: b.id, x: e.clientX - r.left, y: e.clientY - r.top, w: r.width }); }}>
                {shape === "circle"
                  ? <circle r={b.r} fill={col} fillOpacity={0.45} stroke={col} strokeWidth={1.1} />
                  : <rect x={-s / 2} y={-s / 2} width={s} height={s} fill={col} fillOpacity={0.45} stroke={col} strokeWidth={1.1} />}
                {b.r > 17 && <text textAnchor="middle" y={b.r > 24 ? -1 : 4} fontSize={fs} fontWeight={600} fill={cssVar("--ink")} pointerEvents="none">{name.length > 13 && b.r < 40 ? b.id : name}</text>}
                {b.r > 24 && <text textAnchor="middle" y={fs + 3} fontSize={fs * 0.85} fill={cssVar("--ink-2")} fontFamily="ui-monospace, monospace" pointerEvents="none">{short(b.value)}</text>}
                {b.r > 9 && b.r <= 17 && <text textAnchor="middle" y={3} fontSize={Math.max(7, b.r / 2.4)} fill={cssVar("--ink-2")} pointerEvents="none">{b.id}</text>}
              </g>
            );
          })}
        </svg>
        {tip && range && (
          <div className="lc-tip" style={{ left: tip.x > tip.w - 240 ? tip.x - 224 : tip.x + 14, top: tip.y + 14 }}>
            <b>{names[tip.id] ?? tip.id}</b>
            <div className="mono">{values[tip.id] !== undefined ? fmt(values[tip.id]) : "no figure"} <span className="muted small">{year}{isProj(year) ? " projection" : ""}</span></div>
            <svg width={200} height={52} aria-hidden>{spark(range.rows[tip.id] ?? [], 200, 50)}</svg>
          </div>
        )}
        {sum && years.length > 1 && (
          <div className="carto-strip">
            <div className="small"><b style={{ color: "#b5891b" }}>{year}</b> {short(totals[yi] ?? 0)} in all{isProj(year) ? <span className="muted"> (projection)</span> : null}</div>
            <svg viewBox="0 0 1000 46" preserveAspectRatio="none" width="100%" height={46} onClick={pickYear} style={{ cursor: "pointer" }} aria-label="Total by year: click to choose a year">
              {spark(totals, 1000, 44)}
            </svg>
            <div className="small muted carto-axis"><span>{years[0]}</span>{projFrom && <span>projection after {projFrom} →</span>}<span>{years[years.length - 1]}</span></div>
          </div>
        )}
        {!sum && years.length > 1 && (
          <input type="range" min={0} max={years.length - 1} value={Math.max(0, yi)} onChange={(e) => { setPlaying(false); setYear(years[Number(e.target.value)]); }} style={{ width: "100%" }} aria-label="Year" />
        )}
        <div className="chips-row small" style={{ gap: 12, flexWrap: "wrap" }}>
          {groups.map((g, i) => <span key={g}><span className="swatch round" style={{ background: cssVar(`--series-${(i % 7) + 1}`) }} /> {g}</span>)}
        </div>
        <p className="caption">{ind?.name ?? indicator}, {year}{isProj(year) ? " (projection)" : ""}. Area in proportion to the figure{fixed ? ", on one scale for every year" : ", scaled to fit this year"}; countries without a figure that year are left out. Click a country for its page.</p>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------- size in countries
type SizeRow = { year: number; from: number | null; value: number; match: { id: string; name: string; value: number } | null; in_unit: number | null };

function Sizes({ indicators }: { indicators: Indicator[] }) {
  const [indicator, setIndicator] = useState("gdp_usd");
  const [step, setStep] = useState(2);
  const [what, setWhat] = useState<"change" | "level">("change");
  const [unit, setUnit] = useState("NZL");
  const [start, setStart] = useState(1990);
  const [rows, setRows] = useState<SizeRow[] | null>(null);
  const [unitName, setUnitName] = useState("New Zealand");
  const [error, setError] = useState<string | null>(null);
  const ind = indicators.find((i) => i.indicator_id === indicator);
  useEffect(() => {
    setError(null);
    get<{ rows: SizeRow[]; unit_name: string }>("/size-in-countries", { indicator, step, what, unit, start })
      .then((r) => { setRows(r.rows); setUnitName(r.unit_name); }).catch((e) => { setRows(null); setError(String(e.message || e)); });
  }, [indicator, step, what, unit, start]);
  const sums = indicators.filter((i) => /usd|pop_total|emissions|_t$|_total/.test(i.indicator_id));
  return (
    <>
      <div className="chips-row" style={{ gap: 10, flexWrap: "wrap", alignItems: "end", marginBottom: 8 }}>
        <label className="small">World total of <IndicatorSelect indicators={sums.length ? sums : indicators} value={indicator} onChange={setIndicator} /></label>
        <div className="seg" role="group" aria-label="Change or level">
          {([["change", "Growth each step"], ["level", "The total"]] as const).map(([v, t]) => <button key={v} className={what === v ? "on" : ""} aria-pressed={what === v} onClick={() => setWhat(v)}>{t}</button>)}
        </div>
        <label className="small">Every <select value={step} onChange={(e) => setStep(Number(e.target.value))}>{[1, 2, 5, 10].map((n) => <option key={n} value={n}>{n} year{n > 1 ? "s" : ""}</option>)}</select></label>
        <label className="small">From <input type="number" value={start} min={1950} max={2030} style={{ width: 80 }} onChange={(e) => setStart(Number(e.target.value))} /></label>
        <CountryChoice value={unit} onChange={setUnit} label="Count in" />
      </div>
      {error && <p className="error">{error}</p>}
      {rows && rows.length > 0 && (
        <div className="card">
          <EChart height={Math.max(300, rows.length * 26)} label="Size in countries" option={() => ({
            grid: { left: 90, right: 230, top: 10, bottom: 30 },
            xAxis: { type: "value", axisLabel: { formatter: (v: number) => compact(v), color: cssVar("--muted") } },
            yAxis: { type: "category", inverse: true, data: rows.map((r) => (r.from ? `${r.from}-${r.year}` : String(r.year))), axisLabel: { color: cssVar("--ink-2") } },
            tooltip: { trigger: "axis", valueFormatter: (v) => formatValue(Number(v), ind?.unit ?? "", 0) },
            series: [{
              type: "bar", data: rows.map((r) => r.value), itemStyle: { color: cssVar("--series-1") },
              label: { show: true, position: "right", color: cssVar("--ink"),
                formatter: (p: { dataIndex: number }) => {
                  const r = rows[p.dataIndex];
                  const u = r.in_unit ? ` · ${r.in_unit >= 10 ? Math.round(r.in_unit) : r.in_unit.toFixed(1)} × ${unitName}` : "";
                  return `${r.match ? `≈ ${r.match.name}` : ""}${u}`;
                } },
            }],
          })} />
          {rows.length > 0 && rows[rows.length - 1].match && (
            <p>
              <b>{what === "change" ? `World ${ind?.name.toLowerCase() ?? indicator} grew` : `World ${ind?.name.toLowerCase() ?? indicator} was`} {compact(rows[rows.length - 1].value)}{" "}
              {what === "change" ? `from ${rows[rows.length - 1].from} to ${rows[rows.length - 1].year}` : `in ${rows[rows.length - 1].year}`}</b>: about the size of{" "}
              {rows[rows.length - 1].match!.name}{rows[rows.length - 1].in_unit ? `, or ${Math.round(rows[rows.length - 1].in_unit!)} times ${unitName}` : ""}.
            </p>
          )}
          <p className="caption">Each bar is the world&apos;s {what === "change" ? "growth over the step" : "total"}; the label names the country whose own total that year is closest (in current figures, not adjusted for prices unless the indicator is).</p>
        </div>
      )}
    </>
  );
}

export default function ShapesPage() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><ShapesView /></Suspense>;
}
