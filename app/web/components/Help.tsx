"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { Indicator } from "@/lib/api";
import { HELP, type HelpNote } from "@/lib/help";
import { SOURCE_LABEL } from "@/lib/format";

// A small "?" beside a card or panel title. It opens a short note: what the chart
// shows in plain words, how it is worked out, its units and its sources (each
// linked to its entry on the Indicators page). Notes for the country page's topic
// cards are written in lib/help.ts; a single-indicator chart uses the indicator's
// own description from the catalogue.
export default function Help({ note, indicator, label }: { note?: keyof typeof HELP | HelpNote; indicator?: Indicator; label?: string }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  const n: HelpNote | null = typeof note === "string" ? HELP[note] : note ?? (indicator ? fromIndicator(indicator) : null);
  if (!n) return null;
  const title = label ?? n.title;
  return (
    <span className="help" ref={box}>
      <button className="help-q" aria-label={`What is ${title}?`} aria-expanded={open} title="What this shows" onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(!open); }}>?</button>
      {open && (
        <span className="help-pop" role="dialog" aria-label={title} onClick={(e) => e.stopPropagation()}>
          <b>{title}</b>
          <span className="help-p">{n.what}</span>
          {n.how && <span className="help-p"><i>How it is worked out:</i> {n.how}</span>}
          {n.units && <span className="help-p"><i>Units:</i> {n.units}</span>}
          {n.sources?.length ? (
            <span className="help-p"><i>Sources:</i>{" "}
              {n.sources.map((s, i) => (
                <span key={s.label}>
                  {s.indicator ? <Link href={`/indicators?ind=${s.indicator}`}>{s.label}</Link> : s.label}
                  {i < n.sources!.length - 1 ? "; " : ""}
                </span>
              ))}
            </span>
          ) : null}
        </span>
      )}
    </span>
  );
}

function fromIndicator(ind: Indicator): HelpNote {
  return {
    title: ind.name,
    what: ind.description || "No description in the catalogue yet.",
    units: ind.unit || undefined,
    sources: ind.sources.map((s) => ({ label: s.source_name ?? SOURCE_LABEL[s.source_id] ?? s.source_id, indicator: ind.indicator_id })),
  };
}
