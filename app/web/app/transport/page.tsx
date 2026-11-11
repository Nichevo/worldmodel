"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import AskButton from "@/components/AskButton";
import CountryChoice from "@/components/CountryChoice";
import EChart from "@/components/EChart";
import IndicatorSet from "@/components/IndicatorSet";
import NatureEvents from "@/components/NatureEvents";
import TransportCard, { AccidentList } from "@/components/TransportCard";
import WorldMap from "@/components/WorldMap";
import { api, type ChokepointSeries, type TransportPage } from "@/lib/api";
import { cssVar } from "@/lib/colors";
import { compact } from "@/lib/format";
import { logHistory } from "@/lib/history";

// Transport and trade routes: sea (ports, chokepoints, lanes), air, rail and rivers, the
// networks under it all (undersea cables, pipelines), accidents, and one country.

type Tab = "sea" | "air" | "land" | "networks" | "accidents" | "country";
const TABS: [Tab, string][] = [["sea", "Sea"], ["air", "Air"], ["land", "Rivers and rail"], ["networks", "Cables and pipelines"],
  ["accidents", "Accidents"], ["country", "One country"]];
const INTRO: Record<Exclude<Tab, "country">, string> = {
  sea: "About 80% of world trade by volume goes by sea, and much of it through a few straits and canals. When one is blocked (the Ever Given in Suez in 2021, Houthi attacks in the Red Sea from late 2023, drought at Panama in 2023) ships take weeks longer and freight costs jump everywhere.",
  air: "Air carries few goods by weight but about a third of world trade by value, and most long trips by people. Passengers and freight by country, and the busiest airports where their figures are stored.",
  land: "Rivers and canals still carry much of the freight of Europe, the United States and China. The map shows rivers by size, whole river basins (click one for the countries in it and roughly how many people live there) and the waterways ships use.",
  networks: "Almost all traffic between continents goes through about 600 undersea cables; gas and oil move through pipelines that cross many borders. Click a cable or pipeline on the map to outline every country it reaches.",
  accidents: "Air, sea and rail accidents (from Wikidata; New Zealand's TAIC inquiries where saved) and road deaths per person. Settings > Transport sets how many deaths an accident needs to be listed.",
};
const MAP_LAYERS: Record<string, string[]> = {
  sea: ["shipping_lanes", "chokepoints", "ports"], air: ["airports"], land: ["basins", "rivers", "waterways"],
  networks: ["cables", "cable_landings", "gas_pipelines", "oil_pipelines", "lng_terminals"], accidents: [],
};

function ChokepointChart({ id, name }: { id: string; name: string }) {
  const [d, setD] = useState<ChokepointSeries | null>(null);
  useEffect(() => { setD(null); api.chokepoint(id).then(setD).catch(() => setD(null)); }, [id]);
  if (!d) return <p className="small muted">Loading {name}…</p>;
  if (!d.points.length) return <p className="small muted">No daily figures stored for {name}.</p>;
  const series = (key: "transits" | "tankers" | "container" | "dry_bulk" | "cargo", label: string, color: string, width = 1.2) => ({
    type: "line" as const, name: label, showSymbol: false, data: d.points.map((p) => [p.week, p[key]]), lineStyle: { width, color }, itemStyle: { color } });
  return (
    <>
      <EChart height={300} label={`Ships through ${name}`} option={() => ({
        tooltip: { trigger: "axis" }, legend: { textStyle: { color: cssVar("--ink-2") } },
        grid: { left: 48, right: 16, top: 36, bottom: 64 },
        xAxis: { type: "time", axisLabel: { color: cssVar("--ink-2") } },
        yAxis: { type: "value", name: "ships a day", axisLabel: { color: cssVar("--ink-2") }, splitLine: { lineStyle: { color: cssVar("--border") } } },
        dataZoom: [{ type: "slider", bottom: 8, height: 18 }, { type: "inside", zoomOnMouseWheel: "shift" }],
        series: [series("transits", "All ships", cssVar("--series-1"), 2), series("container", "Container", cssVar("--series-2")),
          series("tankers", "Tankers", cssVar("--series-6")), series("dry_bulk", "Dry bulk", cssVar("--series-3")), series("cargo", "General cargo", cssVar("--series-5"))],
      })} />
      <p className="caption">Weekly averages of ships a day (IMF PortWatch, from satellite tracking). On its shores: {d.depends.map((c) => c.name).join(", ") || "not listed"}.
        A fall of 40% or more against the same months of the two years before is listed as an event.</p>
    </>
  );
}

function TransportView() {
  const router = useRouter();
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "sea");
  const [country, setCountry] = useState(params.get("country") ?? "NZL");
  const [p, setP] = useState<TransportPage | null>(null);
  const [choke, setChoke] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.transport().then((d) => { setP(d); setChoke((c) => c ?? d.chokepoints[0]?.id ?? null); }).catch((e) => setError(String(e.message || e)));
    logHistory({ kind: "page", title: "Transport", url: "/transport", detail: "page" });
  }, []);
  const go = (t: Tab) => { setTab(t); router.replace(`/transport?tab=${t}${t === "country" ? `&country=${country}` : ""}`, { scroll: false }); };
  if (error) return <p className="error">{error}</p>;
  if (!p) return <p className="muted">Loading…</p>;
  const loaded = (ids: string[]) => ids.filter((i) => p.loaded[i]).length;
  const notLoaded = <p>Nothing stored for this yet. It comes with <code>.\refresh.bat</code> (switches in <Link href="/settings#transport">Settings: Transport</Link>);
    files saved by hand are listed on <Link href="/data">Data status</Link>.</p>;
  const ids = tab === "networks" || tab === "country" ? [] : p.tabs[tab === "accidents" ? "safety" : tab] ?? [];
  const cp = p.chokepoints.find((c) => c.id === choke);
  return (
    <div className="grid sector-page">
      <div className="title-row"><h1>Transport and trade routes</h1>
        <AskButton title={`Transport: ${TABS.find((t) => t[0] === tab)?.[1]}`} parts={async () => [
          { key: "description", kind: "description", label: "What this tab shows", text: tab === "country" ? `Transport in ${country}` : INTRO[tab] },
          { key: "chokepoints", kind: "data", label: "Chokepoints, ships a day (last 30 days, change on a year before)",
            text: p.chokepoints.map((c) => `${c.name}: ${c.now ?? "?"} (${c.change != null ? `${c.change > 0 ? "+" : ""}${c.change}%` : "?"})`).join("\n") },
          { key: "events", kind: "events", label: "Cuts and blockages", text: p.infrastructure.map((e) => `${e.start_date?.slice(0, 7)} ${e.title}`).join("\n") },
        ]} /></div>
      <div className="seg" role="tablist">{TABS.map(([t, label]) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => go(t)}>{label}</button>)}</div>
      {tab === "country" ? (
        <>
          <div className="chips-row small"><CountryChoice value={country} onChange={(c) => { setCountry(c); router.replace(`/transport?tab=country&country=${c}`, { scroll: false }); }} /></div>
          <TransportCard entity={country} name={country} showLink={false} />
        </>
      ) : (
        <>
          <p className="ink-2" style={{ marginTop: 0, maxWidth: 860 }}>{INTRO[tab]}</p>
          {MAP_LAYERS[tab].length ? (
            <div className="card">
              <div className="map-box"><WorldMap fill values={[]} unit="" decimals={0} diverging={false} hideScale layers={MAP_LAYERS[tab]} onPick={() => {}} /></div>
              <p className="caption">{loaded(MAP_LAYERS[tab]) || tab === "land" || tab === "networks" ? "" : "These layers are not loaded yet: a refresh fetches them. "}
                Hover for names; zoom in for smaller rivers and ports. The same layers are on the main <Link href="/">Map</Link> under Layers &gt; Transport and trade,
                with planes and ships now.</p>
            </div>
          ) : null}
          {tab === "sea" ? (
            <div className="grid two">
              <div className="card"><h3>Chokepoints</h3>
                {p.chokepoints.length ? (
                  <table className="small"><thead><tr><th>Strait or canal</th><th className="num">Ships a day</th><th className="num">A year before</th><th className="num">Change</th></tr></thead>
                    <tbody>{p.chokepoints.map((c) => (
                      <tr key={c.id} className={c.id === choke ? "on" : ""} style={{ cursor: "pointer" }} onClick={() => setChoke(c.id)}>
                        <td><button className="link" onClick={() => setChoke(c.id)}>{c.name}</button></td><td className="num">{c.now ?? ""}</td>
                        <td className="num muted">{c.year_before ?? ""}</td>
                        <td className="num" style={{ color: c.change != null && c.change <= -20 ? cssVar("--div-neg-3") : undefined }}>
                          {c.change != null ? `${c.change > 0 ? "+" : ""}${c.change}%` : ""}</td></tr>))}</tbody></table>
                ) : notLoaded}
                {p.chokepoints[0] ? <p className="caption">Last 30 days to {p.chokepoints[0].as_of} against the same days a year before. Click one for its chart.</p> : null}
              </div>
              <div className="card"><h3>{cp ? `Ships through ${cp.name}` : "Ships through a chokepoint"}</h3>{cp ? <ChokepointChart id={cp.id} name={cp.name} /> : notLoaded}</div>
              <div className="card"><h3>Busiest ports</h3>
                {p.ports.length ? <table className="small"><thead><tr><th>Port</th><th className="num">Ship calls</th><th className="num">Tonnes in</th><th className="num">Tonnes out</th></tr></thead>
                  <tbody>{p.ports.map((r) => (
                    <tr key={r.port_id}><td>{r.name} {r.entity_id ? <Link className="muted" href={`/entity/${r.entity_id}`}>{r.entity_id}</Link> : null}</td>
                      <td className="num">{r.calls.toLocaleString()}</td><td className="num">{r.import_t ? compact(r.import_t) : ""}</td>
                      <td className="num">{r.export_t ? compact(r.export_t) : ""}</td></tr>))}</tbody></table> : notLoaded}
                {p.ports[0] ? <p className="caption">{p.ports[0].year}, estimated from ship tracking (IMF PortWatch).</p> : null}
              </div>
              <div className="card"><h3>Shipping cut or blocked</h3><NatureEvents events={p.infrastructure.filter((e) => ["canal", "shipping", "port", "chokepoint"].includes(e.subkind ?? ""))} />
                <p className="caption">Hand-checked events and falls PortWatch shows; they also show on charts and the Events page (kind: infrastructure).</p></div>
            </div>
          ) : null}
          {tab === "air" && p.airports.length ? (
            <div className="card"><h3>Busiest airports stored</h3><table className="small"><thead><tr><th>Airport</th><th className="num">Passengers</th><th className="num">Freight (t)</th><th className="num">Year</th></tr></thead>
              <tbody>{p.airports.map((a) => (
                <tr key={a.airport}><td>{a.name ?? a.airport} <span className="muted">{a.airport}</span></td><td className="num">{a.passengers ? compact(a.passengers) : ""}</td>
                  <td className="num">{a.freight_t ? compact(a.freight_t) : ""}</td><td className="num muted">{a.year}</td></tr>))}</tbody></table>
              <p className="caption">Eurostat for Europe; other countries from files saved by hand (Australia BITRE, UK CAA, US BTS, New Zealand airports).</p></div>
          ) : null}
          {tab === "networks" ? (
            <div className="card"><h3>Cables and pipelines cut</h3><NatureEvents events={p.infrastructure.filter((e) => ["cable", "power_cable", "pipeline", "oil", "gas"].includes(e.subkind ?? ""))} />
              <p className="caption">Loaded: {p.loaded.cables ?? 0} cables, {p.loaded.gas_pipelines ?? 0} gas and {p.loaded.oil_pipelines ?? 0} oil pipeline routes,
                {" "}{p.loaded.lng_terminals ?? 0} LNG terminals. Pipelines come from Global Energy Monitor&apos;s files saved by hand (see Data status).</p></div>
          ) : null}
          {tab === "accidents" ? (
            <div className="card"><h3>Air, sea and rail accidents ({p.min_deaths}+ deaths)</h3><AccidentList rows={p.accidents} limit={300} /></div>
          ) : null}
          {ids.length || tab !== "networks" ? <IndicatorSet ids={ids} empty={notLoaded} /> : null}
        </>
      )}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><TransportView /></Suspense>;
}
