// Big cycles (Long history > Big cycles, the country page's debt cycle card) and Episodes:
// types, calls and chart options.

import type { EChartsOption, SeriesOption } from "echarts";
import { get } from "@/lib/api";
import { chrome } from "@/lib/charts";
import { cssVar as cv } from "@/lib/colors";
import { entityColors } from "@/lib/look";

const cssVar = (name: string, fallback = "") => cv(name) || fallback;

// ------------------------------------------------------------------ types
export type Spell = { kind: string; name: string; from: number; to: number };
export type War = { title: string; from: number; to: number };
export type Arc = { entity: string; name: string; points: [number, number][]; peak: [number, number] | null;
  phases: { phase: "rise" | "top" | "decline"; from: number; to: number }[]; now?: string; crises: Spell[]; wars: War[] };
export type Arcs = { lines: Arc[]; note: string | null; how: string | null };
export type StageCell = { year: number; stage: number | null; reasons: string[] };
export type Stages = { years: number[]; stages: { n: number; name: string; about: string }[];
  countries: { entity: string; name: string; cells: StageCell[] }[]; how: string };
export type DebtCycle = { entity: string; name: string; since: number | null; debt: [number, number][]; debt_from_long: boolean;
  real_rate: [number, number][]; inflation: [number, number][]; private_credit: [number, number][]; crises: Spell[]; wars: War[];
  peak: { year: number; value: number } | null; latest: { year: number; value: number } | null; how: string; note: string };
export type ClockCountry = { entity: string; name: string; phase: string | null; angle: number | null; reasons: string[]; as_of: number | null };
export type Clock = { phases: { name: string; about: string }[]; countries: ClockCountry[]; how: string; note: string };
export type ShortCycle = { entity: string; growth: [number, number][]; credit: [number, number][]; rate: [number, number][]; recessions: [string, string][] };

export type EpisodeCard = { id: string; title: string; kind: string; kind_name: string; nz: boolean; start: string; end: string;
  years: [number, number]; countries: string[]; country_names: string[]; summary: string;
  worst: { entity: string; name: string; fall: number } | null };
export type EpisodeList = { kinds: Record<string, string>; episodes: EpisodeCard[] };
export type EpisodeChart = { indicator: string; name: string; unit: string; freq: string;
  lines: { entity: string; name: string; points: [number, number][] }[] };
export type Episode = {
  episode: EpisodeCard & { from: number; to: number; timeline: { date: string; text: string; at: number }[];
    links: { title: string; url: string }[]; charts: string[] };
  charts: EpisodeChart[]; hit: { entity_id: string; name: string; value: number }[]; hit_how: string;
  table: { entity: string; name: string; centre: boolean; values: Record<string, { before: number | null; during: number | null; after: number | null }> }[];
  table_measures: { id: string; name: string; unit: string }[]; table_how: string;
  like: { run_up_years: [number, number]; run_up: Record<string, number>;
    measures: { id: string; name: string; unit: string; close_within: number }[];
    today: Record<string, { name: string; years: [number, number]; values: Record<string, number>; close: string[]; compared: number; likeness: number | null }>;
    similar: { id: string; title: string; years: [number, number]; likeness: number; compared: number }[]; how: string };
};
export type FoundEvent = { event_id: string; entity_id: string; name: string; source_id: string; kind: string; subkind: string | null;
  title: string; start_date: string; end_date: string | null; size: number | null; size_unit: string | null };
export type Found = { events: FoundEvent[]; waves: { year: number; kind: string; n: number; countries: string[]; episode: { id: string; title: string } | null }[]; note?: string };

export const cyclesApi = {
  arcs: (start = 1500) => get<Arcs>("/long/arcs", { start }),
  stages: (entities?: string[]) => get<Stages>("/long/stages", { entities: entities?.join(",") }),
  debt: (entity: string) => get<DebtCycle>(`/cycles/debt/${encodeURIComponent(entity)}`),
  clock: (entities?: string[]) => get<Clock>("/cycles/clock", { entities: entities?.join(",") }),
  short: (entity: string) => get<ShortCycle>(`/cycles/short/${encodeURIComponent(entity)}`),
  episodes: () => get<EpisodeList>("/episodes"),
  episode: (id: string) => get<Episode>(`/episodes/${encodeURIComponent(id)}`),
  found: (entity?: string, kinds?: string[]) => get<Found>("/episodes/found", { entity, kinds: kinds?.join(",") }),
};

export const PHASE_COLOR: Record<string, string> = { rise: "--div-pos-2", top: "--c-aus", decline: "--div-neg-2" };
export const STAGE_COLOR = ["--div-pos-3", "--div-pos-2", "--div-pos-1", "--c-aus", "--div-neg-2", "--div-neg-3"];
const yearLabel = (v: number) => (v < 0 ? `${-v} BC` : `${Math.round(v)}`);

// ------------------------------------------------------------------ rise and decline
export function arcsOption(lines: Arc[], pick: string | null, aligned: boolean): EChartsOption {
  const base = chrome();
  const colors = entityColors(lines.map((l) => l.entity));
  const shift = (l: Arc) => (aligned && l.peak ? l.peak[0] : 0);
  const series: SeriesOption[] = lines.map((l, i) => {
    const on = !pick || pick === l.entity;
    const s = shift(l);
    const out: SeriesOption = {
      type: "line", name: l.name, showSymbol: false, color: colors[i], triggerLineEvent: true,
      lineStyle: { width: pick === l.entity ? 3 : 1.5, opacity: on ? 1 : 0.35 }, emphasis: { focus: "series" },
      data: l.points.map(([y, v]) => [y - s, +(100 * v).toFixed(2), y]),
    };
    if (pick === l.entity) {
      (out as { markArea?: object }).markArea = { silent: true, label: { show: true, position: "insideTop", color: cssVar("--muted"), fontSize: 10 },
        data: l.phases.map((p) => [{ xAxis: p.from - s, name: p.phase, itemStyle: { color: cssVar(PHASE_COLOR[p.phase]), opacity: 0.16 } }, { xAxis: p.to - s }]) };
    }
    return out;
  });
  const picked = lines.find((l) => l.entity === pick);
  if (picked) {
    const s = shift(picked);
    series.push({ type: "scatter", name: "Crises", symbol: "triangle", symbolSize: 8, color: cssVar("--warn-ink", "#c26a1b"),
      data: picked.crises.map((c) => ({ value: [c.from - s, 0], name: `${c.from}${c.to !== c.from ? `-${c.to}` : ""}: ${c.name}` })),
      tooltip: { trigger: "item", formatter: (p: unknown) => (p as { name: string }).name } });
    series.push({ type: "scatter", name: "Wars", symbol: "rect", symbolSize: [6, 10], color: cssVar("--muted"),
      data: picked.wars.map((w) => ({ value: [w.from - s, 1.2], name: `${w.from}-${w.to}: ${w.title}` })),
      tooltip: { trigger: "item", formatter: (p: unknown) => (p as { name: string }).name } });
  }
  return {
    ...base,
    legend: { top: 0, left: 0, type: "scroll", textStyle: { color: cssVar("--ink-2") } },
    grid: { left: 8, right: 16, top: 48, bottom: 8, containLabel: true },
    xAxis: { type: "value", scale: true, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => (aligned ? (v === 0 ? "peak" : `${v > 0 ? "+" : ""}${v} yrs`) : yearLabel(v)) },
      splitLine: { show: false }, ...(aligned ? { min: -300, max: 300 } : {}) },
    yAxis: { type: "value", min: 0, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => `${v}%` }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
    tooltip: { trigger: "item", backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"), textStyle: { color: cssVar("--ink") },
      formatter: (p: unknown) => {
        const q = p as { seriesName: string; data: [number, number, number] | { name: string } };
        if (!Array.isArray(q.data)) return q.data.name;
        return `<b>${q.seriesName}</b><br/>${yearLabel(q.data[2])}: ${q.data[1].toFixed(1)}% of the ten powers' total`;
      } },
    series,
  };
}

// ------------------------------------------------------------------ long-term debt cycle
export function debtOption(d: DebtCycle, withRate: boolean): EChartsOption {
  const base = chrome();
  const series: SeriesOption[] = [{
    type: "line", name: "Government debt, % of GDP", showSymbol: false, color: cssVar("--ink"), lineStyle: { width: 2 },
    areaStyle: { opacity: 0.08 }, data: d.debt,
    markArea: { silent: false, label: { show: false }, emphasis: { label: { show: true, position: "insideTop", color: cssVar("--ink"), formatter: (p: { name: string }) => p.name } },
      itemStyle: { color: cssVar("--band", "rgba(160,160,160,0.22)") },
      data: d.wars.map((w) => [{ xAxis: w.from - 0.5, name: w.title }, { xAxis: w.to + 0.5 }]) as never },
  }];
  series.push({ type: "scatter", name: "Crises", symbol: "triangle", symbolSize: 8, color: cssVar("--warn-ink", "#c26a1b"),
    data: d.crises.map((c) => ({ value: [c.from, 0], name: `${c.from}${c.to !== c.from ? `-${c.to}` : ""}: ${c.name}` })),
    tooltip: { trigger: "item", formatter: (p: unknown) => (p as { name: string }).name } });
  if (withRate && d.real_rate.length) {
    series.push({ type: "line", name: "Real interest rate, %", yAxisIndex: 1, showSymbol: false, color: cssVar("--c-usa", "#1f5fa8"),
      lineStyle: { width: 1.5, type: "dashed" }, data: d.real_rate });
  }
  return {
    ...base,
    legend: { top: 0, left: 0, textStyle: { color: cssVar("--ink-2") } },
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    xAxis: { type: "value", scale: true, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => `${v}` }, splitLine: { show: false } },
    yAxis: [{ type: "value", min: 0, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => `${v}%` }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
      { type: "value", show: withRate && d.real_rate.length > 0, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => `${v}%` }, splitLine: { show: false } }],
    tooltip: { ...(base.tooltip as object), trigger: "axis", valueFormatter: (v: unknown) => `${Number(v).toFixed(0)}%` },
    series,
  };
}

// ------------------------------------------------------------------ short-term cycle over time
export function shortOption(s: ShortCycle): EChartsOption {
  const base = chrome();
  const toYear = (iso: string) => +iso.slice(0, 4) + (+iso.slice(5, 7) - 1) / 12;
  return {
    ...base,
    legend: { top: 0, left: 0, textStyle: { color: cssVar("--ink-2") } },
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    xAxis: { type: "value", scale: true, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => `${v}` }, splitLine: { show: false } },
    yAxis: [{ type: "value", axisLabel: { color: cssVar("--muted"), formatter: (v: number) => `${v}%` }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
      { type: "value", axisLabel: { color: cssVar("--muted"), formatter: (v: number) => `${v}%` }, splitLine: { show: false } }],
    tooltip: { ...(base.tooltip as object), trigger: "axis", valueFormatter: (v: unknown) => `${Number(v).toFixed(1)}%` },
    series: [
      { type: "bar", name: "Growth", data: s.growth, itemStyle: { color: cssVar("--series-1") }, barMaxWidth: 8,
        markArea: { silent: true, itemStyle: { color: cssVar("--div-neg-3"), opacity: 0.1 },
          data: s.recessions.map(([a, b]) => [{ xAxis: toYear(a) - 0.5 }, { xAxis: toYear(b) + 0.5 }]) as never } },
      { type: "line", name: "Central bank rate", showSymbol: false, data: s.rate, color: cssVar("--ink"), lineStyle: { width: 1.5 } },
      { type: "line", name: "Private credit (% of GDP, right)", yAxisIndex: 1, showSymbol: false, data: s.credit, color: cssVar("--c-aus", "#c9a227"), lineStyle: { width: 2, type: "dashed" } },
    ],
  };
}

// ------------------------------------------------------------------ an episode's chart
export function episodeOption(c: EpisodeChart, from: number, to: number, timeline: { at: number; text: string }[], centre: string[]): EChartsOption {
  const base = chrome();
  const colors = entityColors(c.lines.map((l) => l.entity));
  const sub = c.freq !== "A";
  // A yearly value sits on its year, so the band runs from half a year before the start.
  const shade = sub ? [from, to] : [Math.floor(from) - 0.5, Math.ceil(to) - 0.5];
  const series: SeriesOption[] = c.lines.map((l, i) => ({
    type: "line", name: l.name, showSymbol: !sub && l.points.length < 25, symbolSize: 4, color: colors[i],
    lineStyle: { width: centre.includes(l.entity) || l.entity === "world" ? 2 : 1.2, opacity: centre.includes(l.entity) || ["NZL", "world"].includes(l.entity) ? 1 : 0.55 },
    data: l.points,
    ...(i === 0 ? { markArea: { silent: true, itemStyle: { color: cssVar("--div-neg-3"), opacity: 0.08 }, data: [[{ xAxis: shade[0] }, { xAxis: shade[1] }]] as never },
      markLine: { symbol: "none", silent: false, label: { show: false }, lineStyle: { color: cssVar("--muted"), type: "dotted" },
        emphasis: { label: { show: true, formatter: (p: { name: string }) => p.name, color: cssVar("--ink"), backgroundColor: cssVar("--surface"), padding: [2, 4] } },
        data: timeline.filter((t) => t.at >= shade[0] - 1).map((t) => ({ xAxis: t.at, name: t.text.length > 60 ? `${t.text.slice(0, 59)}…` : t.text })) } } : {}),
  }));
  return {
    ...base,
    legend: { top: 0, left: 0, type: "scroll", textStyle: { color: cssVar("--ink-2") } },
    grid: { left: 8, right: 16, top: 40, bottom: 8, containLabel: true },
    xAxis: { type: "value", scale: true, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => `${Math.round(v)}` }, splitLine: { show: false }, minInterval: 1 },
    yAxis: { type: "value", scale: !/growth|rate/.test(c.indicator), axisLabel: { color: cssVar("--muted") }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
    tooltip: { ...(base.tooltip as object), trigger: "axis", valueFormatter: (v: unknown) => Number(v).toFixed(1),
      axisPointer: { type: "line" } },
    series,
  };
}

export const fmt1 = (v: number | null | undefined) => (v === null || v === undefined ? "–" : v.toFixed(1));
