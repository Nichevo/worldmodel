"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import AskButton from "@/components/AskButton";
import CountryChoice from "@/components/CountryChoice";
import IndicatorSet from "@/components/IndicatorSet";
import NatureEvents from "@/components/NatureEvents";
import PollutionCard from "@/components/PollutionCard";
import WorldMap from "@/components/WorldMap";
import { RankedCard, useKeys } from "@/components/PageLook";
import { api, type NatureEvent, type PollutionPage } from "@/lib/api";
import { logHistory } from "@/lib/history";

// Pollution: the air, water and the ocean, and pollution that crosses borders (smoke,
// dust, spills down shared rivers, emissions carried in trade), with one country's figures.

type Tab = "air" | "water" | "ocean" | "borders" | "country";
const TABS: [Tab, string][] = [["air", "Air"], ["water", "Water"], ["ocean", "Ocean"], ["borders", "Across borders"], ["country", "One country"]];
const INTRO: Record<Exclude<Tab, "country">, string> = {
  air: "Fine particles (PM2.5) from burning fuel, crops and forests, dust and industry are the deadliest pollution. The map below shows smoke and dust as satellites see it on a given day.",
  water: "Safe drinking water, how much household wastewater is treated before it reaches rivers and the sea, how much of the water tested is in good health, and how hard countries draw on their fresh water.",
  ocean: "Plastic reaching the sea from rivers and coasts (2019 estimates, Meijer et al.), and how much of the sea's key nature areas are protected.",
  borders: "Pollution does not stop at borders: haze from Indonesian fires over Singapore and Malaysia, Australian bushfire smoke over New Zealand, Saharan dust over the Caribbean, chemicals carried down the Rhine and the Danube, and emissions made in one country for goods used in another.",
};
// Figures shown first as where each country sits among all countries, with New Zealand's line.
const RANKED: Partial<Record<Tab, string[]>> = { air: ["pm25_exposure", "air_pollution_death_rate"], water: ["safe_drinking_water", "wastewater_treated_share"],
  ocean: ["ocean_plastic_per_capita", "protected_sea_share"] };
const SUBKINDS: Partial<Record<Tab, string[]>> = { air: ["air", "smoke", "dust"], water: ["chemical"], ocean: ["oil"] };
const GIBS_AOD = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Combined_Value_Added_AOD/default/{day}/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png";

function SmokeMap() {
  const ago = (d: number) => new Date(Date.now() - d * 86_400_000).toISOString().slice(0, 10);
  const [day, setDay] = useState(ago(2));
  const raster = useMemo(() => ({ tiles: GIBS_AOD.replace("{day}", day), attribution: "Smoke and dust: NASA GIBS, MODIS aerosol optical depth", maxzoom: 6, over: true, opacity: 0.75 }), [day]);
  return (
    <div className="card">
      <div className="card-head"><h3>Smoke, dust and haze from space</h3>
        <label className="small">Day <input type="date" value={day} max={ago(1)} min="2002-07-04" onChange={(e) => e.target.value && setDay(e.target.value)} /></label></div>
      <div className="map-box"><WorldMap fill values={[]} unit="" decimals={0} diverging={false} hideScale raster={raster} onPick={() => {}} /></div>
      <p className="caption">How much sunlight smoke, dust and haze block (aerosol optical depth, NASA MODIS): yellow is light, red and brown thick. Gaps are cloud or
        the satellites&apos; gaps between passes. Try 2020-01-01 for Australian smoke reaching New Zealand, 2019-09-15 for Indonesian haze, or 2020-06-25 for Saharan dust
        over the Atlantic. Needs the internet.</p>
    </div>
  );
}

function PollutionView() {
  const router = useRouter();
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "air");
  const [country, setCountry] = useState(params.get("country") ?? "NZL");
  const [p, setP] = useState<PollutionPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const keys = useKeys();
  useEffect(() => {
    api.pollution().then(setP).catch((e) => setError(String(e.message || e)));
    logHistory({ kind: "page", title: "Pollution", url: "/pollution", detail: "page" });
  }, []);
  const go = (t: Tab) => { setTab(t); router.replace(`/pollution?tab=${t}${t === "country" ? `&country=${country}` : ""}`, { scroll: false }); };
  if (error) return <p className="error">{error}</p>;
  if (!p) return <p className="muted">Loading…</p>;
  const events: NatureEvent[] = tab === "borders" ? p.events.filter((e) => e.entities.length > 1)
    : p.events.filter((e) => (SUBKINDS[tab] ?? []).includes(e.subkind ?? ""));
  return (
    <div className="grid sector-page">
      <div className="title-row"><h1>Pollution</h1>
        <AskButton title={`Pollution: ${TABS.find((t) => t[0] === tab)?.[1]}`} parts={async () => [
          { key: "description", kind: "description", label: "What this tab shows", text: tab === "country" ? `Pollution in ${country}` : INTRO[tab] },
          { key: "events", kind: "data", label: "Events listed", text: events.map((e) => `${e.start_date?.slice(0, 7)} ${e.title} (${e.entities.join(", ")})`).join("\n") },
        ]} /></div>
      <div className="seg" role="tablist">{TABS.map(([t, label]) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => go(t)}>{label}</button>)}</div>
      {tab === "country" ? (
        <>
          <div className="chips-row small"><CountryChoice value={country} onChange={(c) => { setCountry(c); router.replace(`/pollution?tab=country&country=${c}`, { scroll: false }); }} /></div>
          <PollutionCard entity={country} name={country} showLink={false} />
        </>
      ) : (
        <>
          <p className="ink-2" style={{ marginTop: 0, maxWidth: 860 }}>{INTRO[tab]}</p>
          {RANKED[tab]?.length ? <div className="grid two">{RANKED[tab]!.filter((i) => p.tabs[tab].includes(i)).map((i) => <RankedCard key={i} indicator={i} keys={keys} />)}</div> : null}
          {tab === "air" || tab === "borders" ? <SmokeMap /> : null}
          <IndicatorSet ids={p.tabs[tab]} empty={<p>Nothing stored for this tab yet. Its figures come with <code>.\refresh.bat</code> (World Bank, Our World in Data and the UN SDG database;
            switch in <Link href="/settings#nature">Settings: Nature and pollution</Link>).</p>} />
          <div className="card"><h3>{tab === "borders" ? "Pollution that crossed borders" : "Pollution disasters"}</h3><NatureEvents events={events} />
            <p className="caption">Hand-checked list with a link for each; they also show as events on charts and the Events page (kind: pollution).</p></div>
        </>
      )}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><PollutionView /></Suspense>;
}
