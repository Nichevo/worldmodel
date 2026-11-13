"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import AskButton from "@/components/AskButton";
import CountryChoice from "@/components/CountryChoice";
import IndicatorSet from "@/components/IndicatorSet";
import TourismCard from "@/components/TourismCard";
import WorldMap from "@/components/WorldMap";
import { RecoveryCard, useKeys } from "@/components/PageLook";
import { api, type TourismPage } from "@/lib/api";
import { compact } from "@/lib/format";
import { logHistory } from "@/lib/history";

// Tourism: visitors and where they go, what they spend, how countries rank, World Heritage
// sites, New Zealand in full, and one country.

type Tab = "visitors" | "money" | "standing" | "nz" | "country";
const TABS: [Tab, string][] = [["visitors", "Visitors"], ["money", "Money"], ["standing", "Sites and standing"], ["nz", "New Zealand"], ["country", "One country"]];
const INTRO: Record<Exclude<Tab, "country">, string> = {
  visitors: "Overnight visitors from abroad and trips abroad by each country's people. COVID-19 border closures in 2020 cut arrivals by about three quarters; most countries were back near 2019 by 2024.",
  money: "What visitors spend, and tourism's share of what a country earns from abroad. Small islands (Fiji, the Maldives, the Caribbean) depend on it most.",
  standing: "The World Economic Forum's Travel and Tourism Development Index, World Heritage sites (the map; red rings are in danger) and the places with a million or more visitors a year.",
  nz: "New Zealand in full: arrivals by country and purpose (Stats NZ), visitor spending (MBIE International Visitor Survey), and tourism's share of GDP and jobs (Tourism Satellite Account), from files saved by hand.",
};

function TourismView() {
  const router = useRouter();
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "visitors");
  const [country, setCountry] = useState(params.get("country") ?? "NZL");
  const [p, setP] = useState<TourismPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const keys = useKeys();
  useEffect(() => {
    api.tourism().then(setP).catch((e) => setError(String(e.message || e)));
    logHistory({ kind: "page", title: "Tourism", url: "/tourism", detail: "page" });
  }, []);
  const go = (t: Tab) => { setTab(t); router.replace(`/tourism?tab=${t}${t === "country" ? `&country=${country}` : ""}`, { scroll: false }); };
  if (error) return <p className="error">{error}</p>;
  if (!p) return <p className="muted">Loading…</p>;
  const notLoaded = <p>Nothing stored for this yet. The World Bank&apos;s figures come with <code>.\refresh.bat</code>; UN Tourism, the WEF index and New Zealand&apos;s
    files are saved by hand (see <Link href="/data">Data status</Link>).</p>;
  return (
    <div className="grid sector-page">
      <div className="title-row"><h1>Tourism</h1>
        <AskButton title={`Tourism: ${TABS.find((t) => t[0] === tab)?.[1]}`} parts={async () => [
          { key: "description", kind: "description", label: "What this tab shows", text: tab === "country" ? `Tourism in ${country}` : INTRO[tab] },
          { key: "data", kind: "data", label: "Most visited countries", text: p.top.map((t) => `${t.name}: ${t.value} (${t.year})`).join("\n") },
        ]} /></div>
      <div className="seg" role="tablist">{TABS.map(([t, label]) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => go(t)}>{label}</button>)}</div>
      {tab === "country" ? (
        <>
          <div className="chips-row small"><CountryChoice value={country} onChange={(c) => { setCountry(c); router.replace(`/tourism?tab=country&country=${c}`, { scroll: false }); }} /></div>
          <TourismCard entity={country} name={country} showLink={false} />
        </>
      ) : (
        <>
          <p className="ink-2" style={{ marginTop: 0, maxWidth: 860 }}>{INTRO[tab]}</p>
          {tab === "visitors" && (p.tabs.visitors.includes("tourist_arrivals") || p.tabs.visitors.includes("unt_arrivals")) ? (
            <RecoveryCard indicator={p.tabs.visitors.includes("unt_arrivals") ? "unt_arrivals" : "tourist_arrivals"} keys={keys} label="Visitors from abroad a year" />
          ) : null}
          {tab === "money" && (p.tabs.money.includes("tourism_receipts_usd") || p.tabs.money.includes("unt_receipts_usd")) ? (
            <RecoveryCard indicator={p.tabs.money.includes("unt_receipts_usd") ? "unt_receipts_usd" : "tourism_receipts_usd"} keys={keys} label="What visitors spend, US$" />
          ) : null}
          {tab === "visitors" && p.top.length ? (
            <div className="card"><h3>Most visitors</h3><table className="small"><tbody>{p.top.map((t, i) => (
              <tr key={t.entity_id}><td className="num muted">{i + 1}</td><td><Link href={`/entity/${t.entity_id}`}>{t.name}</Link></td>
                <td className="num">{compact(t.value)}</td><td className="num muted">{t.year}</td></tr>))}</tbody></table>
              <p className="caption">Latest year each country gives ({p.names[p.top[0].indicator]?.name ?? p.top[0].indicator}).</p></div>
          ) : null}
          {tab === "standing" ? (
            <div className="card">
              <div className="map-box"><WorldMap fill values={[]} unit="" decimals={0} diverging={false} hideScale layers={["heritage_sites", "visited_sites"]} onPick={() => {}} /></div>
              <p className="caption">{(p.loaded.heritage_sites ?? 0).toLocaleString()} World Heritage sites (UNESCO) and {(p.loaded.visited_sites ?? 0).toLocaleString()} places
                with a million or more visitors a year (Wikidata). Hover for names.</p>
            </div>
          ) : null}
          <IndicatorSet ids={p.tabs[tab]} empty={notLoaded} />
        </>
      )}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><TourismView /></Suspense>;
}
