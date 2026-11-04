"use client";

import Help from "@/components/Help";
import Link from "next/link";
import { useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import { api, type EntityLaws } from "@/lib/api";
import { openAsk } from "@/lib/ai";
import { formatValue } from "@/lib/format";

// The country's rules as they stand, each with the year it took that form, and the changes over time.
export default function LawsCard({ entity, name }: { entity: string; name: string }) {
  const [data, setData] = useState<EntityLaws | null>(null);
  useEffect(() => {
    let live = true;
    api.entityLaws(entity).then((d) => live && setData(d)).catch(() => live && setData(null));
    return () => { live = false; };
  }, [entity]);
  if (!data?.rules.length) return null;
  const text = ["Rule,Value,Since,Latest year", ...data.rules.map((r) => `"${r.name}",${formatValue(r.value, r.unit, r.decimals)},${r.since ?? ""},${r.year}`)].join("\n");
  return (
    <div className="card" id="laws">
      <div className="card-head">
        <h3>Laws and rules <Help note="laws" /></h3>
        <CardAsk onAsk={() => openAsk({ title: `Laws and rules: ${name}`, entity, parts: [{ key: "data", kind: "data", label: "Rules and when they last changed", text }] })} />
        <Link href="/laws" className="small">Every country, by rule →</Link>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="small">
          <thead><tr><th>Rule</th><th className="num">Now</th><th className="num">Since</th></tr></thead>
          <tbody>
            {data.rules.map((r) => (
              <tr key={r.indicator_id}>
                <td><Link href={`/laws?rule=${r.indicator_id}`}>{r.name}</Link></td>
                <td className="num"><b>{formatValue(r.value, r.unit, r.decimals)}</b>{r.unit && r.unit !== "yes/no" && !r.unit.startsWith("index") ? ` ${r.unit}` : ""}</td>
                <td className="num" title={r.changed ? "The year it last changed" : "As far back as the source goes"}>{r.since ?? ""}{r.changed ? "" : " or earlier"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.changes.length > 0 && (
        <details>
          <summary className="small">{data.changes.length} change{data.changes.length > 1 ? "s" : ""} over the years</summary>
          <ul className="small">
            {[...data.changes].reverse().map((e) => <li key={e.event_id}><b>{e.start_date.slice(0, 4)}</b> {e.title}</li>)}
          </ul>
        </details>
      )}
      <p className="caption">Women, Business and the Law gives the laws on 1 October each year. Load WORLD Policy or GunPolicy.org tables (Data status, files you download yourself) to add more rules.</p>
    </div>
  );
}
