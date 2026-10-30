"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type TextField, type Texts } from "@/lib/api";

// The CIA World Factbook entry for a country: any edition from 1990 to the final
// one (2025), by section, with each field's text across all editions on request.
export default function FactbookCard({ entity }: { entity: string }) {
  const [edition, setEdition] = useState<number | null>(null);
  const [data, setData] = useState<Texts | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    setEdition(null);
    setQ("");
  }, [entity]);
  useEffect(() => {
    api.texts(entity, "cia_factbook", edition).then(setData).catch(() => setData(null));
  }, [entity, edition]);

  const sections = useMemo(() => {
    if (!data) return [];
    const needle = q.trim().toLowerCase();
    if (!needle) return data.sections;
    return data.sections
      .map((s) => ({ ...s, fields: s.fields.filter((f) => `${f.field} ${f.content}`.toLowerCase().includes(needle)) }))
      .filter((s) => s.fields.length > 0);
  }, [data, q]);

  if (!data || data.editions.length === 0) return null;
  const editions = data.editions.filter((e): e is number => e !== null);
  const latest = editions[0];

  return (
    <details className="card factbook">
      <summary>
        <b>CIA World Factbook</b>{" "}
        <span className="small ink-2">({editions.length} edition{editions.length > 1 ? "s" : ""}, {editions[editions.length - 1]} to {latest})</span>
      </summary>
      <div className="controls" style={{ marginTop: 8 }}>
        <label className="small">
          Edition{" "}
          <select value={data.edition ?? ""} onChange={(e) => setEdition(Number(e.target.value))}>
            {editions.map((e) => <option key={e} value={e}>{e}{e === 2025 ? " (final)" : ""}</option>)}
          </select>
        </label>
        <input type="search" placeholder="Find a field…" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="spacer" />
        <span className="small ink-2">
          {sections.reduce((n, s) => n + s.fields.length, 0)} fields
        </span>
      </div>
      {sections.map((s, i) => (
        <details key={`${data.edition}-${s.section}`} open={i === 0 || q.trim() !== ""} className="fb-section">
          <summary>{s.section} <span className="small muted">({s.fields.length})</span></summary>
          {s.fields.map((f, j) => <Field key={`${f.field_key}-${j}`} entity={entity} field={f} />)}
        </details>
      ))}
      <p className="caption">
        The CIA has stopped publishing the Factbook and 2025 is its final edition, so this part never changes.
        Editions 1990 to 2025 from the CIA World Factbooks Archive (public domain). Figures in the text are each
        edition&apos;s own estimates; the numbers it holds (population, GDP, reserves and more) are also under source
        &quot;Factbook&quot; in charts and maps.
      </p>
    </details>
  );
}

function Field({ entity, field }: { entity: string; field: TextField }) {
  const [history, setHistory] = useState<{ from: number; to: number; content: string }[] | null>(null);
  const [open, setOpen] = useState(false);

  const toggle = () => {
    setOpen((o) => !o);
    if (history) return;
    api.textHistory(entity, field.field_key).then((rows) => {
      // Runs of editions with the same text shown once.
      const runs: { from: number; to: number; content: string }[] = [];
      for (const r of rows) {
        const last = runs[runs.length - 1];
        if (last && last.content === r.content) last.to = r.edition;
        else runs.push({ from: r.edition, to: r.edition, content: r.content });
      }
      setHistory(runs);
    }).catch(() => setHistory([]));
  };

  return (
    <div className="fb-field">
      <div className="fb-name">
        {field.field}
        <button className="link small" onClick={toggle} title="This field in every edition">{open ? "hide history" : "history"}</button>
      </div>
      <Content text={field.content} />
      {open && (
        <div className="fb-history">
          {!history ? <span className="muted small">Loading…</span> : history.map((h) => (
            <div key={h.from}>
              <div className="small ink-2"><b>{h.from === h.to ? h.from : `${h.from} to ${h.to}`}</b></div>
              <Content text={h.content} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Content({ text }: { text: string }) {
  const parts = text.split(" | ");
  return <div className="fb-content">{parts.map((p, i) => <div key={i}>{p}</div>)}</div>;
}
