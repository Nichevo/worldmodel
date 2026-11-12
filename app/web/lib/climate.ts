import type { EChartsOption, SeriesOption } from "echarts";
import { cssVar, seriesColor } from "@/lib/colors";
import { short } from "@/lib/sectors";
import { get } from "@/lib/api";

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

// Tiles of the Köppen-Geiger climate zones drawn by the local API (absolute, as the map's
// workers need), for a period and emissions path; groups: the five main groups only.
export function zoneTiles(period: string, path: string, groups: boolean): string {
  const origin = typeof location !== "undefined" ? location.origin : "";
  return `${origin}/api/v1/climatezones/tiles/${period}/${path}/{z}/{x}/{y}.png${groups ? "?groups=true" : ""}`;
}

// ----------------------------------------------------------------------------- the year's weather (monthly normals)
export type Normals = { entity_id: string; name: string; temp: (number | null)[]; high: (number | null)[]; low: (number | null)[];
  rain: (number | null)[]; summary: Record<string, number> };
export const normalsApi = (entities: string[]) =>
  get<{ countries: Normals[]; period: string; source: string | null }>("/climate/normals", { entities: entities.join(",") });
export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const NORMAL_SUMMARY: [string, string, string][] = [
  ["clim_temp_year", "Average over the year", "°C"], ["clim_high_hottest", "Daytime high, hottest month", "°C"],
  ["clim_low_coldest", "Night-time low, coldest month", "°C"], ["clim_temp_swing", "Warmest less coldest month", "°C"],
  ["clim_rain_year", "Rainfall in a year", "mm"], ["clim_rain_wettest", "Wettest month", "mm"], ["clim_rain_driest", "Driest month", "mm"],
];

// One country: rainfall as bars (right axis), the average temperature as a line inside a band from the
// night-time low to the daytime high. Several countries: one line (temperature) or one set of bars
// (rainfall) each. `from` starts the year in another month (7: July to June, for the southern summer).
export function normalsOption(cs: Normals[], show: "both" | "temp" | "rain", from = 1): EChartsOption {
  const order = Array.from({ length: 12 }, (_, i) => (i + from - 1) % 12);
  const pick = (a: (number | null)[]) => order.map((i) => a[i]);
  const cats = order.map((i) => MONTHS[i]);
  const one = cs.length === 1;
  const temp = show !== "rain";
  const rain = show !== "temp";
  const series: SeriesOption[] = [];
  const yAxes: EChartsOption["yAxis"] = [];
  if (temp) yAxes.push({ ...yAxis("°C", (v: number) => `${v}`), scale: false });
  if (rain) yAxes.push({ ...yAxis("mm", (v: number) => `${v}`), scale: false, splitLine: { show: !temp } });
  const rainAxis = temp ? 1 : 0;
  cs.forEach((c, k) => {
    const col = seriesColor(k);
    if (rain) series.push({ type: "bar", name: one ? "Rainfall" : `${c.name}: rainfall`, yAxisIndex: rainAxis, data: pick(c.rain),
      itemStyle: { color: one ? "#4a90c8" : col, opacity: one ? 0.55 : 0.8 }, barMaxWidth: 26,
      tooltip: { valueFormatter: (v) => (v == null ? "no data" : `${Math.round(Number(v))} mm`) } });
    if (temp) {
      if (one && c.low.some((v) => v !== null) && c.high.some((v) => v !== null)) {
        // the band: an invisible line at the low, then the gap up to the high stacked on it
        series.push({ type: "line", name: "Night-time low", data: pick(c.low), stack: "band", symbol: "none", lineStyle: { opacity: 0 },
          areaStyle: { opacity: 0 }, tooltip: { valueFormatter: (v) => (v == null ? "no data" : `${Number(v).toFixed(1)} °C`) } });
        series.push({ type: "line", name: "Daytime high", stack: "band", symbol: "none", lineStyle: { opacity: 0 },
          data: order.map((i) => (c.high[i] !== null && c.low[i] !== null ? (c.high[i] as number) - (c.low[i] as number) : null)),
          areaStyle: { color: "#e6550d", opacity: 0.18 },
          tooltip: { valueFormatter: () => "" } });
      }
      series.push({ type: "line", name: one ? "Average temperature" : c.name, data: pick(c.temp), smooth: true, symbolSize: 5,
        lineStyle: { width: 2.5, color: one ? "#d94801" : col }, itemStyle: { color: one ? "#d94801" : col },
        tooltip: { valueFormatter: (v) => (v == null ? "no data" : `${Number(v).toFixed(1)} °C`) } });
      if (one) {
        series.push({ type: "line", name: "Daytime high ", data: pick(c.high), symbol: "none", lineStyle: { width: 1, type: "dashed", color: "#e6550d" }, itemStyle: { color: "#e6550d" },
          tooltip: { valueFormatter: (v) => (v == null ? "no data" : `${Number(v).toFixed(1)} °C`) } });
        series.push({ type: "line", name: "Night-time low ", data: pick(c.low), symbol: "none", lineStyle: { width: 1, type: "dashed", color: "#3182bd" }, itemStyle: { color: "#3182bd" },
          tooltip: { valueFormatter: (v) => (v == null ? "no data" : `${Number(v).toFixed(1)} °C`) } });
      }
    }
  });
  return {
    ...base(),
    legend: { top: 0, textStyle: { color: cssVar("--ink-2") }, data: series.map((s) => String(s.name)).filter((n) => !(one && (n === "Night-time low" || n === "Daytime high"))) },
    xAxis: { type: "category", data: cats, axisLabel: { color: cssVar("--muted") }, axisLine: { lineStyle: { color: cssVar("--axis") } } },
    yAxis: yAxes,
    series,
  };
}

// ---------------------------------------------------------------- sea ice through the year
export type SeaIce = {
  pole: string; name: string; kind: "daily" | "monthly" | null; base?: string; source?: string;
  years: Record<string, [number, number][]>; // day of a 365-day year, million km²
  median: [number, number, number, number][]; // day, median, 10th, 90th percentile
  low: { year: number; day: string; value: number; partial: boolean }[];
  high: { year: number; day: string; value: number; partial: boolean }[];
  latest?: { day: string; value: number; median: number | null; rank: number | null; of: number };
};
export const seaIceApi = (pole: string) => get<SeaIce>("/climate/sea-ice", { pole });
export const ICE_COLOR = "#b5891b";
const MONTH_START = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335];
export const dayToDate = (year: number, x: number) => {
  let m = 0;
  while (m < 11 && MONTH_START[m + 1] <= x) m++;
  return new Date(Date.UTC(year, m, x - MONTH_START[m] + 1));
};
export const fmtDay = (d: Date) => `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;

// NSIDC's picture of the ice for a month, with the 1981-2010 median edge drawn on it.
export function iceImage(pole: string, year: number, month: number, version = "4.0"): string {
  const hemi = pole === "ATA" ? "south" : "north";
  const mm = String(month).padStart(2, "0");
  return `https://noaadata.apps.nsidc.org/NOAA/G02135/${hemi}/monthly/images/${mm}_${MONTHS[month - 1]}/${hemi === "south" ? "S" : "N"}_${year}${mm}_extent_v${version}.png`;
}

// Every year as a faint line, the chosen year bold, the 1981-2010 median dashed inside its 10th-90th band.
// circle: January at the top, the year running clockwise, the ice extent outwards from an empty middle
// (where the map goes). Otherwise an ordinary chart, January to December.
export function seaIceOption(d: SeaIce, year: number, circle: boolean, inner = "34%"): EChartsOption {
  const max = Math.ceil(Math.max(...Object.values(d.years).flat().map((p) => p[1]), ...d.median.map((m) => m[3])) + 0.5);
  const ink = cssVar("--ink-2"), muted = cssVar("--muted"), axis = cssVar("--axis");
  const pt = (p: [number, number]) => (circle ? [p[1], p[0]] : p);
  const coord = circle ? { coordinateSystem: "polar" as const, polarIndex: 0 } : {};
  const ys = Object.keys(d.years).map(Number).sort((a, b) => a - b);
  const series: SeriesOption[] = [];
  const band = d.median.map((m) => [m[0], m[2], m[3] - m[2]] as const);
  series.push({ type: "line", ...coord, name: "band-low", data: band.map((b) => pt([b[0], b[1]])), stack: "band", symbol: "none", silent: true,
    lineStyle: { opacity: 0 }, areaStyle: { opacity: 0 }, tooltip: { show: false }, z: 1 });
  series.push({ type: "line", ...coord, name: "Usual range (10th to 90th percentile, " + (d.base ?? "1981-2010") + ")", data: band.map((b) => pt([b[0], b[2]])),
    stack: "band", symbol: "none", silent: true, lineStyle: { opacity: 0 }, itemStyle: { color: muted }, areaStyle: { color: muted, opacity: 0.16 }, z: 1 });
  for (const y of ys) {
    if (y === year) continue;
    series.push({ type: "line", ...coord, name: String(y), data: d.years[String(y)].map(pt), symbol: "none", silent: true,
      lineStyle: { width: 0.7, color: muted, opacity: 0.35 }, z: 2, tooltip: { show: false } });
  }
  series.push({ type: "line", ...coord, name: `Median ${d.base ?? "1981-2010"}`, data: d.median.map((m) => pt([m[0], m[1]])), symbol: "none", silent: true,
    lineStyle: { width: 1.5, type: "dashed", color: ink }, itemStyle: { color: ink }, z: 3 });
  const lo = d.low.find((l) => l.year === year);
  series.push({ type: "line", ...coord, name: String(year), data: (d.years[String(year)] ?? []).map(pt), symbol: "none", silent: true,
    lineStyle: { width: 3, color: ICE_COLOR }, itemStyle: { color: ICE_COLOR }, z: 5,
    markPoint: lo ? { symbol: "circle", symbolSize: 9, itemStyle: { color: ICE_COLOR, borderColor: "#fff", borderWidth: 1.5 }, label: { show: false },
      data: [{ name: "lowest", coord: pt([dayOf(lo.day), lo.value]) as number[] }] } : undefined });
  series.push({ id: "hover", type: "scatter", ...coord, data: [], symbolSize: 13, silent: true, z: 6,
    itemStyle: { color: "transparent", borderColor: ICE_COLOR, borderWidth: 2.5 } });
  const legend = { bottom: 0, textStyle: { color: ink }, data: [String(year), `Median ${d.base ?? "1981-2010"}`, "Usual range (10th to 90th percentile, " + (d.base ?? "1981-2010") + ")"] };
  if (!circle) {
    return {
      ...base(), legend, tooltip: { show: false }, grid: { left: 8, right: 16, top: 16, bottom: 40, containLabel: true },
      xAxis: { type: "value", min: 1, max: 365, interval: 1, axisLabel: { show: false }, splitLine: { show: false }, axisTick: { show: false },
        axisLine: { lineStyle: { color: axis } } },
      yAxis: { type: "value", min: 0, max, name: "million km²", nameTextStyle: { color: muted }, axisLabel: { color: muted },
        splitLine: { lineStyle: { color: axis, opacity: 0.4 } } },
      graphic: [],
      series: [...series, { type: "line", data: [], markLine: { silent: true, symbol: "none", lineStyle: { color: axis, opacity: 0.5, type: "solid" },
        label: { position: "start", formatter: (p) => MONTHS[MONTH_START.indexOf(Number((p as { value: number }).value))] ?? "", color: muted },
        data: MONTH_START.map((s) => ({ xAxis: s })) } }],
    };
  }
  return {
    ...base(), legend, tooltip: { show: false },
    polar: [{ radius: [inner, "78%"], center: ["50%", "47%"] }, { radius: [inner, "78%"], center: ["50%", "47%"] }],
    angleAxis: [
      { polarIndex: 0, type: "value", min: 1, max: 366, startAngle: 90, clockwise: true, show: false },
      { polarIndex: 1, type: "category", data: MONTHS, startAngle: 90, clockwise: true, boundaryGap: true,
        axisLabel: { color: ink, fontSize: 13, margin: 12 }, axisLine: { lineStyle: { color: axis } }, axisTick: { show: false },
        splitLine: { show: true, lineStyle: { color: axis, opacity: 0.35 } } },
    ],
    radiusAxis: [
      { polarIndex: 0, type: "value", min: 0, max, interval: 5, axisLabel: { color: muted, fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false },
        splitLine: { show: true, lineStyle: { color: axis, type: "dotted", opacity: 0.6 } } },
      { polarIndex: 1, type: "value", min: 0, max, show: false },
    ],
    series,
  };
}

export function dayOf(iso: string): number {
  const d = new Date(iso + "T00:00:00Z");
  return MONTH_START[d.getUTCMonth()] + d.getUTCDate() - 1;
}

// The lowest (or highest) day of each year, the chosen year marked: click a year to choose it.
export function iceStripOption(d: SeaIce, year: number, which: "low" | "high"): EChartsOption {
  const rows = d[which];
  const muted = cssVar("--muted");
  return {
    ...base(), legend: { show: false },
    grid: { left: 8, right: 16, top: 22, bottom: 4, containLabel: true },
    tooltip: { ...base().tooltip, trigger: "axis", valueFormatter: (v) => `${Number(v).toFixed(2)} million km²` },
    xAxis: { type: "category", data: rows.map((r) => String(r.year)), axisLabel: { color: muted }, axisLine: { lineStyle: { color: cssVar("--axis") } } },
    yAxis: { type: "value", scale: true, axisLabel: { color: muted }, splitLine: { show: false } },
    series: [{ type: "line", name: which === "low" ? "Lowest day of the year" : "Highest day of the year", symbol: "circle", symbolSize: 4,
      // the first year starts in late October, so its lowest day is not a real low; the year in progress is shown faint
      data: rows.map((r, i) => (r.partial ? (i === 0 ? null : { value: r.value, itemStyle: { opacity: 0.4 } }) : r.value)),
      lineStyle: { color: cssVar("--ink-2"), width: 1.5 }, itemStyle: { color: cssVar("--ink-2") },
      markLine: { silent: true, symbol: "none", lineStyle: { color: ICE_COLOR, width: 2, type: "solid" }, label: { color: ICE_COLOR, formatter: String(year) },
        data: [{ xAxis: String(year) }] } }],
  };
}
