"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, askStream, type AIAnswer, type AIStatus, type WebResult, type WebSearch } from "@/lib/api";
import { keep, onAsk, type AskPart, type AskRequest } from "@/lib/ai";
import { useSettings } from "@/lib/settings";

// The Ask AI box: a panel down the right of the page, opened by any Ask AI button or
// by the highlight menu. It lists what will go with the question, each part with a
// tick box and editable; asks one model, or two side by side (Settings: Local AI);
// with Search the web ticked, one search (Brave or SearXNG) feeds both. Answers
// stream in and are kept on the AI notes page.
type Run = { model: string; text: string; thinking: boolean; answer: AIAnswer | null; error: string | null };
type Turn = { id: string; question: string; web: WebSearch | null; webError: string | null; searching: boolean; runs: Run[] };

export default function AskAI() {
  const s = useSettings();
  const [req, setReq] = useState<AskRequest | null>(null);
  const [parts, setParts] = useState<(AskPart & { on: boolean; open: boolean })[]>([]);
  const [question, setQuestion] = useState("");
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [model, setModel] = useState("");
  const [second, setSecond] = useState("");
  const [search, setSearch] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => onAsk((r) => {
    const ticked = s.ai_context_default.split(",");
    setReq(r);
    setParts(r.parts.map((p) => ({ ...p, on: p.kind === "page" || p.kind === "notes" || ticked.includes(p.kind), open: false })));
    setQuestion(r.question ?? "");
    setTurns([]);
    api.aiStatus().then((st) => {
      setStatus(st);
      setModel((m) => m || st.default_model || "");
      setSecond(s.ai_model_compare && st.models.some((x) => x.name === s.ai_model_compare) ? s.ai_model_compare : "");
    }).catch(() => setStatus(null));
    setTimeout(() => box.current?.focus(), 50);
  }), [s.ai_context_default, s.ai_model_compare]);

  useEffect(() => {
    if (!req) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) setReq(null); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [req, busy]);

  if (!req || !s.ai_enabled) return null;
  const models = status?.models.map((m) => m.name) ?? [];
  const usage = status?.search.usage;
  const searchNote = !status ? "" : !status.search.ready ? status.search.why ?? "Web search is not available."
    : status.search.engine === "brave" && usage
      ? `Brave: ${usage.today}${usage.daily_limit ? ` of ${usage.daily_limit}` : ""} today, ${usage.month} this month${usage.estimated_cost_usd ? ` (about $${usage.estimated_cost_usd.toFixed(2)} past the credit)` : ""}`
      : `SearXNG at ${s.searxng_url}`;

  const update = (id: string, f: (t: Turn) => Turn) => setTurns((ts) => ts.map((t) => (t.id === id ? f(t) : t)));
  const updateRun = (id: string, i: number, f: (r: Run) => Run) => update(id, (t) => ({ ...t, runs: t.runs.map((r, j) => (j === i ? f(r) : r)) }));

  const ask = async () => {
    const q = question.trim();
    if (!q || busy || !model) return;
    const id = Math.random().toString(36).slice(2, 10);
    const ms = [model, ...(second && second !== model ? [second] : [])];
    setTurns((ts) => [...ts, { id, question: q, web: null, webError: null, searching: search, runs: ms.map((m) => ({ model: m, text: "", thinking: false, answer: null, error: null })) }]);
    setQuestion("");
    setBusy(true);
    const ctl = new AbortController();
    abort.current = ctl;
    let web: WebSearch | null = null;
    if (search) {
      try {
        web = await api.aiSearch(q, model);
        update(id, (t) => ({ ...t, web, searching: false }));
        if (web.usage && status) setStatus({ ...status, search: { ...status.search, usage: web.usage } });
      } catch (e) {
        update(id, (t) => ({ ...t, webError: String((e as Error).message || e).replace(/^\d+: /, ""), searching: false }));
      }
    }
    // Earlier questions and answers in this box go along, so a follow-up makes sense.
    const before = turns.flatMap((t) => t.runs[0]?.answer ? [`Q: ${t.question}\nA: ${t.runs[0].answer.answer}`] : []);
    const context = [...parts.filter((p) => p.on).map((p) => ({ label: p.label, text: p.text })),
      ...(before.length ? [{ label: "Earlier in this conversation", text: before.join("\n\n") }] : [])];
    await Promise.all(ms.map((m, i) => askStream({
      question: q, model: m, context, web, title: req.title, page: req.page, entity: req.entity, indicator: req.indicator,
      group: ms.length > 1 ? id : undefined,
    }, (ev) => {
      if (ev.type === "thinking") updateRun(id, i, (r) => ({ ...r, thinking: true }));
      else if (ev.type === "token") updateRun(id, i, (r) => ({ ...r, text: r.text + ev.text }));
      else if (ev.type === "done") updateRun(id, i, (r) => ({ ...r, answer: ev.answer, text: ev.answer.answer, thinking: false }));
      else if (ev.type === "error") updateRun(id, i, (r) => ({ ...r, error: ev.message, thinking: false }));
    }, ctl.signal).catch((e) => {
      if ((e as Error).name !== "AbortError") updateRun(id, i, (r) => ({ ...r, error: String((e as Error).message || e) }));
    })));
    setBusy(false);
    abort.current = null;
  };

  return (
    <aside className="ask-ai" aria-label="Ask AI">
      <div className="ask-head">
        <b>Ask AI</b>
        <span className="muted small ask-about">about {req.title}</span>
        <Link href="/ai" className="small">AI notes</Link>
        <button className="x" aria-label="Close" onClick={() => { abort.current?.abort(); setReq(null); }}>×</button>
      </div>
      {status && !status.ollama.ok && <p className="error small">{status.ollama.error}</p>}
      {status?.ollama.ok && !models.length && <p className="error small">No models installed in Ollama. Install one, for example: <code>ollama pull qwen3:32b</code></p>}

      <details className="ask-context" open={turns.length === 0}>
        <summary className="small">Sent with the question ({parts.filter((p) => p.on).length} of {parts.length})</summary>
        {parts.map((p, i) => (
          <div key={p.key} className="ask-part">
            <label className="small">
              <input type="checkbox" checked={p.on} onChange={(e) => setParts(parts.map((x, j) => (j === i ? { ...x, on: e.target.checked } : x)))} />
              {" "}{p.label} <span className="muted">({p.text.length.toLocaleString()} characters)</span>
            </label>
            <button className="link small" onClick={() => setParts(parts.map((x, j) => (j === i ? { ...x, open: !x.open } : x)))}>{p.open ? "Hide" : "Edit"}</button>
            {p.open && <textarea className="ask-part-text" value={p.text} rows={6}
              onChange={(e) => setParts(parts.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} />}
          </div>
        ))}
      </details>

      <div className="ask-turns">
        {turns.map((t) => (
          <div key={t.id} className="ask-turn">
            <p className="ask-q">{t.question}</p>
            {t.searching && <p className="muted small">Searching the web…</p>}
            {t.webError && <p className="error small">Web search: {t.webError}</p>}
            {t.web && <WebList web={t.web} />}
            <div className={t.runs.length > 1 ? "ask-runs two" : "ask-runs"}>
              {t.runs.map((r, i) => <RunView key={i} run={r} web={t.web} question={t.question} title={req.title} entity={req.entity} indicator={req.indicator} />)}
            </div>
          </div>
        ))}
      </div>

      <div className="ask-form">
        <textarea ref={box} value={question} rows={3} placeholder="Your question (Ctrl+Enter to ask)"
          onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) ask(); }} />
        <div className="ask-controls small">
          <select value={model} onChange={(e) => setModel(e.target.value)} aria-label="Model">
            {!models.length && <option value="">No models</option>}
            {models.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <select value={second} onChange={(e) => setSecond(e.target.value)} aria-label="Second model, side by side">
            <option value="">No second model</option>
            {models.filter((m) => m !== model).map((m) => <option key={m} value={m}>Also {m}</option>)}
          </select>
          <label title={searchNote}>
            <input type="checkbox" checked={search} disabled={!status?.search.ready} onChange={(e) => setSearch(e.target.checked)} />
            {" "}Search the web
          </label>
          <button className="primary" onClick={ask} disabled={busy || !question.trim() || !model}>{busy ? "Answering…" : "Ask"}</button>
          {busy && <button className="link small" onClick={() => abort.current?.abort()}>Stop</button>}
        </div>
        {searchNote && <p className="muted small" style={{ margin: "4px 0 0" }}>{searchNote}</p>}
      </div>
    </aside>
  );
}

function WebList({ web }: { web: WebSearch }) {
  return (
    <details className="ask-web small">
      <summary>Searched for “{web.query}”: {web.results.length} result{web.results.length === 1 ? "" : "s"}</summary>
      <ol>{web.results.map((r) => <li key={r.url}><a href={r.url} target="_blank" rel="noreferrer">{r.title}</a> <span className="muted">{host(r.url)}</span></li>)}</ol>
    </details>
  );
}

function host(url: string) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; }
}

function RunView({ run, web, question, title, entity, indicator }: { run: Run; web: WebSearch | null; question: string; title: string; entity?: string; indicator?: string }) {
  const [rating, setRating] = useState<-1 | 0 | 1>(0);
  const [kept, setKept] = useState(false);
  const a = run.answer;
  const rate = (v: -1 | 1) => {
    if (!a) return;
    const next = rating === v ? 0 : v;
    setRating(next);
    api.aiPatchAnswer(a.id, { rating: next }).catch(() => {});
  };
  return (
    <div className="ask-run">
      <div className="small muted">{run.model}</div>
      {run.thinking && !visible(run.text) && <p className="muted small">Thinking…</p>}
      {!run.text && !run.thinking && !run.error && <p className="muted small">Waiting for the model…</p>}
      <AnswerText text={run.text} results={web?.results ?? []} />
      {run.error && <p className="error small">{run.error}</p>}
      {a && (
        <div className="ask-meta small muted">
          <span>{statsLine(a)}</span>
          <button className={`link${rating === 1 ? " on" : ""}`} aria-pressed={rating === 1} title="Good answer" onClick={() => rate(1)}>👍</button>
          <button className={`link${rating === -1 ? " on" : ""}`} aria-pressed={rating === -1} title="Poor answer" onClick={() => rate(-1)}>👎</button>
          <button className="link" disabled={kept} onClick={async () => setKept(await keep({
            kind: "answer", title: `${question.slice(0, 100)} (${a.model})`, text: a.answer, question, model: a.model, answer_id: a.id,
            entities: entity ? [entity] : [], indicator, page_title: title,
            sources: web?.results.map((r, i) => `[${i + 1}] ${r.url}`).join(" ") || undefined,
          }))}>{kept ? "Kept" : "Keep"}</button>
        </div>
      )}
    </div>
  );
}

export function statsLine(a: AIAnswer): string {
  const st = a.stats;
  return [st.answer_tokens != null ? `${st.answer_tokens} tokens` : null, st.tokens_per_s != null ? `${st.tokens_per_s} a second` : null,
    st.first_token_s != null ? `first word ${st.first_token_s} s` : null, st.load_s ? `model load ${st.load_s} s` : null]
    .filter(Boolean).join(" · ");
}

const visible = (text: string) => text.replace(/<think>[\s\S]*?(<\/think>|$)/g, "").trim();

// An answer as paragraphs and lists, with **bold** and [n] links to the web results.
export function AnswerText({ text, results }: { text: string; results: WebResult[] }) {
  const clean = visible(text);
  if (!clean) return null;
  const blocks = clean.split(/\n{2,}/);
  return (
    <div className="answer">
      {blocks.map((b, i) => {
        const lines = b.split("\n");
        if (lines.every((l) => /^\s*([-*•]|\d+[.)])\s+/.test(l))) {
          const ordered = /^\s*\d/.test(lines[0]);
          const items = lines.map((l, j) => <li key={j}>{inline(l.replace(/^\s*([-*•]|\d+[.)])\s+/, ""), results)}</li>);
          return ordered ? <ol key={i}>{items}</ol> : <ul key={i}>{items}</ul>;
        }
        if (/^#{1,4}\s/.test(b)) return <p key={i}><b>{inline(b.replace(/^#{1,4}\s+/, ""), results)}</b></p>;
        return <p key={i}>{lines.map((l, j) => <span key={j}>{j > 0 && <br />}{inline(l, results)}</span>)}</p>;
      })}
    </div>
  );
}

function inline(s: string, results: WebResult[]): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = /\*\*([^*]+)\*\*|\[(\d{1,2})\]/g;
  let last = 0, m: RegExpExecArray | null, k = 0;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index));
    if (m[1]) out.push(<b key={k++}>{m[1]}</b>);
    else {
      const r = results[+m[2] - 1];
      out.push(r ? <a key={k++} href={r.url} target="_blank" rel="noreferrer" title={r.title}>[{m[2]}]</a> : `[${m[2]}]`);
    }
    last = m.index + m[0].length;
  }
  if (last < s.length) out.push(s.slice(last));
  return out;
}
