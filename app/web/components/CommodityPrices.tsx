"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import Help from "@/components/Help";
import { api, type PriceSeries, type PriceTrade, type PricesTable } from "@/lib/api";
import { openAsk } from "@/lib/ai";
import { seriesColor } from "@/lib/colors";
import { useChartEvents } from "@/lib/events";
import { change, priceName, priceUnit, priceValue, pricesChart, shownLines, type PriceMode } from "@/lib/prices";
import { money } from "@/lib/sectors";

// The Commodity prices tab: any prices on one chart (as prices, an index or after
// inflation, with the app's event bands), every price in a table, and who gains and who
// pays when the first one moves.

const DEFAULT = ["price_crude_oil", "price_copper", "price_wheat"];
const MODES: [PriceMode, string][] = [["price", "Prices"], ["index", "Index (first month = 100)"], ["real", "After inflation"]];
type SortKey = "name" | "m1" | "y1" | "y5" | "y10" | "real_vs_1980" | "pos10";

export default function CommodityPrices({ ids, setIds }: { ids: string[]; setIds: (ids: string[]) => void }) {
  const [table, setTable] = useState<PricesTable | null>(null);
  const [data, setData] = useState<PriceSeries | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<PriceMode>("price");
  const [from, setFrom] = useState(2000);
  const [to, setTo] = useState(9999);
  const [bands, setBands] = useState(true);
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "name", desc: false });
  const [q, setQ] = useState("");
  const [trade, setTrade] = useState<PriceTrade | null>(null);
  useEffect(() => { api.sectorPrices().then(setTable).catch((e) => setError(String(e.message || e))); }, []);
  const known = useMemo(() => new Set(table?.items.map((r) => r.id) ?? []), [table]);
  const picked = useMemo(() => {
    const got = ids.filter((i) => known.has(i));
    return got.length ? got : DEFAULT.filter((i) => known.has(i)).length ? DEFAULT.filter((i) => known.has(i)) : (table?.items.slice(0, 1).map((r) => r.id) ?? []);
  }, [ids, known, table]);
  const key = picked.join(",");
  useEffect(() => {
    if (!key) return;
    let live = true;
    api.sectorPriceSeries(key.split(",")).then((d) => live && setData(d)).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [key]);
  const first = picked[0];
  useEffect(() => {
    setTrade(null);
    if (!first) return;
    let live = true;
    api.sectorPriceTrade(first).then((t) => live && setTrade(t)).catch(() => live && setTrade(null));
    return () => { live = false; };
  }, [first]);
  const events = useChartEvents(bands ? ["world"] : []);
  const years = useMemo(() => {
    const ys = (data?.series ?? []).flatMap((s) => s.points.map(([d]) => +d.slice(0, 4)));
    return ys.length ? [Math.min(...ys), Math.max(...ys)] : [1960, new Date().getFullYear()];
  }, [data]);
  // prices in more than two units cannot share two axes: shown as an index instead
  const manyUnits = new Set(data?.series.map((x) => x.unit) ?? []).size > 2;
  const shownMode: PriceMode = mode !== "index" && manyUnits ? "index" : mode;
  const lines = useMemo(() => (data ? shownLines(data, shownMode, Math.max(from, years[0]), Math.min(to, years[1])) : []), [data, shownMode, from, to, years]);
  const inView = useMemo(() => events.filter((e) => +(e.end_date ?? e.start_date).slice(0, 4) >= Math.max(from, years[0])
    && +e.start_date.slice(0, 4) <= Math.min(to, years[1])), [events, from, to, years]);
  const option = useCallback(() => pricesChart(lines, inView), [lines, inView]);
  if (error) return <p className="error">{error}</p>;
  if (!table) return <p className="muted">Loading…</p>;
  if (!table.items.length) return <div className="card"><p>No commodity prices stored yet. They come from the World Bank Pink Sheet, the FAO food price index and the ANZ commodity price index during <code>.\refresh.bat</code>.</p></div>;
  const byId = new Map(table.items.map((r) => [r.id, r]));
  const toggle = (id: string) => setIds(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id].slice(-12));
  const headline = picked.map((i) => byId.get(i)).filter(Boolean).map((r) => {
    const c = r!.y1;
    return c === null ? priceName(r!.name) : `${priceName(r!.name)} ${c > 0 ? "up" : "down"} ${Math.abs(c).toFixed(0)}%`;
  }).join(", ") + " on a year";
  const ask = () => openAsk({ title: `Commodity prices: ${picked.map((i) => priceName(byId.get(i)?.name ?? i)).join(", ")}`, page: "/sectors?tab=prices",
    parts: [{ key: "data", kind: "data", label: "Monthly values shown", text: lines.map((l) =>
      `${priceName(l.name)} (${l.unit}): ` + l.points.filter((_, k) => k % 3 === 0 || k === l.points.length - 1).map(([d, v]) => `${d} ${priceValue(v)}`).join("; ")).join("\n") }] });
  const words = q.trim().toLowerCase();
  const rows = table.items.filter((r) => !words || `${r.name} ${r.group_name} ${r.sectors.map((s) => s.name).join(" ")}`.toLowerCase().includes(words));
  const sorted = sort.key === "name" ? rows : [...rows].sort((a, b) => {
    const av = (a[sort.key] as number | null | undefined) ?? -Infinity, bv = (b[sort.key] as number | null | undefined) ?? -Infinity;
    return sort.desc ? bv - av : av - bv;
  });
  const th = (k: SortKey, label: string, title?: string) => (
    <th className={k === "name" ? "" : "c"} title={title}>
      <button className="link" onClick={() => setSort((s) => ({ key: k, desc: s.key === k ? !s.desc : k !== "name" }))}>
        {label}{sort.key === k ? (sort.desc ? " ▼" : " ▲") : ""}</button></th>
  );
  const pct = (v: number | null | undefined) => { const c = change(v); return <td className={`c ${c.cls}`}>{c.text}</td>; };
  return (
    <>
      <div className="card">
        <div className="sx-chips" role="group" aria-label="Prices on the chart">
          <span className="muted small">Showing</span>
          {picked.map((i, k) => (
            <button key={i} className="sx-chip on" style={{ ["--chip" as string]: seriesColor(k) }} onClick={() => toggle(i)}
              title="Take off the chart">{priceName(byId.get(i)?.name ?? i)} ×</button>
          ))}
          <select value="" onChange={(e) => e.target.value && toggle(e.target.value)} aria-label="Add a price">
            <option value="">+ add a price</option>
            {table.groups.map((g) => (
              <optgroup key={g.id} label={g.name}>
                {table.items.filter((r) => r.group === g.id && !picked.includes(r.id)).map((r) => <option key={r.id} value={r.id}>{priceName(r.name)}</option>)}
              </optgroup>
            ))}
          </select>
        </div>
        <div className="chips-row small" style={{ justifyContent: "space-between", marginTop: 10 }}>
          <div className="seg small" role="group" aria-label="Show as">
            {MODES.map(([m, label]) => <button key={m} className={shownMode === m ? "on" : ""} aria-pressed={shownMode === m} onClick={() => setMode(m)}
              disabled={manyUnits && m !== "index"} title={manyUnits && m !== "index" ? "More than two units on the chart: take a price off to show prices" : undefined}>{label}</button>)}
          </div>
          <span className="chips-row small">
            <label>From <select value={Math.max(from, years[0])} onChange={(e) => setFrom(+e.target.value)}>
              {Array.from({ length: years[1] - years[0] + 1 }, (_, k) => years[0] + k).map((y) => <option key={y} value={y}>{y}</option>)}</select></label>
            <label>to <select value={Math.min(to, years[1])} onChange={(e) => setTo(+e.target.value)}>
              {Array.from({ length: years[1] - years[0] + 1 }, (_, k) => years[0] + k).map((y) => <option key={y} value={y}>{y}</option>)}</select></label>
            <button className="link small" onClick={() => { setFrom(0); setTo(9999); }}>Whole range</button>
            <label title="The app's world events (Settings > Events) as bands"><input type="checkbox" checked={bands} onChange={(e) => setBands(e.target.checked)} /> Event bands</label>
          </span>
        </div>
        <div className="card-head" style={{ marginTop: 10 }}>
          <h3 className="finding" style={{ margin: 0 }}>{headline}</h3>
          <CardAsk onAsk={ask} />
        </div>
        <EChart option={option} height={420} label="Commodity prices over time" />
        <p className="caption">
          {shownMode === "real" ? `After inflation: in ${data?.deflator.at(-1)?.[0] ?? "this year's"} US dollars, using US consumer prices (IMF and World Bank). ` : ""}
          {manyUnits ? "These prices come in more than two units, so they are shown as an index (first month shown = 100). " : ""}
          Drag the slider under the chart to zoom. Monthly, nominal US$ unless said; World Bank Pink Sheet, FAO and ANZ.
        </p>
      </div>

      {trade && (trade.sellers.length || trade.buyers.length) ? (
        <div className="card">
          <div className="card-head"><h3>Who gains and who pays when {priceName(byId.get(first)?.name ?? first).toLowerCase()} moves <span className="muted small">· {trade.stage_name}, {trade.sellers_year ?? trade.buyers_year}</span></h3>
            <Link className="small" href={`/sectors/${trade.sector}`}>Open the sector</Link></div>
          <div className="grid two">
            {(["sellers", "buyers"] as const).map((side) => (
              <div key={side}>
                <h4 style={{ margin: "0 0 4px" }}>{side === "sellers" ? "Biggest sellers" : "Biggest buyers"}</h4>
                {!trade[side].length ? <p className="muted small">No {side === "sellers" ? "export" : "import"} figures for this stage.</p> : <table className="small sx-table">
                  <thead><tr><th>Country</th><th className="c">{side === "sellers" ? "Exports" : "Imports"}</th><th className="c">World share</th>
                    <th className="c" title={side === "sellers" ? "Of the country's own goods exports" : "Of the country's own goods imports"}>Of its own {side === "sellers" ? "exports" : "imports"}</th></tr></thead>
                  <tbody>{trade[side].map((r) => (
                    <tr key={r.entity_id}><td><Link href={`/entity/${r.entity_id}`}>{r.name}</Link></td><td className="c">{money(r.value)}</td>
                      <td className="c">{r.share?.toFixed(1)}%</td><td className="c">{r.of_own === null ? "–" : `${r.of_own.toFixed(1)}%`}</td></tr>))}</tbody>
                </table>}
              </div>
            ))}
          </div>
          <p className="caption">CEPII BACI goods trade. A price rise helps the sellers with a big share of their own exports most, and hurts buyers in the same way.</p>
        </div>
      ) : null}

      <div className="card">
        <div className="card-head">
          <h3>Every price, latest month <Help note="sectors_prices" /></h3>
          <input type="search" placeholder="Find a price or sector" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find a price" />
        </div>
        <div style={{ overflowX: "auto", maxHeight: 640 }}>
          <table className="small sx-table">
            <thead><tr>
              {th("name", "Price")}<th>Sectors</th><th className="c">Latest</th>
              {th("m1", "1 month")}{th("y1", "1 year")}{th("y5", "5 years")}{th("y10", "10 years")}
              {th("real_vs_1980", "After inflation vs 1980", "Today's price against its 1980 average, both in today's dollars (US consumer prices)")}
              {th("pos10", "10-year range", "Where today sits between its ten-year low and high")}
            </tr></thead>
            <tbody>
              {(sort.key === "name" ? table.groups : [{ id: "", name: "" }]).map((g) => (
                <FragmentRows key={g.id || "all"} title={g.name}>
                  {sorted.filter((r) => !g.id || r.group === g.id).map((r) => (
                    <tr key={r.id} className={picked.includes(r.id) ? "on" : ""}>
                      <td><label><input type="checkbox" checked={picked.includes(r.id)} onChange={() => toggle(r.id)} /> {priceName(r.name)}</label></td>
                      <td>{r.sectors.map((s, k) => <span key={s.id}>{k ? ", " : ""}<Link href={`/sectors/${s.id}`}>{s.name}</Link></span>)}</td>
                      <td className="c" title={`${r.unit}, ${r.date}`}>{priceValue(r.value)} <span className="muted">{priceUnit(r.unit)}</span></td>
                      {pct(r.m1)}{pct(r.y1)}{pct(r.y5)}{pct(r.y10)}
                      <td className="c">{r.real_vs_1980 ? `×${r.real_vs_1980.toFixed(r.real_vs_1980 < 10 ? 1 : 0)}` : "–"}</td>
                      <td style={{ minWidth: 110 }}><span className="sx-range" title={`${priceValue(r.low10)} to ${priceValue(r.high10)}`}><span style={{ left: `${r.pos10}%` }} /></span></td>
                    </tr>))}
                </FragmentRows>
              ))}
            </tbody>
          </table>
        </div>
        <p className="caption">Tick a row to add it to the chart. ×2 under After inflation means twice as dear as in 1980 in real terms.</p>
      </div>
    </>
  );
}

function FragmentRows({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <>
      {title ? <tr><td colSpan={9} style={{ fontWeight: 700, paddingTop: 10 }}>{title}</td></tr> : null}
      {children}
    </>
  );
}
