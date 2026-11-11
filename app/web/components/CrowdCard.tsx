"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import CrowdRow from "@/components/CrowdRow";
import { openAsk } from "@/lib/ai";
import { crowdApi, type CrowdCountry, pct } from "@/lib/predictions";

// A country page's "What the crowd expects": its busiest open crowd questions and the ViEWS
// conflict forecast for the next year. Hidden when there is neither.
export default function CrowdCard({ entity, name }: { entity: string; name: string }) {
  const [d, setD] = useState<CrowdCountry | null>(null);
  useEffect(() => {
    let live = true;
    crowdApi.country(entity).then((r) => live && setD(r)).catch(() => live && setD(null));
    return () => { live = false; };
  }, [entity]);
  if (!d) return null;
  // ViEWS gives every country a figure; near zero (most of the world) says nothing worth a line.
  const v = d.views && (d.views.deaths_12 >= 1 || d.views.max_chance >= 0.01) ? d.views : null;
  if (!d.questions.length && !v) return null;
  const ask = () => openAsk({ title: `${name}: what the crowd expects`, entity, parts: [
    { key: "data", kind: "data", label: "Crowd questions", text: d.questions.map((q) => `${q.title} | ${q.site_name} | ${pct(q.chance)} | closes ${q.closes?.slice(0, 10) ?? "?"}`).join("\n") },
    ...(v ? [{ key: "views", kind: "data" as const, label: "ViEWS conflict forecast", text: v.months.map((m) => `${m.month}: ${Math.round(m.deaths ?? 0)} deaths, ${pct(m.chance_25)} chance of 25+`).join("\n") }] : [])] });
  return (
    <div className="card" id="crowd">
      <div className="card-head"><h3>What the crowd expects</h3>
        <span><CardAsk onAsk={ask} /> <Link className="small" href={`/crowd?country=${entity}`}>All questions</Link></span></div>
      {d.questions.length > 0 && <div className="crowd-list">{d.questions.map((q) => <CrowdRow key={q.question_key} q={q} />)}</div>}
      {v && (
        <p className="small" style={{ marginTop: 8 }}><b>Conflict (ViEWS):</b> about {Math.round(v.deaths_12).toLocaleString()} deaths in state-based conflict predicted over the
          next 12 months; highest monthly chance of 25 or more: {pct(v.max_chance)}. <Link href="/crowd?tab=conflict">Map</Link></p>
      )}
      <p className="caption">Polymarket, Metaculus and Manifold questions naming {name}, busiest first; matched by names in the title, so Hide any wrong ones on the question&apos;s page.</p>
    </div>
  );
}
