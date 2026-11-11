"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import AskButton from "@/components/AskButton";
import CountryChoice from "@/components/CountryChoice";
import EChart from "@/components/EChart";
import IndicatorSet from "@/components/IndicatorSet";
import WorldMap from "@/components/WorldMap";
import { compact } from "@/lib/format";
import { logHistory } from "@/lib/history";
import {
  type Centre, type CoverList, flowOption, hectares, land, type LandClimate, type LandOverview, type LandRanking, landUseOption,
  type LandWhere, lcdbColour, linesOption, type NzLand, stackedYearsOption, type StreetTrees,
} from "@/lib/land";
import { LAND_COVER } from "@/lib/maplook";
import { useSettings } from "@/lib/settings";

// Land: what the world's land is used for since 1700, where it goes, cities and how they
// spread, trees, New Zealand's land cover in detail, and land beside climate.

type Tab = "use" | "where" | "cities" | "trees" | "nz" | "climate";
const TABS: [Tab, string][] = [["use", "Land use"], ["where", "Where the land goes"], ["cities", "Cities"], ["trees", "Trees"],
  ["nz", "New Zealand"], ["climate", "Land and climate"]];
const INTRO: Record<Tab, string> = {
  use: "Cropland, meadows and pastures, and forest by country or for the world: FAOSTAT from 1961, and HYDE's long run back to 1700 (dashed; modelled from population and old maps, so rough).",
  where: "Earth's surface down to the farmland that feeds us. Most farmland is grazing for animals, which give far less of our food than crops do.",
  cities: "About 11,000 urban centres from the European Commission's Global Human Settlement Layer: people and built-up land from 1975 to 2025 (2030 projected), and their outlines.",
  trees: "Tree cover and what is lost each year (Global Forest Watch), tree cover in cities worked out from the land cover pictures, and council street-tree lists (Auckland first).",
  nz: "New Zealand's Land Cover Database at every survey since 1996, what changed into what, by region, and forestry and farm figures.",
  climate: "Land change beside temperature, fires and emissions, both ways round: clearing and farming add emissions and forests take them up; drought and heat change the land.",
};
const NOT_LOADED = <p>Nothing stored for this yet. It comes with <code>.\refresh.bat</code> (FAOSTAT, HYDE, GHSL, Global Forest Watch, Auckland trees);
  the NZ Land Cover Database and MPI forestry tables are saved by hand (see <Link href="/data">Data status</Link>).</p>;

function LandView() {
  const router = useRouter();
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "use");
  const [entity, setEntity] = useState(params.get("country") ?? "world");
  const go = (t: Tab) => { setTab(t); router.replace(`/land?tab=${t}${entity !== "world" ? `&country=${entity}` : ""}`, { scroll: false }); };
  const pickCountry = (c: string) => { setEntity(c); router.replace(`/land?tab=${tab}${c !== "world" ? `&country=${c}` : ""}`, { scroll: false }); };
  useEffect(() => { logHistory({ kind: "page", title: "Land", url: "/land", detail: "page" }); }, []);
  return (
    <div className="grid sector-page">
      <div className="title-row"><h1>Land</h1>
        <AskButton title={`Land: ${TABS.find((t) => t[0] === tab)?.[1]}`} parts={async () => [
          { key: "description", kind: "description", label: "What this tab shows", text: INTRO[tab] }]} /></div>
      <div className="seg" role="tablist">{TABS.map(([t, label]) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => go(t)}>{label}</button>)}</div>
      <p className="ink-2" style={{ marginTop: 0, maxWidth: 860 }}>{INTRO[tab]}</p>
      {tab === "use" && <UseTab entity={entity} pick={pickCountry} />}
      {tab === "where" && <WhereTab />}
      {tab === "cities" && <CitiesTab />}
      {tab === "trees" && <TreesTab entity={entity === "world" ? "NZL" : entity} pick={pickCountry} />}
      {tab === "nz" && <NzTab />}
      {tab === "climate" && <ClimateTab entity={entity === "world" ? "NZL" : entity} pick={pickCountry} />}
    </div>
  );
}

function Picker({ entity, pick, world = true }: { entity: string; pick: (c: string) => void; world?: boolean }) {
  return (
    <div className="chips-row small">
      {world ? <button className={entity === "world" ? "on" : ""} onClick={() => pick("world")}>World</button> : null}
      <CountryChoice value={entity === "world" ? "" : entity} onChange={pick} />
    </div>
  );
}

// ----------------------------------------------------------------------------- land use
function UseTab({ entity, pick }: { entity: string; pick: (c: string) => void }) {
  const [o, setO] = useState<LandOverview | null>(null);
  const [mode, setMode] = useState<"ha" | "pct" | "person">("pct");
  const [from, setFrom] = useState(1961);
  const [rankBy, setRankBy] = useState("land_forest_ha");
  const [rankFrom, setRankFrom] = useState(1990);
  const [per, setPer] = useState<"change" | "pct">("change");
  const [rank, setRank] = useState<LandRanking | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setO(null); land.overview(entity).then(setO).catch((e) => setError(String(e.message || e))); }, [entity]);
  useEffect(() => { land.ranking(rankBy, rankFrom, per).then(setRank).catch(() => setRank(null)); }, [rankBy, rankFrom, per]);
  const option = useCallback(() => (o ? landUseOption(o, mode, from) : {}), [o, mode, from]);
  if (error) return <p className="error">{error}</p>;
  if (!o) return <p className="muted">Loading…</p>;
  const has = Object.keys(o.series).some((k) => k.startsWith("land_"));
  const last = (id: string) => o.series[id]?.at(-1);
  const rows = rank?.rows ?? [];
  const by = (r: LandRanking["rows"][number]) => (per === "pct" ? r.pct ?? 0 : r.change);
  const gainers = rows.filter((r) => by(r) > 0).slice(0, 10);
  const losers = [...rows].reverse().filter((r) => by(r) < 0).slice(0, 10);
  return (
    <>
      <Picker entity={entity} pick={pick} />
      {!has ? <div className="card">{NOT_LOADED}</div> : (
        <div className="card">
          <div className="card-head"><h3>What the land is used for{entity === "world" ? ", world" : ""}</h3>
            <span className="seg small">
              {(["pct", "ha", "person"] as const).map((m) => <button key={m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}>
                {m === "pct" ? "% of land" : m === "ha" ? "Hectares" : "Per person"}</button>)}
            </span></div>
          <div className="chips-row small">From{" "}
            {[1700, 1800, 1900, 1961, 1990].map((y) => <button key={y} className={from === y ? "on" : ""} onClick={() => setFrom(y)}>{y}</button>)}
          </div>
          <EChart option={option} height={340} label="Land use over time" />
          <div className="grid three small">
            {[["land_forest_ha", "Forest"], ["land_cropland_ha", "Cropland"], ["land_pasture_ha", "Meadows and pastures"]].map(([id, label]) => (
              <div key={id}><span className="muted">{label}, {last(id)?.[0] ?? "–"}</span><br /><b>{hectares(last(id)?.[1])}</b></div>))}
          </div>
          <p className="caption">FAOSTAT land use (solid bands, from 1961). Dashed lines are HYDE 3.3: modelled before 1961, graded exploratory; they can differ from FAOSTAT
            where the two overlap because HYDE counts grazing land more widely. Per person uses UN population.</p>
        </div>
      )}
      <div className="card">
        <div className="card-head"><h3>Biggest changes since {rankFrom}</h3>
          <span className="chips-row small">
            <select value={rankBy} onChange={(e) => setRankBy(e.target.value)} aria-label="Figure">
              <option value="land_forest_ha">Forest</option><option value="land_agri_ha">Farmland</option>
              <option value="land_cropland_ha">Cropland</option><option value="land_pasture_ha">Meadows and pastures</option>
              <option value="land_planted_forest_ha">Planted forest</option>
            </select>
            <select value={rankFrom} onChange={(e) => setRankFrom(+e.target.value)} aria-label="Since">
              {[1961, 1990, 2000, 2010].map((y) => <option key={y} value={y}>since {y}</option>)}
            </select>
            <select value={per} onChange={(e) => setPer(e.target.value as "change" | "pct")} aria-label="Measure">
              <option value="change">hectares</option><option value="pct">per cent</option>
            </select></span></div>
        {rows.length ? (
          <div className="grid two">
            {[["Gained most", gainers], ["Lost most", losers]].map(([title, list]) => (
              <div key={title as string}><h4>{title as string}</h4>{!(list as LandRanking["rows"]).length && <p className="muted small">None.</p>}<table className="small"><tbody>{(list as LandRanking["rows"]).map((r) => (
                <tr key={r.entity_id}><td><Link href={`/land?tab=use&country=${r.entity_id}`}>{r.name}</Link></td>
                  <td className="num">{r.change > 0 ? "+" : ""}{hectares(r.change)}</td>
                  <td className="num muted">{r.pct === null ? "" : `${r.pct > 0 ? "+" : ""}${r.pct.toFixed(1)}%`}</td></tr>))}</tbody></table></div>))}
          </div>
        ) : <p className="muted small">No figures for this yet.</p>}
        <p className="caption">{rank ? `${rank.start} to ${rank.end}, FAOSTAT.` : ""} Click a country for its chart.</p>
      </div>
      <IndicatorSet ids={["land_forest_pct", "land_agri_pct", "land_cropland_pct", "land_pasture_pct"]} empty={NOT_LOADED} mapTitle="Map" />
    </>
  );
}

// ----------------------------------------------------------------------------- where the land goes
function WhereTab() {
  const [w, setW] = useState<LandWhere | null>(null);
  const [year, setYear] = useState<number | undefined>();
  useEffect(() => { land.where(year).then(setW).catch(() => setW(null)); }, [year]);
  if (!w) return <p className="muted">Loading…</p>;
  const rows: [string, number | null, number, string][] = [
    ["Earth's surface", w.surface_ha, w.surface_ha, "71% is ocean"],
    ["Land", w.land_ha, w.surface_ha, "10% is glaciers and 19% barren: deserts, salt flats, beaches, rock"],
    ["Habitable land", w.habitable_ha, w.land_ha, ""],
    ["Farmland", w.agri_ha, w.habitable_ha, "the rest of habitable land: forest, shrub, cities, lakes and rivers"],
    ["Meadows and pastures (grazing)", w.pasture_ha, w.agri_ha ?? 1, `livestock and dairy give ${Math.round(w.livestock_calories_share * 100)}% of the world's calories and ${Math.round(w.livestock_protein_share * 100)}% of its protein`],
    ["Cropland", w.cropland_ha, w.agri_ha ?? 1, `crops for people give ${Math.round((1 - w.livestock_calories_share) * 100)}% of calories and ${Math.round((1 - w.livestock_protein_share) * 100)}% of protein (some cropland grows animal feed)`],
  ];
  return (
    <div className="card">
      <div className="card-head"><h3>Where the land goes{w.year ? `, ${w.year}` : ""}</h3>
        {w.years.length > 1 ? <label className="small">Year <input type="range" min={w.years[0]} max={w.years.at(-1)} value={w.year ?? w.years.at(-1)}
          onChange={(e) => setYear(+e.target.value)} aria-label="Year" /> <b>{w.year}</b></label> : null}</div>
      {!w.agri_ha ? NOT_LOADED : (
        <table className="small"><tbody>{rows.map(([label, v, of, note], i) => (
          <tr key={label}><td style={{ paddingLeft: i * 12 }}>{label}</td>
            <td className="num"><b>{v ? `${compact(v / 100)} km²` : "–"}</b></td>
            <td className="bar-cell num">{v && of ? <><span style={{ width: `${Math.min(100, (v / of) * 100)}%` }} />{((v / of) * 100).toFixed(0)}%</> : null}</td>
            <td className="muted">{note}</td></tr>))}</tbody></table>
      )}
      <p className="caption">{w.about} Each share is of the line above (grazing and cropland are shares of farmland).</p>
    </div>
  );
}

// ----------------------------------------------------------------------------- cities
const SORTS: [string, string][] = [["people", "People"], ["area", "Built-up area"], ["growth", "Growth in people since 1975"],
  ["built_growth", "Growth in built-up area"], ["density", "People per km² built up"]];

function CitiesTab() {
  const [sort, setSort] = useState("people");
  const [country, setCountry] = useState("");
  const [search, setSearch] = useState("");
  const [rows, setRows] = useState<Centre[] | null>(null);
  const [total, setTotal] = useState(0);
  const [picked, setPicked] = useState<string[]>([]);
  useEffect(() => {
    land.cities({ sort, country: country || undefined, search: search || undefined, limit: 100 })
      .then((r) => { setRows(r.rows); setTotal(r.total); }).catch(() => setRows([]));
  }, [sort, country, search]);
  useEffect(() => {
    if (picked.length) return;
    land.cities({ search: "auckland", limit: 1 }).then((a) => land.cities({ search: "sydney", limit: 1 }).then((b) =>
      land.cities({ search: "copenhagen", limit: 1 }).then((c) => setPicked([...a.rows, ...b.rows, ...c.rows].map((r) => r.id))))).catch(() => undefined);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (!rows) return <p className="muted">Loading…</p>;
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id].slice(-6)));
  return (
    <>
      {picked.length ? <CompareOutlines ids={picked} remove={toggle} /> : null}
      <div className="card">
        <div className="card-head"><h3>Urban centres ({total.toLocaleString()})</h3>
          <span className="chips-row small">
            <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort by">{SORTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            <CountryChoice value={country} onChange={setCountry} />
            {country ? <button className="link" onClick={() => setCountry("")}>All countries</button> : null}
            <input type="search" placeholder="Find a city" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Find a city" />
          </span></div>
        {!rows.length ? NOT_LOADED : (
          <table className="small">
            <thead><tr><th>Compare</th><th>City</th><th>Country</th><th className="num">People</th><th className="num">Since 1975</th>
              <th className="num">Built-up km²</th><th className="num">Since 1975</th><th className="num">People per km²</th><th className="num">Tree cover</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.id} className={picked.includes(r.id) ? "selected" : ""}>
                <td><input type="checkbox" checked={picked.includes(r.id)} onChange={() => toggle(r.id)} aria-label={`Compare ${r.name}`} /></td>
                <td>{r.name}</td><td>{r.country_name}</td>
                <td className="num">{compact(r.people ?? 0)}</td>
                <td className="num">{r.growth === null ? "–" : `${r.growth > 0 ? "+" : ""}${r.growth.toFixed(0)}%`}</td>
                <td className="num">{r.built_km2 === null ? "–" : r.built_km2.toFixed(0)}</td>
                <td className="num">{r.built_growth === null ? "–" : `${r.built_growth > 0 ? "+" : ""}${r.built_growth.toFixed(0)}%`}</td>
                <td className="num">{r.density === null ? "–" : Math.round(r.density).toLocaleString()}</td>
                <td className="num">{r.tree_pct === null || r.tree_pct === undefined ? "" : `${r.tree_pct.toFixed(0)}%`}</td>
              </tr>))}</tbody>
          </table>
        )}
        <p className="caption">GHSL Urban Centre Database (European Commission JRC). An urban centre is the built-up area of 1,500 or more people per km² around a city, so its figure
          can differ from the city&apos;s own boundary or the UN&apos;s agglomeration. 2025 figures are estimates from satellite pictures; tree cover shows once worked out (Trees tab).</p>
      </div>
      <div className="card">
        <h3>City outlines on the map</h3>
        <div className="map-box"><WorldMap values={[]} unit="" decimals={0} diverging={false} hideScale layers={["urban_centres"]} onPick={() => {}} /></div>
        <p className="caption">Darker outlines grew more since 1975. Zoom in for smaller cities; the same layer is on the Map (Layers: People and places, City outlines).</p>
      </div>
    </>
  );
}

// Outlines side by side at one scale: each drawn in km around its own middle.
function CompareOutlines({ ids, remove }: { ids: string[]; remove: (id: string) => void }) {
  const [fc, setFc] = useState<GeoJSON.FeatureCollection | null>(null);
  useEffect(() => { land.outlines(ids).then(setFc).catch(() => setFc(null)); }, [ids.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  const shapes = useMemo(() => (fc?.features ?? []).map((f) => {
    const c = f.properties as Centre;
    const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.type === "MultiPolygon" ? f.geometry.coordinates : [];
    const pts = polys.flat(2) as number[][];
    const lat0 = pts.reduce((a, p) => a + p[1], 0) / Math.max(1, pts.length);
    const lon0 = pts.reduce((a, p) => a + p[0], 0) / Math.max(1, pts.length);
    const k = Math.cos((lat0 * Math.PI) / 180) * 111.32;
    const rings = polys.map((poly) => (poly as number[][][]).map((ring) => ring.map(([x, y]) => [(x - lon0) * k, -(y - lat0) * 111.32])));
    const ext = Math.max(...rings.flat(2).map((p) => Math.max(Math.abs(p[0]), Math.abs(p[1]))), 1);
    return { c, rings, ext };
  }), [fc]);
  if (!shapes.length) return null;
  const ext = Math.max(...shapes.map((s) => s.ext)) * 1.05;
  return (
    <div className="card">
      <h3>Compare cities at the same scale</h3>
      <div className="outline-grid">
        {shapes.map(({ c, rings }) => (
          <figure key={c.id}>
            <svg viewBox={`${-ext} ${-ext} ${ext * 2} ${ext * 2}`} width="100%" role="img" aria-label={`Outline of ${c.name}`}>
              {rings.map((poly, i) => <path key={i} fillRule="evenodd" fill="var(--series-1)" fillOpacity={0.35} stroke="var(--series-1)" strokeWidth={ext / 150}
                d={poly.map((r) => r.map((p, j) => `${j ? "L" : "M"}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join("") + "Z").join("")} />)}
              <line x1={-ext * 0.9} x2={-ext * 0.9 + 10} y1={ext * 0.9} y2={ext * 0.9} stroke="var(--ink)" strokeWidth={ext / 100} />
              <text x={-ext * 0.9} y={ext * 0.82} fontSize={ext / 12} fill="var(--ink-2)">10 km</text>
            </svg>
            <figcaption><b>{c.name}</b> <button className="link small" onClick={() => remove(c.id)}>remove</button><br />
              {compact(c.people ?? 0)} people ({c.now}), {c.built_km2?.toFixed(0) ?? "–"} km² built up
              {c.built_first_km2 ? `, up from ${c.built_first_km2.toFixed(0)} km² in ${c.first}` : ""}</figcaption>
          </figure>))}
      </div>
      <p className="caption">Each outline is the urban centre today, drawn at the same scale (the bar is 10 km). Tick cities in the table to add them (six at most).
        GHSL gives one outline per centre; how far each spread shows as the built-up area then and now.</p>
    </div>
  );
}

// ----------------------------------------------------------------------------- trees
function TreesTab({ entity, pick }: { entity: string; pick: (c: string) => void }) {
  const [o, setO] = useState<LandOverview | null>(null);
  const [cover, setCover] = useState<CoverList | null>(null);
  const [trees, setTrees] = useState<StreetTrees | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const settings = useSettings();
  useEffect(() => { land.overview(entity).then(setO).catch(() => setO(null)); }, [entity]);
  useEffect(() => { land.trees().then(setTrees).catch(() => setTrees(null)); }, []);
  useEffect(() => {
    let t: ReturnType<typeof setTimeout>;
    const poll = () => land.cover().then((c) => { setCover(c); if (c.job.state === "running") t = setTimeout(poll, 4000); }).catch(() => undefined);
    poll();
    return () => clearTimeout(t);
  }, [msg]);
  const loss = useCallback(() => linesOption([{ label: "Tree cover lost", pts: o?.series.gfw_tree_cover_loss_ha ?? [] }], ["ha"]), [o]);
  const planted = useCallback(() => linesOption([{ label: "Trees planted", pts: (trees?.planted ?? []).map((p) => [p.y, p.n]) }], ["trees"]), [trees]);
  const start = (body: { top?: number; country?: string }) => land.coverStart(body).then(() => setMsg(`started ${Date.now()}`)).catch((e) => setMsg(String(e.message || e)));
  return (
    <>
      <Picker entity={entity} pick={pick} world={false} />
      <div className="card">
        <h3>Tree cover lost each year, {entity}</h3>
        {o?.series.gfw_tree_cover_loss_ha?.length ? <EChart option={loss} height={260} label="Tree cover lost each year" /> : NOT_LOADED}
        <p className="caption">Global Forest Watch (Hansen, University of Maryland), trees taller than 5 m covering 30% or more of the ground. Harvested plantations count as
          loss and regrowth is not netted off, so in New Zealand much of the loss is pine harvest that is replanted.
          {o?.series.gfw_tree_cover_pct?.length ? ` Tree cover in ${o.series.gfw_tree_cover_pct.at(-1)![0]}: ${o.series.gfw_tree_cover_pct.at(-1)![1].toFixed(0)}% of the land.` : ""}</p>
      </div>
      <div className="card">
        <div className="card-head"><h3>Tree cover in cities</h3>
          <span className="chips-row small">
            <button onClick={() => start({ top: 25, country: "NZL" })} disabled={!settings.land_city_cover}>Work out New Zealand&apos;s cities</button>
            <button onClick={() => start({ top: 50 })} disabled={!settings.land_city_cover}>Work out the 50 biggest cities</button></span></div>
        {cover?.job.state === "running" ? <p className="small">Working out… {cover.job.step} ({cover.job.done ?? 0} of {cover.job.total ?? "?"})</p> : null}
        {cover?.job.error ? <p className="small error">{cover.job.error}</p> : null}
        {msg && !msg.startsWith("started") ? <p className="small error">{msg}</p> : null}
        {cover?.rows.length ? (
          <table className="small">
            <thead><tr><th>City</th><th className="num">Tree cover</th><th className="num">Grass and shrubs</th><th className="num">Built-up</th>
              <th className="num">Trees (estimate)</th><th className="num">Per person (estimate)</th></tr></thead>
            <tbody>{cover.rows.map((r) => (
              <tr key={r.id}><td>{r.name}</td><td className="num">{(r.shares["10"] ?? 0).toFixed(0)}%</td>
                <td className="num">{((r.shares["20"] ?? 0) + (r.shares["30"] ?? 0)).toFixed(0)}%</td>
                <td className="num">{(r.shares["50"] ?? 0).toFixed(0)}%</td>
                <td className="num">~{compact(r.trees_estimate)}</td><td className="num">~{r.trees_per_person?.toFixed(1) ?? "–"}</td></tr>))}</tbody>
          </table>
        ) : <p className="muted small">No city worked out yet. Each city reads a few dozen land cover pictures (saved copies first), once.</p>}
        <div className="swatches small">{LAND_COVER.slice(0, 6).map(([n, c]) => <span key={n} className="legend-item"><i style={{ background: c }} />{n}</span>)}</div>
        <p className="caption">Shares of the urban centre&apos;s outline in each ESA WorldCover {settings.land_cover_year} class, read from the land cover pictures at about 30 m a pixel.
          Tree counts are estimates: tree cover area times {cover?.trees_per_ha ?? 150} trees a hectare of canopy (street and park trees have crowns of 50 to 100 m²).</p>
      </div>
      <div className="card">
        <h3>Council street trees{trees?.council ? `: ${trees.council[0].toUpperCase()}${trees.council.slice(1)}` : ""}</h3>
        {!trees?.total ? NOT_LOADED : (
          <div className="grid two">
            <div><p className="small"><b>{trees.total.toLocaleString()}</b> trees listed. The commonest:</p>
              <table className="small"><tbody>{(trees.species ?? []).slice(0, 15).map((s) => (
                <tr key={s.name}><td>{s.name}{s.species && s.species !== s.name ? <span className="muted"> ({s.species})</span> : null}</td>
                  <td className="num">{s.n.toLocaleString()}</td><td className="num muted">{s.height ? `${s.height.toFixed(0)} m` : ""}</td></tr>))}</tbody></table></div>
            <div>{trees.planted?.length ? <EChart option={planted} height={240} label="Trees planted by year" /> : <p className="muted small">The list gives no planting years.</p>}
              <p className="caption">Planting years where the council records them. Every tree is on the Map from street level (Layers: Earth, Street trees).</p></div>
          </div>
        )}
      </div>
    </>
  );
}

// ----------------------------------------------------------------------------- New Zealand
function NzTab() {
  const [level, setLevel] = useState(2);
  const [region, setRegion] = useState("NZL");
  const [y0, setY0] = useState<number | undefined>();
  const [y1, setY1] = useState<number | undefined>();
  const [d, setD] = useState<NzLand | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  useEffect(() => { land.nz({ level, region, y0, y1 }).then(setD).catch(() => setD(null)); }, [level, region, y0, y1]);
  const bars = useCallback(() => (d ? stackedYearsOption(d.years, d.classes.filter((c) => !focus || c === focus),
    (y, c) => d.cover[String(y)]?.[c] ?? 0, "ha") : {}), [d, focus]);
  const flows = useCallback(() => (d ? flowOption(d.flows, d.y0, d.y1) : {}), [d]);
  if (!d) return <p className="muted">Loading…</p>;
  if (!d.years.length) return (
    <>
      <div className="card">{NOT_LOADED}</div>
      <IndicatorSet ids={["nz_new_planting_ha", "nz_plantation_ha", "nz_ets_forest_ha", "nz_harvest_area_ha"]} empty={<p>No forestry tables saved yet.</p>} />
    </>
  );
  return (
    <>
      <div className="chips-row small">
        <span className="seg">{Object.entries(d.levels).map(([k, label]) => <button key={k} className={level === +k ? "on" : ""} onClick={() => setLevel(+k)}>{label}</button>)}</span>
        <select value={region} onChange={(e) => setRegion(e.target.value)} aria-label="Region">
          <option value="NZL">All New Zealand</option>{d.regions.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</select>
        {focus ? <button className="link" onClick={() => setFocus(null)}>All classes (showing {focus})</button> : null}
      </div>
      <div className="card">
        <h3>Land cover at each survey, {region === "NZL" ? "New Zealand" : d.regions.find((r) => r.id === region)?.name}</h3>
        <EChart option={bars} height={340} label="NZ land cover by survey year" onReady={(c) => c.on("legendselectchanged", () => undefined)} />
        <div className="swatches small">{d.classes.map((c, i) => <button key={c} className="link legend-item" onClick={() => setFocus(focus === c ? null : c)}>
          <i style={{ background: lcdbColour(c, i) }} />{c}</button>)}</div>
        <p className="caption">Manaaki Whenua – Landcare Research, Land Cover Database. Click a class to show it alone. Survey years are when the satellite pictures were taken.</p>
      </div>
      <div className="card">
        <div className="card-head"><h3>What changed into what, {d.y0} to {d.y1}</h3>
          <span className="chips-row small">
            <select value={d.y0} onChange={(e) => setY0(+e.target.value)} aria-label="From">{d.years.slice(0, -1).map((y) => <option key={y} value={y}>{y}</option>)}</select> to
            <select value={d.y1} onChange={(e) => setY1(+e.target.value)} aria-label="To">{d.years.slice(1).map((y) => <option key={y} value={y}>{y}</option>)}</select></span></div>
        {d.flows.length ? <EChart option={flows} height={Math.max(260, Math.min(25, d.flows.length) * 22)} label="Land cover changes" /> : <p className="muted small">No changes between these surveys at this level.</p>}
        <p className="caption">The 25 biggest changes, in hectares. Between surveys further apart, steps add up (land harvested then replanted shows both ways).
          The changed areas are on the Map from region level (Layers: Earth, Land cover change (NZ)).</p>
      </div>
      {d.regions.length ? (
        <div className="card">
          <h3>By region, {d.years.at(-1)}</h3>
          <table className="small">
            <thead><tr><th>Region</th>{d.classes.map((c) => <th key={c} className="num">{c}</th>)}</tr></thead>
            <tbody>{d.regions.map((r) => (
              <tr key={r.id} className={r.id === region ? "selected" : ""} onClick={() => setRegion(r.id)} style={{ cursor: "pointer" }}>
                <td>{r.name}</td>{d.classes.map((c) => <td key={c} className="num">{r.cover[c] ? `${((r.cover[c] / r.total) * 100).toFixed(0)}%` : ""}</td>)}</tr>))}</tbody>
          </table>
          <p className="caption">Share of each region&apos;s land in each kind. Click a region to set the charts.</p>
        </div>
      ) : <p className="small muted">Totals by region need Stats NZ&apos;s regional council boundaries saved beside the LCDB (see Data status).</p>}
      <IndicatorSet ids={["nzreg_dairy_cattle", "nzreg_sheep", "nzreg_beef_cattle", "nzreg_plantation_ha", "nz_new_planting_ha", "nz_plantation_ha", "nz_ets_forest_ha",
        "nz_farm_to_forest_ha", "nz_harvest_area_ha"]} empty={<p>No farm or forestry figures stored yet (Stats NZ comes with refresh; MPI tables are saved by hand).</p>} />
    </>
  );
}

// ----------------------------------------------------------------------------- land and climate
function ClimateTab({ entity, pick }: { entity: string; pick: (c: string) => void }) {
  const [d, setD] = useState<LandClimate | null>(null);
  useEffect(() => { land.climate(entity).then(setD).catch(() => setD(null)); }, [entity]);
  const nm = (id: string) => d?.names[id]?.name ?? id;
  const landLines = useCallback(() => linesOption(["land_forest_ha", "land_agri_ha", "land_pasture_ha"].filter((i) => d?.series[i])
    .map((i) => ({ label: nm(i), pts: d!.series[i] })), ["ha"]), [d]); // eslint-disable-line react-hooks/exhaustive-deps
  const climLines = useCallback(() => {
    const lines = [];
    if (d?.series.temp_anomaly) lines.push({ label: nm("temp_anomaly"), pts: d.series.temp_anomaly, axis: 0 });
    for (const i of ["ghg_sector_lulucf", "ghg_sector_agriculture", "wildfire_area", "gfw_tree_cover_loss_ha", "land_use_change_co2", "owid_co2_land_use_change_co2"]) {
      if (d?.series[i]) lines.push({ label: nm(i), pts: d.series[i], axis: 1 });
    }
    return linesOption(lines, ["°C", ""]);
  }, [d]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!d) return <p className="muted">Loading…</p>;
  return (
    <>
      <Picker entity={entity} pick={pick} world={false} />
      <div className="grid two">
        <div className="card"><h3>Land, {entity}</h3>{Object.keys(d.series).some((k) => k.startsWith("land_")) ? <EChart option={landLines} height={280} label="Land over time" /> : NOT_LOADED}</div>
        <div className="card"><h3>Climate, fires and emissions from land, {entity}</h3><EChart option={climLines} height={280} label="Climate over time" />
          <p className="caption">Temperature against normal on the left axis; the rest on the right (each in its own unit, so compare their shape over time).</p></div>
      </div>
      <p className="small ink-2">Both ways round: clearing forest and farming add emissions (land use and agriculture sectors), while forest growing back takes carbon up;
        drought, heat and fire change the land. The <Link href="/relationships">relationship scan</Link> looks at these pairs across every country after each refresh.</p>
    </>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><LandView /></Suspense>;
}
