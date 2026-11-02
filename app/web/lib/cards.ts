// Shared pieces of the country page's topic cards (house prices, migration,
// education): load a set of indicators for one country, pick the first one that
// has figures, and save the card's chart as a picture with its sources.

import type { ECharts } from "echarts";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Indicator, type SeriesRow } from "@/lib/api";
import { credits, fileName, saveUrl, titledPng } from "@/lib/download";
import { openAsk } from "@/lib/ai";

// Every listed indicator the warehouse has, for one country: id -> rows (empty if none).
export function useSeries(entity: string, ids: string[], indicators: Map<string, Indicator>) {
  const wanted = ids.filter((id) => indicators.get(id)?.available);
  const key = wanted.join(",");
  const [data, setData] = useState<Map<string, SeriesRow[]> | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!key) { setData(new Map()); return; }
    let live = true;
    setData(null);
    Promise.all(key.split(",").map((id) => api.series(id, [entity]).then((rows) => [id, rows] as const)))
      .then((found) => { if (live) { setData(new Map(found)); setError(null); } })
      .catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [entity, key]);
  return { data, error };
}

// The first id in order of preference with figures.
export function firstWith(data: Map<string, SeriesRow[]> | null, ids: string[]): string | null {
  return ids.find((id) => (data?.get(id)?.length ?? 0) > 0) ?? null;
}

export function points(rows: SeriesRow[] | undefined): [number, number, string][] {
  return (rows ?? []).map((r) => [+r.period, r.value, r.status] as [number, number, string]).sort((a, b) => a[0] - b[0]);
}

// Rebase a series so that `year` is 100.
export function indexed(pts: [number, number, string][], year: number): [number, number, string][] {
  const base = pts.find((p) => p[0] === year)?.[1];
  return base ? pts.map((p) => [p[0], (100 * p[1]) / base, p[2]] as [number, number, string]) : [];
}

// Save the card's chart as a picture with a title, a note and the sources' credits.
export function useSavePicture() {
  const chart = useRef<ECharts | null>(null);
  const onReady = useCallback((c: ECharts) => { chart.current = c; }, []);
  const save = async (title: string, note: string, sources: (string | null | undefined)[], ...name: string[]) => {
    const c = chart.current;
    if (!c || c.isDisposed()) return;
    const url = await titledPng(c.getDataURL({ type: "svg" }), c.getWidth(), c.getHeight(), title, note, await credits(sources));
    saveUrl(url, `${fileName(...name)}.png`);
  };
  // Ask AI about the card's chart: what it draws, read back from the chart as a table, and
  // a picture of it for models that can see pictures.
  const ask = (title: string, note: string, sources: (string | null | undefined)[], entity?: string) => {
    const c = chart.current;
    if (!c || c.isDisposed()) return;
    openAsk({
      title, entity,
      parts: [{ key: "data", kind: "data", label: `${title} (the chart's figures)`, text: [note, chartText(c)].filter(Boolean).join("\n") }],
      picture: async () => (c.isDisposed() ? null : titledPng(c.getDataURL({ type: "svg" }), c.getWidth(), c.getHeight(), title, note, await credits(sources))),
    });
  };
  return { onReady, save, ask };
}

// What a chart draws, as CSV: a column per series against its category axis (years), or
// x,y pairs, or a flow chart's links. Read back from the chart itself, so any card can use it.
export function chartText(c: ECharts): string {
  const o = c.getOption() as {
    xAxis?: { type?: string; data?: unknown[] }[]; yAxis?: { type?: string; data?: unknown[] }[];
    series?: { type?: string; name?: string; data?: unknown[]; links?: { source: string; target: string; value: number }[] }[];
  };
  const series = (o.series ?? []).filter((x) => (x.data?.length || x.links?.length) && x.name !== "Total");
  const sankey = series.find((x) => x.links?.length);
  if (sankey) return ["From,To,Value", ...sankey.links!.map((l) => `"${l.source}","${l.target}",${+(+l.value).toPrecision(6)}`)].join("\n");
  const num = (v: unknown): string => {
    const x = v && typeof v === "object" && "value" in v ? (v as { value: unknown }).value : v;
    const y = Array.isArray(x) ? x[x.length > 1 ? 1 : 0] : x;
    return typeof y === "number" && Number.isFinite(y) ? String(+y.toPrecision(6)) : "";
  };
  const cat = [...(o.xAxis ?? []), ...(o.yAxis ?? [])].find((a) => a.type === "category" && a.data?.length);
  if (cat) {
    const head = ["", ...series.map((x) => `"${x.name ?? ""}"`)].join(",");
    return [head, ...cat.data!.map((label, i) => [`"${String(label)}"`, ...series.map((x) => num(x.data![i]))].join(","))].join("\n");
  }
  return series.map((x) => [`# ${x.name ?? ""}`, ...(x.data ?? []).map((d) => {
    const v = d && typeof d === "object" && "value" in d ? (d as { value: unknown }).value : d;
    return Array.isArray(v) ? v.slice(0, 2).map((n) => (typeof n === "number" ? +n.toPrecision(6) : n)).join(",") : String(v);
  })].join("\n")).join("\n\n");
}
