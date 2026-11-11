"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import BriefCard from "@/components/BriefCard";
import { openAsk, type AskPart } from "@/lib/ai";
import { digestApi, type Digest } from "@/lib/briefing";
import { formatValue } from "@/lib/format";
import { useSettings } from "@/lib/settings";

// Briefing > Week: one Monday-to-Sunday week on one page, kept once the week is over, with an
// AI summary on request and a print button (Print to PDF in the browser's print box). No email.
export default function WeekDigest() {
  const s = useSettings();
  const [weeks, setWeeks] = useState<{ kept: string[]; last_complete: string; this_week: string } | null>(null);
  const [week, setWeek] = useState<string | undefined>(undefined);
  const [d, setD] = useState<Digest | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { digestApi.list().then(setWeeks).catch(() => {}); }, [d?.week]);
  useEffect(() => {
    let live = true;
    setD(null);
    digestApi.get(week).then((x) => { if (live) { setD(x); setError(null); } }).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [week]);
  if (error) return <p className="error">{error}</p>;
  if (!d) return <p className="muted">Making the week&apos;s digest…</p>;
  const nm = (id: string) => d.names[id] ?? id;
  const choices = weeks ? [...new Set([weeks.this_week, weeks.last_complete, ...weeks.kept])] : [d.week];
  const label = (w: string) => (weeks && w === weeks.this_week ? `${w} (so far)` : w);
  const text = (): AskPart[] => [
    { key: "changed", kind: "data", label: "Figures that changed", text: d.changed.map((c) => `${nm(c.entity_id)}: ${c.name} ${c.y} now ${formatValue(c.now, c.unit)}${c.before !== null ? ` (was ${formatValue(c.before, c.unit)})` : " (new)"}`).join("\n") || "none" },
    { key: "finds", kind: "data", label: "Discover finds", text: d.finds.map((f) => `${f.title}. ${f.detail}`).join("\n") || "none" },
    { key: "crowd", kind: "data", label: "Crowd moves", text: d.crowd.map((c) => `${c.title}: ${Math.round(c.chance * 100)}% (${c.change >= 0 ? "+" : ""}${Math.round(c.change * 100)} points)`).join("\n") || "none" },
    { key: "preds", kind: "data", label: "Predictions", text: d.predictions.map((p) => `${p.question} (${p.who}): ${p.state}${p.score?.hit !== undefined ? (p.score.hit ? ", right" : ", wrong") : ""}`).join("\n") || "none" },
    { key: "cw", kind: "data", label: "CrisisWatch changes", text: d.crisiswatch.map((c) => c.title).join("\n") || "none" },
    { key: "events", kind: "events", label: "Events", text: d.events.map((e) => `${e.date} ${e.title}`).join("\n") || "none" },
    { key: "news", kind: "data", label: "Top news", text: d.news.map((n) => `${n.date} ${n.title}`).join("\n") || "none" },
  ];
  const summarise = () => openAsk({ title: `The week ${d.from} to ${d.to}`, parts: text(), send: true,
    question: "Summarise this week for me in a few short paragraphs: what changed, what matters most for my key countries, and what to watch next week." });
  return (
    <div className="digest">
      <div className="title-row no-print">
        <label className="small">Week <select value={week ?? d.week} onChange={(e) => setWeek(e.target.value)}>
          {choices.map((w) => <option key={w} value={w}>{label(w)}</option>)}</select></label>
        <span className="muted small">{d.from} to {d.to}{d.kept ? `, kept ${d.made.slice(0, 10)}` : d.complete ? "" : ", so far (worked out each time)"}</span>
        <span className="spacer" />
        {s.ai_enabled && <button className="small" onClick={summarise} title="Ask the local AI for a short summary of the week">Summarise with AI</button>}
        <button className="small" onClick={() => window.print()} title="Print it, or choose Save as PDF in the print box">Print or save as PDF</button>
      </div>
      <h2 className="print-only">Week {d.week}: {d.from} to {d.to}</h2>
      <div className="grid two">
        <section className="card">
          <h3>New figures</h3>
          {d.sources.length === 0 ? <p className="muted small">No source loaded new figures this week.</p> : (
            <p className="small">{d.sources.length} source{d.sources.length === 1 ? "" : "s"} loaded new figures: {d.sources.slice(0, 12).map((x) => x.source_id).join(", ")}{d.sources.length > 12 ? "…" : ""}. <Link href="/data">Data status</Link></p>
          )}
          {d.changed.length > 0 && (
            <table className="small summary-table">
              <thead><tr><th>Country</th><th>Figure</th><th className="num">Year</th><th className="num">Now</th><th className="num">Was</th></tr></thead>
              <tbody>{d.changed.slice(0, 30).map((c, i) => (
                <tr key={i}><td>{nm(c.entity_id)}</td><td>{c.name}</td><td className="num">{c.y}</td>
                  <td className="num">{formatValue(c.now, c.unit)}</td><td className="num">{c.before === null ? "new" : formatValue(c.before, c.unit)}</td></tr>
              ))}</tbody>
            </table>
          )}
          <p className="caption">Headline figures of your key countries ({d.key_countries.map(nm).join(", ")}) whose newest edition differs from the one before.</p>
        </section>
        <section className="card">
          <h3>Predictions</h3>
          {d.predictions.length === 0 ? <p className="muted small">None came due or were settled this week.</p> : (
            <ul className="small">{d.predictions.map((p) => (
              <li key={p.id}><b>{p.state === "settled" ? (p.score?.hit === undefined ? "Settled" : p.score.hit ? "Right" : "Wrong") : "Due"}</b> {p.day}: {p.question} <span className="muted">({p.who})</span></li>
            ))}</ul>
          )}
          <h3>Crowd: biggest moves</h3>
          {d.crowd.length === 0 ? <p className="muted small">No big moves.</p> : (
            <ul className="small">{d.crowd.map((c) => (
              <li key={c.key}><Link href={`/crowd/question?key=${encodeURIComponent(c.key)}`}>{c.title}</Link>: {Math.round(c.chance * 100)}%
                {" "}<span className={c.change >= 0 ? "up" : "down"}>({c.change >= 0 ? "+" : ""}{Math.round(c.change * 100)} points)</span> <span className="muted">{c.site}</span></li>
            ))}</ul>
          )}
        </section>
      </div>
      <Section title="Surprises and finds" cards={d.finds} names={d.names} empty="Discover saw nothing new this week." />
      <Section title="CrisisWatch changes" cards={d.crisiswatch} names={d.names} empty="No CrisisWatch month out this week." />
      <Section title="Events" cards={d.events} names={d.names} empty="No events this week." />
      <Section title="Top news" cards={d.news} names={d.names} empty="No news kept for this week." />
      {d.notes.length > 0 && <p className="caption">{d.notes.join("; ")}</p>}
      <p className="caption no-print">Made on the first visit after the week ends and kept (Settings &gt; Briefing). Nothing is emailed.</p>
    </div>
  );
}

function Section({ title, cards, names, empty }: { title: string; cards: Digest["finds"]; names: Record<string, string>; empty: string }) {
  return (
    <section className="card">
      <h3>{title}</h3>
      {cards.length === 0 ? <p className="muted small">{empty}</p> : <div className="digest-cards">{cards.map((c) => <BriefCard key={c.key} card={c} names={names} compact />)}</div>}
    </section>
  );
}
