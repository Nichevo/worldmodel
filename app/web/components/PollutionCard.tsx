"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import NatureEvents from "@/components/NatureEvents";
import { api, type IndicatorNames, type Latest, type PollutionCountry } from "@/lib/api";
import { openAsk } from "@/lib/ai";
import { formatValue } from "@/lib/format";

// A country's pollution: the latest figure for each measure on the Pollution page, by tab,
// and its pollution disasters and smoke across borders.

const TAB_NAMES: Record<string, string> = { air: "Air", water: "Water", ocean: "Ocean", borders: "Across borders" };

export function LatestTable({ ids, latest, names }: { ids: string[]; latest: Latest; names: IndicatorNames }) {
  const shown = ids.filter((i) => latest[i]);
  if (!shown.length) return <p className="small muted">No figures stored.</p>;
  return (
    <table className="small"><tbody>{shown.map((i) => (
      <tr key={i}><td><Link href={`/indicator/${i}`}>{names[i]?.name ?? i}</Link></td>
        <td className="num">{formatValue(latest[i].value, names[i]?.unit ?? "", names[i]?.decimals ?? 1)}</td>
        <td className="num muted">{latest[i].year}</td></tr>))}</tbody></table>
  );
}

export function latestText(ids: string[], latest: Latest, names: IndicatorNames): string {
  return ids.filter((i) => latest[i]).map((i) => `${names[i]?.name ?? i}: ${formatValue(latest[i].value, names[i]?.unit ?? "", names[i]?.decimals ?? 1)} (${latest[i].year})`).join("\n");
}

export default function PollutionCard({ entity, name, showLink = true }: { entity: string; name: string; showLink?: boolean }) {
  const [d, setD] = useState<PollutionCountry | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.pollutionCountry(entity).then((r) => live && setD(r)).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [entity]);
  if (error) return <div className="card"><h3>Pollution</h3><p className="error">{error}</p></div>;
  if (!d) return null;
  const tabs = Object.entries(d.tabs).filter(([, ids]) => ids.some((i) => d.latest[i]));
  if (!tabs.length && !d.events.length && showLink) return null;
  const ask = () => openAsk({ title: `${name}: pollution`, entity, parts: [{ key: "data", kind: "data", label: "Latest pollution figures",
    text: tabs.map(([t, ids]) => `${TAB_NAMES[t]}:\n${latestText(ids, d.latest, d.names)}`).join("\n\n") },
    { key: "events", kind: "data", label: "Pollution events", text: d.events.map((e) => `${e.start_date?.slice(0, 7)} ${e.title}`).join("\n") }] });
  return (
    <div className="card" id="pollution-card">
      <div className="card-head"><h3>Pollution</h3><span><CardAsk onAsk={ask} />{showLink ? <> <Link className="small" href={`/pollution?tab=country&country=${entity}`}>Pollution page</Link></> : null}</span></div>
      <div className="grid two">
        {tabs.map(([t, ids]) => <div key={t}><h4>{TAB_NAMES[t]}</h4><LatestTable ids={ids} latest={d.latest} names={d.names} /></div>)}
      </div>
      {d.events.length ? <><h4>Pollution disasters and smoke</h4><NatureEvents events={d.events} limit={12} /></> : null}
    </div>
  );
}
