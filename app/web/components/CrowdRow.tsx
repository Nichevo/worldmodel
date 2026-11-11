"use client";

import Link from "next/link";
import Flag from "@/components/Flag";
import { CATEGORY_TEXT, type CrowdQ, pct, pts } from "@/lib/predictions";

// One crowd question in a list: its chance now, title, site, countries, and the week's move.
export default function CrowdRow({ q, names }: { q: CrowdQ; names?: Record<string, string> }) {
  const opts = q.options && q.kind !== "binary" ? q.options.slice(0, 3) : null;
  return (
    <div className="crowd-row">
      <span className="chance" title={q.kind === "binary" ? "Chance of yes now" : q.kind === "numeric" ? "Community median" : "Leading option"}>
        {q.kind === "binary" ? pct(q.chance) : q.kind === "numeric" ? (q.chance == null ? "–" : Number(q.chance.toPrecision(3))) : opts?.[0] ? pct(opts[0].chance) : "–"}</span>
      <span><Link href={`/crowd/question?key=${encodeURIComponent(q.question_key)}`}>{q.title}</Link>
        {opts && <span className="small muted"> {opts.map((o) => `${o.name} ${pct(o.chance)}`).join(", ")}</span>}
        <div className="meta">{q.site_name}
          {q.category ? ` · ${CATEGORY_TEXT[q.category] ?? q.category}` : ""}
          {q.countries.length ? <> · {q.countries.map((c) => <span key={c}><Flag id={c} /> {names?.[c] ?? c} </span>)}</> : null}
          {q.closes ? ` · closes ${q.closes.slice(0, 10)}` : ""}
          {q.forecasters ? ` · ${q.forecasters.toLocaleString()} forecasters` : ""}
          {q.volume ? ` · $${Math.round(q.volume).toLocaleString()} traded` : ""}
          {q.status === "resolved" ? ` · resolved ${q.resolution ?? ""}` : ""}
          {q.followed ? " · followed" : ""}</div></span>
      <span className={`small ${q.change == null ? "" : q.change > 0 ? "up" : q.change < 0 ? "down" : ""}`} title="Change over the last week">{pts(q.change)}</span>
    </div>
  );
}

