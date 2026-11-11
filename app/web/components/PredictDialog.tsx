"use client";

import { useState } from "react";
import { toast } from "@/lib/ai";
import { CATEGORY_TEXT, pred, type Prediction } from "@/lib/predictions";
import { useSettings } from "@/lib/settings";

// Add or edit a prediction: yours, an expert's, the app's or a crowd site's. Opened from the
// Predictions page, a chart's Predict button, a forecast, or a crowd question. "Paste a link"
// asks the local AI to draft an expert's call from an article, for you to check before saving.
export default function PredictDialog({ initial, onClose, onSaved, title = "Add a prediction" }: {
  initial?: Partial<Prediction>; onClose: () => void; onSaved?: (p: Prediction) => void; title?: string;
}) {
  return (
    <div className="find-big-back" onClick={onClose}>
      <div className="find-big card" role="dialog" aria-modal="true" aria-label={title} style={{ maxWidth: 820 }} onClick={(e) => e.stopPropagation()}>
        <div className="row"><h2 style={{ fontSize: "1.15rem", margin: 0 }}>{title}</h2><span className="spacer" />
          <button onClick={onClose}>Close</button></div>
        <PredictForm initial={initial} onSaved={(p) => { onSaved?.(p); onClose(); }} />
      </div>
    </div>
  );
}

const inYear = (n: number) => { const d = new Date(); d.setFullYear(d.getFullYear() + n); return d.toISOString().slice(0, 10); };

export function PredictForm({ initial, onSaved }: { initial?: Partial<Prediction>; onSaved: (p: Prediction) => void }) {
  const s = useSettings();
  const [p, setP] = useState<Partial<Prediction>>({ kind: "binary", who_kind: "you", due: inYear(1), ...initial });
  const [error, setError] = useState<string | null>(null);
  const [link, setLink] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof Prediction, v: unknown) => setP((x) => ({ ...x, [k]: v === "" ? null : v }));
  const num = (k: keyof Prediction) => (e: React.ChangeEvent<HTMLInputElement>) => set(k, e.target.value === "" ? null : Number(e.target.value));
  const draft = async () => {
    setDrafting(true);
    setError(null);
    try {
      const d = await pred.draft(/^https?:\/\//.test(link.trim()) ? { url: link.trim() } : { text: link });
      const { model, ...rest } = d;
      setP((x) => ({ ...x, ...Object.fromEntries(Object.entries(rest).filter(([, v]) => v != null)), who_kind: "expert" }));
      toast(`Drafted by ${model}: check every field before saving`);
    } catch (e) { setError(String((e as Error).message || e)); } finally { setDrafting(false); }
  };
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const out = p.id ? await pred.edit(p.id, p) : await pred.add(p);
      toast(p.id ? "Prediction saved" : "Prediction added to your log");
      onSaved(out);
    } catch (err) { setError(String((err as Error).message || err)); } finally { setBusy(false); }
  };
  return (
    <form className="ratio-form" onSubmit={save}>
      {s.ai_enabled && !p.id && (
        <div style={{ gridColumn: "1 / -1", display: "flex", gap: 8 }}>
          <input value={link} onChange={(e) => setLink(e.target.value)} placeholder="Paste a link to an article, or its text, to draft an expert's call"
            aria-label="Link or text to draft from" style={{ flex: 1, minWidth: 0, width: "100%" }} />
          <button type="button" disabled={drafting || link.trim().length < 8} onClick={draft}>{drafting ? "Reading…" : "Draft from it"}</button>
        </div>
      )}
      <label style={{ gridColumn: "1 / -1" }}>The question or claim
        <input required value={p.question ?? ""} onChange={(e) => set("question", e.target.value)} placeholder="Will NZ inflation be under 3% in 2027?" /></label>
      <label>Kind
        <select value={p.kind} onChange={(e) => set("kind", e.target.value)}>
          <option value="binary">Yes or no (a chance)</option><option value="number">A number (with a range)</option><option value="date">A date</option>
        </select></label>
      {p.kind === "binary" && <label>Chance of yes (%)
        <input type="number" min={0} max={100} step={1} required value={p.chance == null ? "" : Math.round(p.chance * 1000) / 10}
          onChange={(e) => set("chance", e.target.value === "" ? null : Number(e.target.value) / 100)} /></label>}
      {p.kind === "number" && <>
        <label>The number<input type="number" step="any" required value={p.value ?? ""} onChange={num("value")} /></label>
        <label>Low (optional)<input type="number" step="any" value={p.low ?? ""} onChange={num("low")} /></label>
        <label>High (optional)<input type="number" step="any" value={p.high ?? ""} onChange={num("high")} /></label>
        <label>Unit<input value={p.unit ?? ""} onChange={(e) => set("unit", e.target.value)} placeholder="%" /></label>
      </>}
      {p.kind === "date" && <>
        <label>The date called<input type="date" required value={p.date_call ?? ""} onChange={(e) => set("date_call", e.target.value)} /></label>
        <label>Right if within (days)<input type="number" min={0} value={p.window_days ?? 30} onChange={num("window_days")} /></label>
      </>}
      <label>Whose call
        <select value={p.who_kind} onChange={(e) => set("who_kind", e.target.value)}>
          <option value="you">Mine</option><option value="expert">An expert's or a forecaster's</option>
          <option value="app">The app's forecast</option><option value="crowd">A crowd site's</option>
        </select></label>
      {p.who_kind !== "you" && <label>Who<input required value={p.who ?? ""} onChange={(e) => set("who", e.target.value)} placeholder="Reserve Bank of NZ" /></label>}
      <label>Made on<input type="date" value={p.made ?? ""} onChange={(e) => set("made", e.target.value)} /></label>
      <label>Due (when it can be checked)<input type="date" required value={p.due ?? ""} onChange={(e) => set("due", e.target.value)} /></label>
      <label>Category
        <select value={p.category ?? ""} onChange={(e) => set("category", e.target.value)}>
          <option value="">None</option>
          {Object.entries(CATEGORY_TEXT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select></label>
      <label>Country (optional)<input value={p.entity ?? ""} onChange={(e) => set("entity", e.target.value.toUpperCase())} placeholder="NZL" maxLength={12} /></label>
      {p.kind === "number" && <>
        <label>Indicator, to check it by itself<input value={p.indicator ?? ""} onChange={(e) => set("indicator", e.target.value)} placeholder="inflation" /></label>
        <label>For the year<input type="number" value={p.year ?? ""} onChange={num("year")} /></label>
      </>}
      <label style={{ gridColumn: "1 / -1" }}>Link (optional)<input value={p.link ?? ""} onChange={(e) => set("link", e.target.value)} /></label>
      <label style={{ gridColumn: "1 / -1" }}>Why (optional)<textarea rows={2} value={p.why ?? ""} onChange={(e) => set("why", e.target.value)} /></label>
      <div className="row">
        <button type="submit" disabled={busy}>{p.id ? "Save" : "Add to the log"}</button>
        {error && <span className="error small">{error}</span>}
      </div>
      <p className="caption">Kept only on this computer (var\user\predictions.json). A number call tied to an indicator, a country and a year
        is checked by itself when that year&apos;s figure arrives; one tied to a crowd question is settled when the question resolves.</p>
    </form>
  );
}
