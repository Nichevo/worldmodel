// The Disease page's data and charts: flu, COVID, RSV, measles and other infections, by week and by year.

import type { EChartsOption } from "echarts";
import { get } from "@/lib/api";
import { chrome } from "@/lib/charts";
import { cssVar } from "@/lib/colors";
import { entityColors } from "@/lib/look";

export type Measure = {
  id: string; disease: string; label: string; unit: string; kind: "pct" | "rate" | "count"; sources: string; main?: boolean;
  places?: number; latest?: string | null; key?: string[];
};
export type Disease = { key: string; name: string; about: string };
export type Yearly = { id: string; disease: string; label: string; per_million: boolean; sources: string; from_weekly?: boolean };
export type Measures = { diseases: Disease[]; measures: Measure[]; yearly: Yearly[]; key: string[] };
export type Season = { season: number; label: string; points: [number, string, number][]; peak: number | null; strain?: Record<number, string> };
export type Headline = {
  season: string; peak: number; peak_week: string; peak_x: number; rank: number; of: number; since: string | null;
  latest: number; latest_week: string; usual: number | null; ratio: number | null;
};
export type Seasons = {
  entity: string; measure: Measure; split_week?: number; season_note?: string; seasons: Season[]; band: [number, number, number, number][];
  band_label?: string; headline?: Headline | null; sources?: string[]; note?: string;
};
export type NowRow = { entity: string; name: string; week: string; value: number; usual: number | null; ratio: number | null; level: Level; trend: string | null };
export type Level = "low" | "usual" | "high" | "very_high" | "no_usual";
export type Now = { measure: Measure; week: string | null; rows: NowRow[]; levels?: Record<Level, string> };
export type Compare = { measure: Measure | null; since: string; series: { entity: string; name: string; points: [string, number][] }[] };
export type Tile = Omit<NowRow, "entity" | "name"> & { measure: Measure; spark: [string, number][] };
export type Card = {
  entity: string; tiles: Tile[]; levels: Record<Level, string>;
  yearly: { indicator: string; label: string; year: number; value: number; rank: number; of: number; since: number | null }[];
};
export type Long = {
  indicator: Yearly; unit: string; series: { entity: string; name: string; points: [number, number, number][] }[];
  pandemics: { name: string; start: number; end: number }[]; choices: Yearly[];
};
export type Outbreak = { entity: string; name: string; disease: string; title: string; day: string; place: string; url: string | null; detail: string | null };

export const diseaseApi = {
  measures: () => get<Measures>("/disease/measures"),
  seasons: (entity: string, measure: string) => get<Seasons>(`/disease/seasons/${encodeURIComponent(entity)}`, { measure }),
  heat: (entity: string, measure: string) => get<Seasons>(`/disease/heat/${encodeURIComponent(entity)}`, { measure }),
  now: (measure: string) => get<Now>("/disease/now", { measure }),
  compare: (measure: string, entities: string[], years: number) => get<Compare>("/disease/compare", { measure, entities: entities.join(","), years }),
  card: (entity: string) => get<Card>(`/disease/card/${encodeURIComponent(entity)}`),
  long: (indicator: string, entities: string[]) => get<Long>("/disease/long", { indicator, entities: entities.join(",") }),
  outbreaks: (entities?: string[], limit = 60) => get<Outbreak[]>("/disease/outbreaks", { entities: entities?.join(","), limit }),
};

export const KEY = ["NZL", "AUS", "GBR", "USA"];
export const KEY_NAMES: Record<string, string> = { NZL: "New Zealand", AUS: "Australia", GBR: "United Kingdom", USA: "United States" };

// A value as the measure's unit reads: 12.3%, 4.1 per 100,000, 2.4M copies, 27 cases.
export function fmt(v: number | null | undefined, m: Pick<Measure, "unit" | "kind"> | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  if (m?.kind === "pct") return `${v.toFixed(v < 10 ? 1 : 0)}%`;
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (Math.abs(v) >= 1e4) return `${Math.round(v / 1e3)}k`;
  return m?.kind === "count" || Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : v.toFixed(v < 1 ? 2 : 1);
}

export const LEVEL_TONE: Record<Level, string> = { low: "--good", usual: "--muted", high: "--warn-ink", very_high: "--bad", no_usual: "--muted" };
export const levelColor = (l: Level) => cssVar(LEVEL_TONE[l]) || "#888";

// Month names placed on the week of the season each starts in.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function monthTicks(split: number): Map<number, string> {
  const out = new Map<number, string>();
  for (let i = 0; i < 12; i++) {
    const m = split === 1 ? i : (i + 6) % 12;
    out.set(Math.round(1 + (i * 52) / 12), MONTHS[m]);
  }
  return out;
}

const axisMuted = () => ({ color: cssVar("--muted") });

// This season over the earlier ones: the normal range shaded, past seasons thin grey, this one bold.
export function seasonOption(v: Seasons, color: string, showAll: boolean): EChartsOption {
  const base = chrome();
  const ticks = monthTicks(v.split_week ?? 1);
  const last = v.seasons[v.seasons.length - 1];
  const past = showAll ? v.seasons.slice(0, -1) : v.seasons.slice(-6, -1);
  const series: EChartsOption["series"] = [];
  if (v.band.length) {
    series.push({ type: "line", name: "band-low", data: v.band.map((b) => [b[0], b[1]]), stack: "band", lineStyle: { opacity: 0 }, symbol: "none",
      silent: true, tooltip: { show: false } });
    series.push({ type: "line", name: `Normal range ${v.band_label ?? ""}`, data: v.band.map((b) => [b[0], b[2] - b[1]]), stack: "band", symbol: "none",
      lineStyle: { opacity: 0 }, areaStyle: { color: cssVar("--band") || "rgba(150,150,150,0.2)", opacity: 1 }, silent: true, tooltip: { show: false } });
    series.push({ type: "line", name: "Normal (average)", data: v.band.map((b) => [b[0], b[3]]), symbol: "none",
      lineStyle: { width: 1, type: "dashed", color: cssVar("--muted") }, color: cssVar("--muted") });
  }
  for (const s of past) {
    series.push({ type: "line", name: s.label, data: s.points.map((p) => [p[0], p[2]]), symbol: "none",
      lineStyle: { width: 1, color: cssVar("--axis") || "#bbb" }, color: cssVar("--axis") || "#bbb", emphasis: { lineStyle: { width: 2 } } });
  }
  if (last) {
    const pk = last.points.reduce((a, b) => (b[2] > a[2] ? b : a), last.points[0]);
    series.push({ type: "line", name: last.label, data: last.points.map((p) => [p[0], p[2]]), symbol: "none", z: 5,
      lineStyle: { width: 3, color }, color,
      markPoint: pk ? { symbol: "circle", symbolSize: 8, itemStyle: { color }, label: { show: true, position: "top", color: cssVar("--ink"),
        formatter: `${last.label} peak ${fmt(pk[2], v.measure)}` }, data: [{ name: "peak", coord: [pk[0], pk[2]] }] } : undefined });
  }
  return {
    ...base,
    grid: { left: 8, right: 24, top: 28, bottom: 8, containLabel: true },
    xAxis: { type: "value", min: 1, max: 53, interval: 1,
      axisLabel: { ...axisMuted(), formatter: (x: number) => ticks.get(x) ?? "", interval: 0, hideOverlap: false },
      splitLine: { show: false }, axisLine: { lineStyle: { color: cssVar("--axis") } } },
    yAxis: { type: "value", min: 0, axisLabel: { ...axisMuted(), formatter: (x: number) => fmt(x, v.measure) }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
    tooltip: { ...(base.tooltip as object), trigger: "item",
      formatter: (p: unknown) => {
        const x = p as { seriesName: string; value: [number, number] };
        return `${x.seriesName}, week ${x.value[0]} of the season: <b>${fmt(x.value[1], v.measure)}</b>`;
      } },
    series,
  };
}

// Several countries' weeks over the same years, one line each, on one scale.
export function compareOption(c: Compare, ids: string[]): EChartsOption {
  const base = chrome();
  const colors = entityColors(ids);
  return {
    ...base,
    legend: { top: 0, left: 0, textStyle: { color: cssVar("--ink-2") } },
    grid: { left: 8, right: 24, top: 36, bottom: 40, containLabel: true },
    xAxis: { type: "time", axisLabel: axisMuted(), axisLine: { lineStyle: { color: cssVar("--axis") } } },
    yAxis: { type: "value", min: 0, axisLabel: { ...axisMuted(), formatter: (x: number) => fmt(x, c.measure) }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
    dataZoom: [{ type: "slider", height: 18, bottom: 6 }, { type: "inside" }],
    tooltip: { ...(base.tooltip as object), valueFormatter: (x: unknown) => fmt(Number(x), c.measure) },
    series: c.series.map((s) => ({ type: "line", name: s.name, data: s.points, showSymbol: false, lineStyle: { width: 2 },
      color: colors[ids.indexOf(s.entity)] ?? undefined })),
  };
}

// Every season a row, every week a cell: darker for more.
export function heatOption(v: Seasons): EChartsOption {
  const base = chrome();
  const ticks = monthTicks(v.split_week ?? 1);
  const rows = v.seasons.map((s) => s.label);
  const data: [number, number, number][] = [];
  v.seasons.forEach((s, i) => s.points.forEach((p) => data.push([p[0] - 1, i, p[2]])));
  const max = Math.max(1, ...data.map((d) => d[2]));
  const strain = new Map(v.seasons.map((s, i) => [i, s.strain ?? {}]));
  return {
    ...base,
    grid: { left: 8, right: 16, top: 8, bottom: 56, containLabel: true },
    xAxis: { type: "category", data: Array.from({ length: 53 }, (_, i) => String(i + 1)),
      axisLabel: { ...axisMuted(), interval: 0, formatter: (x: string) => ticks.get(+x) ?? "" }, axisTick: { show: false }, splitArea: { show: false } },
    yAxis: { type: "category", data: rows, axisLabel: axisMuted(), axisTick: { show: false } },
    visualMap: { min: 0, max, calculable: false, orient: "horizontal", left: "center", bottom: 0, itemHeight: 160,
      text: [fmt(max, v.measure), "0"], textStyle: { color: cssVar("--muted") },
      inRange: { color: ["#f3f1ea", "#fbe3b0", "#f6b86b", "#e8793b", "#c4402b", "#7e1f1f"] } },
    tooltip: { ...(base.tooltip as object), trigger: "item",
      formatter: (p: unknown) => {
        const x = p as { value: [number, number, number] };
        const st = strain.get(x.value[1])?.[x.value[0] + 1];
        return `${rows[x.value[1]]}, week ${x.value[0] + 1}: <b>${fmt(x.value[2], v.measure)}</b>${st ? `<br/>Main strain ${st}` : ""}`;
      } },
    series: [{ type: "heatmap", data, itemStyle: { borderColor: cssVar("--surface"), borderWidth: 1 }, emphasis: { itemStyle: { borderColor: cssVar("--ink") } } }],
  };
}

// Yearly cases for several countries, pandemics shaded.
export function longOption(l: Long, ids: string[], logScale: boolean): EChartsOption {
  const base = chrome();
  const colors = entityColors(ids);
  const unit = l.unit || "";
  const f = (x: number) => (Math.abs(x) >= 1e4 ? `${Math.round(x / 1e3)}k` : x >= 10 || x === 0 ? Math.round(x).toLocaleString() : x.toFixed(x < 1 ? 2 : 1));
  const first = Math.min(...l.series.flatMap((s) => s.points.map((p) => p[0])), 9999);
  return {
    ...base,
    legend: { top: 0, left: 0, textStyle: { color: cssVar("--ink-2") } },
    grid: { left: 8, right: 24, top: 36, bottom: 40, containLabel: true },
    xAxis: { type: "value", min: "dataMin", max: "dataMax", axisLabel: { ...axisMuted(), formatter: (x: number) => String(x) },
      axisLine: { lineStyle: { color: cssVar("--axis") } }, splitLine: { show: false } },
    yAxis: { type: logScale ? "log" : "value", name: unit, nameTextStyle: { color: cssVar("--muted"), align: "left" },
      axisLabel: { ...axisMuted(), formatter: f }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
    dataZoom: [{ type: "slider", height: 18, bottom: 6 }, { type: "inside" }],
    tooltip: { ...(base.tooltip as object), trigger: "axis",
      formatter: (ps: unknown) => {
        const list = ps as { seriesName: string; value: [number, number, number]; color: string }[];
        if (!list.length) return "";
        return `<b>${list[0].value[0]}</b><br/>` + list.map((p) => `<span style="color:${p.color}">●</span> ${p.seriesName}: ${f(p.value[1])}${unit ? ` ${unit}` : ""}`
          + (l.indicator.per_million ? ` (${Math.round(p.value[2]).toLocaleString()} cases)` : "")).join("<br/>");
      } },
    series: l.series.map((s, i) => ({ type: "line", name: s.name, data: s.points.map((p) => [p[0], logScale && p[1] <= 0 ? null : p[1], p[2]]),
      showSymbol: s.points.length < 40, symbolSize: 4, lineStyle: { width: 2 }, color: colors[ids.indexOf(s.entity)] ?? undefined,
      connectNulls: false,
      markArea: i === 0 ? { silent: true, itemStyle: { color: cssVar("--band") || "rgba(150,150,150,0.18)" },
        label: { color: cssVar("--muted"), fontSize: 10, position: "insideTop" },
        data: l.pandemics.filter((p) => p.end >= first).map((p) => [{ name: p.name, xAxis: p.start }, { xAxis: p.end + 0.9 }]) as never } : undefined })),
  };
}

// A tiny line for a card tile.
export function sparkPoints(spark: [string, number][], w: number, h: number): string {
  if (spark.length < 2) return "";
  const vs = spark.map((p) => p[1]);
  const lo = Math.min(0, ...vs), hi = Math.max(...vs) || 1;
  return spark.map((p, i) => `${i ? "L" : "M"}${((i / (spark.length - 1)) * (w - 4) + 2).toFixed(1)},${(h - 2 - ((p[1] - lo) / (hi - lo || 1)) * (h - 4)).toFixed(1)}`).join("");
}

export const weekLabel = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-NZ", { day: "numeric", month: "short", year: "numeric" });
export const trendWord = (t: string | null) => (t === "rising" ? "rising 3 weeks" : t === "falling" ? "falling 3 weeks" : t === "steady" ? "steady" : "");
