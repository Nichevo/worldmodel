import type { EChartsOption, SeriesOption } from "echarts";
import { cssVar, seriesColor } from "@/lib/colors";
import { short } from "@/lib/sectors";

// Climate charts: warming stripes, lines with an optional zero line, fan charts for
// projections, El Niño with its phases shaded, and stacked areas for emissions.

const font = "system-ui, -apple-system, 'Segoe UI', sans-serif";
function base(): EChartsOption {
  return {
    backgroundColor: "transparent",
    textStyle: { fontFamily: font, color: cssVar("--ink-2") },
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis", confine: true, backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"), textStyle: { color: cssVar("--ink") } },
    legend: { top: 0, textStyle: { color: cssVar("--ink-2") } },
  };
}
const yAxis = (name = "", fmt: (v: number) => string = short) => ({
  type: "value" as const, name, nameTextStyle: { color: cssVar("--muted") }, scale: true,
  axisLabel: { color: cssVar("--muted"), formatter: fmt }, splitLine: { lineStyle: { color: cssVar("--grid") } },
});
const xYears = { type: "value" as const, min: "dataMin" as const, max: "dataMax" as const, minInterval: 1,
  axisLabel: { color: cssVar("--muted"), formatter: (v: number) => String(v) }, axisLine: { lineStyle: { color: cssVar("--axis") } }, splitLine: { show: false } };
const xTime = { type: "time" as const, axisLabel: { color: cssVar("--muted") }, axisLine: { lineStyle: { color: cssVar("--axis") } }, splitLine: { show: false } };

// Ed Hawkins' warming stripes: one bar a year, blue for cooler and red for warmer than the
// average of the years shown, no axes needed.
const STRIPES = ["#08306b", "#08519c", "#2171b5", "#4292c6", "#6baed6", "#9ecae1", "#c6dbef", "#deebf7",
  "#fee0d2", "#fcbba1", "#fc9272", "#fb6a4a", "#ef3b2c", "#cb181d", "#a50f15", "#67000d"];
export function stripesOption(points: [number, number][], unit = "°C"): EChartsOption {
  const vals = points.map((p) => p[1]);
  const mid = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
  const span = Math.max(0.1, ...vals.map((v) => Math.abs(v - mid)));
  const color = (v: number) => STRIPES[Math.max(0, Math.min(STRIPES.length - 1, Math.floor((((v - mid) / span) + 1) / 2 * STRIPES.length)))];
  return {
    backgroundColor: "transparent",
    grid: { left: 0, right: 0, top: 0, bottom: 18 },
    tooltip: { trigger: "item", confine: true, backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"), textStyle: { color: cssVar("--ink") },
      formatter: (p: unknown) => { const q = p as { name: string; value: number }; return `${q.name}: <b>${q.value > 0 ? "+" : ""}${q.value.toFixed(2)} ${unit}</b>`; } },
    xAxis: { type: "category", data: points.map((p) => String(p[0])), axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: cssVar("--muted"), interval: Math.max(0, Math.floor(points.length / 8) - 1) } },
    yAxis: { type: "value", show: false, min: 0, max: 1 },
    series: [{ type: "bar", barCategoryGap: 0, data: points.map((p) => ({ value: 1, name: String(p[0]), itemStyle: { color: color(p[1]) } })),
      tooltip: { formatter: (p: unknown) => { const q = p as { dataIndex: number }; const pt = points[q.dataIndex]; return `${pt[0]}: <b>${pt[1] > 0 ? "+" : ""}${pt[1].toFixed(2)} ${unit}</b>`; } } }],
  };
}

export function lines(series: { name: string; points: [number | string, number][] }[], unit: string,
  o: { zero?: boolean; time?: boolean; area?: boolean; stack?: boolean; decimals?: number } = {}): EChartsOption {
  const d = o.decimals ?? 2;
  return {
    ...base(),
    xAxis: o.time ? xTime : xYears,
    yAxis: yAxis(unit, (v) => (Math.abs(v) >= 1000 ? short(v) : String(+v.toFixed(d)))),
    tooltip: { ...(base().tooltip as object), valueFormatter: (v: unknown) => `${typeof v === "number" ? (Math.abs(v) >= 1000 ? short(v) : v.toFixed(d)) : v} ${unit}` },
    dataZoom: o.time ? [{ type: "inside" }] : undefined,
    series: series.map((s, i) => ({
      type: "line", name: s.name, data: o.time ? s.points.map(([t, v]) => [`${t}-01`, v]) : s.points,
      showSymbol: s.points.length < 3, lineStyle: { width: o.time ? 1.3 : 2, color: seriesColor(i) }, itemStyle: { color: seriesColor(i) },
      stack: o.stack ? "all" : undefined, areaStyle: o.area || o.stack ? { opacity: o.stack ? 0.7 : 0.15 } : undefined,
      markLine: o.zero && i === 0 ? { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: cssVar("--axis"), type: "dashed" }, data: [{ yAxis: 0 }] } : undefined,
    })) as SeriesOption[],
  };
}

// Projections: the median line with the 10th-90th percentile range shaded, one colour per scenario.
export function fanOption(fans: { name: string; points: [number, number | null, number | null, number | null][] }[], unit: string,
  history?: { name: string; points: [number, number][] }): EChartsOption {
  const series: SeriesOption[] = [];
  fans.forEach((f, i) => {
    const c = seriesColor(i + 1);
    series.push({ type: "line", name: `${f.name} range`, stack: `r${i}`, data: f.points.map((p) => [p[0], p[2]]), lineStyle: { opacity: 0 }, symbol: "none",
      tooltip: { show: false } } as SeriesOption);
    series.push({ type: "line", name: `${f.name} range`, stack: `r${i}`, data: f.points.map((p) => [p[0], p[3] != null && p[2] != null ? p[3] - p[2] : null]),
      lineStyle: { opacity: 0 }, symbol: "none", areaStyle: { color: c, opacity: 0.15 }, tooltip: { show: false } } as SeriesOption);
    series.push({ type: "line", name: f.name, data: f.points.map((p) => [p[0], p[1]]), symbol: "none", lineStyle: { color: c, width: 2, type: "dashed" }, itemStyle: { color: c } });
  });
  if (history) series.unshift({ type: "line", name: history.name, data: history.points, symbol: "none", lineStyle: { color: seriesColor(0), width: 2 }, itemStyle: { color: seriesColor(0) } });
  return {
    ...base(),
    legend: { top: 0, textStyle: { color: cssVar("--ink-2") }, data: [...(history ? [history.name] : []), ...fans.map((f) => f.name)] },
    xAxis: xYears,
    yAxis: yAxis(unit, (v) => String(+v.toFixed(1))),
    tooltip: { ...(base().tooltip as object), valueFormatter: (v: unknown) => (typeof v === "number" ? `${v.toFixed(1)} ${unit}` : String(v)) },
    series,
  };
}

// The El Niño index by month, red above +0.5, blue below -0.5.
export function ensoOption(series: { name: string; points: [string, number][] }[]): EChartsOption {
  const o = lines(series, "°C", { time: true, zero: true });
  const first = (o.series as SeriesOption[])[0] as SeriesOption & { markArea?: object };
  first.markArea = { silent: true, data: [
    [{ yAxis: 0.5, itemStyle: { color: cssVar("--div-neg-3"), opacity: 0.08 } }, { yAxis: 4 }],
    [{ yAxis: -4, itemStyle: { color: cssVar("--div-pos-3"), opacity: 0.08 } }, { yAxis: -0.5 }],
  ] };
  return { ...o, visualMap: series.length === 1 ? { show: false, seriesIndex: 0, pieces: [
    { lt: -0.5, color: cssVar("--div-pos-3") }, { gte: -0.5, lte: 0.5, color: cssVar("--muted") }, { gt: 0.5, color: cssVar("--div-neg-3") }] } : undefined };
}

// Storms each year, stacked by basin, with the strong ones as a line.
export function stormsOption(years: number[], basins: string[], counts: number[][], strong: number[]): EChartsOption {
  return {
    ...base(),
    tooltip: { ...(base().tooltip as object), axisPointer: { type: "shadow" } },
    xAxis: { type: "category", data: years.map(String), axisLabel: { color: cssVar("--muted") } },
    yAxis: { ...yAxis("storms", (v) => String(v)), scale: false, min: 0, minInterval: 1 },
    series: [
      ...basins.map((b, i) => ({ type: "bar" as const, name: b, stack: "s", data: counts.map((c) => c[i]), itemStyle: { color: seriesColor(i) } })),
      { type: "line" as const, name: "Category 3 or more", data: strong, symbol: "none", lineStyle: { color: cssVar("--ink"), width: 2 }, itemStyle: { color: cssVar("--ink") } },
    ],
  };
}
