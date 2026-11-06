"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import { api, type Regions } from "@/lib/api";
import { useSavePicture } from "@/lib/cards";
import { cssVar, seriesColor } from "@/lib/colors";
import { formatValue } from "@/lib/format";
import { short } from "@/lib/sectors";

// A country's regions (New Zealand's 16, from Stats NZ): one figure at a time, as bars for
// a year or lines over the years, and a table of every figure's latest year. Counts of
// people can be shown as a share of each region's population.
export default function RegionsCard({ entity, name }: { entity: string; name: string }) {
  const [data, setData] = useState<Regions | null>(null);
  const [pick, setPick] = useState<string | null>(null);
  const [year, setYear] = useState<number | null>(null);
  const [view, setView] = useState<"bars" | "lines">("bars");
  const [share, setShare] = useState(false);
  const { onReady, save, ask } = useSavePicture();
  useEffect(() => {
    let live = true;
    api.regions(entity).then((d) => live && setData(d)).catch(() => live && setData(null));
    return () => { live = false; };
  }, [entity]);
  const m = data?.measures.find((x) => x.indicator_id === pick) ?? data?.measures.find((x) => x.indicator_id === "nzreg_population") ?? data?.measures[0];
  const y = year && m?.years.includes(year) ? year : m?.years[m.years.length - 1];
  const names = useMemo(() => new Map((data?.regions ?? []).map((r) => [r.entity_id, r.name])), [data]);
  // Population to divide by: the census count in a census year, else the estimate for that year.
  const pop = useCallback((e: string, yr: number) => {
    const c = data?.measures.find((x) => x.indicator_id === "nzreg_census_population")?.values[e]?.[String(yr)];
    return c ?? data?.measures.find((x) => x.indicator_id === "nzreg_population")?.values[e]?.[String(yr)] ?? null;
  }, [data]);
  const canShare = !!m && m.unit === "people" && !["nzreg_population", "nzreg_census_population"].includes(m.indicator_id);
  const asShare = share && canShare;
  const val = useCallback((e: string, yr: number) => {
    const v = m?.values[e]?.[String(yr)];
    if (v == null) return null;
    if (!asShare) return v;
    const p = pop(e, yr);
    return p ? (100 * v) / p : null;
  }, [m, asShare, pop]);
  const unit = asShare ? "% of people" : m?.unit ?? "";
  const option = useCallback(() => {
    if (!m || y == null) return {};
    const base = { backgroundColor: "transparent", textStyle: { color: cssVar("--ink-2") },
      tooltip: { trigger: "axis" as const, confine: true, backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"), textStyle: { color: cssVar("--ink") },
        valueFormatter: (v: unknown) => (typeof v === "number" ? `${formatValue(v, unit, asShare ? 1 : m.decimals)} ${unit}` : String(v)) } };
    if (view === "bars") {
      const rows = (data?.regions ?? []).map((r) => ({ name: r.name, v: val(r.entity_id, y) })).filter((r) => r.v != null).sort((a, b) => a.v! - b.v!);
      return { ...base, grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
        xAxis: { type: "value", axisLabel: { color: cssVar("--muted"), formatter: short }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
        yAxis: { type: "category", data: rows.map((r) => r.name), axisLabel: { color: cssVar("--ink-2") } },
        series: [{ type: "bar", data: rows.map((r) => r.v), itemStyle: { color: seriesColor(0) }, label: { show: true, position: "right", color: cssVar("--muted"),
          formatter: (p: { value: number }) => (asShare ? `${p.value.toFixed(1)}%` : short(p.value)) } }] };
    }
    return { ...base, grid: { left: 8, right: 16, top: 48, bottom: 8, containLabel: true }, legend: { top: 0, type: "scroll", textStyle: { color: cssVar("--ink-2") } },
      xAxis: { type: "value", min: "dataMin", max: "dataMax", minInterval: 1, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => String(v) } },
      yAxis: { type: "value", scale: true, axisLabel: { color: cssVar("--muted"), formatter: short }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
      series: (data?.regions ?? []).map((r, i) => ({ type: "line", name: r.name, showSymbol: m.years.length < 6, lineStyle: { color: seriesColor(i), width: 1.5 }, itemStyle: { color: seriesColor(i) },
        data: m.years.map((yr) => [yr, val(r.entity_id, yr)]).filter((p) => p[1] != null) })) };
  }, [m, y, view, data, val, unit, asShare]);
  if (!data?.measures.length || !m) return null;
  const title = `${m.name}${asShare ? " (share of people)" : ""}, ${view === "bars" ? y : `${m.years[0]}–${m.years[m.years.length - 1]}`}`;
  const latest = (mm: Regions["measures"][number], e: string) => { const ys = mm.years.filter((yr) => mm.values[e]?.[String(yr)] != null); return ys.length ? mm.values[e][String(ys[ys.length - 1])] : null; };
  return (
    <div className="card" id="regions">
      <div className="card-head">
        <h3>Regions of {name}</h3>
        <span>
          <CardAsk onAsk={() => ask(title, "", ["statsnz"], entity)} />{" "}
          <button className="link small" onClick={() => save(title, "", ["statsnz"], "regions", m.indicator_id, entity)}>Save picture</button>
        </span>
      </div>
      <div className="chips-row small">
        <label>Figure <select value={m.indicator_id} onChange={(e) => setPick(e.target.value)}>
          {data.measures.map((x) => <option key={x.indicator_id} value={x.indicator_id}>{x.name.replace(/ \(NZ regions\)$/, "")}</option>)}</select></label>
        <div className="seg" role="group" aria-label="Chart">
          <button className={view === "bars" ? "on" : ""} aria-pressed={view === "bars"} onClick={() => setView("bars")}>One year</button>
          <button className={view === "lines" ? "on" : ""} aria-pressed={view === "lines"} disabled={m.years.length < 2} onClick={() => setView("lines")}>Over time</button>
        </div>
        {view === "bars" && <label>Year <select value={y} onChange={(e) => setYear(+e.target.value)}>{m.years.map((yr) => <option key={yr}>{yr}</option>)}</select></label>}
        {canShare && <label><input type="checkbox" checked={share} onChange={(e) => setShare(e.target.checked)} /> As a share of people</label>}
      </div>
      <EChart option={option} height={view === "bars" ? 380 : 320} label={title} onReady={onReady} />
      <details>
        <summary className="small">Every figure, latest year</summary>
        <div style={{ overflowX: "auto" }}>
          <table className="small">
            <thead><tr><th>Region</th>{data.measures.map((x) => <th key={x.indicator_id} className="num">{x.name.replace(/ \(NZ regions\)$/, "")}</th>)}</tr></thead>
            <tbody>{data.regions.map((r) => (
              <tr key={r.entity_id}><td><Link href={`/entity/${r.entity_id}`}>{r.name}</Link></td>
                {data.measures.map((x) => { const v = latest(x, r.entity_id); return <td key={x.indicator_id} className="num">{v == null ? "" : formatValue(v, x.unit, x.decimals)}</td>; })}</tr>
            ))}</tbody>
          </table>
        </div>
      </details>
      <p className="caption">Stats NZ, Aotearoa Data Explorer (CC BY 4.0): {[...new Set(data.measures.map((x) => x.name.replace(/ \(NZ regions\)$/, "")))].slice(0, 6).join(", ")}{data.measures.length > 6 ? " and more" : ""}.
        Regional council areas; {names.size} regions.</p>
    </div>
  );
}
