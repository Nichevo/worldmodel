"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, GRADE_TEXT, type Grade, type QualityChange, type QualitySummary } from "@/lib/api";
import { SOURCE_SHORT } from "@/lib/format";

const GRADES: Grade[] = ["A", "B", "C", "D"];
const FILL: Record<Grade, string> = { A: "color-mix(in srgb, #3f9b5a 45%, transparent)", B: "color-mix(in srgb, var(--series-1) 35%, transparent)",
  C: "var(--border)", D: "repeating-linear-gradient(90deg, var(--border) 0 3px, transparent 3px 6px)" };

// The Quality tab on Data status: how many indicators sit at each grade, by topic and by
// source, and what changed since the build before.
export default function QualityTab() {
  const [s, setS] = useState<QualitySummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [by, setBy] = useState<"domain" | "source">("domain");
  useEffect(() => { api.qualitySummary().then(setS).catch((e) => setError(String(e.message || e))); }, []);
  if (error) return <p className="error">{error}</p>;
  if (!s) return <p className="muted">Working out the grades…</p>;
  const total = GRADES.reduce((n, g) => n + s.totals[g], 0);
  const table = by === "domain" ? s.by_domain : s.by_source;
  const keys = Object.keys(table).sort((a, b) => (table[b].A + table[b].B) - (table[a].A + table[a].B) || a.localeCompare(b));
  const ch = s.changes;
  const list = (title: string, xs: QualityChange[], what: (c: QualityChange) => string) => xs.length > 0 && (
    <div>
      <h4>{title} ({xs.length})</h4>
      <ul className="small plain">
        {xs.slice(0, 40).map((c) => <li key={c.indicator_id}><Link href={`/indicator/${c.indicator_id}`}>{c.name}</Link> <span className="muted">{what(c)}</span></li>)}
        {xs.length > 40 && <li className="muted">and {xs.length - 40} more</li>}
      </ul>
    </div>
  );
  return (
    <>
      <div className="card">
        <h2>Indicators by grade</h2>
        <div className="tiles">
          {GRADES.map((g) => (
            <div key={g} className="tile">
              <div className="label"><span className={`grade grade-${g}`}>{g}</span> {GRADE_TEXT[g]}</div>
              <div className="value">{s.totals[g].toLocaleString()}</div>
              <div className="small muted">{total ? Math.round((100 * s.totals[g]) / total) : 0}%</div>
            </div>
          ))}
        </div>
        <p className="caption">Grades are worked out at each refresh from six scores (see any indicator&apos;s Quality card, or the{" "}
          <Link href="/indicators">Indicators</Link> page, where you can sort by them and set a grade yourself). The drop-downs show B and better
          unless you change Show at the top of a list or in <Link href="/settings#quality">Settings</Link>.</p>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>What changed{s.since ? ` since build ${s.since}` : ""}</h2>
        </div>
        {!ch ? <p className="small muted">Nothing to compare with yet: changes show after the next refresh.</p> : (
          <div className="grid two">
            {list("Starred indicators whose grade fell", ch.starred_fell, (c) => `${c.from} to ${c.to}`)}
            {list("Lost a grade", ch.lost, (c) => `${c.from} to ${c.to}`)}
            {list("Gained a grade", ch.gained, (c) => `${c.from} to ${c.to}`)}
            {list("Went out of date", ch.stale, (c) => c.note ?? "")}
            {list("Newly flagged by the checks", ch.flagged, (c) => c.note ?? "")}
            {!ch.lost.length && !ch.gained.length && !ch.stale.length && !ch.flagged.length && <p className="small muted">No grade changed.</p>}
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <h2>By {by === "domain" ? "topic" : "source"}</h2>
          <div className="seg small" role="group" aria-label="Group by">
            <button className={by === "domain" ? "on" : ""} onClick={() => setBy("domain")}>Topic</button>
            <button className={by === "source" ? "on" : ""} onClick={() => setBy("source")}>Source</button>
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="small">
            <thead><tr><th>{by === "domain" ? "Topic" : "Source"}</th>{GRADES.map((g) => <th key={g} className="num">{g}</th>)}<th style={{ width: "40%" }} /></tr></thead>
            <tbody>
              {keys.map((k) => {
                const row = table[k], n = GRADES.reduce((a, g) => a + row[g], 0) || 1;
                return (
                  <tr key={k}>
                    <td>{by === "source" ? (SOURCE_SHORT[k] ?? k) : k[0].toUpperCase() + k.slice(1)}</td>
                    {GRADES.map((g) => <td key={g} className="num">{row[g] || ""}</td>)}
                    <td><div style={{ display: "flex", height: 10, borderRadius: 2, overflow: "hidden" }}>
                      {GRADES.map((g) => <div key={g} style={{ width: `${(100 * row[g]) / n}%`, background: FILL[g] }} />)}
                    </div></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {s.starred.length > 0 && (
        <div className="card">
          <h2>Your starred indicators ({s.starred.length})</h2>
          <p className="small">{s.starred.map((x, n) => <span key={x.indicator_id}>{n ? " · " : ""}<Link href={`/indicator/${x.indicator_id}`}>{x.name}</Link>{x.grade ? ` (${x.grade})` : ""}</span>)}</p>
        </div>
      )}
    </>
  );
}
