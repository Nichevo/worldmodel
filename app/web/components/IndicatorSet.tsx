"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ChartCard from "@/components/ChartCard";
import IndicatorMap from "@/components/IndicatorMap";
import { api, type Indicator } from "@/lib/api";
import { KEY_COUNTRIES, WORLD } from "@/lib/topics";

let allIndicators: Promise<Indicator[]> | null = null;

// A map of one of a list of indicators (with a drop-down to switch) and a chart of each for
// the key countries and the world, as on a topic page. Indicators not loaded are left out.
export default function IndicatorSet({ ids, empty, mapTitle }: { ids: string[]; empty: React.ReactNode; mapTitle?: string }) {
  const [inds, setInds] = useState<Map<string, Indicator> | null>(null);
  const [mapInd, setMapInd] = useState<string | null>(null);
  useEffect(() => {
    allIndicators ??= api.indicators().catch((e) => { allIndicators = null; throw e; });
    allIndicators.then((l) => setInds(new Map(l.map((i) => [i.indicator_id, i])))).catch(() => setInds(new Map()));
  }, []);
  if (!inds) return <p className="muted">Loading…</p>;
  const list = ids.map((i) => inds.get(i)).filter((i): i is Indicator => !!i);
  if (!list.length) return <div className="card">{empty}</div>;
  const mapped = inds.get(mapInd ?? "") ?? list[0];
  return (
    <>
      <section className="card">
        <div className="card-head">
          <h3>{mapTitle ? `${mapTitle}: ` : ""}<Link href={`/indicator/${mapped.indicator_id}`}>{mapped.name}</Link></h3>
          <select className="small" value={mapped.indicator_id} onChange={(e) => setMapInd(e.target.value)} aria-label="Indicator on the map">
            {list.map((i) => <option key={i.indicator_id} value={i.indicator_id}>{i.name}</option>)}
          </select>
        </div>
        <IndicatorMap indicator={mapped} />
      </section>
      <div className="grid two">
        {list.map((i) => (
          <div key={i.indicator_id}>
            <ChartCard indicator={i} entities={[WORLD, ...KEY_COUNTRIES]} />
            <p className="small" style={{ marginTop: -6 }}><Link href={`/indicator/${i.indicator_id}`}>{i.name}: every country, sources and map →</Link></p>
          </div>
        ))}
      </div>
    </>
  );
}
