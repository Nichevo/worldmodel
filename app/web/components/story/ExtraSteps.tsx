"use client";

// Story steps added with the third set of stories: monthly lines, dated events counted by year
// or country, and a map layer counted by country.

import { useCallback, useEffect, useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import EChart from "@/components/EChart";
import { Frame, notLoaded, type Props } from "@/components/story/Frame";
import { api, type EventRow, type SeriesRow } from "@/lib/api";
import { chrome } from "@/lib/charts";
import { cssVar, seriesColor } from "@/lib/colors";
import { formatValue } from "@/lib/format";
import { layerApi, type LayerDetail } from "@/lib/layerDetails";
import { entityColors, shortValue } from "@/lib/look";
import type { EventsData, LayerData, MonthlyData, Step } from "@/lib/story";

// "2024", "2024-Q2", "2024-03" or "2024-03-31" as an ISO date (the period's first day).
function isoOf(period: string): string {
  if (/^\d{4}$/.test(period)) return `${period}-01-01`;
  const q = period.match(/^(\d{4})-Q(\d)$/);
  if (q) return `${q[1]}-${String((+q[2] - 1) * 3 + 1).padStart(2, "0")}-01`;
  if (/^\d{4}-\d{2}$/.test(period)) return `${period}-01`;
  return period;
}

// ---------------------------------------------------------------- monthly lines
export function MonthlyStep(p: Props & { step: Extract<Step, { kind: "monthly" }> }) {
  const st = p.step;
  const [rows, setRows] = useState<SeriesRow[][] | null>(null);
  const key = st.series.map((s) => `${s.indicator}:${s.entity}`).join(",");
  useEffect(() => {
    Promise.all(st.series.map((s) => api.series(s.indicator, [s.entity], st.from).catch(() => [] as SeriesRow[]))).then(setRows);
  }, [key, st.from]); // eslint-disable-line react-hooks/exhaustive-deps
  const d = useMemo((): MonthlyData | null => {
    if (!rows) return null;
    const series = st.series.map((s, k) => {
      let pts = (rows[k] ?? []).filter((r) => r.entity_id === s.entity && r.status !== "P")
        .map((r) => [isoOf(r.period), r.value] as [string, number]).sort((a, b) => a[0].localeCompare(b[0]));
      const ind = p.inds.get(s.indicator);
      if (st.index && pts.length) { const b = pts[0][1]; pts = b ? pts.map(([t, v]) => [t, (100 * v) / b] as [string, number]) : pts; }
      const max = pts.length ? pts.reduce((a, b) => (b[1] > a[1] ? b : a)) : null;
      return { label: s.label, unit: st.index ? "index" : ind?.unit ?? "", pts, first: pts[0] ?? null, last: pts.at(-1) ?? null, max };
    });
    return { series };
  }, [rows, st, p.inds]);
  const option = useCallback((): EChartsOption => {
    if (!d) return {};
    const c = chrome();
    const shown = d.series.filter((s) => s.pts.length);
    return { ...c, grid: { left: 8, right: 150, top: 24, bottom: 8, containLabel: true },
      xAxis: { type: "time", axisLabel: { color: cssVar("--muted") } },
      yAxis: { type: "value", scale: true, name: st.index ? `first month = 100` : shown[0]?.unit, nameTextStyle: { color: cssVar("--muted"), align: "left" },
        axisLabel: { color: cssVar("--muted") }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
      tooltip: { ...(c.tooltip as object), trigger: "axis", valueFormatter: (v: unknown) => (typeof v === "number" ? v.toFixed(1) : String(v)) },
      series: shown.map((s, k) => { const col = st.series.find((x) => x.label === s.label)?.color ?? seriesColor(k);
        return { type: "line", name: s.label, showSymbol: false, color: col, lineStyle: { width: 2 }, data: s.pts,
          endLabel: { show: true, color: col, fontSize: 11, fontWeight: 600, formatter: () => `${s.label}  ${s.last ? s.last[1].toFixed(0) : ""}` },
          labelLayout: { moveOverlap: "shiftY" } }; }),
    } as EChartsOption;
  }, [d, st]);
  const none = d && d.series.every((s) => !s.pts.length);
  if (none) return <Frame {...p} sentence={null} data="" missing={notLoaded(st.series.map((s) => p.inds.get(s.indicator)?.name ?? s.indicator))} />;
  return (
    <Frame {...p} sentence={d ? st.say(d) : null} data={d ? d.series.map((s) => `${s.label} (${s.unit})\n${s.pts.map(([t, v]) => `${t.slice(0, 7)},${+v.toPrecision(5)}`).join("\n")}`).join("\n\n") : ""}>
      {d && <EChart option={option} height={380} label={p.title} />}
      <p className="caption">{st.series.map((s) => p.inds.get(s.indicator)?.name ?? s.label).join("; ")}.{st.index ? " Each line starts at 100, so they show change, not level." : ""}</p>
    </Frame>
  );
}

// ---------------------------------------------------------------- events by year or country
export function EventsStep(p: Props & { step: Extract<Step, { kind: "events" }> }) {
  const st = p.step;
  const [ev, setEv] = useState<EventRow[] | null>(null);
  useEffect(() => { api.events({ kinds: [st.event], start: String(st.from), limit: 20000 }).then(setEv).catch(() => setEv([])); }, [st.event, st.from]);
  const d = useMemo((): EventsData | null => {
    if (!ev) return null;
    const years = new Map<number, Record<string, number>>();
    const by = new Map<string, { name: string; n: number }>();
    for (const e of ev) {
      const y = +e.start_date.slice(0, 4);
      if (y < st.from) continue;
      const k = e.subkind ?? "other";
      const r = years.get(y) ?? {};
      r[k] = (r[k] ?? 0) + 1;
      years.set(y, r);
      const c = by.get(e.entity_id) ?? { name: e.entity_name ?? e.entity_id, n: 0 };
      c.n++;
      by.set(e.entity_id, c);
    }
    const last = Math.max(st.from, ...years.keys());
    const ys = Array.from({ length: last - st.from + 1 }, (_, i) => st.from + i)
      .map((y) => { const r = years.get(y) ?? {}; return { year: y, by: r, total: Object.values(r).reduce((a, b) => a + b, 0) }; });
    return { years: ys, countries: [...by.entries()].map(([id, c]) => ({ id, ...c })).sort((a, b) => b.n - a.n), total: ev.length, since: st.from };
  }, [ev, st.from]);
  const option = useCallback((): EChartsOption => {
    if (!d) return {};
    const c = chrome();
    if (st.show === "countries") {
      const rows = d.countries.slice(0, 15);
      const cols = entityColors(rows.map((r) => r.id));
      const key = new Set(["NZL", "AUS", "GBR", "USA"]);
      return { ...c, grid: { left: 8, right: 40, top: 8, bottom: 8, containLabel: true }, xAxis: { type: "value", show: false },
        yAxis: { type: "category", inverse: true, data: rows.map((r) => r.name), axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: cssVar("--ink-2") } },
        tooltip: { ...(c.tooltip as object), trigger: "item" },
        series: [{ type: "bar", barMaxWidth: 16, data: rows.map((r, k) => ({ value: r.n, itemStyle: { color: key.has(r.id) ? cols[k] : p.colour, borderRadius: 3 },
          label: { show: true, position: "right", color: cssVar("--ink"), fontSize: 11, fontWeight: 600 } })) }] } as EChartsOption;
    }
    const kinds = [...new Set(d.years.flatMap((y) => Object.keys(y.by)))].sort();
    const colour = (k: string, i: number) => (k === "successful" ? p.colour : k === "failed" ? cssVar("--muted") : seriesColor(i));
    return { ...c, grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
      legend: { top: 0, left: 0, textStyle: { color: cssVar("--ink-2") }, formatter: (n: string) => st.labels?.[n] ?? n },
      xAxis: { type: "category", data: d.years.map((y) => String(y.year)), axisLabel: { color: cssVar("--muted") } },
      yAxis: { type: "value", minInterval: 1, axisLabel: { color: cssVar("--muted") }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
      tooltip: { ...(c.tooltip as object), trigger: "axis" },
      series: kinds.map((k, i) => ({ type: "bar", stack: "all", name: k, color: colour(k, i), barMaxWidth: 10, data: d.years.map((y) => y.by[k] ?? 0) })) } as EChartsOption;
  }, [d, st, p.colour]);
  if (ev && !ev.length) return <Frame {...p} sentence={null} data="" missing={notLoaded([`${st.event} events`])} />;
  return (
    <Frame {...p} sentence={d ? st.say(d) : null} data={d ? ["Year,Total,By kind", ...d.years.map((y) => `${y.year},${y.total},"${JSON.stringify(y.by)}"`)].join("\n") : ""}>
      {d && <EChart option={option} height={st.show === "countries" ? 400 : 340} label={p.title} />}
      <p className="caption">{st.show === "countries" ? `Countries with the most, ${st.from} onward.` : `Each year from ${st.from}, split by outcome.`}</p>
    </Frame>
  );
}

// ---------------------------------------------------------------- a map layer by country
export function LayerStep(p: Props & { step: Extract<Step, { kind: "layer" }> }) {
  const st = p.step;
  const [g, setG] = useState<LayerDetail | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => { layerApi.detail(st.layer).then(setG).catch(() => setErr(true)); }, [st.layer]);
  const per = st.measure === "per_m";
  const d = useMemo((): LayerData | null => {
    if (!g) return null;
    const rows = g.countries.filter((r) => r.entity_id).map((r) => ({ id: r.entity_id!, name: r.name, v: per ? r.per_m ?? NaN : r.count }))
      .filter((r) => Number.isFinite(r.v) && r.v > 0).sort((a, b) => b.v - a.v);
    return { name: g.layer.name ?? g.layer.many, one: g.layer.one, many: g.layer.many, total: g.totals.count, rows,
      row: (id) => { const k = rows.findIndex((r) => r.id === id); return k < 0 ? undefined : { ...rows[k], rank: k + 1 }; } };
  }, [g, per]);
  const option = useCallback((): EChartsOption => {
    if (!d) return {};
    const top = d.rows.slice(0, st.top ?? 10);
    for (const id of st.also ?? []) { const r = d.rows.find((x) => x.id === id); if (r && !top.includes(r)) top.push(r); }
    const mark = new Set(st.also ?? []);
    const cols = entityColors(top.map((r) => r.id));
    const c = chrome();
    return { ...c, grid: { left: 8, right: 56, top: 8, bottom: 8, containLabel: true }, xAxis: { type: "value", show: false },
      yAxis: { type: "category", inverse: true, data: top.map((r) => r.name), axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: cssVar("--ink-2") } },
      tooltip: { ...(c.tooltip as object), trigger: "item" },
      series: [{ type: "bar", barMaxWidth: 16, data: top.map((r, k) => ({ value: r.v, itemStyle: { color: mark.has(r.id) ? cols[k] : p.colour, opacity: mark.size && !mark.has(r.id) ? 0.6 : 1, borderRadius: 3 },
        label: { show: true, position: "right", color: cssVar("--ink"), fontSize: 11, fontWeight: 600, formatter: () => (per ? r.v.toFixed(1) : shortValue(r.v, "", 0)) } })) }] } as EChartsOption;
  }, [d, st, p.colour, per]);
  if (err || (d && !d.rows.length)) return <Frame {...p} sentence={null} data="" missing={notLoaded([`the ${st.layer.replace(/_/g, " ")} map layer`])} />;
  return (
    <Frame {...p} sentence={d ? st.say(d) : null} data={d ? ["Country,Value", ...d.rows.map((r) => `"${r.name}",${+r.v.toPrecision(5)}`)].join("\n") : ""}>
      {d && <EChart option={option} height={Math.max(240, (Math.min(d.rows.length, st.top ?? 10) + (st.also?.length ?? 0)) * 24 + 20)} label={p.title} />}
      <p className="caption">{d ? `${d.many[0].toUpperCase()}${d.many.slice(1)}${per ? " per million people" : ""}, by country (map layer, ${formatValue(d.total, "", 0)} in all).` : ""}</p>
    </Frame>
  );
}
