// ECharts option builders. Estimates are solid; the source's projections are
// dashed (lines) or faded (bars), so forecasts never pass for data.

import type { EChartsOption, SeriesOption } from "echarts";
import type { SeriesRow } from "@/lib/api";
import { cssVar, seriesColor } from "@/lib/colors";
import { compact, formatValue } from "@/lib/format";

export type Named = { id: string; name: string };

function chrome(): EChartsOption {
  const ink2 = cssVar("--ink-2");
  const muted = cssVar("--muted");
  return {
    backgroundColor: "transparent",
    textStyle: { fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif", color: ink2 },
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    xAxis: {
      type: "value",
      min: "dataMin",
      max: "dataMax",
      axisLabel: { color: muted, formatter: (v: number) => String(v) },
      axisLine: { lineStyle: { color: cssVar("--axis") } },
      splitLine: { show: false },
    },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "line", lineStyle: { color: cssVar("--axis") } },
      backgroundColor: cssVar("--surface"),
      borderColor: cssVar("--border"),
      textStyle: { color: cssVar("--ink") },
    },
  };
}

function yAxis(unit: string): EChartsOption["yAxis"] {
  return {
    type: "value",
    scale: unit !== "persons" && !unit.includes("dollars"),
    axisLabel: { color: cssVar("--muted"), formatter: (v: number) => compact(v) },
    splitLine: { lineStyle: { color: cssVar("--grid") } },
    name: unit === "percent" ? "%" : unit,
    nameTextStyle: { color: cssVar("--muted"), align: "left" },
  };
}

function tooltipFormatter(labels: Map<string, string>, fmt: Map<string, (v: number) => string>) {
  return (params: unknown) => {
    const list = (Array.isArray(params) ? params : [params]) as {
      seriesId: string; seriesName: string; value: [number, number]; color: string;
    }[];
    if (!list.length) return "";
    const year = list[0].value[0];
    const seen = new Set<string>();
    const lines = list
      .filter((p) => {
        if (seen.has(p.seriesName)) return false;
        seen.add(p.seriesName);
        return true;
      })
      .map((p) => {
        const proj = p.seriesId.endsWith(":P") ? " <span style='opacity:.7'>(projection)</span>" : "";
        return `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${p.color};margin-right:6px"></span>` +
          `${labels.get(p.seriesName) ?? p.seriesName}: <b>${fmt.get(p.seriesName)?.(p.value[1]) ?? p.value[1]}</b>${proj}`;
      });
    return [`<b>${year}</b>`, ...lines].join("<br/>");
  };
}

export function lineOption(rows: SeriesRow[], entities: Named[], unit: string, decimals: number): EChartsOption {
  return linesOption([{ id: "", name: "", unit, decimals, rows }], entities);
}

// One indicator's rows for a multi-line chart.
export type Layer = { id: string; name: string; unit: string; decimals: number; rows: SeriesRow[] };

// A line per entity and indicator. Indicators in the first layer's unit share
// the left axis; one other unit gets a right axis (callers keep it to two units).
// Each series is named "entity|indicator" so hover can find its entity.
export function linesOption(layers: Layer[], entities: Named[]): EChartsOption {
  const names = new Map(entities.map((e) => [e.id, e.name]));
  const multi = layers.length > 1;
  const units = [...new Set(layers.map((l) => l.unit))].slice(0, 2);
  const series: SeriesOption[] = [];
  const labels = new Map<string, string>();
  const fmt = new Map<string, (v: number) => string>();
  let n = 0;
  for (const e of entities) {
    for (const l of layers) {
      const key = `${e.id}|${l.id}`;
      labels.set(key, multi ? (entities.length > 1 ? `${e.name} · ${l.name}` : l.name) : e.name);
      fmt.set(key, (v) => formatValue(v, l.unit, l.decimals));
      const pts = l.rows.filter((r) => r.entity_id === e.id);
      const est = pts.filter((p) => p.status === "E").map((p) => [+p.period, p.value]);
      const projRows = pts.filter((p) => p.status === "P");
      // Start the dashed line at the last estimate so the two parts join.
      const proj = projRows.length && est.length ? [est[est.length - 1], ...projRows.map((p) => [+p.period, p.value])]
        : projRows.map((p) => [+p.period, p.value]);
      const base = { type: "line" as const, name: key, showSymbol: false, symbolSize: 8, color: seriesColor(n++),
        yAxisIndex: Math.max(0, units.indexOf(l.unit)), emphasis: { focus: "series" as const } };
      series.push({ ...base, id: `${key}:E`, data: est, lineStyle: { width: 2 } });
      if (proj.length) series.push({ ...base, id: `${key}:P`, data: proj, lineStyle: { width: 2, type: "dashed" } });
    }
  }
  const base = chrome();
  const legend = n > 1;
  const right = units.length > 1 ? { ...(yAxis(units[1]) as object), position: "right", splitLine: { show: false },
    nameTextStyle: { color: cssVar("--muted"), align: "right" } } : null;
  return {
    ...base,
    grid: { ...(base.grid as object), top: legend ? 60 : 36 },
    legend: legend ? {
      top: 0, left: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, type: "scroll",
      textStyle: { color: cssVar("--ink-2") }, formatter: (key: string) => labels.get(key) ?? key,
    } : undefined,
    yAxis: (right ? [yAxis(units[0]), right] : yAxis(units[0])) as EChartsOption["yAxis"],
    series,
    tooltip: { ...(chrome().tooltip as object), formatter: tooltipFormatter(labels, fmt) },
  };
}

export function barOption(rows: SeriesRow[], entity: Named, unit: string, decimals: number): EChartsOption {
  const color = seriesColor(0);
  const names = new Map([[entity.id, entity.name]]);
  const data = rows.map((r) => ({
    value: [+r.period, r.value],
    itemStyle: { color, opacity: r.status === "P" ? 0.4 : 1, borderRadius: r.value >= 0 ? [3, 3, 0, 0] : [0, 0, 3, 3] },
  }));
  return {
    ...chrome(),
    yAxis: { ...(yAxis(unit) as object), scale: false },
    series: [{ type: "bar", id: `${entity.id}:E`, name: entity.id, data, barMaxWidth: 10 }],
    tooltip: {
      ...(chrome().tooltip as object),
      axisPointer: { type: "shadow" },
      formatter: (params: unknown) => {
        const p = (Array.isArray(params) ? params[0] : params) as { value: [number, number]; dataIndex: number };
        const r = rows[p.dataIndex];
        return `<b>${p.value[0]}</b><br/>${names.get(entity.id)}: <b>${formatValue(p.value[1], unit, decimals)}</b>` +
          (r?.status === "P" ? " (projection)" : "");
      },
    },
  };
}

export function pyramidOption(groups: { age: string; male?: number; female?: number }[], maleLabel = "Male", femaleLabel = "Female"): EChartsOption {
  const ages = groups.map((g) => g.age);
  const male = groups.map((g) => -(g.male ?? 0));
  const female = groups.map((g) => g.female ?? 0);
  const max = Math.max(...male.map(Math.abs), ...female, 1);
  const muted = cssVar("--muted");
  return {
    backgroundColor: "transparent",
    textStyle: { fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif", color: cssVar("--ink-2") },
    grid: { left: 8, right: 16, top: 30, bottom: 8, containLabel: true },
    legend: { top: 0, left: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: cssVar("--ink-2") } },
    xAxis: {
      type: "value", min: -max, max,
      axisLabel: { color: muted, formatter: (v: number) => compact(Math.abs(v)) },
      splitLine: { lineStyle: { color: cssVar("--grid") } },
    },
    yAxis: { type: "category", data: ages, axisTick: { show: false }, axisLabel: { color: muted, fontSize: 10 },
      axisLine: { lineStyle: { color: cssVar("--axis") } } },
    tooltip: {
      trigger: "axis", axisPointer: { type: "shadow" },
      backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"), textStyle: { color: cssVar("--ink") },
      formatter: (params: unknown) => {
        const list = params as { dataIndex: number }[];
        const g = groups[list[0].dataIndex];
        return `<b>Age ${g.age}</b><br/>${maleLabel}: ${formatValue(g.male, "persons")}<br/>${femaleLabel}: ${formatValue(g.female, "persons")}`;
      },
    },
    series: [
      { name: maleLabel, type: "bar", stack: "p", data: male, color: seriesColor(0), barCategoryGap: "12%", itemStyle: { borderRadius: [3, 0, 0, 3] } },
      { name: femaleLabel, type: "bar", stack: "p", data: female, color: seriesColor(1), itemStyle: { borderRadius: [0, 3, 3, 0] } },
    ],
  };
}

export type PyramidSide = { label: string; groups: { age: string; male?: number; female?: number }[] };

// A population pyramid, men left and women right, with an optional second pyramid
// drawn as an outline over the first so the two shapes compare directly. Shares
// of each population's own total by default, so countries of any size compare.
export function pyramidCompareOption(base: PyramidSide, overlay: PyramidSide | null, absolute: boolean): EChartsOption {
  const ages = base.groups.map((g) => g.age);
  const scaled = (side: PyramidSide) => {
    const total = side.groups.reduce((t, g) => t + (g.male ?? 0) + (g.female ?? 0), 0) || 1;
    const k = absolute ? 1 : 100 / total;
    const at = new Map(side.groups.map((g) => [g.age, g]));
    return {
      male: ages.map((a) => -((at.get(a)?.male ?? 0) * k)),
      female: ages.map((a) => (at.get(a)?.female ?? 0) * k),
    };
  };
  const a = scaled(base);
  const b = overlay ? scaled(overlay) : null;
  const max = Math.max(1e-9, ...a.male.map(Math.abs), ...a.female, ...(b ? [...b.male.map(Math.abs), ...b.female] : []));
  const fmt = (v: number) => (absolute ? formatValue(Math.abs(v), "persons") : `${Math.abs(v).toFixed(1)}%`);
  const muted = cssVar("--muted");
  const ink = cssVar("--ink");
  const outline = { color: "transparent", borderColor: ink, borderWidth: 1.5 };
  const series: SeriesOption[] = [
    { name: base.label, type: "bar", stack: "base", data: a.male, color: seriesColor(0), barCategoryGap: "12%", itemStyle: { borderRadius: [3, 0, 0, 3] } },
    { name: base.label, type: "bar", stack: "base", data: a.female, color: seriesColor(1), itemStyle: { borderRadius: [0, 3, 3, 0] } },
  ];
  if (b && overlay) {
    series.push(
      { name: overlay.label, type: "bar", stack: "overlay", data: b.male, barGap: "-100%", itemStyle: outline, color: ink, z: 3 },
      { name: overlay.label, type: "bar", stack: "overlay", data: b.female, barGap: "-100%", itemStyle: outline, color: ink, z: 3 },
    );
  }
  return {
    backgroundColor: "transparent",
    textStyle: { fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif", color: cssVar("--ink-2") },
    grid: { left: 8, right: 16, top: 34, bottom: 8, containLabel: true },
    legend: {
      top: 0, left: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: cssVar("--ink-2") },
      data: [base.label, ...(overlay ? [{ name: overlay.label, itemStyle: { color: "transparent", borderColor: ink, borderWidth: 1.5 } }] : [])],
    },
    graphic: [
      { type: "text", right: 16, top: 2, style: { text: "Men ◂  ▸ Women", fill: muted, fontSize: 11 } },
    ],
    xAxis: {
      type: "value", min: -max, max,
      axisLabel: { color: muted, formatter: (v: number) => (absolute ? compact(Math.abs(v)) : `${Math.abs(v)}%`) },
      splitLine: { lineStyle: { color: cssVar("--grid") } },
    },
    yAxis: { type: "category", data: ages, axisTick: { show: false }, axisLabel: { color: muted, fontSize: 10 },
      axisLine: { lineStyle: { color: cssVar("--axis") } } },
    tooltip: {
      trigger: "axis", axisPointer: { type: "shadow" },
      backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"), textStyle: { color: ink },
      formatter: (params: unknown) => {
        const i = (params as { dataIndex: number }[])[0].dataIndex;
        const line = (label: string, s: { male: number[]; female: number[] }) =>
          `${label}: men <b>${fmt(s.male[i])}</b>, women <b>${fmt(s.female[i])}</b>`;
        return [`<b>Age ${ages[i]}</b>`, line(base.label, a), ...(b && overlay ? [line(overlay.label, b)] : [])].join("<br/>");
      },
    },
    series,
  };
}

export type ScatterPoint = { id: string; name: string; x: number; y: number; size?: number; proj: boolean; group?: number };
export type Axis = { name: string; unit: string; decimals: number; log: boolean };
// How dots are coloured and labelled. grouped: dots carry a group index (one
// colour each; dots without one are grey), else only selected countries get colour.
// trim: fit each axis to the bulk of the countries; the few far outside it are
// drawn as triangles on the edge, with their real values in the tooltip.
export type ScatterStyle = { grouped: boolean; labelled: Set<string>; trim: boolean };

// The range outside which values count as outliers: 3 interquartile ranges
// beyond the quartiles (on the log scale for a log axis). Null when nothing is out.
export function outlierFence(values: number[], log: boolean): [number, number] | null {
  const v = values.map((x) => (log ? Math.log10(x) : x)).sort((a, b) => a - b);
  if (v.length < 8) return null;
  const q = (f: number) => v[Math.floor(f * (v.length - 1))];
  const iqr = q(0.75) - q(0.25);
  let lo = q(0.25) - 3 * iqr, hi = q(0.75) + 3 * iqr;
  if (v[0] >= lo && v[v.length - 1] <= hi) return null;
  lo = Math.max(lo, v[0]);
  hi = Math.min(hi, v[v.length - 1]);
  return log ? [10 ** lo, 10 ** hi] : [lo, hi];
}

// One dot per country: x and y from two indicators, optionally sized by a
// third (area proportional to the value). Selected countries keep their
// selection colour (or get a dark ring when colour shows groups) and a label.
// Projections are faded.
export function scatterOption(points: ScatterPoint[], x: Axis, y: Axis, size: Axis | null,
  selection: string[], style: ScatterStyle): EChartsOption {
  const max = size ? Math.max(0, ...points.map((p) => p.size ?? 0)) : 0;
  const radius = (v?: number) => (size ? (max > 0 && v && v > 0 ? 4 + 40 * Math.sqrt(v / max) : 4) : 9);
  const grey = cssVar("--ink-2");
  const ink = cssVar("--ink");
  const fx = style.trim ? outlierFence(points.map((p) => p.x), x.log) : null;
  const fy = style.trim ? outlierFence(points.map((p) => p.y), y.log) : null;
  const clamp = (v: number, f: [number, number] | null) => (f ? Math.min(f[1], Math.max(f[0], v)) : v);
  const data = points
    // Unselected first and big bubbles first, so small and selected dots stay on top.
    .sort((a, b) => (+selection.includes(a.id) - +selection.includes(b.id)) || ((b.size ?? 0) - (a.size ?? 0)))
    .map((p) => {
      const i = selection.indexOf(p.id);
      const on = i >= 0;
      const color = style.grouped ? (p.group !== undefined ? seriesColor(p.group) : grey) : on ? seriesColor(i) : grey;
      const strong = on || (style.grouped && p.group !== undefined);
      const ring = on && style.grouped;
      const px = clamp(p.x, fx), py = clamp(p.y, fy);
      const out = px !== p.x || py !== p.y;
      return {
        // Drawn at the clamped position; the real values ride along for the tooltip.
        name: p.id, value: [px, py, p.size ?? null, p.x, p.y],
        symbol: out ? "triangle" : "circle",
        symbolRotate: out ? (py > p.y ? 180 : px < p.x ? -90 : px > p.x ? 90 : 0) : 0,
        symbolSize: radius(p.size),
        itemStyle: {
          color, opacity: (strong ? 0.85 : 0.45) * (p.proj ? 0.6 : 1),
          borderColor: ring ? ink : "rgba(255,255,255,0.6)", borderWidth: ring ? 2 : 0.5,
        },
        label: { show: on || style.labelled.has(p.id), formatter: p.name, position: "right" as const,
          color: cssVar("--ink-2"), fontSize: 11, fontWeight: on ? ("bold" as const) : ("normal" as const) },
      };
    });
  const names = new Map(points.map((p) => [p.id, p.name]));
  const axis = (a: Axis, dim: "x" | "y", f: [number, number] | null) => ({
    type: a.log ? ("log" as const) : ("value" as const), scale: true, name: f ? `${a.name} (outliers at the edge)` : a.name,
    nameLocation: dim === "x" ? ("middle" as const) : ("end" as const), nameGap: dim === "x" ? 28 : 12,
    nameTextStyle: { color: cssVar("--muted"), align: dim === "y" ? ("left" as const) : undefined },
    axisLabel: { color: cssVar("--muted"), formatter: (v: number) => compact(v) },
    axisLine: { lineStyle: { color: cssVar("--axis") } },
    splitLine: { lineStyle: { color: cssVar("--grid") } },
  });
  const base = chrome();
  return {
    ...base,
    grid: { left: 8, right: 24, top: 36, bottom: 36, containLabel: true },
    xAxis: axis(x, "x", fx),
    yAxis: axis(y, "y", fy),
    series: [{ type: "scatter", data,
      // Hover is drawn by ECharts' own emphasis state (also set from other
      // panels via dispatchAction), so hovering never rebuilds the chart.
      emphasis: { focus: "none", scale: false, itemStyle: { borderColor: ink, borderWidth: 2 }, label: { show: true } },
      animationDurationUpdate: 300,
      labelLayout: { hideOverlap: true } }],
    tooltip: {
      ...(base.tooltip as object), trigger: "item",
      formatter: (p: unknown) => {
        const { name, value } = p as { name: string; value: [number, number, number | null, number, number] };
        const lines = [`<b>${names.get(name) ?? name}</b>`, `${x.name}: ${formatValue(value[3], x.unit, x.decimals)}`,
          `${y.name}: ${formatValue(value[4], y.unit, y.decimals)}`];
        if (size && value[2] !== null) lines.push(`${size.name}: ${formatValue(value[2], size.unit, size.decimals)}`);
        return lines.join("<br/>");
      },
    },
  };
}

// A popup's small chart: the country against its region and the world, with
// projections dashed and a rule at the year shown.
export type MiniLine = { label: string; points: [number, number, string][] };
export function miniOption(lines: MiniLine[], unit: string, decimals: number, year: number): EChartsOption {
  const series: SeriesOption[] = [];
  const fmt = new Map<string, (v: number) => string>();
  const labels = new Map<string, string>();
  lines.forEach((l, n) => {
    if (!l.points.length) return;
    const key = `${n}`;
    labels.set(key, l.label);
    fmt.set(key, (v) => formatValue(v, unit, decimals));
    const est = l.points.filter((p) => p[2] === "E").map((p) => [p[0], p[1]]);
    const proj = l.points.filter((p) => p[2] === "P").map((p) => [p[0], p[1]]);
    const color = n === 0 ? seriesColor(0) : n === 1 ? seriesColor(1) : cssVar("--muted");
    const base = { type: "line" as const, name: key, showSymbol: false, color, lineStyle: { width: n === 0 ? 2 : 1.5 } };
    series.push({ ...base, id: `${key}:E`, data: est });
    if (proj.length) series.push({ ...base, id: `${key}:P`, data: est.length ? [est[est.length - 1], ...proj] : proj,
      lineStyle: { ...base.lineStyle, type: "dashed" } });
  });
  series.push({ type: "line", id: "year", data: [], silent: true, markLine: { symbol: "none", silent: true, animation: false,
    label: { show: false }, lineStyle: { color: cssVar("--axis"), type: "solid", width: 1 }, data: [{ xAxis: year }] } });
  const base = chrome();
  return {
    ...base,
    animation: false,
    grid: { left: 2, right: 6, top: 8, bottom: 2, containLabel: true },
    xAxis: { ...(base.xAxis as object), axisLabel: { color: cssVar("--muted"), fontSize: 9, formatter: (v: number) => String(v) } },
    yAxis: { ...(yAxis(unit) as object), name: "", axisLabel: { color: cssVar("--muted"), fontSize: 9, formatter: (v: number) => compact(v) } },
    series,
    tooltip: { ...(base.tooltip as object), confine: true, formatter: tooltipFormatter(labels, fmt) },
  };
}

// A tiny inline SVG trend line for map tooltips: the values up to the year shown,
// with a dot on that year.
export function sparklineSvg(years: number[], values: (number | null)[], upTo: number, color: string, span = 30): string {
  const pts: [number, number][] = [];
  years.forEach((y, i) => { if (y <= upTo && y > upTo - span && values[i] !== null) pts.push([y, values[i] as number]); });
  if (pts.length < 2) return "";
  const w = 140, h = 34, pad = 3;
  const x0 = pts[0][0], x1 = pts[pts.length - 1][0];
  const vs = pts.map((p) => p[1]);
  const lo = Math.min(...vs), hi = Math.max(...vs);
  const sx = (x: number) => pad + ((x - x0) / Math.max(1, x1 - x0)) * (w - 2 * pad);
  const sy = (v: number) => h - pad - ((v - lo) / (hi - lo || 1)) * (h - 2 * pad);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join("");
  const last = pts[pts.length - 1];
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="display:block;margin-top:4px" aria-hidden="true">` +
    `<path d="${d}" fill="none" stroke="${color}" stroke-width="1.5"/>` +
    `<circle cx="${sx(last[0]).toFixed(1)}" cy="${sy(last[1]).toFixed(1)}" r="2.5" fill="${color}"/></svg>` +
    `<span style="font-size:10px;opacity:.7">${x0}–${x1}</span>`;
}

// ---------------------------------------------------------------------------- Data status page
// Charts of the refresh log: one bar or point per refresh run, oldest first.
export type RunPoint = { label: string; when: string };
const GBYTES = 1024 ** 3;

function runAxis(runs: RunPoint[]): EChartsOption["xAxis"] {
  return {
    type: "category", data: runs.map((r) => r.label),
    axisLabel: { color: cssVar("--muted"), fontSize: 10, hideOverlap: true },
    axisLine: { lineStyle: { color: cssVar("--axis") } }, axisTick: { show: false },
  };
}

function runChrome(legend: boolean): EChartsOption {
  const base = chrome();
  return {
    ...base,
    grid: { left: 8, right: 16, top: legend ? 34 : 16, bottom: 8, containLabel: true },
    legend: legend ? { top: 0, left: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: cssVar("--ink-2") } } : undefined,
    tooltip: { ...(base.tooltip as object), trigger: "axis", confine: true },
  };
}

// Disk use by category after each run, stacked, with the 80% and 95% lines of the
// limit drawn when the total comes near enough for them to matter.
export function spaceOption(runs: RunPoint[], cats: { key: string; label: string }[], disk: Record<string, number>[], limit: number): EChartsOption {
  const totals = disk.map((d) => cats.reduce((t, c) => t + (d[c.key] ?? 0), 0));
  const showLimits = Math.max(0, ...totals) > limit * 0.5;
  const series: SeriesOption[] = cats.map((c, i) => ({
    type: "line", name: c.label, stack: "disk", areaStyle: { opacity: 0.85 }, symbol: "none", lineStyle: { width: 0 },
    color: seriesColor(i), data: disk.map((d) => +(((d[c.key] ?? 0) / GBYTES).toFixed(3))),
  }));
  if (showLimits) series.push({
    type: "line", name: "limit", data: [], silent: true, markLine: {
      symbol: "none", silent: true, label: { color: cssVar("--ink-2"), formatter: "{b}", position: "insideEndTop" },
      lineStyle: { color: cssVar("--ink-2"), type: "dashed", width: 1 },
      data: [{ yAxis: +((limit * 0.8) / GBYTES).toFixed(2), name: "80%" }, { yAxis: +((limit * 0.95) / GBYTES).toFixed(2), name: "95%" }],
    },
  });
  return {
    ...runChrome(true),
    legend: { ...(runChrome(true).legend as object), data: cats.map((c) => c.label) },
    xAxis: runAxis(runs),
    yAxis: { type: "value",
      axisLabel: { color: cssVar("--muted") }, splitLine: { lineStyle: { color: cssVar("--grid") } },
      max: showLimits ? Math.max(limit / GBYTES, ...totals.map((t) => t / GBYTES)) : undefined },
    tooltip: { ...(runChrome(true).tooltip as object), valueFormatter: (v: unknown) => `${(+(v as number)).toFixed(2)} GB` },
    series,
  };
}

// Rows added, changed and removed by each run, all sources together.
export function changesOption(runs: RunPoint[], added: number[], changed: number[], removed: number[]): EChartsOption {
  const bar = (name: string, data: number[], i: number): SeriesOption => ({
    type: "bar", name, stack: "rows", data, color: seriesColor(i), barMaxWidth: 18,
    itemStyle: { borderColor: cssVar("--surface"), borderWidth: 1 },
  });
  return {
    ...runChrome(true),
    xAxis: runAxis(runs),
    yAxis: { type: "value",
      axisLabel: { color: cssVar("--muted"), formatter: (v: number) => compact(v) }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
    tooltip: { ...(runChrome(true).tooltip as object), valueFormatter: (v: unknown) => (+(v as number)).toLocaleString("en") },
    series: [bar("Added", added, 0), bar("Changed", changed, 1), bar("Removed", removed, 2)],
  };
}

// How long each run took; failed runs in red, named in the tooltip.
export function healthOption(runs: (RunPoint & { minutes: number | null; ok: boolean; note: string })[]): EChartsOption {
  return {
    ...runChrome(false),
    xAxis: runAxis(runs),
    yAxis: { type: "value",
      axisLabel: { color: cssVar("--muted") }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
    tooltip: {
      ...(runChrome(false).tooltip as object), trigger: "item",
      formatter: (p: unknown) => {
        const r = runs[(p as { dataIndex: number }).dataIndex];
        return `<b>${r.when}</b><br/>${r.ok ? "Passed" : "<b>Failed</b>"}${r.minutes !== null ? `, ${r.minutes.toFixed(1)} min` : ""}<br/>${r.note}`;
      },
    },
    series: [{
      type: "bar", barMaxWidth: 18,
      data: runs.map((r) => ({ value: r.minutes ?? 0, itemStyle: { color: r.ok ? seriesColor(0) : cssVar("--div-neg-3"), borderRadius: [3, 3, 0, 0] } })),
    }],
  };
}
