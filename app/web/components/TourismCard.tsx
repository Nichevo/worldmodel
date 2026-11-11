"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import { LatestTable, latestText } from "@/components/PollutionCard";
import { api, type TourismCountry } from "@/lib/api";
import { openAsk } from "@/lib/ai";
import { compact } from "@/lib/format";

// A country's tourism: visitors and what they spend, where they come from, the WEF index,
// and its World Heritage sites.

const TAB_NAMES: Record<string, string> = { visitors: "Visitors", money: "Money", standing: "Standing", nz: "New Zealand in full" };

export default function TourismCard({ entity, name, showLink = true }: { entity: string; name: string; showLink?: boolean }) {
  const [d, setD] = useState<TourismCountry | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [allSites, setAllSites] = useState(false);
  useEffect(() => {
    let live = true;
    api.tourismCountry(entity).then((r) => live && setD(r)).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [entity]);
  if (error) return <div className="card"><h3>Tourism</h3><p className="error">{error}</p></div>;
  if (!d) return null;
  const tabs = Object.entries(d.tabs).filter(([, ids]) => ids.some((i) => d.latest[i]));
  if (!tabs.length && !d.sites.length && !d.origins.length && showLink) return null;
  const ask = () => openAsk({ title: `${name}: tourism`, entity, parts: [
    { key: "data", kind: "data", label: "Latest tourism figures", text: tabs.map(([t, ids]) => `${TAB_NAMES[t]}:\n${latestText(ids, d.latest, d.names)}`).join("\n\n") },
    { key: "origins", kind: "data", label: "Where visitors come from", text: d.origins.map((o) => `${o.name}: ${o.value} (${o.year})`).join("\n") },
    { key: "sites", kind: "data", label: "World Heritage sites", text: d.sites.map((s) => `${s.name} (${s.type}, ${s.year})${s.danger ? " in danger" : ""}`).join("\n") }] });
  const sites = allSites ? d.sites : d.sites.slice(0, 8);
  return (
    <div className="card" id="tourism-card">
      <div className="card-head"><h3>Tourism</h3>
        <span><CardAsk onAsk={ask} />{showLink ? <> <Link className="small" href={`/tourism?tab=country&country=${entity}`}>Tourism page</Link></> : null}</span></div>
      <div className="grid two">
        {tabs.map(([t, ids]) => <div key={t}><h4>{TAB_NAMES[t]}</h4><LatestTable ids={ids} latest={d.latest} names={d.names} /></div>)}
        {d.origins.length ? <div><h4>Where visitors come from ({d.origins[0].year})</h4><table className="small"><tbody>{d.origins.map((o) => (
          <tr key={o.id}><td><Link href={`/entity/${o.id}`}>{o.name}</Link></td><td className="num">{compact(o.value)}</td></tr>))}</tbody></table></div> : null}
        {d.sites.length ? <div><h4>World Heritage sites ({d.sites.length})</h4><ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{sites.map((s) => (
          <li key={s.name}>{s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.name}</a> : s.name} <span className="muted">({s.type}, {s.year})</span>
            {s.danger ? <b> in danger</b> : null}</li>))}</ul>
          {d.sites.length > 8 ? <button className="link small" onClick={() => setAllSites(!allSites)}>{allSites ? "Fewer" : `All ${d.sites.length}`}</button> : null}</div> : null}
      </div>
      <p className="caption">Visitor numbers fell by about three quarters in 2020 when borders closed for COVID-19. World Bank figures stop in 2020 for many countries;
        UN Tourism and New Zealand&apos;s own files (saved by hand, see Data status) go further.</p>
    </div>
  );
}
