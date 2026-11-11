"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import { openAsk } from "@/lib/ai";
import { compact } from "@/lib/format";
import { land, type LandCardData, linesOption, type Pt } from "@/lib/land";

// A land-based sector's Land card: the land it uses against what it makes since a chosen
// year (both as an index, 100 in that year), how intensive it is, the same for Ireland, the
// Netherlands, the US and Australia, and New Zealand by region.

const SINCE = [1961, 1990, 2000, 2010];

function indexed(pts: Pt[], from: number): Pt[] {
  const rest = pts.filter(([y]) => y >= from);
  const base = rest[0]?.[1];
  return base ? rest.map(([y, v]) => [y, (v / base) * 100]) : [];
}

export default function LandCard({ sector, country = "NZL" }: { sector: string; country?: string }) {
  const [d, setD] = useState<LandCardData | null>(null);
  const [from, setFrom] = useState(1990);
  const [ratio, setRatio] = useState(0);
  useEffect(() => { land.card(sector).then(setD).catch(() => setD(null)); }, [sector]);
  const ent = d?.entities.includes(country) ? country : d?.entities[0] ?? "NZL";
  // Both indexed to the first year from `from` on that both series have, so they start together.
  const landPts = d?.land.by[ent] ?? [], outPts = d?.output.by[ent] ?? [];
  const outYears = new Set(outPts.map(([y]) => y));
  const both = landPts.map(([y]) => y).filter((y) => y >= from && outYears.has(y));
  const base = both.length ? Math.min(...both) : from;
  const vs = useCallback(() => linesOption([
    { label: `${d?.land.label ?? "Land"} (${indexed(landPts, base).length ? landPts.find(([y]) => y >= base)?.[0] : base} = 100)`, pts: indexed(landPts, base) },
    { label: `${d?.output.label ?? "Output"} (${outPts.find(([y]) => y >= base)?.[0] ?? base} = 100)`, pts: indexed(outPts, base) },
  ].filter((l) => l.pts.length), ["index"]), [d, base, ent]);
  const r = d?.ratios[Math.min(ratio, (d?.ratios.length ?? 1) - 1)];
  const cmp = useCallback(() => linesOption(Object.entries(r?.by ?? {}).map(([e, pts]) => ({ label: d?.names[e] ?? e, pts: pts.filter(([y]) => y >= from) })),
    [r?.unit ?? ""]), [r, d, from]);
  if (!d || (!Object.keys(d.land.by).length && !d.ratios.length)) return null;
  const ask = () => openAsk({ title: `Land used by ${sector}`, entity: ent, parts: [
    { key: "data", kind: "data", label: "Land and output", text: [d.land, d.output].map((s) => `${s.label}: ${(s.by[ent] ?? []).map(([y, v]) => `${y} ${compact(v)}`).join(", ")}`).join("\n") },
    { key: "ratios", kind: "data", label: "Intensity", text: d.ratios.map((x) => `${x.label} (${x.unit}): ${Object.entries(x.by).map(([e, p]) => `${d.names[e] ?? e} ${p.at(-1)?.[1].toFixed(2)} (${p.at(-1)?.[0]})`).join("; ")}`).join("\n") }] });
  return (
    <div className="card" id="land-card">
      <div className="card-head"><h3>Land</h3><span><CardAsk onAsk={ask} /> <Link className="small" href="/land">Land page</Link></span></div>
      <div className="chips-row small">Since {SINCE.map((y) => <button key={y} className={from === y ? "on" : ""} onClick={() => setFrom(y)}>{y}</button>)}</div>
      <div className="grid two">
        <div><h4>Land against output, {d.names[ent] ?? ent}</h4><EChart option={vs} height={240} label="Land against output" />
          <p className="caption">{both.length ? `Both as 100 in ${base}` : "No year with both figures yet, so each is 100 in its own first year"}: output rising faster than land means more from each hectare.</p></div>
        {r ? <div><h4>
          <select className="small" value={ratio} onChange={(e) => setRatio(+e.target.value)} aria-label="Measure">
            {d.ratios.map((x, i) => <option key={x.label} value={i}>{x.label}</option>)}</select> <span className="muted small">{r.unit}</span></h4>
          <EChart option={cmp} height={240} label={r.label} />
          <p className="caption">New Zealand beside Ireland, the Netherlands, the United States and Australia (FAOSTAT).</p></div> : null}
      </div>
      {d.regions ? <div><h4>{d.regions.label}, {d.regions.rows[0]?.y}</h4><table className="small"><tbody>{d.regions.rows.map((x) => (
        <tr key={x.e}><td>{x.name}</td><td className="num">{compact(x.v)}</td></tr>))}</tbody></table></div> : null}
    </div>
  );
}
