"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import NatureEvents from "@/components/NatureEvents";
import { LatestTable, latestText } from "@/components/PollutionCard";
import { api, type Accident, type TransportCountry } from "@/lib/api";
import { openAsk } from "@/lib/ai";
import { compact } from "@/lib/format";

// A country's transport and links to the world: its ports, airports, air, sea and rail
// figures, the undersea cables and pipelines that reach it, the river basins it shares,
// and its accidents and cut cables or pipelines.

const TAB_NAMES: Record<string, string> = { sea: "Sea", air: "Air", land: "Rail and river", safety: "Safety" };

export function AccidentList({ rows, limit = 30 }: { rows: Accident[]; limit?: number }) {
  if (!rows.length) return <p className="small muted">None stored at or above the deaths set in Settings &gt; Transport.</p>;
  return (
    <div style={{ overflowX: "auto", maxHeight: 420 }}>
      <table className="small"><thead><tr><th>When</th><th>What</th><th>Kind</th><th className="num">Deaths</th></tr></thead>
        <tbody>{rows.slice(0, limit).map((a) => (
          <tr key={`${a.title}|${a.start_date}`}><td style={{ whiteSpace: "nowrap" }}>{a.start_date}</td>
            <td>{a.url ? <a href={a.url} target="_blank" rel="noreferrer">{a.title}</a> : a.title}{a.place ? <span className="muted"> ({a.place})</span> : null}</td>
            <td>{a.subkind ?? ""}</td><td className="num">{a.deaths != null ? Math.round(a.deaths).toLocaleString() : ""}</td></tr>))}</tbody></table>
    </div>
  );
}

export default function TransportCard({ entity, name, showLink = true }: { entity: string; name: string; showLink?: boolean }) {
  const [d, setD] = useState<TransportCountry | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.transportCountry(entity).then((r) => live && setD(r)).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [entity]);
  if (error) return <div className="card"><h3>Transport and links</h3><p className="error">{error}</p></div>;
  if (!d) return null;
  const tabs = Object.entries(d.tabs).filter(([, ids]) => ids.some((i) => d.latest[i]));
  const nets = d.networks ?? {};
  const empty = !tabs.length && !d.ports.length && !d.airports.length && !d.accidents.length && !Object.values(nets).some((v) => v.length);
  if (empty && showLink) return null;
  const cables = nets.cables ?? [], gas = nets.gas_pipelines ?? [], oil = nets.oil_pipelines ?? [], basins = nets.basins ?? [];
  const ask = () => openAsk({ title: `${name}: transport and links`, entity, parts: [
    { key: "data", kind: "data", label: "Latest transport figures", text: tabs.map(([t, ids]) => `${TAB_NAMES[t]}:\n${latestText(ids, d.latest, d.names)}`).join("\n\n") },
    { key: "ports", kind: "data", label: "Busiest ports", text: d.ports.map((p) => `${p.name}: ${p.calls} ship calls (${p.year})`).join("\n") },
    { key: "links", kind: "data", label: "Cables, pipelines and shared river basins",
      text: [`Undersea cables: ${cables.map((c) => c.name).join(", ")}`, `Gas pipelines: ${gas.map((c) => c.name).join(", ")}`,
        `River basins: ${basins.map((b) => `${b.name ?? b.id} (${Math.round((b.share ?? 0) * 100)}% of it here)`).join(", ")}`].join("\n") },
    { key: "events", kind: "events", label: "Accidents and cuts", text: [...d.accidents.map((a) => `${a.start_date} ${a.title} (${a.deaths} deaths)`),
      ...d.infrastructure.map((e) => `${e.start_date} ${e.title}`)].join("\n") }] });
  return (
    <div className="card" id="transport-card">
      <div className="card-head"><h3>Transport and links</h3>
        <span><CardAsk onAsk={ask} />{showLink ? <> <Link className="small" href={`/transport?tab=country&country=${entity}`}>Transport page</Link></> : null}</span></div>
      <div className="grid two">
        {tabs.map(([t, ids]) => <div key={t}><h4>{TAB_NAMES[t]}</h4><LatestTable ids={ids} latest={d.latest} names={d.names} /></div>)}
        {d.ports.length ? <div><h4>Busiest ports ({d.ports[0].year})</h4><table className="small"><tbody>{d.ports.map((p) => (
          <tr key={p.port_id}><td>{p.name}</td><td className="num">{p.calls.toLocaleString()} calls</td>
            <td className="num muted">{p.export_t ? `${compact(p.export_t)} t out` : ""}</td></tr>))}</tbody></table></div> : null}
        {d.airports.length ? <div><h4>Busiest airports</h4><table className="small"><tbody>{d.airports.map((a) => (
          <tr key={a.airport}><td>{a.name ?? a.airport}</td><td className="num">{a.passengers ? `${compact(a.passengers)} passengers` : ""}</td>
            <td className="num muted">{a.year}</td></tr>))}</tbody></table></div> : null}
        {cables.length || gas.length || oil.length ? <div><h4>Cables and pipelines that reach it</h4>
          <p className="small" style={{ margin: 0 }}>{cables.length ? <><b>{cables.length} undersea cables</b>: {cables.slice(0, 12).map((c) => c.name).join(", ")}{cables.length > 12 ? "…" : ""}. </> : null}
            {gas.length ? <><b>{gas.length} gas pipelines</b>: {gas.slice(0, 8).map((c) => c.name).join(", ")}{gas.length > 8 ? "…" : ""}. </> : null}
            {oil.length ? <><b>{oil.length} oil pipelines</b>: {oil.slice(0, 8).map((c) => c.name).join(", ")}{oil.length > 8 ? "…" : ""}.</> : null}</p>
          <p className="caption">Turn on Undersea cables or Pipelines on the <Link href="/">Map</Link> and click one to see every country that relies on it.</p></div> : null}
        {basins.length ? <div><h4>River basins</h4><table className="small"><thead><tr><th>Basin</th><th className="num">Of the country</th><th className="num">Of the basin here</th></tr></thead>
          <tbody>{basins.slice(0, 10).map((b) => (
            <tr key={b.id}><td>{b.name ?? "Unnamed basin"}{b.transboundary ? <span className="muted"> (shared with {(b.countries ?? 1) - 1} more)</span> : null}</td>
              <td className="num">{b.of_country != null ? `${Math.round(b.of_country * 100)}%` : ""}</td>
              <td className="num">{b.share != null ? `${Math.round(b.share * 100)}%` : ""}</td></tr>))}</tbody></table></div> : null}
      </div>
      {d.accidents.length ? <><h4>Air, sea and rail accidents</h4><AccidentList rows={d.accidents} limit={10} /></> : null}
      {d.infrastructure.length ? <><h4>Cables, pipelines and shipping cut or blocked</h4><NatureEvents events={d.infrastructure} limit={10} /></> : null}
    </div>
  );
}
