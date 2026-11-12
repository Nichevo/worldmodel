// Commodity prices: short names, numbers and changes in words, and the chart on the
// Commodity prices tab (monthly lines on a year axis, so the app's event bands fit).

import type { EChartsOption, SeriesOption } from "echarts";
import type { EventRow, PriceSeries } from "@/lib/api";
import { chrome } from "@/lib/charts";
import { cssVar, seriesColor } from "@/lib/colors";
import { eventMarks } from "@/lib/events";
import { compact } from "@/lib/format";
import { look } from "@/lib/look";

// Short names for the board and chips: "Crude oil, average price" -> "Crude oil";
// "NZ export prices: dairy (NZ$)" -> "NZ dairy (NZ$)"; "Dairy price index (FAO)" -> "Dairy (FAO)".
const SHORT: Record<string, string> = {
  "Crude oil, average": "Crude oil", "Natural gas, Europe": "Gas, Europe", "Natural gas, US": "Gas, US",
  "Liquefied natural gas, Japan": "LNG, Japan", "Coal, Australian": "Coal", "Aluminum": "Aluminium", "Wheat, US HRW": "Wheat",
  "Rice, Thai 5%": "Rice", "Sugar, world": "Sugar", "Coffee, Arabica": "Coffee", "Potassium chloride": "Potash",
  "Logs, Malaysian": "Logs", "Sawnwood, Malaysian": "Sawnwood", "Cotton, A Index": "Cotton", "Rubber, TSR20": "Rubber",
  "Tea, avg 3 auctions": "Tea", "Phosphate rock": "Phosphate rock",
};
export function priceName(name: string): string {
  const n = name.replace(/ price$/, "");
  if (SHORT[n]) return SHORT[n];
  const nz = n.match(/^NZ export prices: (.*)$/);
  if (nz) return `NZ ${nz[1].replace(/^all commodities$/i, "all exports")}`;
  return n.replace(/ price index \((FAO|World Bank)\)$/, " ($1)").replace(/^FAO Food Price Index$/, "Food (FAO)");
}

// "US$ per mt" -> "$/t"; an index stays "index".
export function priceUnit(unit: string): string {
  if (unit.startsWith("index")) return "index";
  return unit.replace(/^US\$ per /, "$/").replace(/\bmt\b|dmtu|dmt/, "t").replace(/troy oz/, "oz").replace(/mmbtu/, "mmbtu");
}

export function priceValue(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const a = Math.abs(v);
  if (a >= 100_000) return compact(v);
  if (a >= 1000) return Math.round(v).toLocaleString("en");
  if (a >= 100) return v.toFixed(0);
  if (a >= 10) return v.toFixed(1);
  return v.toFixed(2);
}

export function change(v: number | null | undefined): { text: string; cls: string } {
  if (v === null || v === undefined) return { text: "–", cls: "" };
  if (Math.abs(v) < 0.5) return { text: "0%", cls: "" };
  return { text: `${v > 0 ? "▲" : "▼"} ${Math.abs(v).toFixed(Math.abs(v) < 10 ? 1 : 0)}%`, cls: v > 0 ? "sx-up" : "sx-down" };
}

// The colour of a price board group (and of the sectors group it stands for).
export function groupVar(id: string | null | undefined): string {
  const g = id === "wood" ? "forestry" : id || "made";
  return `var(--sg-${g})`;
}

export type PriceMode = "price" | "index" | "real";

// A month as a fractional year: "2024-07" -> 2024.5.
export const monthX = (ym: string) => +ym.slice(0, 4) + (+ym.slice(5, 7) - 1) / 12;

function deflate(points: [string, number][], deflator: [number, number][]): [string, number][] {
  const lv = new Map(deflator);
  const last = deflator.length ? deflator[deflator.length - 1] : null;
  if (!last) return points;
  return points.flatMap(([d, v]) => {
    const l = lv.get(+d.slice(0, 4)) ?? (+d.slice(0, 4) > last[0] ? last[1] : undefined);
    return l ? [[d, (v * last[1]) / l] as [string, number]] : [];
  });
}

// The lines as shown: in the mode chosen and cut to the years chosen.
export function shownLines(data: PriceSeries, mode: PriceMode, from: number, to: number) {
  return data.series.map((s) => {
    let pts = s.points.filter(([d]) => +d.slice(0, 4) >= from && +d.slice(0, 4) <= to);
    if (mode === "real") pts = deflate(pts, data.deflator);
    if (mode === "index" && pts.length) {
      const base = pts[0][1];
      pts = base ? pts.map(([d, v]) => [d, (100 * v) / base] as [string, number]) : pts;
    }
    const unit = mode === "index" ? `index, ${pts[0]?.[0] ?? from} = 100` : mode === "real" ? `${s.unit}, ${data.deflator.at(-1)?.[0] ?? ""} dollars` : s.unit;
    return { ...s, unit, points: pts };
  });
}

export function pricesChart(lines: ReturnType<typeof shownLines>, events: EventRow[]): EChartsOption {
  const units = [...new Set(lines.map((l) => l.unit))];
  const axes = units.length ? units.slice(0, 2) : [""];
  const base = chrome();
  const names = new Map(lines.map((l) => [l.id, priceName(l.name)]));
  const ends = look.endLabels && axes.length === 1; // with a second axis on the right, a legend instead
  const series: SeriesOption[] = lines.map((l, i) => {
    const color = seriesColor(i);
    const last = l.points.at(-1);
    return {
      type: "line", id: l.id, name: names.get(l.id), yAxisIndex: Math.max(0, axes.indexOf(l.unit)), showSymbol: false,
      data: l.points.map(([d, v]) => [monthX(d), v]), lineStyle: { width: 1.8, color }, itemStyle: { color },
      endLabel: ends && last ? { show: true, color, fontWeight: 600, formatter: () => `${names.get(l.id)} ${priceValue(last[1])}` } : undefined,
      labelLayout: { moveOverlap: "shiftY" },
    } as SeriesOption;
  });
  if (events.length) series.push(eventMarks(events) as SeriesOption);
  return {
    ...base,
    grid: { left: 8, right: ends ? 150 : 16, top: ends ? 30 : 52, bottom: 56, containLabel: true },
    legend: ends ? undefined : { top: 0, textStyle: { color: cssVar("--ink-2") } },
    xAxis: { ...(base.xAxis as object), axisLabel: { color: cssVar("--muted"), formatter: (v: number) => String(Math.floor(v)) } },
    yAxis: axes.map((u, i) => ({
      type: "value", scale: true, name: u, nameTextStyle: { color: cssVar("--muted"), align: i ? "right" : "left" },
      axisLabel: { color: cssVar("--muted"), formatter: (v: number) => compact(v) },
      splitLine: { show: i === 0, lineStyle: { color: cssVar("--grid") } },
    })),
    tooltip: {
      ...(base.tooltip as object),
      formatter: (params: unknown) => {
        const list = (Array.isArray(params) ? params : [params]) as { seriesName: string; value: [number, number]; color: string }[];
        if (!list.length) return "";
        const x = list[0].value[0];
        const y = Math.floor(x + 1e-6), m = Math.round((x - y) * 12) + 1;
        const head = new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("en-NZ", { month: "short", year: "numeric", timeZone: "UTC" });
        return [`<b>${head}</b>`, ...list.filter((p) => p.seriesName).map((p) =>
          `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${p.color};margin-right:6px"></span>${p.seriesName}: <b>${priceValue(p.value[1])}</b>`)].join("<br/>");
      },
    },
    dataZoom: [{ type: "slider", height: 18, bottom: 8, filterMode: "none" }, { type: "inside", filterMode: "none" }],
    series,
  };
}
