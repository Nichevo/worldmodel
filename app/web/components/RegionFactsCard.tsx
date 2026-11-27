"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import { plainName } from "@/components/RegionsCard";
import { openAsk } from "@/lib/ai";
import { api, type RegionFacts } from "@/lib/api";
import { formatValue } from "@/lib/format";

// A state's or county's figures, each with its value, its place among the regions beside it
// (#n of N, tinted from green for the top to red for the bottom; whether high is good is left to
// the reader), their middle value, and the state's or country's own figure where held.
const DOMAIN_ORDER = ["population", "migration", "economy", "housing", "education", "health", "politics", "energy"];
const LEVEL_PLURAL: Record<string, string> = { state: "states", county: "counties", region: "regions" };

function Spark({ pts }: { pts: [number, number][] }) {
  if (pts.length < 2) return null;
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${(((x - x0) / (x1 - x0 || 1)) * 70).toFixed(1)},${(16 - ((y - y0) / (y1 - y0 || 1)) * 14).toFixed(1)}`).join(" ");
  return <svg width={72} height={18} aria-hidden><path d={d} fill="none" stroke="var(--accent)" strokeWidth={1.4} /></svg>;
}

export default function RegionFactsCard({ entity, name }: { entity: string; name: string }) {
  const [d, setD] = useState<RegionFacts | null>(null);
  useEffect(() => {
    let live = true;
    api.regionFacts(entity).then((x) => live && setD(x)).catch(() => live && setD(null));
    return () => { live = false; };
  }, [entity]);
  const facts = useMemo(() => [...(d?.facts ?? [])].sort((a, b) =>
    (DOMAIN_ORDER.indexOf(a.domain ?? "") + 99) % 99 - (DOMAIN_ORDER.indexOf(b.domain ?? "") + 99) % 99 || a.name.localeCompare(b.name)), [d]);
  if (!d?.place || !facts.length) return null;
  const p = d.place;
  const among = `${LEVEL_PLURAL[p.level] ?? "regions"} of ${p.parent_name}`;
  const tint = (rank: number, of: number) => {
    if (of < 3) return undefined;
    const t = (rank - 1) / (of - 1); // 0 top, 1 bottom
    return `color-mix(in srgb, ${t < 0.5 ? "var(--good, #2e7d32)" : "var(--bad, #c62828)"} ${Math.round(Math.abs(t - 0.5) * 60)}%, transparent)`;
  };
  const text = () => ["Figure,Year,Value,Unit,Rank,Of,Middle,Parent", ...facts.map((f) =>
    `"${plainName(f.name)}",${f.year},${+f.value.toPrecision(6)},"${f.unit}",${f.rank},${f.of},${+f.middle.toPrecision(6)},${f.parent_value ?? ""}`)].join("\n");
  return (
    <div className="card" id="region-facts">
      <div className="card-head">
        <h3>{name} among the {among}</h3>
        <CardAsk onAsk={() => openAsk({ title: `${name} among the ${among}`, entity,
          parts: [{ key: "data", kind: "data", label: "Figures with ranks", text: text() }] })} />
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="summary-table small">
          <thead><tr><th>Figure</th><th className="num">{name}</th><th className="num">Rank</th><th className="num">Middle</th>
            <th className="num"><Link href={`/entity/${p.parent_id}`}>{p.parent_name}</Link></th><th>Last 15 years</th></tr></thead>
          <tbody>{facts.map((f) => (
            <tr key={f.indicator_id}>
              <td>{plainName(f.name)} <span className="muted">{f.year}</span></td>
              <td className="num"><b>{formatValue(f.value, f.unit, f.decimals)}</b> <span className="muted">{f.unit}</span></td>
              <td className="num" style={{ background: tint(f.rank, f.of) }} title={`Highest ${formatValue(f.highest, f.unit, f.decimals)}, lowest ${formatValue(f.lowest, f.unit, f.decimals)}`}>
                #{f.rank} of {f.of}</td>
              <td className="num">{formatValue(f.middle, f.unit, f.decimals)}</td>
              <td className="num">{f.parent_value == null ? "" : formatValue(f.parent_value, f.unit, f.decimals)}</td>
              <td><Spark pts={f.spark} /></td>
            </tr>))}</tbody>
        </table>
      </div>
      <p className="caption">#1 is the highest of the {among} that year, whether that is good or bad. Middle is the median.
        {" "}Figures from the Census Bureau, BEA, BLS, FHFA, MIT Election Lab, County Health Rankings and EIA (US), Stats NZ and the
        {" "}Ministry for Cities, Environment, Regions and Transport (New Zealand), or the ABS (Australia).</p>
    </div>
  );
}
