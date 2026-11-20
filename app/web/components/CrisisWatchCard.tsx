"use client";

import Help from "@/components/Help";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import { api, type EventRow } from "@/lib/api";
import { openAsk } from "@/lib/ai";
import { osintApi, type OsintMonth } from "@/lib/osint";
import { mapLayersHref } from "@/lib/workspace";

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

// What the OSINT sources recorded in a month, in one line: deaths, protests, outages, new sanctions.
export function monthDetail(m: { ucdp_deaths: number | null; acled_deaths: number | null; protests: number; outages: number;
  sanctions_added: number; riots?: number; violence?: number; events?: number; outage_causes?: string[] } | undefined): string {
  if (!m) return "";
  const bits: string[] = [];
  if (m.ucdp_deaths != null) bits.push(`${m.ucdp_deaths.toLocaleString()} killed in fighting (UCDP)`);
  if (m.acled_deaths != null) bits.push(`${m.acled_deaths.toLocaleString()} (ACLED, ${(m.violence ?? m.events ?? 0).toLocaleString()} violent events)`);
  const unrest = m.protests + (m.riots ?? 0);
  if (unrest) bits.push(`${unrest.toLocaleString()} protests and riots`);
  if (m.outages) bits.push(`${m.outages} internet outage${m.outages === 1 ? "" : "s"}${m.outage_causes?.length ? ` (${m.outage_causes.join(", ")})` : ""}`);
  if (m.sanctions_added) bits.push(`${m.sanctions_added.toLocaleString()} newly sanctioned`);
  return bits.join(" · ");
}

export default function CrisisWatchCard({ entity, name }: { entity: string; name: string }) {
  const [rows, setRows] = useState<EventRow[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [detail, setDetail] = useState<Map<string, OsintMonth>>(new Map());
  useEffect(() => {
    let live = true;
    api.events({ entities: [entity], kinds: ["crisiswatch"] }).then((r) => live && setRows(r)).catch(() => live && setRows([]));
    osintApi.country(entity, 240).then((d) => live && setDetail(new Map(d.months.map((m) => [m.month, m])))).catch(() => live && setDetail(new Map()));
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
              const odd = detail.get(m)?.mismatch;
              return <button key={m} className={`cw-cell ${open === m ? "on" : ""}`} disabled={!e} onClick={() => setOpen(open === m ? null : m)}
                style={{ background: e ? CW_COLOR[e.subkind ?? ""] ?? "var(--grid)" : "transparent", ...(odd ? { outline: "2px solid var(--ink)", outlineOffset: -1 } : {}) }}
                title={`${m}: ${e ? CW_LABEL[e.subkind ?? ""] ?? e.subkind : "not rated or not stored"}${odd ? ` (${odd.toLowerCase()})` : ""}`} aria-label={m} />;
            })}
          </div>
        ))}
      </div>
      <div className="chips-row small">
        {counts.map(([k, n]) => <span key={k}><i className="dot" style={{ background: CW_COLOR[k] }} /> {CW_LABEL[k]} {n}</span>)}
      </div>
      {(picked ? [picked] : latest).map((e) => {
        const mo = e.start_date.slice(0, 7);
        const d = detail.get(mo);
        const line = monthDetail(d);
        const last = new Date(Date.UTC(+mo.slice(0, 4), +mo.slice(5, 7), 0)).toISOString().slice(0, 10);
        return (
          <div key={e.event_id}>
            <p className="small" style={{ marginBottom: 2 }}>
              <b>{mo} · {CW_LABEL[e.subkind ?? ""] ?? e.subkind}</b>{e.place ? <span className="muted"> ({e.place})</span> : null}: {e.detail}
              {e.url ? <> <a href={e.url} target="_blank" rel="noreferrer">Crisis Group</a></> : null}
            </p>
            {(line || d?.mismatch) && (
              <p className="small muted" style={{ marginTop: 0, paddingLeft: 10, borderLeft: "3px solid var(--grid)" }}>
                Recorded that month: {line || "nothing in the event sources"}
                {d?.mismatch ? <> · <b style={{ color: "var(--ink)" }}>Worth a second look: {d.mismatch.toLowerCase()}</b></> : null}
                {" "}· <Link href={mapLayersHref("3", `${mo}-01~${last}`)}>Look closer on the map</Link>
              </p>
            )}
          </div>
        );
      })}
      <p className="caption">Click a month to read it, with what UCDP, ACLED, the internet-outage monitors and OpenSanctions recorded that month.
        Outlined months are ones where the rating and the recorded violence point different ways. Months the refresh has not reached yet are blank; it fills in a few older months each time (Settings: CrisisWatch).</p>
    </div>
  );
}
