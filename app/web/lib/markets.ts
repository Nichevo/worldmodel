import type { EChartsOption, SeriesOption } from "echarts";
import type { StorageSeries } from "@/lib/api";
import { cssVar, seriesColor } from "@/lib/colors";
import { short } from "@/lib/sectors";

// Market charts: dated lines (exchange rates), and a year of storage drawn as a clock
// (round, January at the top, going clockwise) or as one line per year, with the band
// of past years behind it.

const font = "system-ui, -apple-system, 'Segoe UI', sans-serif";
const tip = () => ({ confine: true, backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"), textStyle: { color: cssVar("--ink") } });
const fmt = (v: number, d: number) => (Math.abs(v) >= 10000 ? short(v) : v.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: Math.min(d, 2) }));

export function datedLines(series: { name: string; points: [string, number][] }[], unit: string, decimals = 3,
  o: { base?: number } = {}): EChartsOption {
  return {
    backgroundColor: "transparent",
    textStyle: { fontFamily: font, color: cssVar("--ink-2") },
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    legend: { top: 0, textStyle: { color: cssVar("--ink-2") } },
    tooltip: { trigger: "axis", ...tip(), valueFormatter: (v: unknown) => (typeof v === "number" ? `${fmt(v, decimals)}${unit ? ` ${unit}` : ""}` : String(v)) },
    xAxis: { type: "time", axisLabel: { color: cssVar("--muted") }, axisLine: { lineStyle: { color: cssVar("--axis") } }, splitLine: { show: false } },
    yAxis: { type: "value", scale: true, name: unit, nameTextStyle: { color: cssVar("--muted") },
      axisLabel: { color: cssVar("--muted"), formatter: (v: number) => fmt(v, Math.min(decimals, 2)) }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
    dataZoom: [{ type: "inside" }],
    series: series.map((s, i) => ({
      type: "line", name: s.name, data: s.points, showSymbol: false, sampling: "lttb",
      lineStyle: { width: 1.5, color: seriesColor(i) }, itemStyle: { color: seriesColor(i) },
      markLine: o.base != null && i === 0 ? { silent: true, symbol: "none", label: { show: false },
        lineStyle: { color: cssVar("--axis"), type: "dashed" }, data: [{ yAxis: o.base }] } : undefined,
    })) as SeriesOption[],
  };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTH_START = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335];
export const dayLabel = (d: number) => { const m = MONTH_START.findLastIndex((s) => s <= d); return `${Math.max(1, Math.round(d - MONTH_START[Math.max(0, m)] + 1))} ${MONTHS[Math.max(0, m)]}`; };

// The years drawn: this one (bold), last year (thin), and the band of the years before.
function lines(s: StorageSeries) {
  const now = String(s.year), before = String(s.year - 1);
  return { now: s.years[now] ?? [], before: s.years[before] ?? [] };
}

export function storageClock(s: StorageSeries, events = true): EChartsOption {
  const { now, before } = lines(s);
  const d = s.decimals ?? 1;
  const all = [...s.band.map((b) => b.high), ...now.map((p) => p[1]), ...before.map((p) => p[1])];
  const top = Math.max(...all, 0) * 1.12;
  const low = s.band.map((b) => [b.low, b.day]);
  const span = s.band.map((b) => [b.high - b.low, b.day]);
  const ring = cssVar("--grid");
  const series: SeriesOption[] = [
    { type: "line", coordinateSystem: "polar", name: "low", stack: "band", data: low, symbol: "none", lineStyle: { opacity: 0 }, tooltip: { show: false }, silent: true },
    { type: "line", coordinateSystem: "polar", name: `${s.years_back[0]}–${s.years_back[s.years_back.length - 1]} range`, stack: "band", data: span, symbol: "none",
      lineStyle: { opacity: 0 }, itemStyle: { color: seriesColor(0), opacity: 0.4 }, areaStyle: { color: seriesColor(0), opacity: 0.16 }, tooltip: { show: false }, silent: true },
    { type: "line", coordinateSystem: "polar", name: `${s.years_back.length}-year average`, data: s.band.map((b) => [b.mean, b.day]), symbol: "none",
      lineStyle: { color: cssVar("--muted"), width: 1.2, type: "dashed" }, itemStyle: { color: cssVar("--muted") } },
    { type: "line", coordinateSystem: "polar", name: String(s.year - 1), data: before.map((p) => [p[1], p[0], p[2]]), symbol: "none",
      lineStyle: { color: seriesColor(2), width: 1.2 }, itemStyle: { color: seriesColor(2) } },
    { type: "line", coordinateSystem: "polar", name: String(s.year), data: now.map((p) => [p[1], p[0], p[2]]), symbol: "none",
      lineStyle: { color: seriesColor(1), width: 2.6 }, itemStyle: { color: seriesColor(1) } },
  ];
  if (events && s.events.length) {
    series.push({ type: "scatter", coordinateSystem: "polar", name: "Events", symbol: "pin", symbolSize: 18,
      itemStyle: { color: cssVar("--ink-2") }, data: s.events.map((e) => ({ value: [top * 0.97, e.day], name: `${e.date}: ${e.title}` })),
      tooltip: { formatter: (p: unknown) => (p as { name: string }).name } } as SeriesOption);
  }
  return {
    backgroundColor: "transparent",
    textStyle: { fontFamily: font, color: cssVar("--ink-2") },
    legend: { top: 0, textStyle: { color: cssVar("--ink-2") }, data: series.map((x) => x.name as string).filter((n) => n !== "low") },
    tooltip: { trigger: "item", ...tip(), formatter: (p: unknown) => {
      const q = p as { seriesName: string; value: [number, number, string?]; name?: string };
      if (q.seriesName === "Events") return q.name ?? "";
      return `${q.seriesName}, ${q.value[2] ?? dayLabel(q.value[1])}: <b>${fmt(q.value[0], d)} ${s.unit}</b>`;
    } },
    polar: { radius: ["4%", "78%"], center: ["50%", "56%"] },
    angleAxis: { type: "value", min: 1, max: 366, startAngle: 90, clockwise: true, interval: 30.5,
      axisLabel: { color: cssVar("--muted"), formatter: (v: number) => MONTHS[Math.round((v - 1) / 30.5)] ?? "" },
      axisLine: { lineStyle: { color: cssVar("--axis") } }, splitLine: { show: true, lineStyle: { color: ring } }, axisTick: { show: false } },
    radiusAxis: { type: "value", min: 0, max: top, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => short(v) },
      axisLine: { show: false }, splitLine: { lineStyle: { color: ring } }, axisTick: { show: false } },
    series,
  };
}

export function storageLines(s: StorageSeries, events = true): EChartsOption {
  const d = s.decimals ?? 1;
  const years = Object.keys(s.years).map(Number).sort();
  const series: SeriesOption[] = [
    { type: "line", name: "low", stack: "band", data: s.band.map((b) => [b.day, b.low]), symbol: "none", lineStyle: { opacity: 0 }, tooltip: { show: false }, silent: true },
    { type: "line", name: `${s.years_back[0]}–${s.years_back[s.years_back.length - 1]} range`, stack: "band", data: s.band.map((b) => [b.day, b.high - b.low]),
      symbol: "none", lineStyle: { opacity: 0 }, itemStyle: { color: seriesColor(0), opacity: 0.4 }, areaStyle: { color: seriesColor(0), opacity: 0.16 }, tooltip: { show: false }, silent: true },
    { type: "line", name: `${s.years_back.length}-year average`, data: s.band.map((b) => [b.day, b.mean]), symbol: "none",
      lineStyle: { color: cssVar("--muted"), width: 1.2, type: "dashed" }, itemStyle: { color: cssVar("--muted") } },
    ...years.map((y, i) => ({
      type: "line" as const, name: String(y), data: (s.years[String(y)] ?? []).map((p) => [p[0], p[1], p[2]]), symbol: "none",
      lineStyle: { color: y === s.year ? seriesColor(1) : y === s.year - 1 ? seriesColor(2) : cssVar("--muted"), width: y === s.year ? 2.6 : 1, opacity: y >= s.year - 1 ? 1 : 0.35 + 0.1 * i },
      itemStyle: { color: y === s.year ? seriesColor(1) : seriesColor(2) },
    })),
  ];
  return {
    backgroundColor: "transparent",
    textStyle: { fontFamily: font, color: cssVar("--ink-2") },
    grid: { left: 8, right: 16, top: 48, bottom: 8, containLabel: true },
    legend: { top: 0, textStyle: { color: cssVar("--ink-2") }, data: series.map((x) => x.name as string).filter((n) => n !== "low") },
    tooltip: { trigger: "item", ...tip(), formatter: (p: unknown) => {
      const q = p as { seriesName: string; value: [number, number, string?] };
      return `${q.seriesName}, ${q.value[2] ?? dayLabel(q.value[0])}: <b>${fmt(q.value[1], d)} ${s.unit}</b>`;
    } },
    xAxis: { type: "value", min: 1, max: 366, interval: 30.5, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => MONTHS[Math.round((v - 1) / 30.5)] ?? "" },
      axisLine: { lineStyle: { color: cssVar("--axis") } }, splitLine: { show: false } },
    yAxis: { type: "value", scale: true, name: s.unit, nameTextStyle: { color: cssVar("--muted") }, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => short(v) },
      splitLine: { lineStyle: { color: cssVar("--grid") } } },
    series: events && s.events.length
      ? [...series, { type: "scatter", name: "Events", symbol: "pin", symbolSize: 16, itemStyle: { color: cssVar("--ink-2") },
          data: s.events.map((e) => ({ value: [e.day, Math.max(...s.band.map((b) => b.high))], name: `${e.date}: ${e.title}` })),
          tooltip: { formatter: (p: unknown) => (p as { name: string }).name } } as SeriesOption]
      : series,
  };
}
