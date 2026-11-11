"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import { openAsk } from "@/lib/ai";
import { alikeApi, type Alike } from "@/lib/alike";

// A country page's "Like this one": the five countries nearest to it on every figure the
// ready-made sets use, now and in 1990. Hidden when there are too few figures.
export default function AlikeCard({ entity, name }: { entity: string; name: string }) {
  const [now, setNow] = useState<Alike | null>(null);
  const [then, setThen] = useState<Alike | null>(null);
  useEffect(() => {
    let live = true;
    setNow(null);
    setThen(null);
    alikeApi.like(entity, "everything", undefined, 5).then((r) => live && setNow(r)).catch(() => {});
    alikeApi.like(entity, "everything", 1990, 5).then((r) => live && setThen(r)).catch(() => {});
    return () => { live = false; };
  }, [entity]);
  if (!now || !now.nearest.length) return null;
  const line = (d: Alike) => d.nearest.map((r) => `${r.name} (${r.likeness.toFixed(0)}, closest on ${r.closest_on.map((c) => d.indicator_names[c] ?? c).join(", ")})`).join("; ");
  const ask = () => openAsk({ title: `Countries like ${name}`, entity, parts: [
    { key: "now", kind: "data", label: `Most like ${name}, ${now.year}`, text: line(now) },
    ...(then?.nearest.length ? [{ key: "then", kind: "data" as const, label: `Most like ${name}, 1990`, text: line(then) }] : []),
    { key: "how", kind: "description", label: "How", text: `Compared on ${now.used.length} figures (economy, people, government, energy), each on one scale across countries; likeness 100 means identical.` }] });
  const list = (d: Alike) => d.nearest.map((r, i) => (
    <span key={r.entity_id}>{i ? ", " : ""}<Link href={`/entity/${r.entity_id}`}>{r.name}</Link> <span className="muted">{r.likeness.toFixed(0)}</span></span>));
  return (
    <div className="card" id="alike">
      <div className="card-head"><h3>Like this one</h3>
        <span><CardAsk onAsk={ask} /> <Link className="small" href={`/alike?e=${entity}`}>More</Link></span></div>
      <p className="small" style={{ margin: "4px 0" }}><b>{now.year}:</b> {list(now)}</p>
      {then && then.nearest.length > 0 && <p className="small" style={{ margin: "4px 0" }}><b>1990:</b> {list(then)}</p>}
      <p className="caption">Nearest on {now.used.length} figures about the economy, people, government and energy; 100 would be identical.</p>
    </div>
  );
}
