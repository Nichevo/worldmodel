import type { EChartsOption, SeriesOption } from "echarts";
import type { SectorMeasure, SectorRoute } from "@/lib/api";
import { cssVar, seriesColor } from "@/lib/colors";

// Sectors pages: amounts in words people read at a glance, and the charts.

export function money(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "no data";
  const a = Math.abs(v);
  const s = v < 0 ? "-" : "";
  if (a >= 1e12) return `${s}US$ ${(a / 1e12).toFixed(2)} trillion`;
  if (a >= 1e9) return `${s}US$ ${(a / 1e9).toFixed(a >= 1e11 ? 0 : 1)} billion`;
  if (a >= 1e6) return `${s}US$ ${(a / 1e6).toFixed(a >= 1e8 ? 0 : 1)} million`;
  if (a >= 1e3) return `${s}US$ ${(a / 1e3).toFixed(0)} thousand`;
  return `${s}US$ ${a.toFixed(0)}`;
}

const UNIT_SHORT: Record<string, string> = { tonnes: "t", kilograms: "kg", "cubic metres": "m³", "tonnes of nitrogen": "t N",
  "tonnes of P2O5": "t P₂O₅", "tonnes of K2O": "t K₂O" };

export function amount(v: number | null | undefined, unit: string): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "no data";
  if (unit.includes("dollars")) return money(v);
  const u = UNIT_SHORT[unit] ?? unit;
  const a = Math.abs(v);
  const n = a >= 1e9 ? `${(v / 1e9).toFixed(2)} billion` : a >= 1e6 ? `${(v / 1e6).toFixed(a >= 1e8 ? 0 : 1)} million`
    : a >= 1e4 ? `${Math.round(v / 1e3).toLocaleString()} thousand` : v.toLocaleString(undefined, { maximumFractionDigits: 1 });
  return `${n} ${u}`;
}

export function short(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e12) return `${+(v / 1e12).toFixed(1)}T`;
  if (a >= 1e9) return `${+(v / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${+(v / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${+(v / 1e3).toFixed(1)}k`;
  return String(+v.toFixed(1));
}

// How concentrated supply is, in words: the US competition agencies' thresholds.
export function hhiText(hhi: number | null | undefined): string {
  if (hhi === null || hhi === undefined) return "";
  return hhi > 2500 ? "highly concentrated" : hhi >= 1500 ? "moderately concentrated" : "spread out";
}

function base(): EChartsOption {
  return {
    backgroundColor: "transparent",
    textStyle: { fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif", color: cssVar("--ink-2") },
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis", confine: true, backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"),
      textStyle: { color: cssVar("--ink") } },
    legend: { top: 0, textStyle: { color: cssVar("--ink-2") } },
  };
}

const axis = (fmt: (v: number) => string, name = "") => ({
  type: "value" as const, name, nameTextStyle: { color: cssVar("--muted") }, scale: false,
  axisLabel: { color: cssVar("--muted"), formatter: fmt }, splitLine: { lineStyle: { color: cssVar("--grid") } },
});
const xYears = { type: "value" as const, min: "dataMin" as const, max: "dataMax" as const, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => String(v) },
  axisLine: { lineStyle: { color: cssVar("--axis") } }, splitLine: { show: false } };

// Lines over the years, one unit for all.
export function yearLines(lines: { name: string; points: [number, number][] }[], unit: string): EChartsOption {
  return {
    ...base(),
    xAxis: xYears,
    yAxis: axis(short, unit.includes("dollars") ? "US$" : UNIT_SHORT[unit] ?? unit),
    tooltip: { ...(base().tooltip as object), valueFormatter: (v: unknown) => amount(v as number, unit) },
    series: lines.map((l, i) => ({ type: "line", name: l.name, data: l.points, showSymbol: l.points.length < 3, smooth: false,
      lineStyle: { width: 2, color: seriesColor(i) }, itemStyle: { color: seriesColor(i) } })) as SeriesOption[],
  };
}

// The top three's share of the world (left axis, %) and the Herfindahl-Hirschman index
// (right axis) each year, with the 1,500 and 2,500 thresholds marked.
export function concentrationOption(m: { name: string; c: SectorMeasure["concentration"] }[]): EChartsOption {
  const series: SeriesOption[] = [];
  m.forEach((x, i) => {
    series.push({ type: "line", name: `${x.name}: top 3 share`, yAxisIndex: 0, data: x.c.map((r) => [r[0], r[1]]), showSymbol: x.c.length < 3,
      lineStyle: { width: 2, color: seriesColor(i) }, itemStyle: { color: seriesColor(i) } });
    series.push({ type: "line", name: `${x.name}: HHI`, yAxisIndex: 1, data: x.c.map((r) => [r[0], r[2]]), showSymbol: x.c.length < 3,
      lineStyle: { width: 1.5, type: "dashed", color: seriesColor(i) }, itemStyle: { color: seriesColor(i) },
      markLine: i === 0 ? { silent: true, symbol: "none", label: { color: cssVar("--muted"), formatter: (p: { value: unknown }) => `HHI ${p.value}` },
        lineStyle: { color: cssVar("--axis"), type: "dotted" }, data: [{ yAxis: 1500 }, { yAxis: 2500 }] } : undefined });
  });
  return {
    ...base(),
    grid: { left: 8, right: 16, top: 56, bottom: 8, containLabel: true },
    xAxis: xYears,
    yAxis: [{ ...axis((v) => `${v}%`, "top 3"), min: 0, max: 100 }, { ...axis((v) => String(v), "HHI"), min: 0, max: 10000, splitLine: { show: false } }],
    series,
  };
}

// Horizontal bars of the leading countries, values written on the bars.
export function rankingBars(rows: { name: string; value: number }[], unit: string, n = 12): EChartsOption {
  const top = rows.slice(0, n).reverse();
  return {
    ...base(),
    legend: undefined,
    grid: { left: 8, right: 90, top: 8, bottom: 8, containLabel: true },
    tooltip: { ...(base().tooltip as object), trigger: "item", formatter: (p: unknown) => {
      const q = p as { name: string; value: number };
      return `${q.name}: <b>${amount(q.value, unit)}</b>`;
    } },
    xAxis: { type: "value", show: false },
    yAxis: { type: "category", data: top.map((r) => r.name), axisLabel: { color: cssVar("--ink-2") }, axisLine: { show: false }, axisTick: { show: false } },
    series: [{ type: "bar", data: top.map((r) => r.value), itemStyle: { color: seriesColor(0) }, barMaxWidth: 18,
      label: { show: true, position: "right", color: cssVar("--ink-2"), formatter: (p: { value: unknown }) => short(p.value as number) } }],
  };
}

// The biggest routes as a flow from exporters (left) to buyers (right).
export function routesSankey(routes: SectorRoute[]): EChartsOption {
  const left = (n: string) => `${n} `; // the same country can sell and buy; a trailing space keeps the nodes apart
  const nodes = new Map<string, number>();
  routes.forEach((r) => { if (!nodes.has(left(r.from_name))) nodes.set(left(r.from_name), nodes.size); });
  routes.forEach((r) => { if (!nodes.has(r.to_name)) nodes.set(r.to_name, nodes.size); });
  return {
    backgroundColor: "transparent",
    textStyle: { fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif", color: cssVar("--ink-2") },
    tooltip: { trigger: "item", confine: true, backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"), textStyle: { color: cssVar("--ink") },
      formatter: (p: unknown) => {
        const q = p as { dataType: string; data: { source?: string; target?: string; value?: number; name?: string }; value: number };
        return q.dataType === "edge" ? `${q.data.source?.trim()} → ${q.data.target}: <b>${money(q.data.value ?? 0)}</b>` : `${q.data.name?.trim()}: <b>${money(q.value)}</b>`;
      } },
    series: [{
      type: "sankey", left: 8, right: 120, top: 8, bottom: 8, nodeWidth: 10, nodeGap: 6, draggable: false, layoutIterations: 32,
      emphasis: { focus: "adjacency" }, label: { color: cssVar("--ink"), fontSize: 11 },
      lineStyle: { color: "gradient", opacity: 0.35, curveness: 0.5 },
      data: [...nodes.keys()].map((name, i) => ({ name, itemStyle: { color: seriesColor(i), borderWidth: 0 } })),
      links: routes.map((r) => ({ source: left(r.from_name), target: r.to_name, value: r.value })),
    }],
  } as EChartsOption;
}

// Monthly prices: one line each, on their own axes when units differ.
export function pricesOption(prices: { name: string; unit: string; points: [string, number][] }[]): EChartsOption {
  const units = [...new Set(prices.map((p) => p.unit))].slice(0, 2);
  return {
    ...base(),
    xAxis: { type: "time", axisLabel: { color: cssVar("--muted") }, axisLine: { lineStyle: { color: cssVar("--axis") } }, splitLine: { show: false } },
    yAxis: units.map((u, i) => ({ ...axis(short, u), splitLine: { show: i === 0, lineStyle: { color: cssVar("--grid") } } })),
    dataZoom: [{ type: "inside" }],
    series: prices.map((p, i) => ({ type: "line", name: `${p.name} (${p.unit})`, yAxisIndex: Math.max(0, units.indexOf(p.unit)),
      data: p.points.map(([d, v]) => [`${d}-01`, v]), showSymbol: false, lineStyle: { width: 1.6, color: seriesColor(i) }, itemStyle: { color: seriesColor(i) } })) as SeriesOption[],
  };
}

// Exports and imports by chapter side by side, biggest first.
export function chapterBars(rows: { name: string; exports: number | null; imports: number | null }[], n = 15): EChartsOption {
  const top = [...rows].sort((a, b) => Math.max(b.exports ?? 0, b.imports ?? 0) - Math.max(a.exports ?? 0, a.imports ?? 0)).slice(0, n).reverse();
  return {
    ...base(),
    grid: { left: 8, right: 24, top: 30, bottom: 8, containLabel: true },
    tooltip: { ...(base().tooltip as object), axisPointer: { type: "shadow" }, valueFormatter: (v: unknown) => money(v as number) },
    xAxis: { type: "value", axisLabel: { color: cssVar("--muted"), formatter: short }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
    yAxis: { type: "category", data: top.map((r) => r.name), axisLabel: { color: cssVar("--ink-2"), width: 180, overflow: "truncate" } },
    series: [
      { type: "bar", name: "Exports", data: top.map((r) => r.exports ?? 0), itemStyle: { color: seriesColor(0) }, barMaxWidth: 12 },
      { type: "bar", name: "Imports", data: top.map((r) => r.imports ?? 0), itemStyle: { color: seriesColor(1) }, barMaxWidth: 12 },
    ],
  };
}
