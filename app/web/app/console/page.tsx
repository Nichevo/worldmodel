"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type ConsoleResult, type ConsoleTables } from "@/lib/api";
import { logHistory } from "@/lib/history";
import { useSettings } from "@/lib/settings";

// The Data console: questions to the warehouse in SQL, answered as a table. Read-only and from this
// PC only (the API checks both); off until switched on in Settings. Saved queries live in the user
// folder; results download as CSV.
const EXAMPLES: [string, string][] = [
  ["Latest population, biggest first", `SELECT s.entity_id, e.name, year(s.period_start) AS year, s.value
FROM series s JOIN entities e USING (entity_id)
WHERE s.indicator_id = 'pop_total' AND s.source_id = 'un_wpp' AND s.status = 'E' AND e.type = 'country'
QUALIFY row_number() OVER (PARTITION BY s.entity_id ORDER BY s.period_start DESC) = 1
ORDER BY s.value DESC`],
  ["New Zealand's figures, latest year each", `SELECT s.indicator_id, i.name, s.source_id, year(s.period_start) AS year, s.value, i.unit
FROM series s JOIN indicators i USING (indicator_id)
WHERE s.entity_id = 'NZL' AND s.breakdown = '' AND s.status = 'E'
QUALIFY row_number() OVER (PARTITION BY s.indicator_id, s.source_id ORDER BY s.period_start DESC) = 1
ORDER BY i.name`],
  ["Sources and how many rows each", `SELECT source_id, count(*) AS rows, count(DISTINCT indicator_id) AS indicators, max(period_start) AS latest
FROM series GROUP BY 1 ORDER BY 2 DESC`],
];

function csv(r: ConsoleResult): string {
  const cell = (v: unknown) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [r.columns.map(cell).join(","), ...r.rows.map((row) => row.map(cell).join(","))].join("\n");
}

export default function ConsolePage() {
  const s = useSettings();
  const [tables, setTables] = useState<ConsoleTables | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sql, setSql] = useState(EXAMPLES[0][1]);
  const [limit, setLimit] = useState(1000);
  const [result, setResult] = useState<ConsoleResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [took, setTook] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [filter, setFilter] = useState("");
  useEffect(() => { logHistory({ kind: "page", title: "Data console", url: "/console", detail: "page" }); }, []);
  useEffect(() => {
    if (!s.data_console) return;
    api.consoleTables().then(setTables).catch((e) => setError(String(e.message || e)));
  }, [s.data_console]);

  if (!s.data_console) {
    return (
      <div className="grid"><h1>Data console</h1>
        <p className="ink-2">The Data console is switched off. It lets you ask the warehouse questions in SQL, read-only, from this PC only.
          {" "}<Link href="/settings#console">Turn it on in Settings</Link>.</p>
      </div>
    );
  }

  const run = () => {
    setBusy(true); setError(null);
    const t0 = performance.now();
    api.consoleQuery(sql, limit).then((r) => { setResult(r); setTook(performance.now() - t0); })
      .catch((e) => { setError(String(e.message || e).replace(/^\d+: /, "")); setResult(null); }).finally(() => setBusy(false));
  };
  const download = () => {
    if (!result) return;
    const url = URL.createObjectURL(new Blob([csv(result)], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = `${(name || "query").replace(/[^\w-]+/g, "_")}.csv`; a.click();
    URL.revokeObjectURL(url);
  };
  const save = () => api.consoleSave(name, sql).then((saved) => setTables((t) => (t ? { ...t, saved } : t)))
    .catch((e) => setError(String(e.message || e).replace(/^\d+: /, "")));
  const drop = (n: string) => api.consoleDrop(n).then((saved) => setTables((t) => (t ? { ...t, saved } : t)));
  const shown = (tables?.tables ?? []).filter((t) => !filter || t.table.includes(filter.toLowerCase())
    || t.columns.some((c) => c.name.includes(filter.toLowerCase())));

  return (
    <div className="grid">
      <div className="title-row"><h1>Data console</h1><span className="small muted">Read-only. SELECT, WITH or FROM; one query at a time; {tables?.max_rows ?? 5000} rows at most; stops after 20 seconds.</span></div>
      <div className="console-cols">
        <div className="card console-tables small">
          <h3>Saved</h3>
          {tables?.saved.length ? tables.saved.map((q) => (
            <div key={q.name} className="chips-row" style={{ margin: 0 }}>
              <button className="link small" onClick={() => { setSql(q.sql); setName(q.name); }}>{q.name}</button>
              <button className="link small muted" aria-label={`Delete ${q.name}`} title="Delete this saved query" onClick={() => drop(q.name)}>×</button>
            </div>)) : <p className="muted">None yet.</p>}
          <h3>Examples</h3>
          {EXAMPLES.map(([n, q]) => <div key={n}><button className="link small" onClick={() => { setSql(q); setName(""); }}>{n}</button></div>)}
          <h3>Tables</h3>
          <input type="search" placeholder="Find a table or column" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: "100%" }} />
          {shown.map((t) => (
            <details key={t.table}>
              <summary>{t.table}</summary>
              <button className="link small" onClick={() => setSql(`SELECT * FROM ${t.table} LIMIT 100`)}>Look at the first 100 rows</button>
              <div>{t.columns.map((c) => <div key={c.name}><code>{c.name}</code> <span className="muted">{c.type.toLowerCase()}</span></div>)}</div>
            </details>
          ))}
        </div>
        <div className="card">
          <textarea className="console-sql" value={sql} spellCheck={false} aria-label="SQL"
            onChange={(e) => setSql(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); run(); } }} />
          <div className="chips-row small">
            <button className="primary" disabled={busy} onClick={run} title="Ctrl+Enter">{busy ? "Running…" : "Run"}</button>
            <label>Rows{" "}
              <select value={limit} onChange={(e) => setLimit(+e.target.value)}>{[100, 1000, 5000].map((n) => <option key={n} value={n}>{n}</option>)}</select>
            </label>
            <span className="spacer" style={{ flex: 1 }} />
            <input placeholder="Name to save as" value={name} onChange={(e) => setName(e.target.value)} />
            <button disabled={!name.trim()} onClick={save}>Save query</button>
            <button disabled={!result?.rows.length} onClick={download}>Download CSV</button>
          </div>
          {error && <p className="error">{error}</p>}
          {result && <>
            <p className="small muted">{result.rows.length} {result.rows.length === 1 ? "row" : "rows"}{result.more ? ` (stopped at ${result.limit}; there are more)` : ""}
              {took != null ? `, ${(took / 1000).toFixed(2)} s` : ""}</p>
            <div className="console-result">
              <table className="summary-table small">
                <thead><tr>{result.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                <tbody>{result.rows.map((r, i) => <tr key={i}>{r.map((v, j) => (
                  <td key={j} className={typeof v === "number" ? "num" : ""}>{v == null ? <span className="muted">null</span> : String(v)}</td>))}</tr>)}</tbody>
              </table>
            </div>
          </>}
        </div>
      </div>
    </div>
  );
}
