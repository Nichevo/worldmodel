"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { GRADE_TEXT, TYPE_TEXT, type Indicator, type MeasureType, type QualityShow } from "@/lib/api";
import { isStarred, passes, setStar, SHOW_TEXT, useStars } from "@/lib/quality";
import { saveSettings, useSettings } from "@/lib/settings";
import { NO_INDICATOR } from "@/lib/workspace";
import { STRIP_KNEE, stripX, summarise, useIndicatorYears, yearsSentence, yearsText, type YearSummary } from "@/lib/years";
import YearStrip from "@/components/YearStrip";

// The Years filter: every indicator, or only those with the source's own forecasts, history
// from before 1950, or figures in the last three years.
type Span = "" | "forecast" | "long" | "recent";
const SPAN_TEXT: Record<Span, string> = { "": "Any years", forecast: "With forecasts", long: "History before 1950", recent: "Up to date (last 3 years)" };
const STRIP_W = 84;

// The indicator drop-down: a Show filter (by grade) and a Type filter (by measure) at the top,
// starred indicators first, then the rest by topic. Typing a name finds every indicator, with
// those the filters hide marked, so nothing is lost. The filters are remembered in Settings.
// With `none`, the list starts with that choice (a plain map), picked as NO_INDICATOR.
// Each indicator shows its years (Settings > Events on charts > years in drop-downs): the
// first and last year of history, "→ 2050" in orange when the source forecasts, and a small
// strip on one shared time scale. Hovering one says more at the foot of the list.
export default function IndicatorSelect({ indicators, value, onChange, skip, label = "Indicator", className, none }: {
  indicators: Indicator[]; value: string; onChange: (id: string) => void; skip?: string; label?: string; className?: string; none?: string;
}) {
  const { quality_show: show, quality_type: type, year_strips: strips, forecast_horizon: horizon } = useSettings();
  const [folded, setFolded] = useState<Record<string, boolean>>({});
  const years = useIndicatorYears(strips);
  const [span, setSpan] = useState<Span>("");
  const [hover, setHover] = useState<string | null>(null);
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
  const sums = useMemo(() => {
    const m = new Map<string, YearSummary>();
    if (strips) for (const i of indicators) m.set(i.indicator_id, summarise(i, years?.[i.indicator_id]));
    return m;
  }, [indicators, years, strips]);
  const now = new Date().getFullYear();
  const spanOk = (i: Indicator) => {
    const y = sums.get(i.indicator_id);
    if (!span || !y) return true;
    if (span === "forecast") return y.projTo != null;
    if (span === "long") return y.first != null && y.first < 1950;
    return y.lastHist != null && y.lastHist >= now - 3;
  };
  const found = (words.length
    ? list.filter((i) => words.every((w) => `${i.name} ${i.indicator_id} ${(i.synonyms ?? []).join(" ")}`.toLowerCase().includes(w)))
    : list.filter((i) => !hidden(i))).filter(spanOk);
  const starred = found.filter((i) => isStarred(i, local));
  const rest = found.filter((i) => !isStarred(i, local));
  // Indicators under another (Male population under Population) follow it, indented; one whose
  // parent is filtered out stands alone with "under Population" beside it.
  const restIds = new Set(rest.map((i) => i.indicator_id));
  const kids = new Map<string, Indicator[]>();
  const KIND_ORDER = { part: 0, sex: 1, share: 2 } as const;
  for (const i of rest) {
    const p = i.part_of?.parent;
    if (p && restIds.has(p)) kids.set(p, [...(kids.get(p) ?? []), i]);
  }
  kids.forEach((l) => l.sort((a, b) => KIND_ORDER[a.part_of!.kind] - KIND_ORDER[b.part_of!.kind]));
  const tops = rest.filter((i) => !(i.part_of && restIds.has(i.part_of.parent)));
  const domains = [...new Set(tops.map((i) => i.domain))];
  const nameOf = (id: string) => indicators.find((i) => i.indicator_id === id)?.name ?? id;
  const pick = (id: string) => { onChange(id); setOpen(false); setQ(""); };
  const shownCount = list.filter((i) => !hidden(i) && spanOk(i)).length;
  const yearsOf = (i: Indicator) => {
    const y = sums.get(i.indicator_id);
    if (!y) return null;
    const t = yearsText(y);
    return (
      <span className="isel-years" title={yearsSentence(y, horizon)}>
        <span>{t.hist}{t.proj && <span className="proj"> {t.proj}</span>}{t.by && <span className="isel-by"> {t.by}</span>}</span>
        <YearStrip years={years?.[i.indicator_id]} first={i.first_year} last={i.last_year} lastHist={i.last_estimate_year} width={STRIP_W} />
      </span>
    );
  };
  const footFor = indicators.find((i) => i.indicator_id === (hover ?? value));
  const footSum = footFor ? sums.get(footFor.indicator_id) : undefined;

  const KIND_TAG = { part: "part", sex: "by sex", share: "% of" } as const;
  const row = (i: Indicator, child = false) => {
    const st = isStarred(i, local);
    const why = words.length ? hidden(i) : null;
    const n = child ? 0 : (kids.get(i.indicator_id)?.length ?? 0);
    const orphan = !child && i.part_of && !restIds.has(i.part_of.parent);
    return (
      <li key={i.indicator_id} className={`isel-row${child ? " isel-child" : ""}${i.indicator_id === value ? " on" : ""}${why ? " isel-hidden" : ""}`}
        onMouseEnter={() => setHover(i.indicator_id)} onFocus={() => setHover(i.indicator_id)}>
        <button className="isel-star" aria-label={st ? `Unstar ${i.name}` : `Star ${i.name}`} title={st ? "Starred: always in the lists" : "Star: always keep in the lists"}
          aria-pressed={st} onClick={() => setStar(i.indicator_id, !st)}>{st ? "★" : "☆"}</button>
        {child && <span className="isel-kind" title={`${i.name} is ${{ part: "a part of", sex: "the women's or men's figure for", share: "a share of" }[i.part_of!.kind]} ${nameOf(i.part_of!.parent)}`}>{KIND_TAG[i.part_of!.kind]}</span>}
        <button className="isel-pick" onClick={() => pick(i.indicator_id)}>
          {i.name}{why && <span className="muted small"> (hidden: {why})</span>}
          {orphan && <span className="muted small"> (under {nameOf(i.part_of!.parent)})</span>}
        </button>
        {n > 0 && (
          <button className="isel-fold" aria-expanded={!folded[i.indicator_id]} title={`${n} indicator${n === 1 ? "" : "s"} under ${i.name}: show or hide them`}
            onClick={() => setFolded({ ...folded, [i.indicator_id]: !folded[i.indicator_id] })}>
            {folded[i.indicator_id] ? `▸ ${n}` : `▾ ${n}`}
          </button>
        )}
        {yearsOf(i)}
        {i.grade && <span className={`grade grade-${i.grade}`} title={`Grade ${i.grade}: ${GRADE_TEXT[i.grade]}`}>{i.grade}</span>}
      </li>
    );
  };

  return (
    <div className={`isel${className ? ` ${className}` : ""}`} ref={box}>
      <button className="isel-button" aria-haspopup="listbox" aria-expanded={open} aria-label={label} onClick={() => setOpen(!open)}>
        <span className="isel-name">{current?.name ?? (none && value === NO_INDICATOR ? none : "Choose…")}</span>
        {current && sums.get(current.indicator_id) && (
          <YearStrip years={years?.[current.indicator_id]} first={current.first_year} last={current.last_year}
            lastHist={current.last_estimate_year} width={48} title={yearsSentence(sums.get(current.indicator_id)!, horizon)} />
        )}
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
            {strips && <label>Years <select value={span} onChange={(e) => setSpan(e.target.value as Span)}>
              {(Object.keys(SPAN_TEXT) as Span[]).map((k) => <option key={k} value={k}>{SPAN_TEXT[k]}</option>)}
            </select></label>}
            <span className="muted">{shownCount} of {list.length}</span>
          </div>
          <input ref={search} type="search" placeholder="Type to find any indicator" value={q} onChange={(e) => { setQ(e.target.value); setHover(null); }}
            onKeyDown={(e) => { if (e.key === "Enter" && found[0]) pick(found[0].indicator_id); }} aria-label="Find an indicator" />
          {strips && (
            <div className="isel-axis" aria-hidden>
              <span><span className="key-e" />history</span>
              <span title="The source's own forecast (UN, IMF, World Bank...). Our statistical forecast is the Forecast button on charts."><span className="key-p" />source forecast</span>
              <span><span className="key-now" />now</span>
              <span className="ticks" style={{ width: STRIP_W }} title="Years before 1950 are squeezed into the left end">
                <span style={{ left: stripX(STRIP_KNEE, STRIP_W) }}>1950</span>
                <span style={{ left: STRIP_W - 10 }}>2100</span>
              </span>
            </div>
          )}
          <ul className="isel-list" role="listbox" onMouseLeave={() => setHover(null)}>
            {none && !words.length && (
              <li className={`isel-row${value === NO_INDICATOR ? " on" : ""}`}>
                <span className="isel-star" aria-hidden />
                <button className="isel-pick" onClick={() => pick(NO_INDICATOR)} title="No colours: only the map's layers">{none}</button>
              </li>
            )}
            {starred.length > 0 && <li className="isel-head">Starred</li>}
            {starred.map((i) => row(i))}
            {domains.map((d) => [
              <li key={`h-${d}`} className="isel-head">{d[0].toUpperCase() + d.slice(1)}</li>,
              ...tops.filter((i) => i.domain === d).flatMap((i) => [row(i),
                ...(folded[i.indicator_id] ? [] : (kids.get(i.indicator_id) ?? []).map((c) => row(c, true)))]),
            ])}
            {!found.length && <li className="muted small isel-empty">{words.length ? "No indicator has those words." : "Nothing at this level: try Show: Everything, or star some."}</li>}
          </ul>
          {strips && (
            <div className="isel-foot" aria-live="polite">
              {footFor && footSum ? <><b>{footFor.name}</b>: {yearsSentence(footSum, horizon)}{footFor.part_of && <> Sits under {nameOf(footFor.part_of.parent)}.</>}</> : "Point at an indicator to see its years."}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
