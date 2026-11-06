"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { GRADE_TEXT, TYPE_TEXT, type Indicator, type MeasureType, type QualityShow } from "@/lib/api";
import { isStarred, passes, setStar, SHOW_TEXT, useStars } from "@/lib/quality";
import { saveSettings, useSettings } from "@/lib/settings";

// The indicator drop-down: a Show filter (by grade) and a Type filter (by measure) at the top,
// starred indicators first, then the rest by topic. Typing a name finds every indicator, with
// those the filters hide marked, so nothing is lost. The filters are remembered in Settings.
export default function IndicatorSelect({ indicators, value, onChange, skip, label = "Indicator", className }: {
  indicators: Indicator[]; value: string; onChange: (id: string) => void; skip?: string; label?: string; className?: string;
}) {
  const { quality_show: show, quality_type: type } = useSettings();
  const local = useStars();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const box = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    setTimeout(() => search.current?.focus(), 0);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  const current = indicators.find((i) => i.indicator_id === value);
  const list = useMemo(() => indicators.filter((i) => i.indicator_id !== skip), [indicators, skip]);
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const hidden = (i: Indicator) => {
    const st = isStarred(i, local);
    if (!passes(i, show, st)) return `grade ${i.grade ?? "?"}`;
    if (type && !st && i.type && i.type !== type) return TYPE_TEXT[i.type];
    return null;
  };
  const found = words.length
    ? list.filter((i) => words.every((w) => `${i.name} ${i.indicator_id} ${(i.synonyms ?? []).join(" ")}`.toLowerCase().includes(w)))
    : list.filter((i) => !hidden(i));
  const starred = found.filter((i) => isStarred(i, local));
  const rest = found.filter((i) => !isStarred(i, local));
  const domains = [...new Set(rest.map((i) => i.domain))];
  const pick = (id: string) => { onChange(id); setOpen(false); setQ(""); };
  const shownCount = list.filter((i) => !hidden(i)).length;

  const row = (i: Indicator) => {
    const st = isStarred(i, local);
    const why = words.length ? hidden(i) : null;
    return (
      <li key={i.indicator_id} className={`isel-row${i.indicator_id === value ? " on" : ""}${why ? " isel-hidden" : ""}`}>
        <button className="isel-star" aria-label={st ? `Unstar ${i.name}` : `Star ${i.name}`} title={st ? "Starred: always in the lists" : "Star: always keep in the lists"}
          aria-pressed={st} onClick={() => setStar(i.indicator_id, !st)}>{st ? "★" : "☆"}</button>
        <button className="isel-pick" onClick={() => pick(i.indicator_id)}>
          {i.name}{why && <span className="muted small"> (hidden: {why})</span>}
        </button>
        {i.grade && <span className={`grade grade-${i.grade}`} title={`Grade ${i.grade}: ${GRADE_TEXT[i.grade]}`}>{i.grade}</span>}
      </li>
    );
  };

  return (
    <div className={`isel${className ? ` ${className}` : ""}`} ref={box}>
      <button className="isel-button" aria-haspopup="listbox" aria-expanded={open} aria-label={label} onClick={() => setOpen(!open)}>
        <span className="isel-name">{current?.name ?? "Choose…"}</span>
        {current?.grade && <span className={`grade grade-${current.grade}`}>{current.grade}</span>}
        <span aria-hidden className="isel-caret">▾</span>
      </button>
      {open && (
        <div className="isel-pop" role="dialog" aria-label={`Choose ${label.toLowerCase()}`}>
          <div className="isel-filters small">
            <label>Show <select value={show} onChange={(e) => saveSettings({ quality_show: e.target.value as QualityShow })}>
              {(Object.keys(SHOW_TEXT) as QualityShow[]).map((k) => <option key={k} value={k}>{SHOW_TEXT[k]}</option>)}
            </select></label>
            <label>Type <select value={type} onChange={(e) => saveSettings({ quality_type: e.target.value as "" | MeasureType })}>
              <option value="">All types</option>
              {(Object.keys(TYPE_TEXT) as MeasureType[]).map((k) => <option key={k} value={k}>{TYPE_TEXT[k]}</option>)}
            </select></label>
            <span className="muted">{shownCount} of {list.length}</span>
          </div>
          <input ref={search} type="search" placeholder="Type to find any indicator" value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && found[0]) pick(found[0].indicator_id); }} aria-label="Find an indicator" />
          <ul className="isel-list" role="listbox">
            {starred.length > 0 && <li className="isel-head">Starred</li>}
            {starred.map(row)}
            {domains.map((d) => [
              <li key={`h-${d}`} className="isel-head">{d[0].toUpperCase() + d.slice(1)}</li>,
              ...rest.filter((i) => i.domain === d).map(row),
            ])}
            {!found.length && <li className="muted small isel-empty">{words.length ? "No indicator has those words." : "Nothing at this level: try Show: Everything, or star some."}</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
