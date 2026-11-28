// Inventions over time (Explore > Inventions): types, calls and chart options.
// The charts show changes seen around an invention, never that it caused them.

import type { EChartsOption, SeriesOption } from "echarts";
import { get } from "@/lib/api";
import { chrome } from "@/lib/charts";
import { cssVar } from "@/lib/colors";
import { compact } from "@/lib/format";
import { entityColors } from "@/lib/look";

export type Invention = { id: string; name: string; year: number; approx: boolean; category: string; category_name: string;
  place: string | null; where: string | null; who: string | null; what: string; link: string | null; wiki: string | null;
  spread: string[]; related: string[] };
export type Extra = { id: string; name: string; year: number; where: string | null; links: number; url: string };
export type Measure = { series: string; name: string; unit: string; source: string | null; us_only: boolean; long: boolean };
export type InventionList = { categories: { id: string; name: string }[]; inventions: Invention[]; extras: Extra[];
  measures: Measure[]; caution: string };
export type Line = { entity: string; name: string; points: [number, number][] };
export type Other = { id: string; name: string; year: number; category: string };
export type InventionChart = { series: string; name: string; unit: string; source: string | null; kind: "spread" | "related";
  lines: Line[]; others: Other[] };
export type InventionCard = { invention: Invention; entities: string[]; charts: InventionChart[]; caution: string;
  before: { id: string; name: string; year: number } | null; after: { id: string; name: string; year: number } | null };
export type Along = { series: string; name: string; unit: string; source: string | null; lines: Line[]; caution: string;
  inventions: (Other & { category_name: string; linked: boolean })[] };

export const inventionsApi = {
  list: () => get<InventionList>("/inventions"),
  card: (id: string, entities?: string[]) => get<InventionCard>(`/inventions/${encodeURIComponent(id)}`, { entities: entities?.join(",") }),
  along: (series: string, entities?: string[], categories?: string[]) =>
    get<Along>("/inventions/along", { series, entities: entities?.join(","), categories: categories?.join(",") }),
};

// One strong colour per category, the same on the timeline, chips and chart lines.
export const CATEGORY_COLOR: Record<string, string> = {
  energy: "--series-4", transport: "--series-1", medicine: "--series-8", communication: "--series-7", food: "--series-6",
  computing: "--series-3", materials: "--series-2", science: "--div-pos-2", home: "--series-5", money: "--ink-2",
};
export const catVar = (c: string) => `var(${CATEGORY_COLOR[c] ?? "--muted"})`;
export const catColor = (c: string) => cssVar(CATEGORY_COLOR[c] ?? "--muted");

export function yearText(y: number, approx = false): string {
  const c = approx ? "c. " : "";
  if (y <= -10000) return `${c}${compact(-y)} years ago`.replace(/^c\. /, "about ");
  if (y < 0) return `${c}${(-y).toLocaleString()} BC`;
  return y < 1000 ? `${c}AD ${y}` : `${c}${y}`;
}

// "All time" squeezes the years before 1500 so the crowded recent centuries stay readable:
// x = year from 1500 on; before that, 150 units for each tenfold step back in time.
export const SQUEEZE_FROM = 1500;
export function squeeze(y: number): number {
  return y >= SQUEEZE_FROM ? y : SQUEEZE_FROM - 150 * Math.log10(1 + (SQUEEZE_FROM - y) / 10);
}
export function unsqueeze(x: number): number {
  return x >= SQUEEZE_FROM ? x : SQUEEZE_FROM - 10 * (Math.pow(10, (SQUEEZE_FROM - x) / 150) - 1);
}
function roundYear(y: number): string {
  if (y >= SQUEEZE_FROM) return String(Math.round(y));
  const mag = Math.pow(10, Math.max(1, Math.floor(Math.log10(Math.abs(y) + 1)) - 0));
  return yearText(Math.round(y / mag) * mag);
}

export type Dot = { id: string; name: string; year: number; category: string; extra?: boolean; approx?: boolean };

// The timeline: one lane per category, a dot per invention, names next to the larger dots.
export function timelineOption(dots: Dot[], cats: { id: string; name: string }[], range: [number, number], squeezed: boolean,
  selected: string | null): EChartsOption {
  const base = chrome();
  const lane = new Map(cats.map((c, i) => [c.id, i]));
  const X = (y: number) => (squeezed ? squeeze(y) : y);
  const inRange = dots.filter((d) => d.year >= range[0] && d.year <= range[1] && lane.has(d.category));
  const typed = inRange.filter((d) => !d.extra);
  const extra = inRange.filter((d) => d.extra);
  // Stagger labels within a lane so neighbours do not sit on each other.
  const lastAt = new Map<number, number[]>();
  const span = X(range[1]) - X(range[0]);
  const labelled = typed.map((d) => {
    const l = lane.get(d.category)!;
    const x = X(d.year);
    const rows = lastAt.get(l) ?? [-Infinity, -Infinity];
    const gap = span / 9;
    let row = -1;
    if (x - rows[0] > gap) row = 0; else if (x - rows[1] > gap) row = 1;
    if (row >= 0) rows[row] = x;
    lastAt.set(l, rows);
    return { d, l, x, row };
  });
  const series: SeriesOption[] = [
    { type: "scatter", id: "extra", name: "From Wikidata", symbolSize: 5, z: 1,
      itemStyle: { color: cssVar("--muted"), opacity: 0.45 },
      symbolOffset: [0, 9],
      data: extra.map((d) => ({ value: [X(d.year), lane.get(d.category)!], name: d.name, id: d.id, year: d.year })) },
    { type: "scatter", id: "typed", name: "Inventions", z: 3,
      data: labelled.map(({ d, l, x, row }) => ({
        value: [x, l], name: d.name, id: d.id, year: d.year, approx: d.approx,
        symbolSize: selected === d.id ? 15 : 10,
        itemStyle: { color: catColor(d.category), borderColor: selected === d.id ? cssVar("--ink") : "transparent", borderWidth: 2 },
        label: { show: row >= 0, position: row === 0 ? "top" : "bottom", distance: 4, fontSize: 10.5, color: cssVar("--ink-2"),
          formatter: () => (d.name.length > 24 ? `${d.name.slice(0, 23)}…` : d.name) },
      })) },
  ];
  return {
    ...base,
    grid: { left: 8, right: 24, top: 16, bottom: 44, containLabel: true },
    tooltip: { ...(base.tooltip as object), trigger: "item",
      formatter: (p: unknown) => {
        const q = p as { data: { name: string; year: number; approx?: boolean }; seriesId: string };
        return `<b>${q.data.name}</b><br/>${yearText(q.data.year, q.data.approx)}${q.seriesId === "extra" ? "<br/><span style='opacity:.7'>From Wikidata, unchecked</span>" : ""}`;
      } },
    xAxis: { type: "value", min: X(range[0]), max: X(range[1]), splitLine: { show: true, lineStyle: { color: cssVar("--grid") } },
      axisLabel: { color: cssVar("--muted"), hideOverlap: true, formatter: (v: number) => (squeezed ? roundYear(unsqueeze(v)) : yearText(Math.round(v))) } },
    yAxis: { type: "category", data: cats.map((c) => c.name), inverse: true, axisTick: { show: false },
      axisLine: { show: false }, axisLabel: { color: cssVar("--ink-2") },
      splitLine: { show: false } },
    dataZoom: [{ type: "slider", xAxisIndex: 0, height: 18, bottom: 6, filterMode: "none", labelFormatter: () => "" }, { type: "inside", xAxisIndex: 0, filterMode: "none" }],
    series,
  };
}

// A chart on a card or the "Changes over time" tab: the lines, the invention's year marked, and
// other inventions as faint dotted lines named on hover.
export function inventionChartOption(lines: Line[], unit: string, mark: { year: number; name: string; category: string } | null,
  others: (Other & { linked?: boolean })[], showOthers: boolean, startAt?: number): EChartsOption {
  const base = chrome();
  const colors = entityColors(lines.map((l) => l.entity));
  const first = Math.min(...lines.map((l) => l.points[0]?.[0] ?? Infinity));
  const last = Math.max(...lines.map((l) => l.points[l.points.length - 1]?.[0] ?? -Infinity));
  const from = startAt !== undefined && Number.isFinite(first) ? Math.max(first, startAt) : first;
  const marks: object[] = [];
  if (mark && Number.isFinite(first)) {
    marks.push({ xAxis: mark.year, name: `${mark.name} (${yearText(mark.year)})`,
      lineStyle: { color: catColor(mark.category), type: "dashed", width: 2 },
      label: { show: true, position: "insideEndTop", formatter: () => yearText(mark.year), color: catColor(mark.category), fontSize: 11 } });
  }
  if (showOthers) {
    for (const o of others) {
      if (o.year < first || o.year > last) continue;
      marks.push({ xAxis: o.year, name: `${o.name} (${yearText(o.year)})`, url: o.id,
        lineStyle: { color: catColor(o.category), type: "dotted", width: o.linked ? 1.5 : 1, opacity: o.linked ? 0.9 : 0.45 }, label: { show: false } });
    }
  }
  const series: SeriesOption[] = lines.map((l, i) => ({
    type: "line", name: l.name, showSymbol: l.points.length < 30, symbolSize: 4, color: colors[i],
    lineStyle: { width: ["world", "NZL"].includes(l.entity) ? 2.2 : 1.6 }, data: l.points, connectNulls: true,
    ...(i === 0 ? { markLine: { symbol: "none", silent: false, animation: false, data: marks,
      emphasis: { label: { show: true, formatter: (p: { name: string }) => p.name, color: cssVar("--ink"), backgroundColor: cssVar("--surface"), padding: [2, 4] } } } } : {}),
  }));
  const long = last - first > 120;
  return {
    ...base,
    legend: { top: 0, left: 0, type: "scroll", textStyle: { color: cssVar("--ink-2") } },
    grid: { left: 8, right: 18, top: 34, bottom: long ? 40 : 8, containLabel: true },
    xAxis: { type: "value", min: Number.isFinite(first) ? first : undefined, max: Number.isFinite(last) ? last : undefined, minInterval: 1,
      axisLabel: { color: cssVar("--muted"), formatter: (v: number) => yearText(Math.round(v)) }, splitLine: { show: false } },
    yAxis: { type: "value", scale: !/%|per|price|cost/.test(unit),
      axisLabel: { color: cssVar("--muted"), formatter: (v: number) => compact(v) }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
    tooltip: { ...(base.tooltip as object), trigger: "axis", valueFormatter: (v: unknown) => (typeof v === "number" ? compact(v) : String(v)) },
    ...(long ? { dataZoom: [{ type: "slider", height: 18, bottom: 6, filterMode: "none", startValue: from, endValue: last },
      { type: "inside", filterMode: "none", startValue: from, endValue: last }] } : {}),
    series,
  };
}

// Where a card's chart starts: some decades before the invention, or where the figures begin.
export function startFor(year: number): number | undefined {
  if (year < 1500) return undefined;
  return year - 60;
}
