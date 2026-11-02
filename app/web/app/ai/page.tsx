"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { AnswerText, statsLine } from "@/components/AskAI";
import { api, type AIAnswer, type AIUsage } from "@/lib/api";
import { keep } from "@/lib/ai";
import { saveText } from "@/lib/download";
import { useSettings } from "@/lib/settings";

// AI notes: every question asked of the local AI, with what went with it, the
// answer, its speed and tokens, a rating, tags and a note. A Statistics tab adds up
// questions, tokens and speed per model, and Brave searches against their limits.
export default function AIPage() {
  return (
    <Suspense fallback={<p className="muted">Loading…</p>}>
      <AINotes />
    </Suspense>
  );
}

function AINotes() {
  const params = useSearchParams();
  const router = useRouter();
  const tab = params.get("tab") === "stats" ? "stats" : "notes";
  const focus = params.get("answer");
  const s = useSettings();
  return (
    <div className="grid">
      <div>
        <h1 style={{ marginBottom: 4 }}>AI notes</h1>
        <p className="ink-2" style={{ marginTop: 0 }}>
          Questions asked of the local AI and its answers, kept on this computer. {s.ai_enabled ? <>Ask from any chart, panel or page with <b>Ask AI</b>, or select text and pick Ask AI.</>
            : <>Local AI is switched off; switch it on in <Link href="/settings#ai">Settings</Link>.</>}
        </p>
        <div className="seg">
          <button className={tab === "notes" ? "on" : ""} aria-pressed={tab === "notes"} onClick={() => router.replace("/ai")}>Questions and answers</button>
          <button className={tab === "stats" ? "on" : ""} aria-pressed={tab === "stats"} onClick={() => router.replace("/ai?tab=stats")}>Statistics</button>
        </div>
      </div>
      {tab === "stats" ? <Stats /> : <Notes focus={focus} />}
    </div>
  );
}

function Notes({ focus }: { focus: string | null }) {
  const [items, setItems] = useState<AIAnswer[] | null>(null);
  const [q, setQ] = useState("");
  const [model, setModel] = useState("");
  const [tag, setTag] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const t = setTimeout(() => api.aiAnswers({ q: q || undefined, model: model || undefined, limit: 500 })
      .then((xs) => { setItems(xs); setError(null); }).catch((e) => setError(String(e.message || e))), q ? 250 : 0);
    return () => clearTimeout(t);
  }, [q, model]);
  useEffect(() => {
    if (focus && items) document.getElementById(`a-${focus}`)?.scrollIntoView({ block: "start" });
  }, [focus, items]);
  const models = useMemo(() => [...new Set((items ?? []).map((a) => a.model))].sort(), [items]);
  const tags = useMemo(() => [...new Set((items ?? []).flatMap((a) => a.tags))].sort(), [items]);
  const shown = (items ?? []).filter((a) => !tag || a.tags.includes(tag));
  const replace = (a: AIAnswer) => setItems((xs) => (xs ?? []).map((x) => (x.id === a.id ? a : x)));

  return (
    <>
      <div className="chips-row small">
        <input type="search" placeholder="Search questions and answers" value={q} onChange={(e) => setQ(e.target.value)} style={{ minWidth: 260 }} />
        <select value={model} onChange={(e) => setModel(e.target.value)} aria-label="Model">
          <option value="">Every model</option>
          {models.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        {tags.length > 0 && (
          <select value={tag} onChange={(e) => setTag(e.target.value)} aria-label="Tag">
            <option value="">Every tag</option>
            {tags.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        )}
        <span className="spacer" />
        <button className="link" disabled={!shown.length} onClick={() => saveText(answersMarkdown(shown), "ai-notes.md", "text/markdown")}>
          Save as Markdown</button>
      </div>
      {error && <p className="error">{error}</p>}
      {items && !shown.length && <p className="muted">{items.length ? "Nothing matches." : "No questions asked yet."}</p>}
      {shown.map((a) => <AnswerCard key={a.id} a={a} focused={a.id === focus} onChange={replace}
        onDelete={() => setItems((xs) => (xs ?? []).filter((x) => x.id !== a.id))} />)}
    </>
  );
}

function AnswerCard({ a, focused, onChange, onDelete }: { a: AIAnswer; focused: boolean; onChange: (a: AIAnswer) => void; onDelete: () => void }) {
  const [note, setNote] = useState(a.note);
  const [tags, setTags] = useState(a.tags.join(", "));
  const [err, setErr] = useState<string | null>(null);
  const patch = (p: Parameters<typeof api.aiPatchAnswer>[1]) => api.aiPatchAnswer(a.id, p).then(onChange).catch((e) => setErr(String(e.message || e)));
  return (
    <article className={`card answer-card${focused ? " focused" : ""}`} id={`a-${a.id}`}>
      <div className="card-head">
        <h3>{a.question}</h3>
        <span className="small muted">{a.created_at.slice(0, 16).replace("T", " ")}</span>
      </div>
      <p className="small muted" style={{ margin: "0 0 6px" }}>
        {a.model} · about <Link href={a.page || "/"}>{a.title || a.page}</Link>
        {a.web?.results.length ? ` · searched the web (${a.web.results.length} results)` : ""}
        {a.group ? " · asked of two models side by side" : ""}
      </p>
      <AnswerText text={a.answer} results={a.web?.results ?? []} />
      {a.web && a.web.results.length > 0 && (
        <details className="small"><summary>Web results</summary>
          <ol>{a.web.results.map((r) => <li key={r.url}><a href={r.url} target="_blank" rel="noreferrer">{r.title}</a></li>)}</ol>
        </details>
      )}
      {a.context.length > 0 && (
        <details className="small"><summary>Sent with the question ({a.context.map((c) => c.label).join("; ")})</summary>
          {a.context.map((c, i) => <div key={i}><b>{c.label}</b><pre className="ask-sent">{c.text}</pre></div>)}
        </details>
      )}
      <div className="ask-meta small muted">
        <span>{statsLine(a)}</span>
        <button className={`link${a.rating === 1 ? " on" : ""}`} aria-pressed={a.rating === 1} title="Good answer"
          onClick={() => patch({ rating: a.rating === 1 ? 0 : 1 })}>👍</button>
        <button className={`link${a.rating === -1 ? " on" : ""}`} aria-pressed={a.rating === -1} title="Poor answer"
          onClick={() => patch({ rating: a.rating === -1 ? 0 : -1 })}>👎</button>
        <button className="link" onClick={() => keep({ kind: "answer", title: `${a.question.slice(0, 100)} (${a.model})`, text: a.answer, question: a.question,
          model: a.model, answer_id: a.id, entities: a.entity ? [a.entity] : [], indicator: a.indicator, page_url: a.page, page_title: a.title,
          sources: a.web?.results.map((r, i) => `[${i + 1}] ${r.url}`).join(" ") || undefined })}>Keep in Highlights</button>
        <button className="link" onClick={() => { if (confirm("Delete this question and answer?")) api.aiDeleteAnswer(a.id).then(onDelete).catch((e) => setErr(String(e.message || e))); }}>Delete</button>
      </div>
      <div className="note-row small">
        <label>Tags <input value={tags} placeholder="comma separated" onChange={(e) => setTags(e.target.value)}
          onBlur={() => tags !== a.tags.join(", ") && patch({ tags })} /></label>
        <label className="grow">Note <input value={note} onChange={(e) => setNote(e.target.value)} onBlur={() => note !== a.note && patch({ note })} /></label>
      </div>
      {err && <p className="error small">{err}</p>}
    </article>
  );
}

const clean = (t: string) => t.replace(/<think>[\s\S]*?(<\/think>|$)/g, "").trim();

function answersMarkdown(items: AIAnswer[]): string {
  const out = [`# AI notes`, "", `Saved ${new Date().toISOString().slice(0, 10)}, ${items.length} question${items.length === 1 ? "" : "s"}.`, ""];
  for (const a of items) {
    out.push(`## ${a.question}`, "", `*${a.model}, ${a.created_at.slice(0, 16).replace("T", " ")}, about ${a.title || a.page}*`, "", clean(a.answer), "");
    if (a.web?.results.length) out.push(...a.web.results.map((r, i) => `${i + 1}. [${r.title}](${r.url})`), "");
    if (a.tags.length) out.push(`Tags: ${a.tags.join(", ")}`, "");
    if (a.note) out.push(`**Note:** ${a.note}`, "");
  }
  return out.join("\n");
}

function Stats() {
  const [u, setU] = useState<AIUsage | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.aiStats().then(setU).catch((e) => setError(String(e.message || e))); }, []);
  if (error) return <p className="error">{error}</p>;
  if (!u) return <p className="muted">Loading…</p>;
  const n = (v: number | null, d = 0) => (v === null ? "–" : v.toLocaleString(undefined, { maximumFractionDigits: d }));
  const days = Object.entries(u.questions_by_day);
  const max = Math.max(1, ...days.map(([, v]) => v));
  const sd = Object.entries(u.search.by_day ?? {}).slice(-31);
  const smax = Math.max(1, ...sd.map(([, v]) => v));
  const total = u.models.reduce((s, m) => s + m.questions, 0);
  return (
    <>
      <section className="card">
        <h3>By model</h3>
        {!u.models.length ? <p className="muted">No questions asked yet.</p> : (
          <table className="data">
            <thead><tr><th>Model</th><th className="num">Questions</th><th className="num">Tokens sent</th><th className="num">Tokens answered</th>
              <th className="num">Typical speed (tokens a second)</th><th className="num">Typical wait for the first word (s)</th>
              <th className="num">👍</th><th className="num">👎</th><th className="num">With web search</th></tr></thead>
            <tbody>{u.models.map((m) => (
              <tr key={m.model}><td>{m.model}</td><td className="num">{n(m.questions)}</td><td className="num">{n(m.prompt_tokens)}</td>
                <td className="num">{n(m.answer_tokens)}</td><td className="num">{n(m.tokens_per_s, 1)}</td><td className="num">{n(m.first_token_s, 1)}</td>
                <td className="num">{n(m.thumbs_up)}</td><td className="num">{n(m.thumbs_down)}</td><td className="num">{n(m.with_web)}</td></tr>
            ))}</tbody>
          </table>
        )}
        <p className="caption">{total} question{total === 1 ? "" : "s"} in all. Speeds and waits are medians, as Ollama reports them.</p>
      </section>
      <div className="grid two">
        <section className="card">
          <h3>Questions a day (last 90 days)</h3>
          {days.length ? <Bars rows={days} max={max} /> : <p className="muted">None yet.</p>}
        </section>
        <section className="card">
          <h3>Web searches</h3>
          <p className="small" style={{ marginTop: 0 }}>
            {u.search.engine === "brave" ? "Brave Search" : u.search.engine === "searxng" ? "SearXNG (free, no limits counted)" : "Web search off"}:{" "}
            <b>{u.search.today}</b> today{u.search.daily_limit ? ` of ${u.search.daily_limit}` : ""}, <b>{u.search.month}</b> this month
            {u.search.monthly_limit ? ` of ${u.search.monthly_limit}` : ""}.
            {u.search.engine === "brave" && <> Brave&apos;s monthly credit covers {u.search.free_monthly.toLocaleString()}; past that, about
              ${u.search.price_per_1000} per 1,000. This month&apos;s estimate: <b>${u.search.estimated_cost_usd.toFixed(2)}</b>.</>}
            {" "}<Link href="/settings#ai">Change the limits</Link>.
          </p>
          {sd.length ? <Bars rows={sd} max={smax} /> : <p className="muted small">No searches yet.</p>}
        </section>
      </div>
    </>
  );
}

function Bars({ rows, max }: { rows: [string, number][]; max: number }) {
  return (
    <div className="day-bars" role="img" aria-label={rows.map(([d, v]) => `${d}: ${v}`).join(", ")}>
      {rows.map(([d, v]) => <div key={d} title={`${d}: ${v}`} style={{ height: `${Math.max(4, (100 * v) / max)}%` }} />)}
      <span className="small muted day-bars-from">{rows[0][0]}</span><span className="small muted day-bars-to">{rows[rows.length - 1][0]}</span>
    </div>
  );
}
