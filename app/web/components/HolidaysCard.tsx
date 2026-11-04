"use client";

import Help from "@/components/Help";
import { useEffect, useState } from "react";
import { api, type EventRow } from "@/lib/api";

// This year's public holidays (or next year's from December), month by month.
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

export default function HolidaysCard({ entity, name }: { entity: string; name: string }) {
  const now = new Date();
  const [year, setYear] = useState(now.getMonth() === 11 && now.getDate() > 20 ? now.getFullYear() + 1 : now.getFullYear());
  const [rows, setRows] = useState<EventRow[] | null>(null);
  const [regional, setRegional] = useState(false);
  useEffect(() => {
    let live = true;
    api.events({ entities: [entity], kinds: ["holiday"], start: `${year}-01-01`, end: `${year}-12-31` })
      .then((r) => live && setRows(r)).catch(() => live && setRows([]));
    return () => { live = false; };
  }, [entity, year]);
  if (!rows) return null;
  if (!rows.length && year === now.getFullYear()) return null;
  const shown = rows.filter((e) => regional || e.subkind !== "regional");
  const nRegional = rows.filter((e) => e.subkind === "regional").length;
  const today = now.toISOString().slice(0, 10);
  const next = shown.find((e) => e.start_date >= today);
  return (
    <div className="card" id="holidays">
      <div className="card-head">
        <h3>Public holidays in {name}, {year} <Help note="holidays" /></h3>
        <span className="seg small">
          {[now.getFullYear(), now.getFullYear() + 1].map((y) => <button key={y} className={y === year ? "on" : ""} aria-pressed={y === year} onClick={() => setYear(y)}>{y}</button>)}
        </span>
      </div>
      {!rows.length ? <p className="small muted">Not stored for {year} yet.</p> : (
        <>
          <p className="small">{shown.filter((e) => e.subkind !== "regional").length} national holidays{next ? <>; next: <b>{next.title}</b> on {next.start_date}</> : ""}.
            {nRegional > 0 && <label> <input type="checkbox" checked={regional} onChange={(e) => setRegional(e.target.checked)} /> Show {nRegional} regional days</label>}</p>
          <div className="holidays">
            {MONTHS.map((m, i) => {
              const here = shown.filter((e) => +e.start_date.slice(5, 7) === i + 1);
              return (
                <div key={m} className="holiday-month">
                  <div className="small muted">{m}</div>
                  {here.map((e) => (
                    <div key={e.event_id} className="small" title={[e.detail, e.place ? `Kept in: ${e.place}` : ""].filter(Boolean).join(". ")}>
                      <b>{+e.start_date.slice(8, 10)}</b> {e.title}{e.subkind === "regional" ? <span className="muted"> (regional)</span> : null}
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        </>
      )}
      <p className="caption">Nager.Date. Hover a holiday for its local name and where it is kept.</p>
    </div>
  );
}
