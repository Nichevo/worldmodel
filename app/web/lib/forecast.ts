"use client";

// The Forecast button on charts: fetch a statistical forecast for each line and draw
// it on the chart as a dotted line with its 80% and 95% ranges as shaded bands, plus,
// for a single country, each forecaster's own latest projections (IMF, OECD, World
// Bank). Settings: Forecasts (how far ahead, which ranges, forecasters on or off).
import type { CustomSeriesRenderItemAPI, CustomSeriesRenderItemParams, EChartsOption, SeriesOption } from "echarts";
import { entityColors } from "@/lib/look";
import { useEffect, useState } from "react";
import { api, type Forecast } from "@/lib/api";
import { seriesColor } from "@/lib/colors";
import { formatValue } from "@/lib/format";
import { useSettings } from "@/lib/settings";

export type ForecastSet = { byEntity: Map<string, Forecast>; errors: Map<string, string> };

// Fetches forecasts for up to eight entities while `on`; null while off or loading.
export function useForecasts(indicator: string | null, entities: string[], on: boolean): ForecastSet | null {
  const s = useSettings();
  const [set, setSet] = useState<ForecastSet | null>(null);
  const ids = entities.slice(0, 8).join(",");
  useEffect(() => {
    if (!on || !indicator || !ids) { setSet(null); return; }
    let live = true;
    const list = ids.split(",");
    Promise.all(list.map((e, i) => api.forecast(indicator, e, s.forecast_horizon, s.forecast_official && list.length === 1 && i === 0)
      .then((f) => [e, f] as const).catch((err) => [e, String(err.message || err)] as const)))
      .then((res) => {
        if (!live) return;
        const byEntity = new Map<string, Forecast>(), errors = new Map<string, string>();
        for (const [e, r] of res) {
          if (typeof r === "string") errors.set(e, r); else byEntity.set(e, r);
        }
        setSet({ byEntity, errors });
      });
    return () => { live = false; };
  }, [indicator, ids, on, s.forecast_horizon, s.forecast_official]);
  return set;
}

const OFFICIAL_COLORS = ["#b45309", "#7c3aed", "#0f766e", "#be185d", "#4d7c0f"];

// A shaded band between two lines, drawn as one polygon (works on a value x axis).
function band(id: string, pts: [number, number, number][], color: string, opacity: number, yAxisIndex = 0): SeriesOption {
  return {
    type: "custom", id, name: id, silent: true, z: 1, yAxisIndex, data: pts, encode: { x: 0, y: [1, 2] },
    renderItem: (params: CustomSeriesRenderItemParams, api: CustomSeriesRenderItemAPI) => {
      if (params.dataIndex !== 0) return null;
      const top = pts.map((p) => api.coord([p[0], p[2]]));
      const bottom = pts.map((p) => api.coord([p[0], p[1]])).reverse();
      return { type: "polygon", shape: { points: [...top, ...bottom] }, style: { fill: color, opacity } };
    },
  } as SeriesOption;
}

// Adds the forecasts to a line chart made by linesOption (one indicator, entities in
// order, so entity i has colour i). `skipSource` leaves out the official projections
// of the source the chart already draws (its dashed line).
export function withForecast(o: EChartsOption, set: ForecastSet | null, entities: { id: string; name: string }[],
  ranges: "80+95" | "80" | "none", skipSource?: string): EChartsOption {
  if (!set || !set.byEntity.size) return o;
  const extra: SeriesOption[] = [];
  const labels = new Map<string, string>();
  const fmt = new Map<string, (v: number) => string>();
  const single = entities.length === 1;
  const colors = entityColors(entities.map((e) => e.id));
  entities.forEach((e, i) => {
    const f = set.byEntity.get(e.id);
    if (!f) return;
    const color = colors[i];
    const start: [number, number, number] = [f.history_end, f.last_value, f.last_value];
    const show = (v: number) => formatValue(v, f.unit, f.decimals);
    if (ranges === "80+95" && single) {
      extra.push(band(`fc:${e.id}:95`, [start, ...f.points.map((p) => [p.year, p.lo95, p.hi95] as [number, number, number])], color, 0.10));
    }
    if (ranges !== "none") {
      extra.push(band(`fc:${e.id}:80`, [start, ...f.points.map((p) => [p.year, p.lo80, p.hi80] as [number, number, number])], color, single ? 0.18 : 0.10));
    }
    const key = `fc:${e.id}:mean`;
    labels.set(key, `${single ? "Forecast" : `${e.name}, forecast`}`);
    fmt.set(key, (v) => {
      const p = f.points.find((q) => Math.abs(q.mean - v) < 1e-9);
      const r = p && ranges !== "none" ? ` <span style="opacity:.7">(80%: ${show(p.lo80)} to ${show(p.hi80)}${ranges === "80+95" ? `; 95%: ${show(p.lo95)} to ${show(p.hi95)}` : ""})</span>` : "";
      return `<b>${show(v)}</b>${r}`;
    });
    extra.push({ type: "line", id: key, name: key, showSymbol: false, color, z: 3,
      lineStyle: { width: 2, type: [2, 4] as unknown as "dotted" }, data: [[start[0], start[1]], ...f.points.map((p) => [p.year, p.mean])] });
    if (single) {
      f.official.filter((x) => x.source_id !== skipSource).forEach((x, j) => {
        const k = `fc:off:${x.source_id}`;
        labels.set(k, `${x.name} forecast (${x.release.slice(0, 7)})`);
        fmt.set(k, (v) => `<b>${show(v)}</b>`);
        extra.push({ type: "line", id: k, name: k, showSymbol: true, symbolSize: 4, z: 3, color: OFFICIAL_COLORS[j % OFFICIAL_COLORS.length],
          lineStyle: { width: 1.5, type: "dashed" }, data: x.points });
      });
    }
  });
  const prev = (o.tooltip as { formatter?: (p: unknown) => string } | undefined)?.formatter;
  const formatter = (params: unknown) => {
    const list = (Array.isArray(params) ? params : [params]) as { seriesId: string; value: [number, number]; color: string }[];
    const mine = list.filter((p) => p.seriesId?.startsWith("fc:") && labels.has(p.seriesId));
    const rest = list.filter((p) => !p.seriesId?.startsWith("fc:"));
    const head = rest.length && prev ? prev(rest) : list.length ? `<b>${list[0].value[0]}</b>` : "";
    const lines = mine.map((p) => `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${p.color};margin-right:6px"></span>`
        + `${labels.get(p.seriesId)}: ${fmt.get(p.seriesId)?.(p.value[1]) ?? p.value[1]}`);
    return [head, ...lines].filter(Boolean).join("<br/>");
  };
  const legend = o.legend as { formatter?: (k: string) => string; data?: unknown } | undefined;
  return {
    ...o,
    xAxis: { ...(o.xAxis as object), max: "dataMax" },
    // The legend keeps to the chart's own lines (the forecasts share their colours).
    legend: (legend ? { ...legend, data: legend.data ?? [...new Set(((o.series as { name?: string; type?: string }[]) ?? [])
      .filter((x) => x.type === "line" && x.name && x.name !== "year-marker").map((x) => x.name!))] } : legend) as EChartsOption["legend"],
    series: [...((o.series as SeriesOption[]) ?? []), ...extra],
    tooltip: { ...(o.tooltip as object), formatter },
  };
}

// One line under the chart: which model, how it did, and where the ranges come from.
export function forecastCaption(set: ForecastSet | null, entities: { id: string; name: string }[],
  ranges: "80+95" | "80" | "none" = "80+95"): string {
  if (!set) return "";
  const parts: string[] = [];
  for (const e of entities) {
    const f = set.byEntity.get(e.id);
    if (f) {
      const best = f.models.find((m) => m.id === f.model);
      parts.push(`${entities.length > 1 ? `${e.name}: ` : ""}${f.model_name.toLowerCase()} from ${f.history_end}` +
        (best?.mae != null ? `, typical miss ${formatValue(best.mae, f.unit, f.decimals)} in the back-test` : ""));
    } else if (set.errors.has(e.id)) {
      parts.push(`${e.name}: no forecast (${set.errors.get(e.id)!.replace(/^\d+: /, "")})`);
    }
  }
  const bands = ranges === "none" ? "" : ranges === "80" || entities.length > 1
    ? " The band is the range it fell inside 80% of the time." : " Bands are the ranges it fell inside 80% and 95% of the time.";
  return parts.length ? `Forecast (dotted): ${parts.join("; ")}.${bands}` : "";
}
