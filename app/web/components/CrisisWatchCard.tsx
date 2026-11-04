"use client";

import Help from "@/components/Help";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import { api, type EventRow } from "@/lib/api";
import { openAsk } from "@/lib/ai";

// CrisisWatch ratings: a strip with a cell per month since August 2003 (red worse, blue
// better, grey unchanged, blank not rated), and the latest months' paragraphs.
export const CW_LABEL: Record<string, string> = {
  deteriorated: "Deteriorated", risk_alert: "Conflict risk alert", unchanged: "Unchanged", improved: "Improved",
  resolution_opportunity: "Resolution opportunity",
};
export const CW_COLOR: Record<string, string> = {
  deteriorated: "var(--div-neg-3)", risk_alert: "var(--div-neg-1)", unchanged: "var(--grid)", improved: "var(--div-pos-2)",
  resolution_opportunity: "var(--div-pos-3)",
};
const FIRST = 2003 * 12 + 7; // August 2003, as months since year 0

export default function CrisisWatchCard({ entity, name }: { entity: string; name: string }) {
  const [rows, setRows] = useState<EventRow[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.events({ entities: [entity], kinds: ["crisiswatch"] }).then((r) => live && setRows(r)).catch(() => live && setRows([]));
    return () => { live = false; };
  }, [entity]);
  const byMonth = useMemo(() => new Map((rows ?? []).map((e) => [e.start_date.slice(0, 7), e])), [rows]);
  if (!rows?.length) return null;
  const now = new Date();
  const last = now.getUTCFullYear() * 12 + now.getUTCMonth() - 1;
  const months: string[] = [];
  for (let m = FIRST; m <= last; m++) months.push(`${Math.floor(m / 12)}-${String((m % 12) + 1).padStart(2, "0")}`);
  const years = [...new Set(months.map((m) => m.slice(0, 4)))];
  const latest = [...rows].reverse().slice(0, 3);
  const picked = open ? byMonth.get(open) : null;
  const counts = Object.keys(CW_LABEL).map((k) => [k, rows.filter((e) => e.subkind === k).length] as const).filter(([, n]) => n);
  return (
    <div className="card" id="crisiswatch">
      <div className="card-head">
        <h3>CrisisWatch <Help note="crisiswatch" /></h3>
        <CardAsk onAsk={() => openAsk({ title: `CrisisWatch: ${name}`, entity, parts: [{ key: "events", kind: "events",
          label: "CrisisWatch monthly ratings and paragraphs", text: rows.slice(-36).map((e) => `${e.start_date.slice(0, 7)} ${CW_LABEL[e.subkind ?? ""] ?? e.subkind}: ${e.detail ?? ""}`).join("\n") }] })} />
        <Link href={`/crisiswatch`} className="small">World map by month →</Link>
      </div>
      <div className="cw-strip" role="img" aria-label={`CrisisWatch ratings for ${name}, a cell per month since August 2003`}>
        {years.map((y) => (
          <div key={y} className="cw-year">
            <span className="cw-y small muted">{y}</span>
            {months.filter((m) => m.startsWith(y)).map((m) => {
              const e = byMonth.get(m);
              return <button key={m} className={`cw-cell ${open === m ? "on" : ""}`} disabled={!e} onClick={() => setOpen(open === m ? null : m)}
                style={{ background: e ? CW_COLOR[e.subkind ?? ""] ?? "var(--grid)" : "transparent" }}
                title={`${m}: ${e ? CW_LABEL[e.subkind ?? ""] ?? e.subkind : "not rated or not stored"}`} aria-label={m} />;
            })}
          </div>
        ))}
      </div>
      <div className="chips-row small">
        {counts.map(([k, n]) => <span key={k}><i className="dot" style={{ background: CW_COLOR[k] }} /> {CW_LABEL[k]} {n}</span>)}
      </div>
      {(picked ? [picked] : latest).map((e) => (
        <p key={e.event_id} className="small">
          <b>{e.start_date.slice(0, 7)} · {CW_LABEL[e.subkind ?? ""] ?? e.subkind}</b>{e.place ? <span className="muted"> ({e.place})</span> : null}: {e.detail}
          {e.url ? <> <a href={e.url} target="_blank" rel="noreferrer">Crisis Group</a></> : null}
        </p>
      ))}
      <p className="caption">Click a month to read it. Months the refresh has not reached yet are blank; it fills in a few older months each time (Settings: CrisisWatch).</p>
    </div>
  );
}
