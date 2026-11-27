"use client";

// The chart in a clicked port's or airport's map card: a port's ship calls (or cargo in and out)
// each month from IMF PortWatch; an airport's passengers (or freight) each year from the yearly
// airport figures kept. A World Port Index dot borrows the PortWatch port within 8 km, if any.
import type * as echarts from "echarts";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import EChart from "@/components/EChart";
import { api, type AirportYears, type PortMonths } from "@/lib/api";
import { cssVar } from "@/lib/colors";
import { compact } from "@/lib/format";

export const HISTORY_LAYERS = new Set(["ports", "port_pressure", "ports_all", "airports"]);

type Props = { layer: string; p: Record<string, unknown>; at: { lng: number; lat: number } };
type Got = { kind: "port"; id: string; name?: string | null; km?: number; d: PortMonths }
  | { kind: "airport"; d: AirportYears } | { kind: "none"; why: string };

const str = (v: unknown) => (typeof v === "string" && v.trim() ? v.trim() : null);

export default function PlaceHistory({ layer, p, at }: Props) {
  const [got, setGot] = useState<Got | null>(null);
  const [show, setShow] = useState<"a" | "b">("a");
  const key = `${layer}:${String(p.id ?? p.icao ?? p.name ?? "")}`;
  useEffect(() => {
    let live = true;
    setGot(null);
    setShow("a");
    const port = (id: string, extra: { name?: string | null; km?: number } = {}) =>
      api.portMonths(id).then((d) => { if (live) setGot({ kind: "port", id, ...extra, d }); });
    const fail = (why: string) => () => { if (live) setGot({ kind: "none", why }); };
    if (layer === "airports") {
      const codes = [str(p.icao), str(p.iata)].filter((c): c is string => !!c);
      if (!codes.length) setGot({ kind: "none", why: "This airport has no code to look its figures up by." });
      else api.airportYears(codes).then((d) => { if (live) setGot({ kind: "airport", d }); }).catch(fail("Could not ask the server for its figures."));
    } else if (layer === "ports_all") {
      api.portNear(at.lat, at.lng).then((n) => {
        if (!live) return;
        if (!n) setGot({ kind: "none", why: "No IMF PortWatch port within 8 km, so no monthly ship figures for this one." });
        else return port(n.id, { name: n.name, km: n.km });
      }).catch(fail("Could not ask the server for its figures."));
    } else if (str(p.id)) {
      port(String(p.id)).catch(fail("Could not ask the server for its figures."));
    } else setGot({ kind: "none", why: "No PortWatch id on this port." });
    return () => { live = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const option = useCallback((): echarts.EChartsOption => {
    if (!got || got.kind === "none") return {};
    const ink = cssVar("--ink-2"), grid = cssVar("--border");
    const axis = { axisLabel: { color: ink, fontSize: 10 }, axisLine: { lineStyle: { color: grid } } };
    const yAxis = { type: "value" as const, ...axis, splitLine: { lineStyle: { color: grid, opacity: 0.5 } },
      axisLabel: { color: ink, fontSize: 10, formatter: (v: number) => compact(v) } };
    if (got.kind === "port") {
      const ms = got.d.months;
      const x = ms.map((m) => `${m.year}-${String(m.month).padStart(2, "0")}`);
      const series: echarts.SeriesOption[] = show === "a"
        ? [{ type: "line", name: "Ship calls", data: ms.map((m) => m.calls), showSymbol: false, lineStyle: { width: 1.6 }, color: cssVar("--series-1") }]
        : [{ type: "line", name: "Cargo in (t)", data: ms.map((m) => m.import_t), showSymbol: false, lineStyle: { width: 1.4 }, color: cssVar("--series-1") },
          { type: "line", name: "Cargo out (t)", data: ms.map((m) => m.export_t), showSymbol: false, lineStyle: { width: 1.4 }, color: cssVar("--series-2") }];
      return {
        animation: false, grid: { left: 40, right: 8, top: show === "b" ? 22 : 8, bottom: 42 },
        legend: show === "b" ? { top: 0, textStyle: { color: ink, fontSize: 10 }, itemHeight: 6 } : undefined,
        tooltip: { trigger: "axis", valueFormatter: (v) => (typeof v === "number" ? Math.round(v).toLocaleString() : "–") },
        xAxis: { type: "category", data: x, ...axis }, yAxis, series,
        dataZoom: x.length > 36 ? [{ type: "inside" }, { type: "slider", height: 14, bottom: 4, showDetail: false }] : undefined,
      };
    }
    const ys = got.d.years;
    return {
      animation: false, grid: { left: 40, right: 8, top: 8, bottom: 22 },
      tooltip: { trigger: "axis", valueFormatter: (v) => (typeof v === "number" ? Math.round(v).toLocaleString() : "–") },
      xAxis: { type: "category", data: ys.map((y) => String(y.year)), ...axis }, yAxis,
      series: [{ type: "bar", name: show === "a" ? "Passengers" : "Freight (t)", data: ys.map((y) => (show === "a" ? y.passengers : y.freight_t)),
        color: cssVar("--series-5"), barMaxWidth: 14,
        label: ys.length <= 8 ? { show: true, position: "top", fontSize: 9, color: ink, formatter: (q) => (typeof q.value === "number" ? compact(q.value) : "") } : undefined }],
    };
  }, [got, show]);

  if (!got) return <p className="small muted" style={{ margin: "4px 0" }}>Loading its history…</p>;
  if (got.kind === "none") return <p className="small muted" style={{ margin: "4px 0" }}>{got.why}</p>;
  if (got.kind === "port") {
    const ms = got.d.months;
    if (!ms.length) return <p className="small muted" style={{ margin: "4px 0" }}>No monthly ship figures stored for this port yet (a refresh fetches IMF PortWatch).</p>;
    const first = ms[0], last = ms[ms.length - 1];
    const year = ms.filter((m) => m.year === last.year - 1);
    return (
      <div className="place-history" style={{ marginTop: 6 }}>
        <div className="row small" style={{ gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
          <b>{show === "a" ? "Ship calls a month" : "Cargo a month"}</b>
          <span className="seg" role="group" aria-label="What to show">
            <button className={show === "a" ? "on" : ""} aria-pressed={show === "a"} onClick={() => setShow("a")}>Ships</button>
            <button className={show === "b" ? "on" : ""} aria-pressed={show === "b"} onClick={() => setShow("b")}>Cargo</button>
          </span>
        </div>
        <EChart option={option} height={170} label={`Ship calls each month at this port, ${first.year} to ${last.year}`} />
        <p className="caption" style={{ margin: "2px 0" }}>
          IMF PortWatch (from satellite ship tracking), {first.year}-{String(first.month).padStart(2, "0")} to {last.year}-{String(last.month).padStart(2, "0")}.
          {year.length === 12 ? ` ${last.year - 1}: ${Math.round(year.reduce((s, m) => s + (m.calls ?? 0), 0)).toLocaleString()} calls.` : ""}
          {got.km !== undefined ? ` Figures of ${got.name ?? "the PortWatch port"}, ${got.km} km away.` : ""}{" "}
          <Link href={`/transport?tab=pressure&place=port:${encodeURIComponent(got.id)}`}>Against normal, events and ship types</Link></p>
      </div>
    );
  }
  const ys = got.d.years;
  if (!ys.length) return <p className="small muted" style={{ margin: "4px 0" }}>No yearly passenger figures for this airport: they come from Eurostat (European airports) and files saved by hand for New Zealand, Australia, the UK and the US (Data status).</p>;
  const hasFreight = ys.some((y) => y.freight_t);
  return (
    <div className="place-history" style={{ marginTop: 6 }}>
      <div className="row small" style={{ gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        <b>{show === "a" ? "Passengers a year" : "Freight a year (tonnes)"}</b>
        {hasFreight && (
          <span className="seg" role="group" aria-label="What to show">
            <button className={show === "a" ? "on" : ""} aria-pressed={show === "a"} onClick={() => setShow("a")}>Passengers</button>
            <button className={show === "b" ? "on" : ""} aria-pressed={show === "b"} onClick={() => setShow("b")}>Freight</button>
          </span>)}
      </div>
      <EChart option={option} height={150} label={`Passengers each year at ${got.d.name ?? "this airport"}`} />
      <p className="caption" style={{ margin: "2px 0" }}>{ys[0].year} to {ys[ys.length - 1].year}, from the airport figures kept (Eurostat; NZ, Australia, UK and US files).</p>
    </div>
  );
}
