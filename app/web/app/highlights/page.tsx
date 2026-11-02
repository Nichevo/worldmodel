"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AnswerText } from "@/components/AskAI";
import { api, type Highlight, type HighlightKind } from "@/lib/api";
import { openAsk } from "@/lib/ai";
import { useSettings } from "@/lib/settings";

const KIND_LABEL: Record<HighlightKind, string> = { text: "Text", chart: "Charts and maps", table: "Tables", answer: "AI answers" };
const KIND_ONE: Record<HighlightKind, string> = { text: "Text", chart: "Chart", table: "Table", answer: "AI answer" };

// Highlights: text, charts and maps (with their settings, so they reopen live),
// tables and AI answers kept from anywhere, with tags and notes, saved as Markdown.
export default function HighlightsPage() {
  const [items, setItems] = useState<Highlight[] | null>(null);
  const [tags, setTags] = useState<{ tag: string; count: number }[]>([]);
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [tag, setTag] = useState("");
  const [error, setError] = useState<string | null>(null);
  const filters = { q: q || undefined, kind: kind || undefined, tag: tag || undefined };
  const load = () => api.highlights(filters).then((r) => { setItems(r.items); setTags(r.tags); setError(null); })
    .catch((e) => setError(String(e.message || e)));
  useEffect(() => {
    const t = setTimeout(load, q ? 250 : 0);
    return () => clearTimeout(t);
  }, [q, kind, tag]); // eslint-disable-line react-hooks/exhaustive-deps
  const saveMarkdown = () => {
    const q = new URLSearchParams({ ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) as Record<string, string>, base: location.origin });
    location.href = `/api/v1/highlights-export.md?${q}`;
  };

  return (
    <div className="grid">
      <div>
        <h1 style={{ marginBottom: 4 }}>Highlights</h1>
        <p className="ink-2" style={{ marginTop: 0 }}>
          What you kept: select text anywhere and pick <b>Save highlight</b>, or press <b>Keep</b> on a chart, a panel&apos;s ⤓ menu or an AI answer.
          Charts and maps keep their settings and reopen live; each also keeps a picture of how it looked.
        </p>
      </div>
      <div className="chips-row small">
        <input type="search" placeholder="Search highlights" value={q} onChange={(e) => setQ(e.target.value)} style={{ minWidth: 240 }} />
        <div className="seg">
          <button className={kind === "" ? "on" : ""} aria-pressed={kind === ""} onClick={() => setKind("")}>All</button>
          {(Object.keys(KIND_LABEL) as HighlightKind[]).map((k) => (
            <button key={k} className={kind === k ? "on" : ""} aria-pressed={kind === k} onClick={() => setKind(k)}>{KIND_LABEL[k]}</button>
          ))}
        </div>
        {tags.length > 0 && (
          <select value={tag} onChange={(e) => setTag(e.target.value)} aria-label="Tag">
            <option value="">Every tag</option>
            {tags.map((t) => <option key={t.tag} value={t.tag}>{t.tag} ({t.count})</option>)}
          </select>
        )}
        <span className="spacer" />
        <button className="link" onClick={saveMarkdown} disabled={!items?.length}>Save as Markdown</button>
      </div>
      {error && <p className="error">{error}</p>}
      {items && !items.length && <p className="muted">{q || kind || tag ? "Nothing matches." : "Nothing kept yet."}</p>}
      {items?.map((h) => <HighlightCard key={h.id} h={h} onChange={(n) => setItems((xs) => (xs ?? []).map((x) => (x.id === n.id ? n : x)))}
        onDelete={() => { setItems((xs) => (xs ?? []).filter((x) => x.id !== h.id)); }} />)}
    </div>
  );
}

function HighlightCard({ h, onChange, onDelete }: { h: Highlight; onChange: (h: Highlight) => void; onDelete: () => void }) {
  const s = useSettings();
  const [note, setNote] = useState(h.note);
  const [tags, setTags] = useState(h.tags.join(", "));
  const [title, setTitle] = useState(h.title);
  const [err, setErr] = useState<string | null>(null);
  const [showTable, setShowTable] = useState(false);
  const patch = (p: Parameters<typeof api.patchHighlight>[1]) => api.patchHighlight(h.id, p).then(onChange).catch((e) => setErr(String(e.message || e)));
  const ask = () => openAsk({
    title: h.title, entity: h.entities[0], indicator: h.indicator ?? undefined,
    parts: [
      ...(h.text ? [{ key: "highlight", kind: "highlight" as const, label: h.kind === "answer" ? "An earlier AI answer" : "Kept text", text: h.text }] : []),
      ...(h.table ? [{ key: "data", kind: "data" as const, label: `Kept table${h.table.unit ? ` (${h.table.unit})` : ""}`,
        text: [h.table.columns.join(","), ...h.table.rows.map((r) => r.map((v) => (v === null ? "" : String(v))).join(","))].join("\n") }] : []),
      ...(h.note ? [{ key: "notes", kind: "notes" as const, label: "Your note", text: h.note }] : []),
    ],
  });
  return (
    <article className="card highlight-card">
      <div className="card-head">
        <input className="title-input" value={title} aria-label="Title" onChange={(e) => setTitle(e.target.value)}
          onBlur={() => title !== h.title && patch({ title })} />
        <span className="small muted">{KIND_ONE[h.kind]} · {h.created_at.slice(0, 16).replace("T", " ")}</span>
      </div>
      {h.picture && <img className="hl-picture" src={`/api/v1/highlights/${h.id}/picture`} alt={h.title} loading="lazy" />}
      {h.kind === "answer" && h.question && <p className="ask-q">{h.question}</p>}
      {h.kind === "answer" ? <AnswerText text={h.text} results={[]} /> : h.text && <blockquote className="hl-text">{h.text}</blockquote>}
      {h.table && h.table.columns.length > 0 && (
        <>
          <button className="link small" onClick={() => setShowTable(!showTable)}>{showTable ? "Hide table" : `Table (${h.table.rows.length} rows)`}</button>
          {showTable && (
            <div className="hl-table">
              <table>
                <thead><tr>{h.table.columns.map((c, i) => <th key={i}>{c}</th>)}</tr></thead>
                <tbody>{h.table.rows.slice(0, 300).map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j} className={typeof v === "number" ? "num" : ""}>{v ?? ""}</td>)}</tr>)}</tbody>
              </table>
            </div>
          )}
        </>
      )}
      <p className="small muted" style={{ margin: "6px 0" }}>
        {h.query && <><Link href={`/?${h.query}`}>Open the chart live</Link> · </>}
        {h.answer_id && <><Link href={`/ai?answer=${h.answer_id}`}>In AI notes</Link> · </>}
        {h.page_url && <>From <Link href={h.page_url}>{h.page_title || h.page_url}</Link></>}
        {h.model ? ` · ${h.model}` : ""}
        {h.sources ? ` · Sources: ${h.sources}` : ""}
      </p>
      <div className="note-row small">
        <label>Tags <input value={tags} placeholder="comma separated" onChange={(e) => setTags(e.target.value)}
          onBlur={() => tags !== h.tags.join(", ") && patch({ tags })} /></label>
        <label className="grow">Note <input value={note} onChange={(e) => setNote(e.target.value)} onBlur={() => note !== h.note && patch({ note })} /></label>
        {s.ai_enabled && <button className="link" onClick={ask}>Ask AI</button>}
        <button className="link" onClick={() => { if (confirm("Delete this highlight?")) api.deleteHighlight(h.id).then(onDelete).catch((e) => setErr(String(e.message || e))); }}>Delete</button>
      </div>
      {err && <p className="error small">{err}</p>}
    </article>
  );
}
