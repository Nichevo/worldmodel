"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import { openAsk } from "@/lib/ai";
import { api } from "@/lib/api";
import { compact } from "@/lib/format";
import { osintApi, type Arms, type Military } from "@/lib/osint";

// A country's military strength (Global Firepower's counts with their rank among all countries, a
// second source beside where the app has one), nuclear warheads, and who it buys major weapons
// from and sells them to (SIPRI). Hidden when none is loaded.
export const KEY_MEASURES = ["gfp_personnel_active", "gfp_personnel_reserve", "gfp_aircraft_total", "gfp_aircraft_fighters",
  "gfp_helicopters", "gfp_tanks", "gfp_vehicles", "gfp_navy_total", "gfp_submarines", "gfp_frigates", "gfp_budget_usd", "gfp_power_index"];

export function fmtMeasure(v: number, unit: string): string {
  if (unit === "US$") return `US$${compact(v)}`;
  if (unit === "score") return v.toFixed(4);
  return Math.round(v).toLocaleString();
}

export default function MilitaryCard({ entity, name }: { entity: string; name: string }) {
  const [m, setM] = useState<Military | null>(null);
  const [arms, setArms] = useState<Arms | null>(null);
  const [warheads, setWarheads] = useState<[number, number] | null>(null);
  useEffect(() => {
    let live = true;
    osintApi.military([entity]).then((x) => live && setM(x)).catch(() => live && setM(null));
    osintApi.arms(entity).then((x) => live && setArms(x)).catch(() => live && setArms(null));
    api.series("nuclear_warheads", [entity]).then((rows) => {
      const last = rows.filter((r) => r.value > 0).sort((a, b) => a.period.localeCompare(b.period)).pop();
      if (live) setWarheads(last ? [+last.period.slice(0, 4), last.value] : null);
    }).catch(() => live && setWarheads(null));
    return () => { live = false; };
  }, [entity]);
  const c = m?.countries[0];
  const vals = c ? KEY_MEASURES.map((id) => [m!.measures.find((x) => x.id === id), c.values[id]] as const).filter(([x, v]) => x && v) : [];
  const hasArms = !!arms && (arms.suppliers.length > 0 || arms.buyers.length > 0);
  if (!vals.length && !hasArms && !warheads) return null;
  const text = () => [
    ...vals.map(([x, v]) => `${x!.name}: ${fmtMeasure(v!.value, x!.unit)} (rank ${v!.rank} of ${v!.of}, Global Firepower ${v!.edition})`),
    warheads ? `Nuclear warheads: ${warheads[1]} (${warheads[0]}, Federation of American Scientists via Our World in Data)` : "",
    ...(arms?.suppliers ?? []).map((s) => `Buys from ${s.partner}: ${s.deals} deals, ${Math.round(s.tiv)} TIV since ${arms!.since}`),
    ...(arms?.buyers ?? []).map((s) => `Sells to ${s.partner}: ${s.deals} deals, ${Math.round(s.tiv)} TIV since ${arms!.since}`),
  ].filter(Boolean).join("\n");
  return (
    <div className="card" id="military">
      <div className="card-head">
        <h3>Military strength and arms</h3>
        <CardAsk onAsk={() => openAsk({ title: `Military strength: ${name}`, entity, parts: [{ key: "data", kind: "data", label: "Military counts and arms deals", text: text() }] })} />
        <Link href={`/military?c=${entity}`} className="small">Compare countries →</Link>
      </div>
      {vals.length > 0 && (
        <table className="small">
          <thead><tr><th>Measure</th><th style={{ textAlign: "right" }}>Count</th><th style={{ textAlign: "right" }}>Rank</th><th>Second source</th></tr></thead>
          <tbody>
            {vals.map(([x, v]) => (
              <tr key={x!.id}>
                <td>{x!.name}{x!.id === "gfp_power_index" ? <span className="muted"> (method unpublished)</span> : null}</td>
                <td style={{ textAlign: "right" }}><b>{fmtMeasure(v!.value, x!.unit)}</b>
                  {v!.before != null && v!.before !== v!.value ? <span className="muted"> ({v!.value > v!.before ? "+" : ""}{fmtMeasure(v!.value - v!.before, x!.unit)})</span> : null}</td>
                <td style={{ textAlign: "right" }} className="muted">{v!.rank ? `#${v!.rank} of ${v!.of}` : ""}</td>
                <td className="muted">{v!.also ? `${fmtMeasure(v!.also.value, x!.unit)} (${x!.id === "gfp_budget_usd" ? "SIPRI" : "World Bank"}, ${v!.also.year})` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {warheads && <p className="small">Nuclear warheads: <b>{warheads[1].toLocaleString()}</b> <span className="muted">({warheads[0]}, Federation of American Scientists)</span></p>}
      {hasArms && (
        <div className="small" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
          <div><b>Buys major weapons from</b> <span className="muted">(since {arms!.since}, SIPRI trend-indicator value)</span>
            <ol>{arms!.suppliers.slice(0, 6).map((s) => <li key={s.partner}><Link href={`/entity/${s.partner}`}>{s.partner}</Link> {compact(s.tiv)} · {s.deals} deal{s.deals === 1 ? "" : "s"}</li>)}</ol>
            {!arms!.suppliers.length && <p className="muted">None recorded.</p>}</div>
          <div><b>Sells to</b>
            <ol>{arms!.buyers.slice(0, 6).map((s) => <li key={s.partner}><Link href={`/entity/${s.partner}`}>{s.partner}</Link> {compact(s.tiv)} · {s.deals} deal{s.deals === 1 ? "" : "s"}</li>)}</ol>
            {!arms!.buyers.length && <p className="muted">None recorded.</p>}</div>
        </div>
      )}
      {hasArms && arms!.deals[0] && (
        <p className="small muted">Latest deal: {arms!.deals[0].supplier} to {arms!.deals[0].recipient}, {arms!.deals[0].number ?? ""} {arms!.deals[0].weapon}
          {arms!.deals[0].description ? ` (${arms!.deals[0].description})` : ""}, ordered {arms!.deals[0].ordered ?? "?"}{arms!.deals[0].status ? `, ${arms!.deals[0].status}` : ""}.</p>
      )}
      <p className="caption">Counts from Global Firepower {m?.edition ?? ""} (read from its pages; its figures are its own compilation, not official). Arms transfers from SIPRI&apos;s
        trade register (a file you save; trend-indicator values measure military capability, not price).</p>
    </div>
  );
}
