"use client";

import CardAsk from "@/components/CardAsk";
import Help from "@/components/Help";
import { useCallback, useMemo, useState } from "react";
import EChart from "@/components/EChart";
import type { Indicator } from "@/lib/api";
import { points, useSavePicture, useSeries } from "@/lib/cards";
import { cardLinesOption, type CardLine } from "@/lib/charts";
import { seriesColor } from "@/lib/colors";

// Recorded crime by broad type, homicide, and people in prison, per 100,000 people.
const SETS = [
  { key: "crime", label: "Recorded crime", lines: [["crime_property_rate", "Property"], ["crime_violent_rate", "Violent"], ["crime_sexual_rate", "Sexual"],
    ["crime_fraud_rate", "Fraud and corruption"], ["crime_drugs_rate", "Drugs"]] },
  { key: "homicide", label: "Homicide", lines: [["homicide_rate", "Victims of homicide"]] },
  { key: "prison", label: "Prisons", lines: [["prisoners_rate", "In prison"], ["prisoners_unsentenced_rate", "Awaiting trial or sentence"],
    ["prisoners_women_rate", "Women in prison"], ["wpb_prison_population_rate", "In prison (World Prison Brief)"]] },
] as const;

export default function CrimeCard({ entity, name, indicators }: { entity: string; name: string; indicators: Map<string, Indicator> }) {
  const ids = useMemo(() => SETS.flatMap((s) => s.lines.map(([id]) => id as string)), []);
  const { data } = useSeries(entity, ids, indicators);
  const [pick, setPick] = useState<string>("crime");
  const { onReady, save, ask } = useSavePicture();
  const sets = SETS.filter((s) => s.lines.some(([id]) => data?.get(id)?.length));
  const set = sets.find((s) => s.key === pick) ?? sets[0];
  const lines: CardLine[] = useMemo(() => (set && data ? set.lines.filter(([id]) => data.get(id)?.length)
    .map(([id, label], i) => ({ key: id, label, color: seriesColor([0, 6, 4, 2, 1][i % 5]), points: points(data.get(id)) })) : []), [set, data]);
  const option = useCallback(() => cardLinesOption(lines, { unit: "per 100,000 people", decimals: 1 }), [lines]);
  if (!data || !set) return null;
  const title = `${set.label} per 100,000 people: ${name}`;
  const note = "UNODC crime and criminal justice statistics, as each country reports them; definitions differ between countries.";
  const sources = ["unodc_crime"];
  return (
    <div className="card" id="crime">
      <div className="card-head">
        <h3>Crime and prisons <Help note="crime" /></h3>
        <CardAsk onAsk={() => ask(title, note, sources, entity)} />
        <button className="link small" onClick={() => save(title, note, sources, "crime", set.key, entity)}>Save picture</button>
      </div>
      <div className="seg small">
        {sets.map((s) => <button key={s.key} className={s === set ? "on" : ""} aria-pressed={s === set} onClick={() => setPick(s.key)}>{s.label}</button>)}
      </div>
      <EChart option={option} height={280} label={title} onReady={onReady} />
      <p className="caption">{note} Compare a country with itself over time rather than levels across countries.</p>
    </div>
  );
}
