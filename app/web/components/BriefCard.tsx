"use client";

import Link from "next/link";
import { useState } from "react";
import Flag from "@/components/Flag";
import { api, type BriefCard as Card } from "@/lib/api";
import { openAsk, toast } from "@/lib/ai";
import { useSettings } from "@/lib/settings";

// One card for everything the app hears about: news and CrisisWatch (feeds), Discover finds,
// events, things due and your own kept items. Every card has the same buttons: open it in
// the app, read the source, keep it in Highlights, and Ask AI.
export const KIND_LABEL: Record<string, string> = { feed: "Feed", find: "Found", event: "Event", due: "Due", yours: "Yours" };
export const GROUP_LABEL: Record<string, string> = {
  crisiswatch: "CrisisWatch", watch: "Reported in the news", news: "News", conflict: "Conflict", coup: "Coup", disaster: "Disaster",
  election: "Election", epidemic: "Epidemic", sport: "Sport", summit: "Summit", earthquake: "Earthquake", storm: "Storm",
};

export default function BriefCard({ card, names, compact = false }: { card: Card; names: Record<string, string>; compact?: boolean }) {
  const s = useSettings();
  const [kept, setKept] = useState(false);
  const who = card.entities.slice(0, 3);
  const label = card.group === "watch"
    ? (card.confirmed ? "Confirmed" : `Reported${card.n_outlets && card.n_outlets > 1 ? ` by ${card.n_outlets} outlets` : ""}`)
    : GROUP_LABEL[card.group ?? ""] ?? KIND_LABEL[card.kind];
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
    <article className={`brief-card tone-${card.tone} kind-${card.kind}${card.group === "watch" && !card.confirmed ? " reported" : ""}${compact ? " compact" : ""}`}>
      <div className="brief-meta small">
        <span className={`brief-kind kind-${card.kind}`}>{label}</span>
        {card.word && <span className="chip-tag">{card.word}</span>}
        {card.new && <span className="chip-tag new">new</span>}
        {card.date && <span className="muted">{card.date.length > 7 && card.group === "crisiswatch" ? card.date.slice(0, 7) : card.date}</span>}
        <span className="spacer" />
        {who.map((e) => <Link key={e} href={`/entity/${e}`} className="brief-who"><Flag id={e} />{names[e] ?? e}</Link>)}
        {card.entities.length > 3 && <span className="muted">+{card.entities.length - 3}</span>}
      </div>
      <div className="brief-title">{card.href ? <Link href={card.href}>{card.title}</Link> : card.title}</div>
      {!compact && card.detail && <p className="brief-detail small">{card.detail}</p>}
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
