"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import AskButton from "@/components/AskButton";
import Flag from "@/components/Flag";
import { osintApi, type SanctionListing, type SanctionsNow } from "@/lib/osint";

// Who sanctions whom, today: listings in force by target country (rows) and by the list that
// names them (columns), from OpenSanctions' merge of more than 300 official lists. Newest
// listings below, and a search by name.
const SCHEMA_TEXT: Record<string, string> = { Person: "People", Company: "Companies", Organization: "Organisations", LegalEntity: "Other bodies",
  Vessel: "Ships", Airplane: "Aircraft" };
const list = (v: string[] | string) => (Array.isArray(v) ? v : (v || "").split(",").filter(Boolean));

function SanctionsPage() {
  const [schema, setSchema] = useState("");
  const [d, setD] = useState<SanctionsNow | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SanctionListing[] | null>(null);
  const [all, setAll] = useState(false);
  const [newOnly, setNewOnly] = useState(false);
  useEffect(() => {
    let live = true;
    osintApi.sanctions(schema || undefined).then((x) => live && setD(x)).catch((e) => live && setErr(String(e.message || e)));
    return () => { live = false; };
  }, [schema]);
  useEffect(() => {
    if (q.trim().length < 2) { setHits(null); return; }
    let live = true;
    const t = setTimeout(() => osintApi.sanctionsSearch(q.trim()).then((r) => live && setHits(r.items)).catch(() => live && setHits([])), 300);
    return () => { live = false; clearTimeout(t); };
  }, [q]);
  if (err) return <p className="error">{err}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  const auths = d.authorities;
  const rows = all ? d.rows : d.rows.slice(0, 30);
  const max = Math.max(1, ...d.rows.flatMap((r) => Object.values(r.cells).map((c) => (newOnly ? c.added : c.listed))));
  const shade = (n: number) => (n ? `color-mix(in srgb, var(--div-neg-3) ${Math.round(12 + 70 * Math.sqrt(n / max))}%, transparent)` : "transparent");
  const authName = (a: string) => d.authority_names[a] ?? a;
  return (
    <div className="grid">
      <div className="title-row">
        <h1>Sanctions now</h1>
        <AskButton title="Sanctions now" parts={() => [{ key: "data", kind: "data", label: "Listings in force by target country and list",
          text: ["Target," + auths.map((a) => a.name).join(","), ...d.rows.slice(0, 40).map((r) => `${r.name},${auths.map((a) => r.cells[a.id]?.listed ?? 0).join(",")}`)].join("\n") }]} />
      </div>
      {!d.loaded ? (
        <p className="card">Nothing loaded yet. Run <code>.\refresh.bat</code> (Settings &gt; Fighting, wars…: Sanctions in force on). It reads OpenSanctions&apos; file
          once a week (about 100 MB, of which only counts and names are kept).</p>
      ) : (
        <>
          <div className="chips-row small">
            <label>Who <select value={schema} onChange={(e) => setSchema(e.target.value)}>
              <option value="">Everyone and everything</option>
              {d.schemas.map((s) => <option key={s.schema} value={s.schema}>{SCHEMA_TEXT[s.schema] ?? s.schema} ({s.n.toLocaleString()})</option>)}
            </select></label>
            <label><input type="checkbox" checked={newOnly} onChange={(e) => setNewOnly(e.target.checked)} /> Only those added in the last year</label>
          </div>
          <div className="card">
            <h3>Listings in force, by target country and by who listed them</h3>
            <div style={{ overflowX: "auto" }}>
              <table className="small">
                <thead><tr><th>Target</th>{auths.map((a) => <th key={a.id} style={{ textAlign: "right", fontWeight: a.key ? 700 : 500 }} title={a.name}>
                  {/^[A-Z]{3}$/.test(a.id) ? <Flag id={a.id} /> : null}{a.name.replace(/ \(.*\)$/, "")}</th>)}<th style={{ textAlign: "right" }}>All lists</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.target}>
                      <td style={{ whiteSpace: "nowrap" }}><Link href={`/entity/${r.target}#fighting`}><Flag id={r.target} />{r.name}</Link></td>
                      {auths.map((a) => {
                        const c = r.cells[a.id];
                        const n = c ? (newOnly ? c.added : c.listed) : 0;
                        return <td key={a.id} style={{ textAlign: "right", background: shade(n) }} title={c ? `${c.listed.toLocaleString()} listed, ${c.added.toLocaleString()} added in the last year` : "none"}>
                          {n ? n.toLocaleString() : <span className="muted">–</span>}</td>;
                      })}
                      <td style={{ textAlign: "right" }}><b>{(newOnly ? r.added : r.total).toLocaleString()}</b></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {d.rows.length > 30 && <button className="link small" onClick={() => setAll(!all)}>{all ? "Show the top 30" : `Show all ${d.rows.length} countries`}</button>}
            <p className="caption">A person, company, ship or aircraft counts once under each list that names it, against the country it is tied to (nationality,
              registration or where it is based). &quot;All lists&quot; also counts lists not shown as columns. New Zealand&apos;s column is its Russia Sanctions Register;
              the UN column is the Security Council&apos;s consolidated list. OpenSanctions, free for non-commercial use.</p>
          </div>
          <div className="card">
            <div className="card-head"><h3>Find a name</h3>
              <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="A person, company or ship" aria-label="Search sanctioned names" /></div>
            {hits !== null && (hits.length ? (
              <table className="small"><tbody>{hits.map((h) => (
                <tr key={h.os_id}><td><a href={h.url} target="_blank" rel="noreferrer">{h.name}</a></td><td className="muted">{SCHEMA_TEXT[h.schema] ?? h.schema}</td>
                  <td>{list(h.targets).map((t) => <Flag key={t} id={t} />)}{list(h.targets).join(", ")}</td>
                  <td className="muted">{list(h.authorities).map(authName).join(", ")}</td><td className="muted">{h.first_seen ?? ""}</td></tr>
              ))}</tbody></table>
            ) : <p className="small muted">No match.</p>)}
          </div>
          <div className="card">
            <h3>Newest listings</h3>
            <table className="small"><tbody>{d.recent.slice(0, 40).map((h) => (
              <tr key={h.os_id}><td style={{ whiteSpace: "nowrap" }}>{h.first_seen ?? ""}</td>
                <td><a href={`https://www.opensanctions.org/entities/${h.os_id}/`} target="_blank" rel="noreferrer">{h.name}</a></td>
                <td className="muted">{SCHEMA_TEXT[h.schema] ?? h.schema}</td><td>{list(h.targets).join(", ")}</td>
                <td className="muted">{list(h.authorities).map(authName).join(", ")}</td></tr>
            ))}</tbody></table>
            <p className="caption">Sanctioned ships are also marked red on the map&apos;s Ships now layer when they report their position.</p>
          </div>
        </>
      )}
      <p className="caption">For sanctions before 2024 by country pair and kind (trade, financial, travel), see the Global Sanctions Database on each country&apos;s
        Between countries card. <Link href="/settings#osint">Settings</Link></p>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><SanctionsPage /></Suspense>;
}
