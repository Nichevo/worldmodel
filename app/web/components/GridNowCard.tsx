"use client";

import type { EChartsOption } from "echarts";
import { useCallback, useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import { fuelColor } from "@/components/EnergyFlowCard";
import { api, type GridNow } from "@/lib/api";
import { openAsk } from "@/lib/ai";
import { cssVar, seriesColor } from "@/lib/colors";
import { formatValue } from "@/lib/format";
import { short } from "@/lib/sectors";

// The electricity grid as it runs now, for New Zealand, Australia, Great Britain and the US:
// generation by fuel over the last two days (stacked), demand and links to neighbours, and a
// "right now" table. Read from the grid operators only while this card is open (at most every
// five minutes, kept on the server), never saved. Fuel colours match the energy flow chart.
export const GRID_COUNTRIES = ["NZL", "AUS", "GBR", "USA"];
const EVERY = 5 * 60 * 1000;

const mw = (v: number) => `${formatValue(v, "", 0)} MW`;

export default function GridNowCard({ entity, name }: { entity: string; name: string }) {
  const [g, setG] = useState<GridNow | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    setBusy(true);
    api.gridNow(entity).then(setG).catch((e) => setG({ country: entity, name, tz: "UTC", source: "", error: String(e.message || e),
      series: [], mix: [], lines: [], links: [] })).finally(() => setBusy(false));
  }, [entity, name]);
  useEffect(() => {
    load();
    const t = setInterval(() => { if (document.visibilityState === "visible") load(); }, EVERY);
    return () => clearInterval(t);
  }, [load]);

  const tz = g?.tz || "UTC";
  const when = useCallback((iso: string, withDay = true) => new Date(iso).toLocaleString("en-NZ", {
    timeZone: tz, hour: "numeric", minute: "2-digit", ...(withDay ? { weekday: "short" } : {}) }), [tz]);

  const stacked = useCallback((): EChartsOption => {
    if (!g) return {};
    const tip = { trigger: "axis" as const, confine: true, backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"),
      textStyle: { color: cssVar("--ink") }, valueFormatter: (v: unknown) => (typeof v === "number" ? mw(v) : String(v)) };
    if (g.series.length) {
      return {
        backgroundColor: "transparent", tooltip: tip,
        legend: { top: 0, type: "scroll", textStyle: { color: cssVar("--ink-2") } },
        grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
        xAxis: { type: "time", axisLabel: { color: cssVar("--muted"), formatter: (v: number) => when(new Date(v).toISOString()) } },
        yAxis: { type: "value", axisLabel: { color: cssVar("--muted"), formatter: short }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
        series: g.series.map((s, i) => {
          const c = fuelColor(s.fuel) ?? seriesColor(i);
          return { type: "line", name: s.fuel, stack: "gen",
            areaStyle: { opacity: 0.85 }, showSymbol: false, lineStyle: { width: 0.5, color: c }, itemStyle: { color: c }, data: s.points };
        }),
      };
    }
    // New Zealand: the latest half hour by fuel, as bars against capacity
    const mix = [...g.mix].sort((a, b) => b.mw - a.mw);
    return {
      backgroundColor: "transparent", tooltip: { ...tip, trigger: "item" as const },
      grid: { left: 8, right: 60, top: 8, bottom: 8, containLabel: true },
      xAxis: { type: "value", axisLabel: { color: cssVar("--muted"), formatter: short }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
      yAxis: { type: "category", inverse: true, data: mix.map((m) => m.fuel), axisLabel: { color: cssVar("--ink-2") } },
      series: [
        { type: "bar", name: "Capacity", barGap: "-100%", data: mix.map((m) => m.capacity ?? 0), itemStyle: { color: cssVar("--grid") }, silent: true },
        { type: "bar", name: "Generating now", data: mix.map((m, i) => ({ value: m.mw, itemStyle: { color: fuelColor(m.fuel) ?? seriesColor(i) } })),
          label: { show: true, position: "right", color: cssVar("--muted"), formatter: (p: { value?: unknown }) => mw(Number(p.value)) } },
      ],
    };
  }, [g, when]);

  const lines = useCallback((): EChartsOption => {
    if (!g?.lines.length) return {};
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", confine: true, backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"), textStyle: { color: cssVar("--ink") },
        valueFormatter: (v: unknown) => (typeof v === "number" ? mw(v) : String(v)) },
      legend: { top: 0, type: "scroll", textStyle: { color: cssVar("--ink-2") } },
      grid: { left: 8, right: 16, top: 32, bottom: 8, containLabel: true },
      xAxis: { type: "time", axisLabel: { color: cssVar("--muted"), formatter: (v: number) => when(new Date(v).toISOString()) } },
      yAxis: { type: "value", scale: true, axisLabel: { color: cssVar("--muted"), formatter: short }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
      series: g.lines.map((l, i) => ({ type: "line", name: l.name, showSymbol: false, data: l.points, lineStyle: { width: 1.6, color: seriesColor(i) },
        itemStyle: { color: seriesColor(i) } })),
    };
  }, [g, when]);

  if (!g) return null;
  if (g.error?.includes("switched off")) return null;
  const text = () => [`Grid now: ${g.name}${g.at ? `, ${when(g.at)}` : ""}`, ...g.mix.map((m) => `${m.fuel}: ${Math.round(m.mw)} MW`),
    g.demand_mw != null ? `Demand ${Math.round(g.demand_mw)} MW` : "", g.renewable_share != null ? `Renewable ${g.renewable_share}%` : "",
    ...g.links.map((l) => `${l.name}: ${Math.round(l.mw)} MW`)].filter(Boolean).join("\n");
  return (
    <div className="card" id="grid-now">
      <div className="card-head">
        <h3>Grid now: {g.name}</h3>
        <span>
          <CardAsk onAsk={() => openAsk({ title: `Grid now: ${g.name}`, entity, parts: [{ key: "data", kind: "data", label: "Grid now", text: text() }] })} />{" "}
          <button className="link small" disabled={busy} onClick={load}>{busy ? "Reading…" : "Read again"}</button>
        </span>
      </div>
      {g.error ? <p className="small muted">{g.error}</p> : (
        <div className="grid-now-cols">
          <div style={{ minWidth: 0 }}>
            <EChart option={stacked} height={g.series.length ? 280 : Math.max(180, g.mix.length * 30 + 20)}
              label={`Generation by fuel, ${g.name}`} />
            {g.lines.length > 0 && <EChart option={lines} height={200} label={`Demand and links, ${g.name}`} />}
          </div>
          <div style={{ minWidth: 0 }}>
            <h4 className="small" style={{ margin: "0 0 4px" }}>Right now{g.at ? `, ${when(g.at)}` : ""}</h4>
            <table className="summary-table small">
              <tbody>
                {g.demand_mw != null && <tr><td>Demand</td><td className="num">{mw(g.demand_mw)}</td></tr>}
                {g.renewable_share != null && <tr><td>Renewable share</td><td className="num">{g.renewable_share.toFixed(0)}%</td></tr>}
                {g.carbon_g_kwh != null && <tr><td>Carbon intensity</td><td className="num">{g.carbon_g_kwh} g CO₂/kWh</td></tr>}
                {g.mix.slice(0, 6).map((m) => <tr key={m.fuel}><td>{m.fuel}</td><td className="num">{mw(m.mw)}</td></tr>)}
                {g.links.map((l) => <tr key={l.name}><td>{l.name}</td><td className="num">{mw(l.mw)}</td></tr>)}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <p className="caption">{g.note ? `${g.note} ` : ""}Times are {tz.split("/").pop()?.replace("_", " ")} time. Read live from {g.source} while
        this card is open, at most every five minutes; nothing is saved.</p>
    </div>
  );
}
