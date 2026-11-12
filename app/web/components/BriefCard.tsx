"use client";

import Link from "next/link";
import { useState } from "react";
import Flag from "@/components/Flag";
import { api, type BriefCard as Card } from "@/lib/api";
import { openAsk, toast } from "@/lib/ai";
import { useSettings } from "@/lib/settings";
import { sparkPath } from "@/lib/look";

// One card for everything the app hears about: news and CrisisWatch (feeds), Discover finds,
// events, things due and your own kept items. Every card has the same buttons: open it in
// the app, read the source, keep it in Highlights, and Ask AI.
export const KIND_LABEL: Record<string, string> = { feed: "Feed", find: "Found", event: "Event", due: "Due", yours: "Yours" };
export const GROUP_LABEL: Record<string, string> = {
  crisiswatch: "CrisisWatch", watch: "Reported in the news", news: "News", conflict: "Conflict", coup: "Coup", disaster: "Disaster",
  election: "Election", epidemic: "Epidemic", sport: "Sport", summit: "Summit", earthquake: "Earthquake", storm: "Storm",
  crowd: "Crowd forecast", prediction: "Your prediction", alert: "Watchlist",
};

export default function BriefCard({ card, names, compact = false }: { card: Card; names: Record<string, string>; compact?: boolean }) {
  const s = useSettings();
  const [kept, setKept] = useState(false);
  const who = card.entities.slice(0, 3);
  const label = card.group === "watch"
    ? (card.confirmed ? "Confirmed" : `Reported${card.n_outlets && card.n_outlets > 1 ? ` by ${card.n_outlets} outlets` : ""}`)
    : GROUP_LABEL[card.group ?? ""] ?? KIND_LABEL[card.kind];
  // The coloured edge by kind of find (records, big moves, turning points); others by tone.
  const edge = card.find_kind ? ({ record: "record", outlier: "record", mover: "move", overtake: "move", turning: "turn", opposite: "turn" } as Record<string, string>)[card.find_kind] : undefined;
  const spark = card.chart?.series?.[0];
  const keep = () => {
    api.addHighlight({ kind: "text", title: card.title, text: [card.title, card.detail].filter(Boolean).join("\n\n"),
      page_url: card.href ?? card.url ?? "/briefing", page_title: "Briefing", entities: card.entities,
      tags: [KIND_LABEL[card.kind].toLowerCase(), ...(card.group ? [card.group] : [])] })
      .then(() => { setKept(true); toast("Kept in Highlights"); })
      .catch((e) => toast(`Not kept: ${e.message || e}`));
  };
  const ask = () => openAsk({ title: card.title, entity: card.entities[0], parts: [{ key: "card", kind: "highlight",
    label: `${label}${card.date ? `, ${card.date}` : ""}`, text: [card.title, card.detail, card.source && `Source: ${card.source}`, card.url ?? ""].filter(Boolean).join("\n") }] });
  return (
    <article className={`brief-card tone-${card.tone} kind-${card.kind}${edge ? ` edge-${edge}` : ""}${card.group === "watch" && !card.confirmed ? " reported" : ""}${compact ? " compact" : ""}`}>
      <div className="brief-body">
        <div className="brief-text">
          <div className="brief-title">{card.href ? <Link href={card.href}>{card.title}</Link> : card.title}</div>
          {!compact && spark && <BriefSpark pts={spark.points} mark={card.chart?.mark ?? []} tone={card.tone} />}
          <div className="brief-meta small">
            <span className={`brief-kind kind-${card.kind}`}>{label}</span>
            {card.word && <span className="chip-tag">{card.word}</span>}
            {card.new && <span className="chip-tag new">new</span>}
            {card.date && <span className="muted">{card.date.length > 7 && card.group === "crisiswatch" ? card.date.slice(0, 7) : card.date}</span>}
            {who.map((e) => <Link key={e} href={`/entity/${e}`} className="brief-who"><Flag id={e} />{names[e] ?? e}</Link>)}
            {card.entities.length > 3 && <span className="muted">+{card.entities.length - 3}</span>}
          </div>
          {!compact && card.detail && <p className="brief-detail small">{card.detail}</p>}
        </div>
      </div>
      <div className="brief-actions small">
        {card.source && <span className="muted">{card.source}</span>}
        <span className="spacer" />
        {card.url && <a href={card.url} target="_blank" rel="noreferrer">Source</a>}
        <button className="link" onClick={keep} disabled={kept} title="Keep this in Highlights">{kept ? "Kept" : "Save"}</button>
        {s.ai_enabled && <button className="link" onClick={ask} title="Ask the local AI about this">Ask AI</button>}
      </div>
    </article>
  );
}

// A find's small chart on its Briefing card: the first line, the years it is about shaded.
function BriefSpark({ pts, mark, tone }: { pts: [number, number][]; mark: number[]; tone: string }) {
  const W = 300, H = 40;
  if (pts.length < 2) return null;
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const sx = (x: number) => 2 + ((x - x0) / (x1 - x0 || 1)) * (W - 4);
  const lo = Math.min(...ys), hi = Math.max(...ys);
  const sy = (y: number) => H - 3 - ((y - lo) / (hi - lo || 1)) * (H - 6);
  const last = pts[pts.length - 1];
  const col = tone === "good" ? "var(--good)" : tone === "bad" ? "var(--bad)" : "var(--ink)";
  return (
    <svg className="brief-spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
      {mark.length > 0 && <rect x={sx(mark[0] - 0.5)} width={Math.max(3, sx(mark[mark.length - 1] + 0.5) - sx(mark[0] - 0.5))} y={0} height={H} fill="var(--surface-2)" />}
      <path d={sparkPath(pts, W, H, 3)} fill="none" stroke="var(--ink-2)" strokeWidth={1.4} vectorEffect="non-scaling-stroke" />
      <circle cx={sx(last[0])} cy={sy(last[1])} r={2.6} fill={col} />
    </svg>
  );
}

// Cards of one group: the first few, and the rest folded away.
export function CardGroup({ title, cards, names, first = 3, note }: { title: string; cards: Card[]; names: Record<string, string>; first?: number; note?: React.ReactNode }) {
  const [all, setAll] = useState(false);
  if (!cards.length) return null;
  const shown = all ? cards : cards.slice(0, first);
  return (
    <section className="brief-group">
      <h3 className="brief-group-head">{title} <span className="muted small">{cards.length}</span></h3>
      {note}
      {shown.map((c) => <BriefCard key={c.key} card={c} names={names} />)}
      {cards.length > first && (
        <button className="link small" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show ${cards.length - first} more`}</button>
      )}
    </section>
  );
}
