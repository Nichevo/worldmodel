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
