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

function tooltipFormatter(unit: string, decimals: number, names: Map<string, string>) {
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
          `${names.get(p.seriesName) ?? p.seriesName}: <b>${formatValue(p.value[1], unit, decimals)}</b>${proj}`;
      });
    return [`<b>${year}</b>`, ...lines].join("<br/>");
  };
}

function byEntity(rows: SeriesRow[]) {
  const out = new Map<string, SeriesRow[]>();
  for (const r of rows) {
    if (!out.has(r.entity_id)) out.set(r.entity_id, []);
    out.get(r.entity_id)!.push(r);
  }
  return out;
}

export function lineOption(rows: SeriesRow[], entities: Named[], unit: string, decimals: number): EChartsOption {
  const grouped = byEntity(rows);
  const names = new Map(entities.map((e) => [e.id, e.name]));
  const series: SeriesOption[] = [];
  entities.forEach((e, i) => {
    const pts = grouped.get(e.id) ?? [];
    const color = seriesColor(i);
    const est = pts.filter((p) => p.status === "E").map((p) => [+p.period, p.value]);
    const projRows = pts.filter((p) => p.status === "P");
    // Start the dashed line at the last estimate so the two parts join.
    const proj = projRows.length && est.length ? [est[est.length - 1], ...projRows.map((p) => [+p.period, p.value])]
      : projRows.map((p) => [+p.period, p.value]);
    const base = { type: "line" as const, name: e.id, showSymbol: false, symbolSize: 8, color, emphasis: { focus: "series" as const } };
    series.push({ ...base, id: `${e.id}:E`, data: est, lineStyle: { width: 2 } });
    if (proj.length) series.push({ ...base, id: `${e.id}:P`, data: proj, lineStyle: { width: 2, type: "dashed" } });
  });
  const base = chrome();
  return {
    ...base,
    grid: { ...(base.grid as object), top: entities.length > 1 ? 60 : 36 },
    legend: entities.length > 1 ? {
      top: 0, left: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8,
      textStyle: { color: cssVar("--ink-2") }, formatter: (id: string) => names.get(id) ?? id,
    } : undefined,
    yAxis: yAxis(unit),
    series,
    tooltip: { ...(chrome().tooltip as object), formatter: tooltipFormatter(unit, decimals, names) },
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
