// Predictions and crowd forecasts: types and calls for the Predictions and Crowd pages, the
// country card, the chart Predict button and the Briefing, and the chart options they share.

import type { EChartsOption } from "echarts";
import { get, send } from "@/lib/api";
import { chrome } from "@/lib/charts";
import { cssVar, seriesColor } from "@/lib/colors";

export type PredKind = "binary" | "number" | "date";
export type WhoKind = "you" | "expert" | "app" | "crowd";
export type Outcome = { actual: boolean | number | string; at: string; by: string };
export type Score = { hit?: boolean | null; brier?: number; miss?: number; rel_miss?: number | null; yes?: boolean };
export type Prediction = {
  id: string; question: string; kind: PredKind; who_kind: WhoKind; who: string; link: string | null; made: string; due: string;
  category: string | null; tags: string[]; why: string | null; indicator: string | null; entity: string | null; year: number | null;
  crowd_key: string | null; unit: string | null; chance?: number; value?: number | null; low?: number | null; high?: number | null;
  date_call?: string; window_days?: number; outcome: Outcome | null; state?: "open" | "due" | "settled"; score?: Score;
};
export type PredictionDraft = Partial<Prediction> & { model?: string };
export type PredList = { items: Prediction[]; who: string[]; categories: string[] };
export type ScoreRow = { name: string; kind: WhoKind; n: number; settled: number; hits: number; scored_hits: number;
  hit_rate: number | null; brier: number | null; brier_n: number; rel_miss: number | null;
  calibration: { from: number; to: number; n: number; forecast: number; observed: number }[] };
export type Preset = { id: string; title: string; kind: "event" | "rule"; event?: string; indicator?: string; if_op?: string;
  if_value?: number; then_op?: string; then_value?: number; within?: number };
export type BaseRate = {
  kind: "event" | "rule"; title: string; preset: string | null; start: number; cases: number; rate: number | null;
  // event
  event?: string; end?: number; countries?: number; country_years?: number; within?: number; chance_within?: number | null;
  by_decade?: { decade: number; cases: number; rate: number | null }[]; top?: { entity_id: string; cases: number }[];
  examples?: { entity_id: string; year: number; title?: string; value?: number; then_year?: number | null; then_value?: number | null }[];
  // rule
  indicator?: string; if_op?: string; if_value?: number; then_op?: string; then_value?: number; happened?: number;
};
export type Watch = { id: string; kind: "indicator" | "crowd" | "forecast"; note: string | null; indicator?: string; entity?: string;
  op?: "above" | "below"; threshold?: number; question_key?: string; points?: number | null;
  alert: boolean; text: string; date: string | null; title?: string; chance?: number; move?: number };

export type CrowdQ = {
  question_key: string; site: string; site_name: string; title: string; url: string | null; kind: string; category: string | null;
  countries: string[]; indicator_id: string | null; created: string | null; closes: string | null; resolved_at: string | null;
  status: string; resolution: string | null; chance: number | null; change: number | null; volume: number | null;
  forecasters: number | null; comments: number | null; options: { name: string; chance: number }[] | null;
  followed?: boolean; hidden?: boolean;
};
export type CrowdList = { total: number; items: CrowdQ[]; counts: { site: string; status: string; n: number }[]; days: number;
  categories: Record<string, string>; sites: Record<string, string>; loaded: boolean };
export type CrowdPoint = { at: string; chance: number; lower: number | null; upper: number | null; origin: string };
export type CrowdComment = { comment_id: string; parent_id: string | null; author: string; created: string | null; votes: number | null;
  forecast: number | null; text: string };
export type CrowdDetail = CrowdQ & {
  description: string | null; points: CrowdPoint[]; mine: { forecaster: string; at: string; chance: number; community: number | null }[];
  comment_list: CrowdComment[]; similar: CrowdQ[]; events: { event_id: string; entity_id: string; kind: string; title: string; start_date: string }[];
  predictions: Prediction[];
};
export type CrowdEvents = { score_days: number; n: number;
  items: { question_key: string; site_name: string; title: string; url: string | null; category: string | null; countries: string[];
    resolution: string; closed: string; chance: number | null; brier: number | null; first_right: string | null; lead_days: number | null;
    surprise: boolean }[];
  by_category: { key: string; n: number; brier: number | null; surprises: number; median_lead: number | null }[];
  by_site: { key: string; n: number; brier: number | null; surprises: number; median_lead: number | null }[] };
export type CrowdCountry = { entity_id: string; questions: CrowdQ[];
  views: { months: { month: string; deaths: number | null; chance_25: number | null }[]; deaths_12: number; max_chance: number } | null };
export type ConflictRow = { entity_id: string; deaths: number; chance: number; first: string; run: string };

export const pred = {
  list: (f: Record<string, string | undefined> = {}) => get<PredList>("/predictions", f),
  add: (p: Partial<Prediction>) => send<Prediction>("POST", "/predictions", p),
  edit: (id: string, p: Partial<Prediction>) => send<Prediction>("PUT", `/predictions/${id}`, p),
  remove: (id: string) => send<{ deleted: string }>("DELETE", `/predictions/${id}`),
  outcome: (id: string, actual: boolean | number | string | null) => send<Prediction>("POST", `/predictions/${id}/outcome`, { actual }),
  scorecard: (f: Record<string, string | undefined> = {}) => get<{ score_days: number; rows: ScoreRow[] }>("/predictions/scorecard", f),
  draft: (body: { url?: string; text?: string }) => send<PredictionDraft>("POST", "/predictions/draft", body),
  presets: () => get<{ presets: Preset[]; event_kinds: { kind: string; label: string }[] }>("/predictions/base-rates"),
  baseRate: (q: Record<string, string | number | undefined>) => get<BaseRate>("/predictions/base-rate", q),
  watchlist: () => get<{ on: boolean; items: Watch[] }>("/watchlist"),
  addWatch: (w: Partial<Watch>) => send<Watch>("POST", "/watchlist", w),
  removeWatch: (id: string) => send<{ deleted: string }>("DELETE", `/watchlist/${id}`),
};

export const crowdApi = {
  list: (q: Record<string, string | number | undefined> = {}) => get<CrowdList>("/crowd", q),
  question: (key: string) => get<CrowdDetail>("/crowd/question", { key }),
  follow: (key: string, body: { follow?: boolean; hide?: boolean }) =>
    send<{ follow: string[]; hide: string[] }>("POST", "/crowd/follow", { key, ...body }),
  moves: (q: Record<string, string | number | undefined> = {}) => get<CrowdQ[]>("/crowd/moves", q),
  events: () => get<CrowdEvents>("/crowd/events"),
  country: (id: string) => get<CrowdCountry>(`/crowd/country/${id}`),
  conflict: () => get<{ rows: ConflictRow[] }>("/crowd/conflict"),
};

export const pct = (v: number | null | undefined, d = 0) => (v == null ? "–" : `${(v * 100).toFixed(d)}%`);
export const pts = (v: number | null | undefined) => (v == null || Math.abs(v) < 0.005 ? "" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(0)} pts`);
export const CATEGORY_TEXT: Record<string, string> = { politics: "Politics", economics: "Economics", geopolitics: "Geopolitics",
  climate: "Climate", science: "Science and technology" };
export const WHO_TEXT: Record<WhoKind, string> = { you: "You", expert: "Experts", app: "The app", crowd: "Crowd sites" };

/** What a prediction says, in a few words: "70% yes", "2.4 (2 to 3)", "around 2027-03-01". */
export function callText(p: Prediction): string {
  if (p.kind === "binary") return `${pct(p.chance)} yes`;
  if (p.kind === "number") return `${p.value}${p.unit ? ` ${p.unit}` : ""}${p.low != null && p.high != null ? ` (${p.low} to ${p.high})` : ""}`;
  return `around ${p.date_call}${p.window_days ? ` (±${p.window_days} days)` : ""}`;
}

export function outcomeText(p: Prediction): string {
  if (!p.outcome) return "";
  const a = p.outcome.actual;
  return typeof a === "boolean" ? (a ? "Yes" : "No") : String(a);
}

/** A question's chance over time, one line per origin (the site's history and the app's saves),
 *  your Metaculus forecasts as dots and events as marks. */
export function chanceOption(d: CrowdDetail): EChartsOption {
  const base = chrome();
  const byOrigin: Record<string, [number, number][]> = {};
  for (const p of d.points) (byOrigin[p.origin] ??= []).push([Date.parse(p.at), p.chance * 100]);
  const names: Record<string, string> = { site: `${d.site_name}'s own history`, refresh: "Saved at each refresh" };
  const series: EChartsOption["series"] = Object.entries(byOrigin).map(([o, data], i) => ({
    type: "line", name: names[o] ?? o, data, showSymbol: data.length < 30, symbolSize: 5, step: o === "refresh" ? "end" : undefined,
    lineStyle: { width: 2, type: o === "refresh" ? "dashed" : "solid" }, itemStyle: { color: seriesColor(i) },
    markLine: i === 0 ? { symbol: "none", silent: true, label: { show: false }, lineStyle: { color: cssVar("--axis"), type: "dotted" },
      data: [{ yAxis: 50 }] } : undefined,
  }));
  const byWho: Record<string, [number, number][]> = {};
  for (const m of d.mine) (byWho[m.forecaster] ??= []).push([Date.parse(m.at), m.chance * 100]);
  Object.entries(byWho).forEach(([who, data], i) => series.push({ type: "scatter", name: `${who} (yours)`, data, symbolSize: 9,
    itemStyle: { color: seriesColor(4 + i) } }));
  if (d.events.length) {
    series.push({ type: "scatter", name: "Events", data: d.events.map((e) => [Date.parse(e.start_date), 2, e.title]), symbol: "triangle",
      symbolSize: 9, itemStyle: { color: cssVar("--muted") },
      tooltip: { trigger: "item", formatter: (p) => { const v = (p as unknown as { value: [number, number, string] }).value; return `${new Date(v[0]).toISOString().slice(0, 10)}: ${v[2]}`; } } });
  }
  return {
    ...base, legend: { top: 0, textStyle: { color: cssVar("--ink-2") } },
    xAxis: { type: "time", axisLabel: { color: cssVar("--muted") }, axisLine: { lineStyle: { color: cssVar("--axis") } } },
    yAxis: { type: "value", min: 0, max: 100, axisLabel: { color: cssVar("--muted"), formatter: "{value}%" },
      splitLine: { lineStyle: { color: cssVar("--grid") } } },
    tooltip: { ...(base.tooltip as object), valueFormatter: (v) => (typeof v === "number" ? `${v.toFixed(0)}%` : String(v)) },
    series,
  };
}

/** Calibration: for each tenth of chance given, how often it happened (a perfect forecaster sits on the diagonal). */
export function calibrationOption(rows: ScoreRow[]): EChartsOption {
  const base = chrome();
  return {
    ...base, legend: { top: 0, textStyle: { color: cssVar("--ink-2") } },
    xAxis: { type: "value", min: 0, max: 100, name: "Chance given", nameLocation: "middle", nameGap: 24, axisLabel: { formatter: "{value}%", color: cssVar("--muted") } },
    yAxis: { type: "value", min: 0, max: 100, name: "Happened", axisLabel: { formatter: "{value}%", color: cssVar("--muted") },
      splitLine: { lineStyle: { color: cssVar("--grid") } } },
    tooltip: { trigger: "item", backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"), textStyle: { color: cssVar("--ink") },
      formatter: (p) => { const v = (p as { seriesName: string; value: number[] }); return `${v.seriesName}: said ${v.value[0].toFixed(0)}%, happened ${v.value[1].toFixed(0)}% (${v.value[2]} calls)`; } },
    series: [
      { type: "line", name: "Perfect", data: [[0, 0], [100, 100]], showSymbol: false, silent: true, lineStyle: { type: "dotted", color: cssVar("--axis") } },
      ...rows.filter((r) => r.calibration.length).map((r, i) => ({
        type: "line" as const, name: r.name, data: r.calibration.map((c) => [c.forecast * 100, c.observed * 100, c.n]),
        symbolSize: (v: number[]) => Math.min(18, 5 + Math.sqrt(v[2]) * 2), itemStyle: { color: seriesColor(i) },
      })),
    ],
  };
}

// Your number predictions on an indicator, shared by every chart on a page (read at most every 30 s).
let cache: { at: number; list: Promise<Prediction[]> } | null = null;
export function chartPredictions(): Promise<Prediction[]> {
  if (!cache || Date.now() - cache.at > 30_000) cache = { at: Date.now(), list: pred.list().then((l) => l.items).catch(() => []) };
  return cache.list;
}
export function forgetChartPredictions() { cache = null; }

/** Predictions as dots on a year chart: the call at its year, and a whisker for its range. */
export function predictionSeries(ps: Prediction[], names: Map<string, string>): object[] {
  if (!ps.length) return [];
  return [{
    type: "scatter", name: "Predictions", symbol: "diamond", symbolSize: 10, z: 5,
    itemStyle: { color: cssVar("--ink-2"), borderColor: cssVar("--surface"), borderWidth: 1 },
    data: ps.map((p) => ({ value: [p.year, p.value], name: `${p.who}: ${p.value}${p.low != null && p.high != null ? ` (${p.low} to ${p.high})` : ""} for ${names.get(p.entity ?? "") ?? p.entity} in ${p.year}${p.outcome ? `, outcome ${p.outcome.actual}` : ""}` })),
    tooltip: { trigger: "item", formatter: (x: { name: string }) => x.name },
  }, {
    type: "line", name: "Prediction ranges", silent: true, showSymbol: false, connectNulls: false,
    lineStyle: { color: cssVar("--ink-2"), width: 1 },
    data: ps.filter((p) => p.low != null && p.high != null).flatMap((p) => [[p.year, p.low], [p.year, p.high], [null, null]]),
    tooltip: { show: false },
  }];
}
