// The Outlook page's data: recession odds, nowcasts, the release calendar and Wikipedia attention.

import type { EChartsOption } from "echarts";
import { get } from "@/lib/api";
import { chrome } from "@/lib/charts";
import { cssVar as cv } from "@/lib/colors";

const cssVar = (name: string, fallback = "") => cv(name) || fallback;

export type Driver = { feature: string; about: string; value: number; unit: string; push: number };
export type Odds = {
  entity: string; name: string; odds: number | null; model: "full" | "no_cli" | "gdp" | null; month: string | null;
  history: [string, number][]; recessions: [string, string][]; drivers: Driver[]; in_recession: boolean;
  yield_curve?: { odds: number; spread: number; month: string; history: [string, number][] };
};
export type ModelAbout = { months: number; recessions: number; base_rate: number; auc: number | null; features: string[] };
export type OddsReply = { countries: Odds[]; models: Record<string, ModelAbout>; note: string };
export type OddsAll = { countries: { entity: string; name: string; odds: number; month: string; model: string; in_recession: boolean }[];
  models: Record<string, ModelAbout> };
export type Nowcast = {
  entity: string; quarter: string | null; estimate: number | null; low?: number | null; high?: number | null;
  annualised?: number; typical_error?: number | null; months_used?: number; uses_cli?: boolean;
  last_quarter?: string; last_actual?: number; note?: string;
  track?: { quarter: string; estimate: number; actual: number }[];
  gdpnow?: { quarter: string; annualised: number; quarterly: number };
};
export type Release = {
  country: string; title: string; date: string; time: string; tz: string; kind: string; kind_name: string; period: string;
  indicator: string; url: string; estimated: boolean; from: string; nz_time: string; nz_date: string; past: boolean;
  expected?: { value: number; what: string };
};
export type Calendar = { items: Release[]; notes: string[]; today: string };
export type Attention = {
  entity: string; article?: string; points: [string, number][]; latest?: number | null; latest_day?: string; usual?: number | null;
  week_avg?: number | null; ratio?: number | null; spikes?: { day: string; views: number; times: number }[]; note?: string;
};
export type AttentionTop = {
  day: string | null; countries: { entity: string; name: string; article: string; views: number; rank: number }[]; note?: string;
  key: (Omit<Attention, "points"> & { name: string; points: [string, number][] })[];
};

export const outlookApi = {
  odds: (entities?: string[]) => get<OddsReply>("/outlook/recession", { entities: entities?.join(",") }),
  oddsAll: () => get<OddsAll>("/outlook/recession/all"),
  nowcast: (entity: string) => get<Nowcast>(`/outlook/nowcast/${encodeURIComponent(entity)}`),
  calendar: (countries?: string[], daysAhead = 42) => get<Calendar>("/outlook/calendar", { countries: countries?.join(","), days_ahead: daysAhead }),
  attention: (entity: string) => get<Attention>(`/attention/${encodeURIComponent(entity)}`),
  attentionTop: () => get<AttentionTop>("/attention/top"),
};

export const MODEL_NAMES: Record<string, string> = {
  full: "leading indicator, rate changes and growth", no_cli: "rate changes and growth (no leading indicator for this country)",
  gdp: "growth only (no leading indicator or central bank rate)",
};

// A word for odds of a recession starting within a year.
export function oddsWord(p: number | null): string {
  if (p === null) return "no reading";
  return p < 10 ? "low" : p < 25 ? "moderate" : p < 50 ? "raised" : "high";
}

export function oddsTone(p: number | null): string {
  if (p === null) return cssVar("--muted");
  return p < 10 ? cssVar("--good", "#3c7d4d") : p < 25 ? cssVar("--c-aus", "#c9a227") : p < 50 ? cssVar("--warn-ink", "#c26a1b") : cssVar("--bad", "#b23a3a");
}

const day = (m: string) => (m.length === 7 ? `${m}-01` : m);

// The odds over time, recessions shaded, and for the US the yield-curve model beside it.
export function oddsOption(o: Odds): EChartsOption {
  const base = chrome();
  const lines: EChartsOption["series"] = [
    { type: "line", name: "Odds (this app's model)", showSymbol: false, lineStyle: { width: 2 }, color: cssVar("--ink"),
      data: o.history.map(([m, v]) => [day(m), v]),
      markArea: { silent: true, label: { show: false }, itemStyle: { color: cssVar("--band", "rgba(160,160,160,0.22)") },
        data: o.recessions.map(([a, b]) => [{ xAxis: day(a) }, { xAxis: day(b) }]) as never } },
  ];
  if (o.yield_curve) {
    lines.push({ type: "line", name: "Odds (New York Fed yield-curve model)", showSymbol: false, lineStyle: { width: 1.5, type: "dashed" },
      color: cssVar("--c-usa", "#1f5fa8"), data: o.yield_curve.history.map(([m, v]) => [day(m), v]) });
  }
  return {
    ...base,
    legend: o.yield_curve ? { top: 0, left: 0, textStyle: { color: cssVar("--ink-2") } } : undefined,
    grid: { left: 8, right: 16, top: o.yield_curve ? 40 : 24, bottom: 8, containLabel: true },
    xAxis: { type: "time", axisLabel: { color: cssVar("--muted") }, axisLine: { lineStyle: { color: cssVar("--axis") } } },
    yAxis: { type: "value", min: 0, max: 100, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => `${v}%` }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
    tooltip: { ...(base.tooltip as object), valueFormatter: (v: unknown) => `${Number(v).toFixed(0)}%` },
    series: lines,
  };
}

// Each of the last quarters: what the method said beforehand against what came out.
export function trackOption(n: Nowcast): EChartsOption {
  const base = chrome();
  const t = n.track ?? [];
  return {
    ...base,
    legend: { top: 0, left: 0, textStyle: { color: cssVar("--ink-2") } },
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: t.map((x) => x.quarter), axisLabel: { color: cssVar("--muted"), rotate: 45, fontSize: 10 } },
    yAxis: { type: "value", axisLabel: { color: cssVar("--muted"), formatter: (v: number) => `${v}%` }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
    tooltip: { ...(base.tooltip as object), trigger: "axis", valueFormatter: (v: unknown) => `${Number(v).toFixed(1)}%` },
    series: [
      { type: "bar", name: "Actual growth on the quarter", data: t.map((x) => x.actual), itemStyle: { color: cssVar("--series-1") } },
      { type: "line", name: "Nowcast beforehand", data: t.map((x) => x.estimate), color: cssVar("--ink"), symbolSize: 5 },
    ],
  };
}

// Views a day, with the usual level dashed.
export function viewsOption(a: Attention, color?: string): EChartsOption {
  const base = chrome();
  return {
    ...base,
    grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
    xAxis: { type: "time", axisLabel: { color: cssVar("--muted") }, axisLine: { lineStyle: { color: cssVar("--axis") } } },
    yAxis: { type: "value", name: "views a day", nameTextStyle: { color: cssVar("--muted"), align: "left" },
      axisLabel: { color: cssVar("--muted") }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
    tooltip: { ...(base.tooltip as object), valueFormatter: (v: unknown) => Number(v).toLocaleString() },
    series: [{ type: "line", name: "Views", showSymbol: false, color: color ?? cssVar("--series-1"), lineStyle: { width: 2 },
      areaStyle: { opacity: 0.12 }, data: a.points,
      markLine: a.usual ? { symbol: "none", silent: true, label: { formatter: "usual", position: "insideEndTop", color: cssVar("--muted") },
        lineStyle: { type: "dashed", color: cssVar("--muted") }, data: [{ yAxis: a.usual }] } : undefined,
      markPoint: a.spikes?.length ? { symbol: "circle", symbolSize: 8, itemStyle: { color: cssVar("--bad", "#b23a3a") },
        label: { show: false }, data: a.spikes.map((s) => ({ coord: [s.day, s.views], name: `${s.times}× usual` })) } : undefined }],
  };
}

export const fmtPct = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(d)}%`);
