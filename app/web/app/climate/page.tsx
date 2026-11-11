"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import CountryChoice from "@/components/CountryChoice";
import EChart from "@/components/EChart";
import Help from "@/components/Help";
import WorldMap, { type MapPoint } from "@/components/WorldMap";
import ClimateCard from "@/components/ClimateCard";
import NatureTab from "@/components/NatureTab";
import ZonesTab from "@/components/ZonesTab";
import WeatherCard from "@/components/WeatherCard";
import { api, type ClimateEnso, type ClimateLive, type ClimateOverview, type ClimatePolicy, type ClimateStorms } from "@/lib/api";
import { ensoOption, lines, stormsOption, stripesOption } from "@/lib/climate";
import { cssVar } from "@/lib/colors";
import { formatValue } from "@/lib/format";
import { layerData } from "@/lib/layers";
import { rankingBars } from "@/lib/sectors";
import { useSettings } from "@/lib/settings";

// The climate across the world: vital signs, an emissions map, storms, El Niño and policy.

type Tab = "world" | "map" | "weather" | "zones" | "storms" | "enso" | "nature" | "policy" | "country";
const TABS: [Tab, string][] = [["world", "The world"], ["map", "Map and rankings"], ["weather", "Weather by month"], ["zones", "Climate zones"], ["storms", "Storms and alerts"], ["enso", "El Niño"],
  ["nature", "Nature"], ["policy", "Net zero and carbon prices"], ["country", "One country"]];
const LIVE_TYPES: Record<string, string> = { TC: "Tropical cyclone", FL: "Flood", DR: "Drought", WF: "Wildfire", EQ: "Earthquake", VO: "Volcano", TS: "Tsunami" };
const ALERT_COLOR: Record<string, string> = { red: "--div-neg-3", orange: "--series-6", green: "--div-pos-2" };

function Nothing({ what }: { what: string }) {
  return <div className="card"><p>No {what} stored yet. The climate sources are read during <code>.\refresh.bat</code> (switch in <Link href="/settings#climate">Settings: Climate</Link>); if a site refuses, Data status lists the file to save by hand.</p></div>;
}

function Vital({ title, points, unit, note, zero, time, decimals }: { title: string; points?: [number | string, number][]; unit: string; note?: string; zero?: boolean; time?: boolean; decimals?: number }) {
  const opt = useCallback(() => lines([{ name: title, points: points ?? [] }], unit, { zero, time, decimals }), [points, title, unit, zero, time, decimals]);
  if (!points?.length) return null;
  const last = points[points.length - 1];
  return (
    <div className="card">
      <h3>{title}</h3>
      <p className="climate-big">{formatValue(last[1], "", decimals ?? 1)} <span className="small ink-2">{unit} ({last[0]})</span></p>
      <EChart option={opt} height={180} label={title} />
      {note ? <p className="caption">{note}</p> : null}
    </div>
  );
}

function World({ o }: { o: ClimateOverview }) {
  const t = o.world.temp_anomaly_world;
  const stripes = useCallback(() => stripesOption(t ?? []), [t]);
  const ice = Object.entries(o.sea_ice).filter(([k]) => k.startsWith("sea_ice_extent_min"));
  const iceOpt = useCallback(() => lines(ice.map(([k, pts]) => ({ name: `${k.split(":")[1][0].toUpperCase()}${k.split(":")[1].slice(1)}, year's lowest month`, points: pts })), "million km²", { decimals: 1 }), [ice]);
  const sheets = useCallback(() => lines(Object.entries(o.ice_sheets).map(([e, pts]) => ({ name: e, points: pts })), o.names.ice_sheet_mass?.unit ?? "", { zero: true, decimals: 0 }), [o]);
  if (!Object.keys(o.world).length && !Object.keys(o.monthly).length) return <Nothing what="climate figures" />;
  return (
    <>
      {o.enso ? <p className="small">Now: <b>{o.enso.name}{o.enso.strength ? ` (${o.enso.strength})` : ""}</b>, El Niño index {o.enso.value > 0 ? "+" : ""}{o.enso.value.toFixed(1)} °C in {o.enso.month}. <Link href="/climate?tab=enso">More on El Niño</Link></p> : null}
      {t?.length ? (
        <div className="card">
          <h3>The world&apos;s warming stripes <Help note="climate_world" /></h3>
          <EChart option={stripes} height={90} label="World warming stripes" />
          <p className="caption">Each stripe is a year: blue cooler and red warmer than the average of the years shown. Hover for the figure against 1951-1980. NASA GISTEMP.</p>
        </div>
      ) : null}
      <div className="grid three">
        <Vital title="World temperature against 1951-1980" points={t} unit="°C" zero decimals={2} note="Land and sea surface, yearly. NASA GISTEMP v4." />
        <Vital title="World temperature, monthly" points={o.monthly.temp_anomaly_world_monthly} unit="°C" time zero decimals={2} />
        <Vital title="CO2 in the air" points={o.monthly.co2_ppm_mlo ?? o.world.co2_ppm} unit="ppm" time={!!o.monthly.co2_ppm_mlo} note="Mauna Loa, monthly (NOAA). Before industry it was about 280." />
        <Vital title="Methane in the air" points={o.world.ch4_ppb} unit="ppb" decimals={0} note="World average (NOAA). About 720 before industry." />
        <Vital title="Nitrous oxide in the air" points={o.world.n2o_ppb} unit="ppb" decimals={1} note="World average (NOAA)." />
        <Vital title="World CO2 emissions" points={o.world.co2_gcp} unit="million t" decimals={0} note="Fossil fuels and industry (Global Carbon Project)." />
        <Vital title="Sea level" points={o.world.sea_level} unit={o.names.sea_level?.unit ?? "mm"} zero decimals={0} />
        <Vital title="Heat in the top 700 m of the oceans" points={o.world.ocean_heat} unit={o.names.ocean_heat?.unit ?? ""} zero decimals={1} />
      </div>
      <div className="grid two">
        {ice.length ? <div className="card"><h3>Sea ice at its yearly low</h3><EChart option={iceOpt} height={220} label="Sea ice minimum" /><p className="caption">NSIDC Sea Ice Index.</p></div> : null}
        {Object.keys(o.ice_sheets).length ? <div className="card"><h3>Ice sheets</h3><EChart option={sheets} height={220} label="Ice sheet mass" /><p className="caption">Change in mass since 2002 (NASA GRACE satellites).</p></div> : null}
      </div>
    </>
  );
}

function MapTab({ o }: { o: ClimateOverview }) {
  const router = useRouter();
  const [ind, setInd] = useState(o.emission_maps[0] ?? "");
  const [year, setYear] = useState(2022);
  const [rows, setRows] = useState<{ entity_id: string; value: number; status: string }[]>([]);
  const [names, setNames] = useState<Map<string, string>>(new Map());
  useEffect(() => { api.entities().then((l) => setNames(new Map(l.map((e) => [e.entity_id, e.short_name])))).catch(() => {}); }, []);
  useEffect(() => {
    if (!ind) return;
    let live = true;
    api.map(ind, year).then((r) => { if (!live) return; if (!r.length && year > 1990) setYear(year - 1); else setRows(r); }).catch(() => live && setRows([]));
    return () => { live = false; };
  }, [ind, year]);
  const meta = o.names[ind];
  const unit = meta?.unit ?? "";
  const ranked = useMemo(() => [...rows].sort((a, b) => b.value - a.value).map((r) => ({ name: names.get(r.entity_id) ?? r.entity_id, value: r.value })), [rows, names]);
  const bars = useCallback(() => rankingBars(ranked, unit, 25), [ranked, unit]);
  // Over time: the five highest this year, the key countries and the world.
  const s = useSettings();
  const [overTime, setOverTime] = useState<{ name: string; points: [number, number][] }[]>([]);
  const top = useMemo(() => [...rows].sort((a, b) => b.value - a.value).slice(0, 5).map((r) => r.entity_id).join(","), [rows]);
  useEffect(() => {
    if (!ind) return;
    const keys = (s.discover_key_countries || "NZL,AUS,GBR,USA").split(",").filter(Boolean);
    const ids = [...new Set(["world", ...keys, ...(top ? top.split(",") : [])])];
    let live = true;
    api.series(ind, ids, 1950).then((r) => {
      if (!live) return;
      const by = new Map<string, [number, number][]>();
      for (const x of r) if (x.value != null) { const k = x.entity_id; if (!by.has(k)) by.set(k, []); by.get(k)!.push([+String(x.period).slice(0, 4), x.value]); }
      setOverTime(ids.filter((e) => by.get(e)?.length).map((e) => ({ name: e === "world" ? "World" : names.get(e) ?? e, points: by.get(e)! })));
    }).catch(() => live && setOverTime([]));
    return () => { live = false; };
  }, [ind, top, names, s.discover_key_countries]);
  const timeOpt = useCallback(() => lines(overTime, unit, { decimals: 2, zero: ind === "temp_anomaly" }), [overTime, unit, ind]);
  if (!o.emission_maps.length) return <Nothing what="emissions or temperatures by country" />;
  return (
    <>
      <div className="chips-row small">
        <label>Show <select value={ind} onChange={(e) => setInd(e.target.value)}>{o.emission_maps.map((i) => <option key={i} value={i}>{o.names[i]?.name ?? i}</option>)}</select></label>
        <label>Year <input type="number" min={1950} max={2030} value={year} onChange={(e) => setYear(+e.target.value)} style={{ width: 80 }} /></label>
      </div>
      <div className="card"><div className="map-box"><WorldMap fill values={rows} unit={unit} decimals={2} diverging={ind === "temp_anomaly"} onPick={(iso) => router.push(`/entity/${iso}#climate`)} /></div></div>
      <div className="card"><h3>Highest, {year}</h3><EChart option={bars} height={520} label={`${ind} ranking`} /></div>
      {overTime.length > 0 && (
        <div className="card"><h3>{meta?.name ?? ind} over time</h3><EChart option={timeOpt} height={360} label={`${ind} over time`} />
          <p className="caption">The world, your key countries (Settings: Discover) and the five highest in {year}. Click a name in the legend to hide it.</p></div>
      )}
    </>
  );
}

function Storms() {
  const s = useSettings();
  const [st, setSt] = useState<ClimateStorms | null>(null);
  const [live, setLive] = useState<ClimateLive | null>(null);
  const [from, setFrom] = useState(2015);
  const [to, setTo] = useState(2030);
  const [minCat, setMinCat] = useState(0);
  const [basin, setBasin] = useState("");
  const [now, setNow] = useState(false); // storms going on now, or the history in a range of years
  const [active, setActive] = useState<{ n: number; note?: string; fetched?: string } | null>(null);
  useEffect(() => {
    if (!now) return;
    layerData("storms_active").then((fc) => { const x = fc as GeoJSON.FeatureCollection & { note?: string; fetched?: string };
      setActive({ n: x.features.length, note: x.note, fetched: x.fetched }); }).catch(() => setActive({ n: 0, note: "Could not read the storms now." }));
  }, [now]);
  useEffect(() => { api.climateStorms().then((r) => { setSt(r); if (r.years.length) { setTo(r.years[r.years.length - 1]); setFrom(Math.max(r.years[0], r.years[r.years.length - 1] - 5)); } }).catch(() => setSt(null)); }, []);
  useEffect(() => { api.climateLive().then(setLive).catch(() => setLive(null)); }, [s.climate_live_map]);
  const chart = useCallback(() => {
    const bi = st ? st.basins.indexOf(basin) : -1;
    if (!st || bi < 0) return stormsOption(st?.years ?? [], st?.basins ?? [], st?.counts ?? [], st?.strong ?? []);
    return stormsOption(st.years, [basin], st.counts.map((c) => [c[bi]]), st.strong_by ? st.strong_by.map((c) => c[bi]) : st.strong);
  }, [st, basin]);
  const points: MapPoint[] = (live?.rows ?? []).map((r) => ({ id: r.id, name: `${LIVE_TYPES[r.type] ?? r.type}: ${r.name ?? ""}`, lng: r.lon, lat: r.lat,
    size: r.alert === "red" ? 3 : r.alert === "orange" ? 2 : 1, color: cssVar(ALERT_COLOR[r.alert] ?? "--muted"), text: `${r.country ?? ""} · ${r.alert} alert · from ${String(r.from ?? "").slice(0, 10)}` }));
  const filter = useMemo(() => ["all", [">=", ["get", "year"], from], ["<=", ["get", "year"], to], [">=", ["coalesce", ["get", "cat"], 0], minCat],
    ...(basin ? [["==", ["get", "basin"], basin]] : [])] as unknown[], [from, to, minCat, basin]);
  const nowFilter = useMemo(() => ["all", [">=", ["coalesce", ["get", "cat"], 0], minCat],
    ...(basin ? [["==", ["get", "basin"], basin]] : [])] as unknown[], [minCat, basin]);
  return (
    <>
      <div className="chips-row small">
        <div className="seg" role="group" aria-label="Which storms">
          <button className={now ? "on" : ""} aria-pressed={now} onClick={() => setNow(true)}>Active now</button>
          <button className={!now ? "on" : ""} aria-pressed={!now} onClick={() => setNow(false)}>History</button>
        </div>
        {!now && <>
          <label>Storms from <input type="number" value={from} min={1980} max={to} onChange={(e) => setFrom(+e.target.value)} style={{ width: 70 }} /></label>
          <label>to <input type="number" value={to} min={from} max={2030} onChange={(e) => setTo(+e.target.value)} style={{ width: 70 }} /></label>
        </>}
        {now && <span className="muted">{active === null ? "Reading the storms now…" : active.note ?? `${active.n} active in the last 4 days (NOAA, ${active.fetched ?? ""})`}</span>}
        <label>Strength at least <select value={minCat} onChange={(e) => setMinCat(+e.target.value)}>
          <option value={0}>Tropical storm</option>{[1, 2, 3, 4, 5].map((c) => <option key={c} value={c}>Category {c}</option>)}</select></label>
        <label>Ocean <select value={basin} onChange={(e) => setBasin(e.target.value)}>
          <option value="">Every ocean</option>{(st?.basins ?? []).map((b) => <option key={b} value={b}>{b}</option>)}</select></label>
        <span className="muted">{live?.off ? "Live alerts are off (Settings: Climate)." : live?.error ? live.error : live?.rows.length ? `${live.rows.length} alerts now (GDACS, ${live.fetched})` : ""}</span>
      </div>
      <div className="card">
        <div className="map-box"><WorldMap fill values={[]} unit="" decimals={0} diverging={false}
          layers={now ? ["storms_active"] : st?.years.length ? ["storm_tracks"] : []}
          layerFilter={now ? { storms_active: nowFilter } : { storm_tracks: filter }} points={points} onPick={() => {}} onCity={() => {}} /></div>
        <p className="caption">{now
          ? "Lines: storms going on now and in the last few days (NOAA IBTrACS, read at most hourly), darker and wider for stronger; the line ends where the storm was last placed."
          : "Lines: tropical storm tracks in the years chosen (NOAA IBTrACS, the monthly file), darker and wider for stronger."} Dots: what GDACS lists now, red and orange alerts larger. Hover for names.</p>
      </div>
      {st?.years.length ? <div className="card"><h3>Storms each year, {basin ? basin : "by ocean"} <Help note="climate_storms" /></h3><EChart option={chart} height={300} label="Storms per year" /></div> : <Nothing what="storm tracks" />}
      <p className="small">Orange and red GDACS alerts since 2000 are events: on the <Link href="/events?kinds=disaster">Events page</Link>, the Timeline and charts.</p>
    </>
  );
}

// Sea temperatures against normal, from NASA's daily satellite map (GIBS, no key): El Niño
// shows as a warm tongue along the equator east of the date line, La Niña as a cool one.
const GIBS_SST = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/GHRSST_L4_MUR_Sea_Surface_Temperature_Anomalies/default/{day}/GoogleMapsCompatible_Level7/{z}/{y}/{x}.png";
const NINO_BOXES = [{ name: "Niño 3.4", west: -170, south: -5, east: -120, north: 5 }];

function SeaMap() {
  const ago = (d: number) => new Date(Date.now() - d * 86_400_000).toISOString().slice(0, 10);
  const [day, setDay] = useState(ago(3)); // the satellite map is a day or two behind
  const raster = useMemo(() => ({ tiles: GIBS_SST.replace("{day}", day), attribution: "Sea temperatures: NASA GIBS, GHRSST MUR", maxzoom: 7 }), [day]);
  return (
    <div className="card">
      <div className="card-head"><h3>Sea temperatures against normal</h3>
        <label className="small">Day <input type="date" value={day} max={ago(1)} min="2002-06-01" onChange={(e) => e.target.value && setDay(e.target.value)} /></label></div>
      <div className="map-box"><WorldMap fill values={[]} unit="" decimals={0} diverging={false} raster={raster} boxes={NINO_BOXES} onPick={() => {}} /></div>
      <p className="caption">Red: warmer than usual for the day; blue: cooler (about ±4 °C at the ends). The dashed box is Niño 3.4, where the El Niño index is
        measured: a warm tongue there is El Niño, a cool one La Niña. Daily satellite map from NASA (GIBS, GHRSST MUR); pick an earlier day to compare,
        for example December 2015 or 2023. Needs the internet; blank if NASA has no map for that day yet.</p>
    </div>
  );
}

function Enso() {
  const [d, setD] = useState<ClimateEnso | null>(null);
  const [which, setWhich] = useState("enso_oni");
  useEffect(() => { api.climateEnso().then(setD).catch(() => setD(null)); }, []);
  const opt = useCallback(() => ensoOption([{ name: { enso_oni: "El Niño index (ONI)", iod_dmi: "Indian Ocean Dipole", sam_index: "Southern Annular Mode" }[which] ?? which,
    points: (d?.series[which] ?? []).filter((p) => p[0] >= "1950") }]), [d, which]);
  if (!d || !d.series.enso_oni) return <Nothing what="El Niño index" />;
  return (
    <>
      {d.phase ? (
        <div className="card enso-now">
          <h3>Now: {d.phase.name}{d.phase.strength ? ` (${d.phase.strength})` : ""} <Help note="climate_enso" /></h3>
          <div className="enso-gauge" aria-label={`El Niño index ${d.phase.value}`}>
            <div className="enso-bar"><span style={{ left: `${Math.max(0, Math.min(100, 50 + d.phase.value * 16.6))}%` }} /></div>
            <div className="small ink-2 enso-scale"><span>La Niña -3</span><span>Neutral</span><span>El Niño +3</span></div>
          </div>
          <p className="small">El Niño index {d.phase.value > 0 ? "+" : ""}{d.phase.value.toFixed(2)} °C for the three months centred on {d.phase.month}. NOAA&apos;s and the Bureau of Meteorology&apos;s outlooks for the months ahead are on their sites.</p>
        </div>
      ) : null}
      <div className="card">
        <div className="card-head"><h3>History since 1950</h3>
          <div className="seg small" role="group">{(["enso_oni", "iod_dmi", "sam_index"] as const).filter((k) => d.series[k]).map((k) =>
            <button key={k} className={which === k ? "on" : ""} aria-pressed={which === k} onClick={() => setWhich(k)}>{{ enso_oni: "El Niño", iod_dmi: "Indian Ocean Dipole", sam_index: "Southern Annular Mode" }[k]}</button>)}</div></div>
        <EChart option={opt} height={280} label="El Niño index history" />
        <p className="caption">Red shading: El Niño side (+0.5 °C or more); blue: La Niña side. Scroll on the chart to zoom. El Niño and La Niña can also show as bands on any chart: tick them in Settings: Events on charts.</p>
      </div>
      <SeaMap />
      <div className="grid two">
        <div className="card">
          <h3>What it usually means</h3>
          {Object.entries(d.notes).map(([e, n]) => (
            <details key={e} open={e === "NZL"}><summary><b>{n.name}</b></summary>
              <p className="small"><b>El Niño:</b> {n.el_nino}</p><p className="small"><b>La Niña:</b> {n.la_nina}</p></details>
          ))}
          <p className="caption">Tendencies, not rules: each episode differs. From NIWA, the Bureau of Meteorology, NOAA and the WMO.</p>
        </div>
        <div className="card">
          <h3>How each country&apos;s temperature has moved with El Niño</h3>
          <div style={{ overflowX: "auto", maxHeight: 420 }}>
            <table className="small"><thead><tr><th>Country</th><th className="num">Link (r)</th><th className="num">Years</th></tr></thead>
              <tbody>{d.link.slice(0, 60).map((r) => <tr key={r.entity_id}><td><Link href={`/entity/${r.entity_id}#climate`}>{r.name}</Link></td>
                <td className={`num ${r.temp_r < 0 ? "neg" : ""}`}>{r.temp_r > 0 ? "+" : ""}{r.temp_r.toFixed(2)}</td><td className="num">{r.years}</td></tr>)}</tbody></table>
          </div>
          <p className="caption">Correlation of each year&apos;s temperature against normal (its warming trend taken out) with the year&apos;s average El Niño index. Above 0: warmer in El Niño years. Moving together is not proof of cause.</p>
        </div>
      </div>
      {d.episodes.length ? (
        <div className="card"><h3>Episodes</h3>
          <div style={{ overflowX: "auto", maxHeight: 300 }}><table className="small"><thead><tr><th>From</th><th>To</th><th>Episode</th></tr></thead>
            <tbody>{[...d.episodes].reverse().map((e) => <tr key={e.start_date}><td>{e.start_date.slice(0, 7)}</td><td>{e.end_date?.slice(0, 7)}</td><td>{e.title}</td></tr>)}</tbody></table></div>
        </div>
      ) : null}
    </>
  );
}

function Policy() {
  const [p, setP] = useState<ClimatePolicy | null>(null);
  useEffect(() => { api.climatePolicy().then(setP).catch(() => setP(null)); }, []);
  if (!p || !p.rows.length) return <Nothing what="net zero targets or carbon prices (both are files you save by hand; see Data status)" />;
  const STATUS: Record<number, string> = { 4: "Achieved", 3: "In law", 2: "Policy document", 1: "Pledge", 0.5: "Proposed" };
  return (
    <div className="card">
      <h3>Net zero targets and carbon prices <Help note="climate_policy" /></h3>
      <div style={{ overflowX: "auto", maxHeight: 640 }}>
        <table className="small">
          <thead><tr><th>Country</th><th className="num">Share of world CO2</th><th className="num">Per person (t CO2e)</th><th className="num">Net zero by</th><th>How firm</th>
            <th className="num">Carbon price (US$/t)</th><th>Paris Agreement</th></tr></thead>
          <tbody>{p.rows.map((r) => <tr key={r.entity_id} className={r.entity_id === "NZL" ? "selected" : ""}>
            <td><Link href={`/entity/${r.entity_id}#climate`}>{r.name}</Link></td>
            <td className="num">{r.co2_share_world != null ? `${r.co2_share_world.toFixed(2)}%` : ""}</td>
            <td className="num">{r.ghg_per_capita != null ? r.ghg_per_capita.toFixed(1) : ""}</td>
            <td className="num">{r.net_zero_year ?? ""}</td><td>{r.net_zero_status != null ? STATUS[r.net_zero_status] ?? "" : ""}</td>
            <td className="num">{r.carbon_price != null ? `${r.carbon_price.toFixed(0)} (${r.carbon_price_year})` : ""}</td>
            <td>{r.paris ? r.paris.slice(0, 4) : ""}</td></tr>)}</tbody>
        </table>
      </div>
      <p className="caption">Net Zero Tracker; World Bank Carbon Pricing Dashboard (the highest national scheme; EU countries also sit under the EU ETS); Paris Agreement dates from the UN treaty records.</p>
    </div>
  );
}

// Weather by month: up to four countries side by side (temperature or rainfall), each month's 1991-2020 average.
function WeatherTab() {
  const [ids, setIds] = useState<string[]>(["NZL", "AUS", "GBR", "USA"]);
  const [adding, setAdding] = useState("");
  return (
    <>
      <div className="chips-row small">
        {ids.map((id) => <span key={id} className="chip">{id} <button className="x" aria-label={`Remove ${id}`} onClick={() => setIds(ids.filter((x) => x !== id))}>×</button></span>)}
        {ids.length < 4 && <CountryChoice label="Add" value={adding} onChange={(c) => { if (!ids.includes(c)) setIds([...ids, c]); setAdding(""); }} />}
      </div>
      {ids.length > 0 && <WeatherCard entities={ids} title="Weather by month" />}
      {ids.length === 1 && <p className="caption">Add countries to compare them.</p>}
      {ids.map((id) => <WeatherCard key={id} entities={[id]} compact />)}
    </>
  );
}

function ClimatePage() {
  const router = useRouter();
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "world");
  const [country, setCountry] = useState(params.get("country") ?? "NZL");
  const [o, setO] = useState<ClimateOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.climate().then(setO).catch((e) => setError(String(e.message || e))); }, []);
  const withCountry = (t: Tab) => t === "country" || t === "zones" || t === "nature";
  const go = (t: Tab) => { setTab(t); router.replace(`/climate?tab=${t}${withCountry(t) ? `&country=${country}` : ""}`, { scroll: false }); };
  const pick = (c: string) => { setCountry(c); router.replace(`/climate?tab=${tab}&country=${c}`, { scroll: false }); };
  if (error) return <p className="error">{error}</p>;
  if (!o) return <p className="muted">Loading…</p>;
  return (
    <div className="grid sector-page">
      <div className="title-row"><h1>Climate</h1> <Help note="climate" /></div>
      <div className="seg" role="tablist">{TABS.map(([t, label]) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => go(t)}>{label}</button>)}</div>
      {tab === "world" ? <World o={o} /> : tab === "map" ? <MapTab o={o} /> : tab === "storms" ? <Storms /> : tab === "enso" ? <Enso /> : tab === "policy" ? <Policy />
        : tab === "weather" ? <WeatherTab />
        : tab === "zones" ? <ZonesTab country={country} onCountry={pick} /> : tab === "nature" ? <NatureTab country={country} onCountry={pick} /> : (
        <>
          <div className="chips-row small"><CountryChoice value={country} onChange={pick} /></div>
          <ClimateCard entity={country} name={country} />
        </>
      )}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><ClimatePage /></Suspense>;
}
