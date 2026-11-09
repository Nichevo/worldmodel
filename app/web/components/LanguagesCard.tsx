"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type EntityLanguages } from "@/lib/api";

// A country's languages: who speaks what (first and second language together) and what is
// official, how many languages are spoken there and which are endangered.
const STATUS_ORDER = ["nearly extinct", "moribund", "shifting", "threatened", "extinct"];

export default function LanguagesCard({ entity, name }: { entity: string; name: string }) {
  const [d, setD] = useState<EntityLanguages | null>(null);
  const [all, setAll] = useState(false);
  useEffect(() => {
    let live = true;
    api.entityLanguages(entity).then((x) => live && setD(x)).catch(() => live && setD(null));
    return () => { live = false; };
  }, [entity]);
  if (!d || (!d.languages.length && !d.endangered.length && !d.factbook)) return null;
  const shown = all ? d.languages : d.languages.slice(0, 8);
  const max = Math.max(1, ...d.languages.map((l) => l.share ?? 0));
  const endangered = [...d.endangered].sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status));
  return (
    <div className="card" id="languages">
      <div className="card-head">
        <h3>Languages</h3>
        <Link href="/languages" className="small">Languages of the world</Link>
      </div>
      {(d.counts.lang_count || d.counts.lang_official_count) && (
        <p className="small">
          {d.counts.lang_official_count ? <><b>{d.counts.lang_official_count}</b> official {d.counts.lang_official_count === 1 ? "language" : "languages"}. </> : null}
          {d.counts.lang_count ? <><b>{d.counts.lang_count}</b> languages spoken, </> : null}
          {d.counts.lang_endangered ? <><b>{d.counts.lang_endangered}</b> endangered{d.counts.lang_extinct ? <>, {d.counts.lang_extinct} no longer spoken</> : null}.</> : null}
        </p>
      )}
      {shown.length > 0 && (
        <table className="small lang-table">
          <thead><tr><th>Language</th><th>People who speak it</th><th>Status</th></tr></thead>
          <tbody>
            {shown.map((l) => (
              <tr key={l.code}>
                <td><Link href={`/languages?lang=${l.code}`}>{l.name}</Link></td>
                <td>{l.share !== null ? <span className="bar-cell"><i style={{ width: `${(l.share / max) * 100}%` }} />{l.share < 1 ? l.share.toFixed(2) : l.share.toFixed(l.share < 10 ? 1 : 0)}%</span> : "–"}</td>
                <td className="muted">{l.official ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {d.languages.length > 8 && <button className="link small" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${d.languages.length}`}</button>}
      {endangered.length > 0 && (
        <details className="small">
          <summary>Endangered and lost languages ({endangered.length})</summary>
          <p>{endangered.map((x, i) => <span key={x.name + i}>{i ? ", " : ""}{x.name} <span className="muted">({x.status}{x.family ? `, ${x.family}` : ""})</span></span>)}</p>
        </details>
      )}
      {d.factbook && <p className="small"><span className="muted">CIA Factbook {d.factbook.edition}:</span> {d.factbook.content}</p>}
      <p className="caption">Shares from Unicode CLDR (estimates, first and second language together, so they add to more than 100%). Counts and endangerment from Glottolog. The Factbook line is as {name}&apos;s edition gives it.</p>
    </div>
  );
}
