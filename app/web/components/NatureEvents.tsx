"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type NatureEvent } from "@/lib/api";

let namesCache: Promise<Map<string, string>> | null = null;
export function useEntityNames(): Map<string, string> {
  const [names, setNames] = useState<Map<string, string>>(new Map());
  useEffect(() => {
    namesCache ??= api.entities().then((l) => new Map(l.map((e) => [e.entity_id, e.short_name]))).catch(() => { namesCache = null; return new Map(); });
    namesCache.then(setNames);
  }, []);
  return names;
}

// A list of hand-checked events (animal disease, pests, pollution) with their countries and a link to read more.
export default function NatureEvents({ events, limit = 40 }: { events: NatureEvent[]; limit?: number }) {
  const names = useEntityNames();
  if (!events.length) return <p className="small muted">None listed.</p>;
  const when = (e: NatureEvent) => {
    const n = e.precision === "year" ? 4 : 7;
    const a = e.start_date?.slice(0, n) ?? "";
    const b = e.end_date?.slice(0, e.end_date?.endsWith("-12-31") && e.precision === "year" ? 4 : 7);
    return b && b !== a ? `${a} to ${b}` : a;
  };
  return (
    <div style={{ overflowX: "auto", maxHeight: 520 }}>
      <table className="small">
        <thead><tr><th>When</th><th>What</th><th>Where</th></tr></thead>
        <tbody>{events.slice(0, limit).map((e) => (
          <tr key={`${e.title}|${e.start_date}`}>
            <td style={{ whiteSpace: "nowrap" }}>{when(e)}</td>
            <td>{e.url ? <a href={e.url} target="_blank" rel="noreferrer">{e.title}</a> : e.title}
              {e.detail ? <div className="muted">{e.detail}</div> : null}</td>
            <td>{e.entities.map((c, i) => <span key={c}>{i ? ", " : ""}<Link href={`/entity/${c}`}>{names.get(c) ?? c}</Link></span>)}
              {e.place ? <span className="muted"> ({e.place})</span> : null}</td>
          </tr>))}</tbody>
      </table>
    </div>
  );
}
