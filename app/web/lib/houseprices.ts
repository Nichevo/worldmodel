// House prices by region (New Zealand's regions, Australia's states): which figures there are,
// turning them into a change over a year, an index or today's dollars, and the chart.

import type { EChartsOption, SeriesOption } from "echarts";
import { chrome } from "@/lib/charts";
import { cssVar } from "@/lib/colors";
import { formatValue } from "@/lib/format";

export type HouseMeasure = { id: string; label: string; unit: string; money: boolean; yearly: string; note: string };

export const HOUSE_MEASURES: Record<string, HouseMeasure[]> = {
  NZL: [
    { id: "nzhouse_median_price_m", yearly: "nzhouse_median_price", label: "Median sale price", unit: "NZ$", money: true,
      note: "The middle price paid for homes sold in the three months to each month." },
    { id: "nzhouse_hpi_m", yearly: "nzhouse_hpi", label: "Price index (MCERT)", unit: "index", money: false,
      note: "The Ministry's house price index, which sets each sale against the home's rating valuation, so a month with more dear homes sold does not look like a rise." },
    { id: "nzhouse_lq_price_m", yearly: "nzhouse_lq_price", label: "Cheaper quarter", unit: "NZ$", money: true,
      note: "The lower quartile: a quarter of homes sold for less than this." },
    { id: "nzhouse_uq_price_m", yearly: "nzhouse_uq_price", label: "Dearer quarter", unit: "NZ$", money: true,
      note: "The upper quartile: a quarter of homes sold for more than this." },
    { id: "nzhouse_sales_m", yearly: "nzhouse_sales", label: "Sales", unit: "sales", money: false,
      note: "Homes sold each month." },
  ],
  AUS: [
    { id: "aureg_mean_dwelling_price_q", yearly: "aureg_mean_dwelling_price", label: "Mean dwelling price", unit: "A$", money: true,
      note: "The average value of all houses and units, each quarter (from 2011)." },
    { id: "aureg_house_median_capital_q", yearly: "aureg_house_median_capital", label: "Median house, capital city", unit: "A$", money: true,
      note: "The middle price of established houses sold in the capital city (Greater Sydney and so on; all of the ACT), each quarter (from 2002)." },
    { id: "aureg_house_median_rest_q", yearly: "aureg_house_median_rest", label: "Median house, rest of state", unit: "A$", money: true,
      note: "The middle price of established houses sold outside the capital city, each quarter (from 2002)." },
    { id: "aureg_unit_median_capital_q", yearly: "aureg_unit_median_capital", label: "Median unit, capital city", unit: "A$", money: true,
      note: "The middle price of flats, units and townhouses sold in the capital city, each quarter (from 2002)." },
    { id: "aureg_dwelling_stock_value_q", yearly: "aureg_dwelling_stock_value", label: "Value of all homes", unit: "A$ billion", money: true,
      note: "What all the homes in the state were worth, each quarter (from 2011)." },
  ],
};
// Shown first: the country and its biggest markets.
export const HOUSE_DEFAULT: Record<string, string[]> = {
  NZL: ["NZL", "NZ-AUK", "NZ-WGN", "NZ-CAN", "NZ-WKO", "NZ-OTA"],
  AUS: ["AUS", "AU-NSW", "AU-VIC", "AU-QLD", "AU-WA", "AU-SA"],
};
export const HOUSE_SOURCE: Record<string, string> = {
  NZL: "Ministry for Cities, Environment, Regions and Transport (formerly HUD), Property and sales statistics, from council valuation rolls",
  AUS: "Australian Bureau of Statistics, Total Value of Dwellings and Residential Dwellings",
};

export type Show = "value" | "real" | "change" | "index";

// A value in its unit, dollars written as $739,600 or $1,234.5 billion.
export function houseValue(v: number, unit: string): string {
  if (unit.endsWith("billion")) return `$${v.toLocaleString(undefined, { maximumFractionDigits: 1 })} billion`;
  if (unit.endsWith("$")) return `$${Math.round(v).toLocaleString()}`;
  return formatValue(v, unit, 0);
}
export type Pt = [number, number]; // ms since 1970, value

export const toMs = (period: string) => {
  const q = /^(\d{4})-Q([1-4])$/.exec(period);
  if (q) return Date.UTC(+q[1], 3 * +q[2] - 3, 1);
  const m = /^(\d{4})-(\d{2})/.exec(period);
  return m ? Date.UTC(+m[1], +m[2] - 1, 1) : Date.UTC(+period, 0, 1);
};
const yearOf = (ms: number) => new Date(ms).getUTCFullYear() + new Date(ms).getUTCMonth() / 12;

// A price level from yearly inflation (%), each year's value set at mid-year and joined by
// straight lines; months beyond either end take the nearest year's level.
export function priceLevel(inflation: [number, number][]): ((ms: number) => number) | null {
  const pts = [...inflation].sort((a, b) => a[0] - b[0]);
  if (pts.length < 2) return null;
  const lv: [number, number][] = [];
  let level = 100;
  for (const [i, [y, pct]] of pts.entries()) {
    if (i > 0 && y !== pts[i - 1][0] + 1) { lv.length = 0; level = 100; } // start again after a gap
    if (lv.length) level *= 1 + pct / 100;
    lv.push([y + 0.5, level]);
  }
  if (lv.length < 2) return null;
  return (ms: number) => {
    const t = yearOf(ms) + 1 / 24;
    if (t <= lv[0][0]) return lv[0][1];
    if (t >= lv[lv.length - 1][0]) return lv[lv.length - 1][1];
    const i = lv.findIndex((p) => p[0] >= t);
    const [x0, y0] = lv[i - 1], [x1, y1] = lv[i];
    return y0 + ((y1 - y0) * (t - x0)) / (x1 - x0);
  };
}

// One line turned into what is shown: the value itself, in the latest dollars, the change on a
// year earlier (%), or an index with the first point shown (from `from`) = 100.
export function shown(pts: Pt[], show: Show, perYear: number, from: number, level: ((ms: number) => number) | null): Pt[] {
  if (show === "real" && level) {
    const now = level(Date.now());
    return pts.map(([t, v]) => [t, (v * now) / level(t)]);
  }
  if (show === "change") {
    return pts.slice(perYear).map(([t, v], i) => [t, 100 * (v / pts[i][1] - 1)] as Pt).filter((p) => Number.isFinite(p[1]));
  }
  if (show === "index") {
    const first = pts.find((p) => p[0] >= from);
    return first ? pts.filter((p) => p[0] >= from).map(([t, v]) => [t, (100 * v) / first[1]]) : [];
  }
  return pts;
}

export type HouseLine = { id: string; name: string; color: string; points: Pt[]; bold: boolean };

export function houseOption(lines: HouseLine[], unit: string, show: Show): EChartsOption {
  const base = chrome();
  const fmt = (v: number) => (show === "change" ? `${v > 0 ? "+" : ""}${v.toFixed(1)}%` : show === "index" ? v.toFixed(0) : houseValue(v, unit));
  const axisFmt = (v: number) => {
    if (show === "change") return `${v}%`;
    const a = Math.abs(v);
    return a >= 1e6 ? `${+(v / 1e6).toFixed(2)}m` : a >= 1e3 ? `${+(v / 1e3).toFixed(0)}k` : String(v);
  };
  const series: SeriesOption[] = lines.map((l) => ({
    type: "line", name: l.name, color: l.color, showSymbol: false, connectNulls: false, emphasis: { focus: "series" },
    lineStyle: { width: l.bold ? 3 : 1.6 }, z: l.bold ? 3 : 2,
    endLabel: { show: lines.length <= 8, formatter: (p: { seriesName?: string }) => p.seriesName ?? "", color: l.color, fontSize: 11 },
    data: l.points,
  }));
  if (show === "change" || show === "index") {
    series.push({ type: "line", data: [], silent: true, tooltip: { show: false }, markLine: { symbol: "none", silent: true, animation: false,
      label: { show: false }, data: [{ yAxis: show === "change" ? 0 : 100 }], lineStyle: { color: cssVar("--axis"), type: "dashed", width: 1 } } });
  }
  return {
    ...base,
    grid: { left: 8, right: lines.length <= 8 ? 110 : 16, top: 16, bottom: 40, containLabel: true },
    xAxis: { type: "time", axisLabel: { color: cssVar("--muted") }, axisLine: { lineStyle: { color: cssVar("--axis") } }, splitLine: { show: false } },
    yAxis: { type: "value", scale: show !== "value" && show !== "real", axisLabel: { color: cssVar("--muted"), formatter: axisFmt },
      splitLine: { lineStyle: { color: cssVar("--grid") } } },
    dataZoom: [{ type: "slider", height: 18, bottom: 6, filterMode: "none" }, { type: "inside", filterMode: "none" }],
    tooltip: { ...(base.tooltip as object), confine: true, formatter: (params: unknown) => {
      const list = (Array.isArray(params) ? params : [params]) as { seriesName: string; value: Pt; color: string }[];
      if (!list.length || !list[0].value) return "";
      const d = new Date(list[0].value[0]);
      const head = d.toLocaleDateString(undefined, { month: "short", year: "numeric", timeZone: "UTC" });
      const rows = [...list].filter((p) => p.value).sort((a, b) => b.value[1] - a.value[1]).map((p) =>
        `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${p.color};margin-right:6px"></span>${p.seriesName}: <b>${fmt(p.value[1])}</b>`);
      return [`<b>${head}</b>`, ...rows].join("<br/>");
    } },
    series,
  };
}

// The latest value, its change over one and five years, and how far it is below its highest.
export type HouseRow = { id: string; name: string; latest: number; at: number; y1: number | null; y5: number | null; peak: number; peakAt: number };
export function houseRow(id: string, name: string, pts: Pt[], perYear: number): HouseRow | null {
  if (!pts.length) return null;
  const [at, latest] = pts[pts.length - 1];
  const back = (n: number) => { const p = pts[pts.length - 1 - n * perYear]; return p ? 100 * (latest / p[1] - 1) : null; };
  const top = pts.reduce((b, p) => (p[1] > b[1] ? p : b), pts[0]);
  return { id, name, latest, at, y1: back(1), y5: back(5), peak: top[1], peakAt: top[0] };
}
