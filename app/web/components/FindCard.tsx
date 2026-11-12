"use client";

import Flag from "@/components/Flag";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import EChart from "@/components/EChart";
import type { EChartsOption } from "echarts";
import { api, type Find, type Tone } from "@/lib/api";
import { keep, openAsk } from "@/lib/ai";
import { cssVar } from "@/lib/colors";
import { entityColors } from "@/lib/look";
import { SOURCE_LABEL } from "@/lib/format";
import { short } from "@/lib/sectors";
import MoreMenu from "@/components/MoreMenu";

// One Discover find (or news item) as a card: what kind it is, its tone as a word with an
// arrow, the headline from the numbers, a small chart with the interesting years marked,
// tags, and Interesting / Not interesting, Open, Keep, Ask AI.
export const TONE_LABEL: Record<Tone, string> = { good: "▲ Good news", bad: "▼ Bad news", neutral: "– Neutral" };

// The page that shows a find in full, set to the same countries, figure and years.
export function openHref(f: Find): string | null {
  const ents = f.entities ?? [];
  if (f.kind === "news") return ents[0] ? `/entity/${ents[0]}` : null;
  if (f.kind === "forecast") return `/forecasts?tab=track&e=${ents[0] ?? "NZL"}&ind=${f.indicator_id}&src=${f.tags.find((t) => SOURCE_LABEL[t]) ?? f.source_id ?? ""}`;
  if (f.kind === "together" && f.pair) return `/relationships?x=${f.pair[0]}&y=${f.pair[1]}`;
  if (f.kind === "after") return `/relationships?tab=events&indicator=${f.indicator_id}`;
  if (!f.indicator_id) return null;
  return ents.length ? `/compare?ids=${ents.join(",")}&indicator=${f.indicator_id}` : `/indicator/${f.indicator_id}`;
}

export default function FindCard({ f, names, ai, why, onChange, onTag, onNever, compact = false }: {
  f: Find; names: Record<string, string>; ai: boolean; why: boolean; compact?: boolean;
  onChange: (f: Find) => void; onTag?: (t: string) => void; onNever?: (kind: string) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [allCountries, setAllCountries] = useState(false);
  const [tagText, setTagText] = useState("");
  const [big, setBig] = useState(false); // the chart enlarged over the page
  useEffect(() => {
    if (!big) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setBig(false); };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [big]);
  const mark = async (change: { rating?: number; tags?: string[]; tone?: Tone | null }) => {
    const r = await api.discoverMark(f.key, change);
    const extra = f.tags.filter((t) => !f.my_tags.includes(t));
    onChange({ ...f, rating: r.rating, my_tags: r.my_tags, tone: r.tone, tags: [...extra, ...r.my_tags] });
  };
  const chartOption = useCallback((large: boolean): EChartsOption => {
    const ser = f.chart?.series ?? [];
    const m = f.chart?.mark ?? [];
    const fs = large ? 13 : 10;
    const cols = entityColors(ser.map((x) => x.entity_id));
    return {
      backgroundColor: "transparent", animation: false,
      grid: { left: large ? 12 : 4, right: large ? 20 : 8, top: ser.length > 1 ? (large ? 34 : 22) : 8, bottom: large ? 12 : 4, containLabel: true },
      legend: ser.length > 1 ? { top: 0, itemHeight: large ? 10 : 8, textStyle: { color: cssVar("--ink-2"), fontSize: large ? 13 : 11 } } : undefined,
      tooltip: { trigger: "axis" as const, confine: true, backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"), textStyle: { color: cssVar("--ink") } },
      xAxis: { type: "value" as const, min: "dataMin", max: "dataMax", minInterval: 1, axisLabel: { color: cssVar("--muted"), fontSize: fs, formatter: (v: number) => String(v) },
        splitLine: { show: false }, axisLine: { lineStyle: { color: cssVar("--axis") } } },
      yAxis: { type: "value" as const, scale: true, axisLabel: { color: cssVar("--muted"), fontSize: fs, formatter: (v: number) => short(v) }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
      series: ser.map((s, i) => ({
        type: "line" as const, name: s.name, data: s.points, showSymbol: large && s.points.length <= 40, lineStyle: { width: (i === 0 ? 2 : 1.5) + (large ? 0.5 : 0), color: cols[i] }, itemStyle: { color: cols[i] },
        markArea: i === 0 && m.length ? { silent: true, itemStyle: { color: cssVar("--surface-2"), opacity: 0.9 },
          data: [[{ xAxis: m[0] - (m.length === 1 ? 0.5 : 0) }, { xAxis: m[m.length - 1] + (m.length === 1 ? 0.5 : 0) }]] } : undefined,
      })),
    } as EChartsOption;
  }, [f.chart]);
  const option = useCallback(() => chartOption(false), [chartOption]);
  const bigOption = useCallback(() => chartOption(true), [chartOption]);
  const href = openHref(f);
  const years = f.years?.length ? (f.years.length > 1 && f.years[0] !== f.years[f.years.length - 1] ? `${f.years[0]}–${f.years[f.years.length - 1]}` : String(f.years[0])) : f.date ?? "";
  const source = f.kind === "news" ? f.outlet : f.source_id ? SOURCE_LABEL[f.source_id] ?? f.source_id : "";
  const context = `${f.headline}\n${f.detail}\n${f.chart?.series.map((s) => `${s.name}: ${s.points.map((p) => `${p[0]} ${p[1]}`).join(", ")}`).join("\n") ?? ""}`;
  const askAbout = (question?: string) => openAsk({
    title: f.headline, entity: f.entities[0], indicator: f.indicator_id, question, send: !!question,
    parts: [{ key: "data", kind: "data", label: `Discover: ${f.headline}`, text: `${context}\nSource: ${source ?? ""}${f.url ? ` (${f.url})` : ""}` }],
  });
  return (
    <div className={`card find kind-edge ${EDGE[f.kind] ?? ""}${f.new ? " new" : ""}`}>
      <h3 className="find-title">{f.kind === "news" && f.url ? <a href={f.url} target="_blank" rel="noreferrer">{f.headline}</a> : f.headline}</h3>
      <div className="find-head small">
        <span className="find-kind">{f.kind === "news" ? f.topic || "News" : kindLabel(f.kind)}</span>
        <span className={`tone ${f.tone}`} title="Tone: from whether the figure is better higher or lower, and which way it moved. You can change it in the … menu.">{TONE_LABEL[f.tone]}</span>
        {f.new && <b className="new-mark">New</b>}
        {f.stale && <span className="muted" title="Not found on the newest build; kept because you marked it Interesting">kept</span>}
        <span className="muted">{[f.category, years].filter(Boolean).join(" · ")}</span>
      </div>
      {!compact && f.chart && f.chart.series.length > 0 && (
        <div className="find-chart" role="button" tabIndex={0} title="Click to enlarge" onClick={() => setBig(true)}
          onKeyDown={(e) => { if (e.key === "Enter") setBig(true); }}>
          <EChart option={option} height={175} label={f.headline} />
        </div>
      )}
      {f.detail && <p className="small ink-2" style={{ margin: "2px 0 4px" }}>{f.detail}</p>}
      {big && f.chart && (
        <div className="find-big-back" onClick={() => setBig(false)}>
          <div className="find-big card" role="dialog" aria-modal="true" aria-label={f.headline} onClick={(e) => e.stopPropagation()}>
            <div className="row">
              <h2 className="find-title" style={{ fontSize: "1.2rem" }}>{f.headline}</h2>
              <span className="spacer" />
              <button onClick={() => setBig(false)} aria-label="Close the enlarged chart">Close</button>
            </div>
            {f.detail && <p className="ink-2">{f.detail}</p>}
            <EChart option={bigOption} height={Math.max(320, Math.round((typeof window !== "undefined" ? window.innerHeight : 800) * 0.6))} label={f.headline} />
            <div className="small muted">{[source, years].filter(Boolean).join(" · ")}{f.chart.mark?.length ? " · shaded: the years this find is about" : ""}</div>
            <div className="find-actions small">
              {href && <Link className="link" href={href}>Open in full</Link>}
              {ai && <button className="link" onClick={() => { setBig(false); askAbout(); }}>Ask AI</button>}
            </div>
          </div>
        </div>
      )}
      {!compact && (
        <div className="chips-row small find-who">
          {f.entities.slice(0, 5).map((e) => <Link key={e} className="chip" href={`/entity/${e}`}><Flag id={e} size={12} />{names[e] ?? e}</Link>)}
          {f.entities.length > 5 && <button className="link" aria-expanded={allCountries} onClick={() => setAllCountries(!allCountries)}>
            {allCountries ? "Fewer" : `All ${f.entities.length} countries`}</button>}
          {f.my_tags.map((t) => (
            <button key={t} className="chip mine" onClick={() => onTag?.(t)} title="Show finds with this tag">{t}
              <span role="button" aria-label={`Remove tag ${t}`} onClick={(e) => { e.stopPropagation(); mark({ tags: f.my_tags.filter((x) => x !== t) }); }}> ×</span></button>
          ))}
          {adding && (
            <form onSubmit={(e) => { e.preventDefault(); if (tagText.trim()) mark({ tags: [...f.my_tags, tagText.trim()] }); setTagText(""); setAdding(false); }}>
              <input autoFocus value={tagText} onChange={(e) => setTagText(e.target.value)} onBlur={() => setAdding(false)} placeholder="Your tag" style={{ width: 110 }} />
            </form>
          )}
        </div>
      )}
      {allCountries && f.members && (
        <ul className="small find-members">{f.members.map((x) => <li key={x.entity_id}><Link href={`/entity/${x.entity_id}`}>{x.name}</Link>: {x.detail}</li>)}</ul>
      )}
      {allCountries && !f.members && <div className="chips-row small">{f.entities.slice(5).map((e) => <Link key={e} className="chip" href={`/entity/${e}`}>{names[e] ?? e}</Link>)}</div>}
      <div className="find-actions small">
        <button className={f.rating > 0 ? "on" : ""} aria-pressed={f.rating > 0} onClick={() => mark({ rating: f.rating > 0 ? 0 : 1 })}>Interesting</button>
        <button className={f.rating < 0 ? "on" : ""} aria-pressed={f.rating < 0} onClick={() => mark({ rating: f.rating < 0 ? 0 : -1 })}>Not interesting</button>
        <span className="spacer" style={{ flex: 1 }} />
        {href && <Link className="link" href={href}>Open</Link>}
        {ai && <button className="link" onClick={() => askAbout()}>Ask AI</button>}
        <MoreMenu items={[
          { label: "Enlarge the chart", hidden: compact || !f.chart?.series.length, onClick: () => setBig(true) },
          { label: "Keep on Highlights", onClick: () => keep({ kind: "text", title: f.headline, text: `${f.headline}\n\n${f.detail}`, entities: f.entities, indicator: f.indicator_id ?? null, tags: ["Discover", f.category], sources: source ?? null }) },
          { label: "Why might this be?", hidden: !(ai && why), title: "Your local AI's guess at the reasons, shown in the Ask AI box. It is a guess, not a finding.",
            onClick: () => askAbout("Why might this have happened? Give the two or three most likely reasons, say how sure you are, and make clear these are guesses.") },
          { label: "Add a tag", hidden: compact, onClick: () => setAdding(true) },
          ...f.tags.filter((t) => !f.my_tags.includes(t) && !f.entities.some((e) => (names[e] ?? e) === t)).slice(0, 4)
            .map((t) => ({ label: `Finds tagged “${t}”`, hidden: compact || !onTag, onClick: () => onTag?.(t) })),
          { label: "Mark as good news", hidden: compact, on: f.tone === "good", onClick: () => mark({ tone: "good" }) },
          { label: "Mark as bad news", hidden: compact, on: f.tone === "bad", onClick: () => mark({ tone: "bad" }) },
          { label: "Mark as neutral", hidden: compact, on: f.tone === "neutral", onClick: () => mark({ tone: "neutral" }) },
          { label: "Tone from the figure", hidden: compact, onClick: () => mark({ tone: null }) },
          { label: `Never show ${f.kind === "news" ? "news" : kindLabel(f.kind).toLowerCase()}`, hidden: compact || !onNever, onClick: () => onNever?.(f.kind) },
        ]} />
      </div>
      <div className="caption" style={{ marginTop: 4 }}>{source}</div>
    </div>
  );
}

// The coloured left edge by kind of find: records red, big moves gold, turning points blue.
const EDGE: Record<string, string> = { record: "record", outlier: "record", mover: "move", overtake: "move", turning: "turn", opposite: "turn" };

export const KIND_LABEL: Record<string, string> = {
  record: "Record", mover: "Big mover", turning: "Turning point", overtake: "Overtake", outlier: "Outlier",
  disagree: "Sources disagree", forecast: "Forecast change", together: "Moving together", after: "Before and after", revised: "New data", opposite: "Opposite trends", news: "News",
};
const kindLabel = (k: string) => KIND_LABEL[k] ?? k;
