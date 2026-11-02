"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Help from "@/components/Help";
import { api, type PlaceKind, type PlaceRow } from "@/lib/api";

// Metro and rail, universities and big companies for a country or a city (Wikidata,
// refreshed every four weeks). Hidden until a refresh has loaded them.
const KINDS: { kind: PlaceKind; title: string }[] = [
  { kind: "transit", title: "Metro and rail" },
  { kind: "university", title: "Universities" },
  { kind: "company", title: "Big companies" },
];

const big = (v: number | undefined, unit = "") => {
  if (v === undefined || v === null) return "–";
  const a = Math.abs(v);
  const s = a >= 1e12 ? `${(v / 1e12).toFixed(1)} trillion` : a >= 1e9 ? `${(v / 1e9).toFixed(1)} billion`
    : a >= 1e6 ? `${(v / 1e6).toFixed(1)} million` : Math.round(v).toLocaleString();
  return unit ? `${unit}${s}` : s;
};
const yr = (y: number | undefined) => (y ? ` (${y})` : "");

function Facts({ p }: { p: PlaceRow }) {
  const f = p.facts;
  if (p.kind === "transit") {
    return <>{[f.length_km ? `${f.length_km} km` : null, f.stations ? `${f.stations} station${f.stations === 1 ? "" : "s"}` : null,
      f.riders ? `${big(f.riders)} trips a year${yr(f.riders_year)}` : null].filter(Boolean).join(" · ") || "–"}</>;
  }
  if (p.kind === "university") return <>{f.students ? `${big(f.students)} students${yr(f.students_year)}` : "–"}</>;
  const rev = f.revenue_usd ? `US$${big(f.revenue_usd)} revenue${yr(f.revenue_year)}` : f.revenue ? `${f.currency} ${big(f.revenue)} revenue${yr(f.revenue_year)}` : null;
  return <>{[rev, f.staff ? `${big(f.staff)} staff` : null, f.industry].filter(Boolean).join(" · ") || "–"}</>;
}

export default function PlacesCard({ country, city, rows: given, name }:
  { country?: string; city?: string; rows?: PlaceRow[]; name: string }) {
  const [rows, setRows] = useState<PlaceRow[] | null>(given ?? null);
  const [kind, setKind] = useState<PlaceKind | null>(null);
  useEffect(() => {
    if (given) { setRows(given); return; }
    setRows(null);
    api.places({ country, city, limit: 300 }).then((r) => setRows(r.rows)).catch(() => setRows([]));
  }, [country, city, given]);
  if (!rows || rows.length === 0) return null;
  const have = KINDS.filter((k) => rows.some((r) => r.kind === k.kind));
  const on = kind && have.some((k) => k.kind === kind) ? kind : have[0].kind;
  const shown = rows.filter((r) => r.kind === on).slice(0, 15);
  return (
    <div className="card" id="places">
      <div className="card-head">
        <h3>Transport, universities and companies <Help note="places" /></h3>
        <span className="seg" role="group" aria-label="What to show">
          {have.map((k) => (
            <button key={k.kind} className={on === k.kind ? "on" : ""} aria-pressed={on === k.kind} onClick={() => setKind(k.kind)}>
              {k.title} ({rows.filter((r) => r.kind === k.kind).length})
            </button>
          ))}
        </span>
      </div>
      <table className="summary-table places-table">
        <thead><tr><th>Name</th>{!city && <th>City</th>}<th>Since</th><th>Figures</th></tr></thead>
        <tbody>
          {shown.map((p) => (
            <tr key={p.place_id}>
              <td className="name">
                {p.url ? <a href={p.url} target="_blank" rel="noreferrer">{p.name}</a> : p.name}
                {p.subkind && <span className="city-tag">{p.subkind}</span>}
              </td>
              {!city && <td>{p.city_id ? <Link href={`/city/${p.city_id}`}>{p.city}</Link> : p.city ?? "–"}</td>}
              <td>{p.founded ?? "–"}</td>
              <td className="small"><Facts p={p} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="caption">
        From Wikidata (CC0), refreshed every four weeks. Biggest first: by trips a year (else length), students, or revenue in US dollars
        (converted at that year&apos;s exchange rate). Only universities and companies well known enough to have articles in several
        Wikipedias are listed. The map&apos;s Layers menu can show stations, universities and companies{name ? ` in ${name}` : ""}.
      </p>
    </div>
  );
}
