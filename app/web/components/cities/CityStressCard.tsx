"use client";

import Link from "next/link";
import CardAsk from "@/components/CardAsk";
import Help from "@/components/Help";
import { openAsk } from "@/lib/ai";
import type { CityScoreForCity } from "@/lib/api";
import { shortUnit, stressColor } from "@/lib/cities";
import { formatValue } from "@/lib/format";

// A city page's City stress line: the score, its rank, each part's figure and place, and
// how the score moved over the years once more than one year is loaded.
export default function CityStressCard({ s, name }: { s: CityScoreForCity; name: string }) {
  const ask = () => openAsk({ title: `${s.name}: ${name}`, parts: [
    { key: "description", kind: "description", label: "How", text: `${s.about}\n${s.how}` },
    { key: "data", kind: "data", label: "Parts", text: [`Score ${s.score} of 10, ${s.rank} of ${s.of} cities`,
      ...s.parts.map((p) => `${p.full_name}: ${p.value} ${p.unit} (${p.year}); place ${p.points} of 10`),
      ...s.history.map((h) => `${h.year}: ${h.score} (${h.rank} of ${h.of})`)].join("\n") }] });
  return (
    <section className="card">
      <div className="card-head"><h3>{s.name}: <span className="stress-score" style={{ background: stressColor(s.score) }}>{s.score.toFixed(1)}</span>
        <span className="small muted"> of 10 · {s.rank} of {s.of} cities</span> <Help note="city_stress" /></h3><CardAsk onAsk={ask} /></div>
      <div className="stress-parts">
        {s.parts.map((p) => (
          <div key={p.indicator} title={`${p.description} ${p.worse_when === "higher" ? "Higher" : "Lower"} is more stressful.`}>
            <span className="small muted">{p.name}</span>
            <b>{formatValue(p.value, "", p.decimals)} <span className="small muted">{shortUnit(p.unit)}</span></b>
            <div className="stress-bar"><i style={{ left: `calc(${p.points * 10}% - 2px)`, background: stressColor(p.points) }} /></div>
            <span className="small muted">{p.year} · {p.points.toFixed(1)} of 10</span>
          </div>))}
      </div>
      {s.history.length > 1 && <p className="small">Over the years: {s.history.map((h, i) => (
        <span key={h.year}>{i ? " · " : ""}{h.year} <b>{h.score.toFixed(1)}</b> ({h.rank} of {h.of})</span>))}</p>}
      <p className="caption">{s.about} {s.how} All cities on <Link href="/cities?view=stress">Cities &gt; City stress</Link>.</p>
    </section>
  );
}
