"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import LandCard from "@/components/LandCard";
import CountryChoice from "@/components/CountryChoice";
import EChart from "@/components/EChart";
import Help from "@/components/Help";
import WorldMap from "@/components/WorldMap";
import { api, type SectorDetail, type SectorMeasure, type SectorStage } from "@/lib/api";
import { openAsk } from "@/lib/ai";
import { amount, concentrationOption, hhiText, money, pricesOption, rankingBars, routesSankey, yearLines } from "@/lib/sectors";

// Sectors with a Land card (worldmodel_contract.land LAND_CARDS).
const LAND_SECTORS = new Set(["dairy", "beef", "sheep", "wheat", "maize", "rice", "soybeans", "forestry", "wine", "fruit"]);

// One sector across the globe: pick a stage of the chain, then see who makes it, who
// sells it and to whom, how concentrated that is, what it sells for, and one country's place.

type Measure = "production" | "exports" | "imports" | "reserves";
const MEASURE_TEXT: Record<Measure, string> = { production: "Production", exports: "Exports", imports: "Imports", reserves: "Reserves" };
const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));

function unitOf(st: SectorStage, m: Measure) {
  return m === "exports" || m === "imports" ? "US dollars" : st.production_unit || st.unit;
}

function Chain({ d, stage, pick }: { d: SectorDetail; stage: string; pick: (id: string) => void }) {
  return (
    <div className="sector-flow" role="tablist" aria-label="Stages">
      {d.stages.map((st, i) => (
        <span key={st.id} className="sector-flow-step">
          {i ? <span className="sector-arrow" aria-hidden>→</span> : null}
          <button role="tab" aria-selected={st.id === stage} className={st.id === stage ? "on" : ""} onClick={() => pick(st.id)}>
            <b>{st.name}</b>
            <span className="small ink-2">
              {st.production?.rows[0] ? `${st.production.rows[0].name} makes ${Math.round(st.production.rows[0].share ?? 0)}%` : ""}
              {st.production?.rows[0] && st.exports?.rows[0] ? " · " : ""}
              {st.exports ? `trade ${money(st.exports.total[st.exports.total.length - 1]?.[1])}` : ""}
            </span>
          </button>
        </span>
      ))}
    </div>
  );
}

function Concentration({ m, name, high }: { m: SectorMeasure; name: string; high: number }) {
  const last = m.concentration[m.concentration.length - 1];
  if (!last) return null;
  const [, top3, hhi, n] = last;
  return (
    <p className="small">
      <b>{name}, {last[0]}:</b> the top three have {top3}% of the world; HHI {hhi?.toLocaleString()} ({hhiText(hhi)}{(hhi ?? 0) > high ? ", a supply risk" : ""}), {n} countries with figures.
    </p>
  );
}

function StageView({ d, st, country, year }: { d: SectorDetail; st: SectorStage; country: string; year?: number }) {
  const have = (["production", "exports", "imports", "reserves"] as Measure[]).filter((m) => st[m]?.rows.length);
  const [measure, setMeasure] = useState<Measure>(have[0] ?? "exports");
  const [routes, setRoutes] = useState(true);
  useEffect(() => { if (!have.includes(measure) && have.length) setMeasure(have[0]); }, [st.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const m = st[measure];
  const unit = unitOf(st, measure);
  const ranking = useCallback(() => rankingBars(m?.rows ?? [], unit), [m, unit]);
  const conc = useCallback(() => concentrationOption((["production", "exports"] as Measure[]).filter((k) => st[k]?.concentration.length)
    .map((k) => ({ name: MEASURE_TEXT[k], c: st[k]!.concentration }))), [st]);
  const totals = useCallback(() => yearLines((m?.total ?? []).length ? [{ name: `World ${MEASURE_TEXT[measure].toLowerCase()}`, points: m!.total }] : [], unit), [m, measure, unit]);
  const sankey = useCallback(() => routesSankey(st.routes.slice(0, 25)), [st]);
  const mine = useCallback(() => {
    const s = st.country.series;
    const lines = (["production", "exports", "imports"] as const).filter((k) => s[k]?.length).map((k) => ({ name: MEASURE_TEXT[k], points: s[k] }));
    return yearLines(lines.filter((l) => l.name !== "Production"), "US dollars");
  }, [st]);
  const mineProd = useCallback(() => yearLines(st.country.series.production?.length ? [{ name: "Production", points: st.country.series.production }] : [], st.production_unit), [st]);
  const lines = measure === "exports" && routes ? st.routes.map((r) => ({ from: r.from, to: r.to, value: r.value,
    text: `${esc(r.from_name)} → ${esc(r.to_name)}: <b>${money(r.value)}</b>` })) : [];
  const ask = () => m && openAsk({ title: `${d.name}: ${st.name}, ${MEASURE_TEXT[measure].toLowerCase()} ${m.year}`,
    parts: [{ key: "data", kind: "data", label: "Leading countries", text: m.rows.slice(0, 25).map((r) => `${r.name}: ${amount(r.value, unit)} (${r.share}%)`).join("\n") },
      ...(st.how ? [{ key: "description", kind: "description" as const, label: "How it is made", text: Object.values(st.how).join(" ") }] : [])] });
  const c = st.country;
  return (
    <>
      <div className="chips-row small">
        <div className="seg" role="group" aria-label="Measure">
          {have.map((k) => <button key={k} className={measure === k ? "on" : ""} aria-pressed={measure === k} onClick={() => setMeasure(k)}>{MEASURE_TEXT[k]}</button>)}
        </div>
        {measure === "exports" && st.routes.length ? <label><input type="checkbox" checked={routes} onChange={(e) => setRoutes(e.target.checked)} /> Routes on the map</label> : null}
        <span className="muted">{st.hs.length ? `HS ${st.hs.join(", ")}` : "No trade code"}{year && m && m.year !== year ? ` · latest with figures: ${m.year}` : ""}</span>
      </div>
      {!have.length ? (
        <div className="card"><p>No figures for this stage yet. Trade comes with the BACI download (<Link href="/settings#sectors">Settings: Sectors</Link>);
          production from FAOSTAT, USGS and World Mining Data during <code>.\refresh.bat</code>
          {st.production_indicator && !st.production_indicator.startsWith("sp_") ? <>, or here from the <Link href={`/indicator/${st.production_indicator}`}>{st.production_indicator}</Link> indicator once its source is loaded</> : null}.</p></div>
      ) : m ? (
        <>
          <div className="card">
            <div className="card-head"><h3>{st.name}: {MEASURE_TEXT[measure].toLowerCase()}, {m.year}</h3><CardAsk onAsk={ask} /></div>
            <div className="map-box">
              <WorldMap fill values={m.rows.map((r) => ({ entity_id: r.entity_id, value: r.value, status: "E" }))} unit={unit} decimals={0}
                diverging={false} lines={lines} onPick={(iso3) => window.location.assign(`/entity/${iso3}`)} selected={[country]} />
            </div>
            <p className="caption">World {MEASURE_TEXT[measure].toLowerCase()}: {amount(m.total.find((t) => t[0] === m.year)?.[1], unit)} from {m.countries} countries.
              {measure === "exports" && routes && st.routes.length ? ` Lines: the ${st.routes.length} biggest routes, wider for more.` : ""}</p>
          </div>
          <div className="card">
            <h3>Leading countries</h3>
            <EChart option={ranking} height={330} label={`${st.name} ${measure} by country`} />
            {st.production ? <Concentration m={st.production} name="Production" high={d.high_hhi} /> : null}
            {st.exports ? <Concentration m={st.exports} name="Exports" high={d.high_hhi} /> : null}
          </div>
        </>
      ) : null}
      {m ? (
        <div className="grid two">
          <div className="card">
            <h3>How concentrated, over the years <Help note="sectors_concentration" /></h3>
            <EChart option={conc} height={260} label={`${st.name} concentration over time`} />
          </div>
          <div className="card">
            <h3>World {MEASURE_TEXT[measure].toLowerCase()} over the years</h3>
            <EChart option={totals} height={260} label={`World ${st.name} ${measure} over time`} />
            {st.unit_value.length ? <p className="caption">Average export value: {money(st.unit_value[st.unit_value.length - 1][1])} a tonne in {st.unit_value[st.unit_value.length - 1][0]}
              {st.unit_value.length > 5 ? ` (${money(st.unit_value[st.unit_value.length - 6][1])} in ${st.unit_value[st.unit_value.length - 6][0]})` : ""}.</p> : null}
          </div>
        </div>
      ) : null}
      {st.routes.length ? (
        <div className="grid two">
          <div className="card">
            <h3>Who sells to whom, {st.exports?.year}</h3>
            <EChart option={sankey} height={420} label={`${st.name} trade routes`} />
          </div>
          <div className="card">
            <h3>Biggest routes</h3>
            <div style={{ overflowX: "auto", maxHeight: 420 }}>
              <table className="small">
                <thead><tr><th>From</th><th>To</th><th className="num">Value</th></tr></thead>
                <tbody>{st.routes.map((r) => <tr key={`${r.from}-${r.to}`} className={r.from === country || r.to === country ? "selected" : ""}>
                  <td>{r.from_name}</td><td>{r.to_name}</td><td className="num">{money(r.value)}</td></tr>)}</tbody>
              </table>
            </div>
          </div>
        </div>
      ) : null}
      <div className="grid two">
        <div className="card">
          <h3>{c.name} in {st.name.toLowerCase()}</h3>
          <ul className="small rel-facts">
            {(["production", "exports", "imports"] as const).map((k) => c.rank[k]?.rank ? (
              <li key={k}>{MEASURE_TEXT[k]}: {amount(c.series[k]?.[c.series[k].length - 1]?.[1], unitOf(st, k))}, number {c.rank[k].rank} of {c.rank[k].of} countries</li>
            ) : null)}
            {!Object.values(c.rank).some((r) => r.rank) ? <li>No figures for {c.name} in this stage.</li> : null}
          </ul>
          {(c.series.exports?.length || c.series.imports?.length) ? <EChart option={mine} height={200} label={`${c.name} ${st.name} trade over time`} /> : null}
          {c.series.production?.length ? <EChart option={mineProd} height={180} label={`${c.name} ${st.name} production over time`} /> : null}
          {st.reliance.length ? (<>
            <h4>Relying on imports <Help note="sectors_reliance" /></h4>
            <div style={{ overflowX: "auto", maxHeight: 260 }}>
              <table className="small">
                <thead><tr><th>Country</th><th className="num">Used</th><th className="num">From imports</th></tr></thead>
                <tbody>{st.reliance.map((r) => <tr key={r.entity_id} className={r.entity_id === country ? "selected" : ""}>
                  <td>{r.name}</td><td className="num">{amount(r.use, "tonnes")}</td><td className="num">{r.reliance}%</td></tr>)}</tbody>
              </table>
            </div>
          </>) : null}
        </div>
        {st.how ? (
          <div className="card">
            <h3>How it is made <Help note="sectors_how" /></h3>
            <dl className="sector-how small">
              {st.how.inputs ? <><dt>Inputs</dt><dd>{st.how.inputs}</dd></> : null}
              {st.how.energy ? <><dt>Energy and emissions</dt><dd>{st.how.energy}</dd></> : null}
              {st.how.time ? <><dt>Time</dt><dd>{st.how.time}</dd></> : null}
              {st.how.waste ? <><dt>By-products and waste</dt><dd>{st.how.waste}</dd></> : null}
            </dl>
            <p className="caption">Rough, rounded figures, checked by hand. Sources: {d.sources}</p>
          </div>
        ) : null}
      </div>
    </>
  );
}

function Electric({ e }: { e: NonNullable<SectorDetail["electric"]> }) {
  const opt = useCallback(() => yearLines(Object.entries(e.sales_share).map(([k, pts]) => ({ name: e.names[k] ?? k, points: pts })), "%"), [e]);
  if (!Object.keys(e.sales_share).length) return null;
  return (
    <div className="grid two">
      <div className="card">
        <h3>The shift to electric: share of new cars sold <Help note="sectors_ev" /></h3>
        <EChart option={opt} height={280} label="Electric share of new car sales" />
        <p className="caption">Battery-electric and plug-in hybrid cars together. Source: IEA Global EV Data.</p>
      </div>
      <div className="card">
        <h3>Electric share of new cars, by country</h3>
        <div style={{ overflowX: "auto", maxHeight: 300 }}>
          <table className="small"><thead><tr><th>Country</th><th className="num">Share</th><th className="num">Year</th></tr></thead>
            <tbody>{e.ranking.map((r) => <tr key={r.entity_id}><td>{r.name}</td><td className="num">{r.value.toFixed(1)}%</td><td className="num">{r.year}</td></tr>)}</tbody></table>
        </div>
      </div>
    </div>
  );
}

function Battery({ b }: { b: NonNullable<SectorDetail["battery"]> }) {
  const mats = Object.keys(b.chemistries[0] ?? {}).filter((k) => k !== "chemistry");
  return (
    <div className="grid two">
      <div className="card">
        <h3>What goes into a battery pack <Help note="sectors_battery" /></h3>
        <table className="small">
          <thead><tr><th>Chemistry</th>{mats.map((m) => <th key={m} className="num">{m[0].toUpperCase() + m.slice(1)}</th>)}</tr></thead>
          <tbody>{b.chemistries.map((c) => <tr key={String(c.chemistry)}><td>{c.chemistry}</td>{mats.map((m) => <td key={m} className="num">{Number(c[m]) ? `${c[m]} kg` : "none"}</td>)}</tr>)}</tbody>
        </table>
        <p className="caption">Kilograms per kWh of capacity, rounded; a 60 kWh car pack holds about 60 times these. NMC is nickel-manganese-cobalt; LFP is lithium iron phosphate.</p>
        <h4>Export limits and rules</h4>
        <ul className="small rel-facts">{b.rules.map((r) => <li key={`${r.country}${r.year}`}><b>{r.year}, {r.name}:</b> {r.text}</li>)}</ul>
      </div>
      <div className="card">
        <h3>Where the materials come from</h3>
        <table className="small">
          <thead><tr><th>Material</th><th>Step</th><th>Leaders</th><th className="num">Top 3</th><th>Supply</th></tr></thead>
          <tbody>{b.materials.flatMap((m) => m.steps.map((s) => (
            <tr key={`${m.material}${s.stage}`}>
              <td><Link href={`/sectors/${m.sector}?stage=${s.stage}`}>{m.material[0].toUpperCase() + m.material.slice(1)}</Link></td>
              <td>{s.name} ({s.year})</td><td>{s.top.map((t) => `${t.name} ${Math.round(t.share ?? 0)}%`).join(", ")}</td>
              <td className="num">{s.top3}%</td><td className={s.high ? "neg" : ""}>{hhiText(s.hhi)}</td>
            </tr>)))}</tbody>
        </table>
        {!b.materials.some((m) => m.steps.length) ? <p className="muted small">No production figures yet; they come from USGS and World Mining Data during a refresh.</p> : null}
      </div>
    </div>
  );
}

function SectorPage() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const [country, setCountry] = useState(params.get("country") ?? "NZL");
  const [year, setYear] = useState<number | undefined>(params.get("year") ? +params.get("year")! : undefined);
  const [stage, setStage] = useState(params.get("stage") ?? "");
  const [d, setD] = useState<SectorDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.sector(id, { year, country }).then((r) => { if (live) { setD(r); setError(null); } }).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [id, year, country]);
  const st = d?.stages.find((s) => s.id === stage) ?? d?.stages[0];
  const years = useMemo(() => [...new Set((d?.stages ?? []).flatMap((s) => [...(s.exports?.years ?? []), ...(s.production?.years ?? [])]))].sort(), [d]);
  const prices = useCallback(() => pricesOption(d?.prices ?? []), [d]);
  const sync = (patch: Record<string, string | undefined>) => {
    const u = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) if (v) u.set(k, v); else u.delete(k);
    router.replace(`/sectors/${id}?${u}`, { scroll: false });
  };
  if (error) return <p className="error">{error}</p>;
  if (!d || !st) return <p className="muted">Loading…</p>;
  return (
    <div className="grid sector-page">
      <div className="title-row">
        <h1>{d.name}</h1> <Help note="sectors" />
        <span className="muted"><Link href="/sectors">Sectors</Link> · {d.group_name}</span>
      </div>
      {d.feeds ? <p className="ink-2" style={{ margin: 0 }}>Feeds: {d.feeds}</p> : null}
      <Chain d={d} stage={st.id} pick={(s) => { setStage(s); sync({ stage: s }); }} />
      <div className="chips-row small">
        <CountryChoice value={country} onChange={(c) => { setCountry(c); sync({ country: c }); }} label="Your country" />
        {years.length > 1 ? (
          <label>Year{" "}
            <input type="range" min={years[0]} max={years[years.length - 1]} value={year ?? years[years.length - 1]}
              onChange={(e) => { setYear(+e.target.value); sync({ year: e.target.value }); }} aria-label="Year" />
            {" "}<b>{year ?? years[years.length - 1]}</b>
            {year ? <button className="link small" onClick={() => { setYear(undefined); sync({ year: undefined }); }}>Latest</button> : null}
          </label>
        ) : null}
      </div>
      <StageView key={st.id} d={d} st={st} country={country} year={year} />
      {LAND_SECTORS.has(d.id) ? <LandCard sector={d.id} country={country} /> : null}
      {d.electric ? <Electric e={d.electric} /> : null}
      {d.battery ? <Battery b={d.battery} /> : null}
      {d.prices.length ? (
        <div className="card">
          <h3>Prices <Help note="sectors_prices" /></h3>
          <EChart option={prices} height={280} label={`${d.name} prices`} />
          <p className="caption">Monthly, nominal US dollars (not adjusted for inflation). Source: World Bank Pink Sheet. Scroll on the chart to zoom.</p>
        </div>
      ) : null}
      {d.companies.length ? (
        <div className="card">
          <h3>Key companies</h3>
          <table className="small">
            <thead><tr><th>Company</th><th>Based in</th><th>Step</th><th>Note</th></tr></thead>
            <tbody>{d.companies.map((c) => <tr key={c.name} className={c.nz ? "selected" : ""}>
              <td>{c.name}{c.nz ? " (NZ)" : ""}</td><td>{c.country_name}</td><td>{c.step_name}</td><td>{c.note}</td></tr>)}</tbody>
          </table>
          <p className="caption">Checked by hand once a year; a starting list, not a full one.</p>
        </div>
      ) : null}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><SectorPage /></Suspense>;
}
