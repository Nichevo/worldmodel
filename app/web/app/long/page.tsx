"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { AgeOfEmpires, WhoRuled } from "@/components/long/Empires";
import LongCharts, { useLongOverview } from "@/components/long/LongCharts";
import { Cycle, Factors, ThenAndNow } from "@/components/long/Order";
import type { LongOverview } from "@/lib/api";
import { yl } from "@/lib/long";

// The Long history page: figures over centuries, empires' size and borders, who ruled
// where, then and now, the eight factors and the big cycle. Explore > Long history.
const TABS = [
  { id: "charts", label: "Long charts" },
  { id: "empires", label: "Age of empires" },
  { id: "ruled", label: "Who ruled where" },
  { id: "thennow", label: "Then and now" },
  { id: "factors", label: "Eight factors" },
  { id: "cycle", label: "The cycle" },
  { id: "voyages", label: "Voyages" },
] as const;
type Tab = (typeof TABS)[number]["id"];

function LongPage() {
  const router = useRouter();
  const params = useSearchParams();
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id ?? "charts") as Tab;
  const { o, error } = useLongOverview();
  const go = (t: Tab) => router.replace(t === "charts" ? "/long" : `/long?tab=${t}`, { scroll: false });
  if (error) return <p className="error">{error}</p>;
  if (!o) return <p className="muted">Loading…</p>;
  const c = o.counts;
  return (
    <div className="grid long">
      <div className="title-row">
        <h1>Long history</h1>
        <span className="muted small">
          {c.polities ? `${c.polities.toLocaleString("en")} border shapes` : "no borders yet"} ·{" "}
          {c.long_series ? `${c.long_series.toLocaleString("en")} long-run figures` : "no long-run figures yet"} ·{" "}
          {c.history_events ? `${c.history_events.toLocaleString("en")} events far back` : "no events yet"}
        </span>
      </div>
      <div className="seg" role="tablist" aria-label="Views">
        {TABS.map((t) => <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? "on" : ""} onClick={() => go(t.id)}>{t.label}</button>)}
      </div>
      {tab === "charts" && <LongCharts o={o} />}
      {tab === "empires" && <AgeOfEmpires o={o} />}
      {tab === "ruled" && <WhoRuled o={o} />}
      {tab === "thennow" && <ThenAndNow o={o} />}
      {tab === "factors" && <Factors o={o} />}
      {tab === "cycle" && <Cycle o={o} />}
      {tab === "voyages" && <Voyages o={o} />}
      <p className="caption">
        Borders: Seshat Global History Databank, Cliopatria (CC BY 4.0). Long-run figures: Our World in Data from HYDE, the Maddison
        Project and others (CC BY 4.0). Events: Wikidata (CC0) and NOAA&apos;s natural hazards database. Years before AD 1 are BC;
        there is no year 0. The main <Link href="/">Map</Link> has a &quot;World in year…&quot; layer, and each country page a
        Long view card. Switches and limits: <Link href="/settings#long-history">Settings &gt; Long history</Link>.
      </p>
    </div>
  );
}

function Voyages({ o }: { o: LongOverview }) {
  const byId = new Map(o.powers.map((p) => [p.id, p]));
  return (
    <div className="card">
      <h3>Voyages of exploration</h3>
      <ul className="long-voyages">
        {o.voyages.map((v) => (
          <li key={v.id}>
            <b>{v.name}</b> <span className="muted">({v.who}, {yl(v.from)}{v.to !== v.from ? ` to ${yl(v.to)}` : ""})</span>
            {v.power && byId.get(v.power) ? <> · on the map with <Link href={`/long/empire/${v.power}?voyage=${v.id}`}>{byId.get(v.power)!.name}</Link></>
              : <> · <Link href={`/long/empire/britain?voyage=${v.id}`}>on a map</Link></>}
          </li>
        ))}
      </ul>
      <p className="caption">Dated stops joined by straight lines: rough, because real routes curved with winds and coasts. The
        stops are typed in from the voyages&apos; histories (Wikipedia has the full stories; each power&apos;s card links them).</p>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><LongPage /></Suspense>;
}
