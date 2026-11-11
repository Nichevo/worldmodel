"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import type { ECharts, EChartsOption } from "echarts";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import { useYearZoom } from "@/components/long/useYearZoom";
import { api, type LongCountry } from "@/lib/api";
import { useSavePicture } from "@/lib/cards";
import { chrome } from "@/lib/charts";
import { cssVar, seriesColor } from "@/lib/colors";
import { compact } from "@/lib/format";
import { axisYear, hueColor, kindColor, yl } from "@/lib/long";

// A country's long view on its page: its figures over the centuries, who ruled the place
// where its capital is, and the best-known events there. Hides itself when there is nothing.
export default function LongViewCard({ entity, name }: { entity: string; name: string }) {
  const [d, setD] = useState<LongCountry | null>(null);
  const [pick, setPick] = useState("population");
  const { onReady: keep, save, ask } = useSavePicture();
  const zoom = useYearZoom();
  const onReady = useCallback((c: ECharts) => { keep(c); zoom.attach(c); }, [keep, zoom.attach]);
  useEffect(() => {
    let live = true;
    api.longCountry(entity).then((x) => live && setD(x)).catch(() => live && setD(null));
    return () => { live = false; };
  }, [entity]);
  const line = d?.series.find((s) => s.series === pick) ?? d?.series[0];
  const option = useCallback((): EChartsOption => {
    const base = chrome();
    return zoom.apply({
      ...base,
      grid: { left: 8, right: 16, top: 30, bottom: 8, containLabel: true },
      xAxis: { ...(base.xAxis as object), axisLabel: { color: cssVar("--muted"), formatter: (v: number) => axisYear(v) } },
      yAxis: { axisLine: { onZero: false }, type: line?.series === "population" ? "log" : "value", name: line?.unit, nameTextStyle: { color: cssVar("--muted"), align: "left" },
        axisLabel: { color: cssVar("--muted"), formatter: (v: number) => compact(v) }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
      tooltip: { ...(base.tooltip as object), formatter: (ps: unknown) => {
        const p = (Array.isArray(ps) ? ps[0] : ps) as { value: [number, number] } | undefined;
        return p ? `<b>${yl(p.value[0])}</b><br/>${line?.name}: <b>${compact(p.value[1])}</b> ${line?.unit ?? ""}` : "";
      } },
      series: [{ type: "line", name: line?.name, showSymbol: (line?.points.length ?? 0) < 30, symbolSize: 4,
        lineStyle: { width: 2, color: seriesColor(0) }, itemStyle: { color: seriesColor(0) }, data: line?.points ?? [] }],
    } as EChartsOption);
  }, [line, zoom.apply]);
  if (!d || (!d.series.length && !d.ruled.length && !d.events.length)) return null;
  const first = d.ruled[0]?.from ?? 0, last = 2024, span = Math.max(1, last - first + 1);
  const title = `${name}: the long view (${line?.name ?? ""})`;
  const note = line ? `${line.unit}. ${line.source}. ${line.note ?? ""}` : "";
  return (
    <div className="card" id="long-view">
      <div className="card-head">
        <h3>The long view</h3>
        <CardAsk onAsk={() => ask(title, note, ["owid_longrun", "cliopatria"], entity)} />
        {line && <button className="link small" onClick={() => save(title, note, ["owid_longrun"], "long-view", entity, pick)}>Save picture</button>}
      </div>
      {d.series.length > 0 && line && (
        <>
          <div className="seg small" role="group" aria-label="Figure">
            {d.series.map((s) => <button key={s.series} className={s === line ? "on" : ""} onClick={() => setPick(s.series)}>{s.name}</button>)}
          </div>
          <EChart option={option} height={220} label={`${name}: ${line.name} over the centuries`} onReady={onReady} />
          {zoom.tools}
          <p className="caption">{line.note ? `${line.note} ` : ""}Unit: {line.unit}. Source: {line.source}. Today&apos;s borders throughout.</p>
        </>
      )}
      {d.ruled.length > 0 && d.capital && (
        <>
          <h4>Who ruled {d.capital.name}</h4>
          <svg className="long-strip" viewBox={`0 0 ${span} 10`} preserveAspectRatio="none" role="img" aria-label={`States that held ${d.capital.name}`}>
            {d.ruled.map((r, i) => <rect key={i} x={r.from - first} width={r.to - r.from + 1} y={0} height={10} fill={hueColor(r.hue)}>
              <title>{`${r.name}${r.part !== r.name ? ` (${r.part})` : ""}: ${yl(r.from)} to ${yl(r.to)}`}</title></rect>)}
          </svg>
          <div className="small muted long-strip-axis"><span>{yl(first)}</span><span>today</span></div>
          <p className="small">{d.ruled.slice(-6).map((r) => `${r.name} (${yl(r.from)} to ${r.to >= 2024 ? "now" : yl(r.to)})`).join(" · ")}</p>
        </>
      )}
      {d.events.length > 0 && (
        <>
          <h4>Best-known events</h4>
          <ul className="long-events small">
            {d.events.slice(-10).map((e) => (
              <li key={e.event_id}><span className="muted">{e.when}</span> <i className="dot" style={{ background: kindColor(e.kind) }} />{" "}
                {e.url ? <a href={e.url} target="_blank" rel="noreferrer">{e.title}</a> : e.title}</li>
            ))}
          </ul>
        </>
      )}
      <p className="caption">More on the <Link href="/long">Long history</Link> page. Borders: Cliopatria (by where the capital is).</p>
    </div>
  );
}
