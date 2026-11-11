"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ECharts, EChartsOption } from "echarts";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import { useYearZoom } from "@/components/long/useYearZoom";
import Flag from "@/components/Flag";
import { api, type LongCycle, type LongFactors, type LongOverview, type LongThenNow } from "@/lib/api";
import { useSavePicture } from "@/lib/cards";
import { chrome } from "@/lib/charts";
import { cssVar, seriesColor } from "@/lib/colors";
import { axisYear, yl } from "@/lib/long";

// C. Then and now: each power's share of the world, lined up at its own peak.
export function ThenAndNow({ o }: { o: LongOverview }) {
  const [measure, setMeasure] = useState<"output" | "people" | "land">("output");
  const [aligned, setAligned] = useState(true);
  const [peak100, setPeak100] = useState(false);
  const [d, setD] = useState<LongThenNow | null>(null);
  const { onReady: keep, save, ask } = useSavePicture();
  const zoom = useYearZoom();
  const onReady = useCallback((c: ECharts) => { keep(c); zoom.attach(c); }, [keep, zoom.attach]);
  useEffect(() => {
    let live = true;
    api.longThenNow(measure).then((x) => live && setD(x)).catch(() => live && setD(null));
    return () => { live = false; };
  }, [measure]);
  const option = useCallback((): EChartsOption => {
    const base = chrome();
    const lines = (d?.lines ?? []).filter((l) => l.peak);
    return zoom.apply({
      ...base,
      legend: { top: 0, left: 0, type: "scroll", textStyle: { color: cssVar("--ink-2") } },
      grid: { left: 8, right: 16, top: 56, bottom: 8, containLabel: true },
      xAxis: { ...(base.xAxis as object), ...(aligned ? { min: -300, max: 300 } : {}),
        axisLabel: { color: cssVar("--muted"), formatter: (v: number) => (aligned ? (v === 0 ? "peak" : `${v > 0 ? "+" : ""}${v} yrs`) : axisYear(v)) } },
      yAxis: { axisLine: { onZero: false }, type: "value", name: peak100 ? "peak = 100" : "% of world", nameTextStyle: { color: cssVar("--muted"), align: "left" },
        axisLabel: { color: cssVar("--muted") }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
      tooltip: { trigger: "item", backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"), textStyle: { color: cssVar("--ink") },
        formatter: (p: unknown) => {
          const q = p as { seriesName: string; data: [number, number, number] };
          return `<b>${q.seriesName}</b><br/>${yl(q.data[2])}: ${q.data[1]?.toFixed(1)}${peak100 ? " (peak = 100)" : "% of world"}`;
        } },
      series: lines.map((l) => {
        const [py, pv] = l.peak!;
        return {
          type: "line", name: l.name, showSymbol: false, connectNulls: false, triggerLineEvent: true, emphasis: { focus: "series" },
          lineStyle: { width: 2, color: l.colour ?? undefined }, itemStyle: { color: l.colour ?? undefined },
          data: l.points.map(([y, v]) => [aligned ? y - py : y, v === null ? null : peak100 ? (100 * v) / pv : v, y]),
        };
      }),
    } as EChartsOption, aligned ? (v) => (v === 0 ? "peak" : `${v > 0 ? "+" : ""}${v} yrs`) : undefined);
  }, [d, aligned, peak100, zoom.apply]);
  const title = `Then and now: ${d?.name ?? ""}`;
  const note = d?.note ?? "";
  const empty = d && !d.lines.some((l) => l.peak);
  return (
    <div className="card">
      <div className="card-head">
        <h3>C. Empires then and now: rise and fall, lined up at each power&apos;s peak</h3>
        <CardAsk onAsk={() => ask(title, note, ["owid_longrun", "cliopatria"])} />
        <button className="link small" onClick={() => save(title, note, ["owid_longrun", "cliopatria"], "then-and-now", measure)}>Save picture</button>
      </div>
      <div className="long-tools">
        <div className="seg small" role="group" aria-label="Measure">
          {(["output", "people", "land"] as const).map((m) => (
            <button key={m} className={measure === m ? "on" : ""} onClick={() => setMeasure(m)}>
              {m === "output" ? "Share of world output" : m === "people" ? "Share of world people" : "Share of world land"}</button>
          ))}
        </div>
        <label className="small"><input type="checkbox" checked={aligned} onChange={(e) => { zoom.reset(); setAligned(e.target.checked); }} /> Line up at each peak</label>
        <label className="small"><input type="checkbox" checked={peak100} onChange={(e) => setPeak100(e.target.checked)} /> Peak = 100</label>
      </div>
      {empty ? <p className="muted">Nothing loaded for this measure yet (it needs {measure === "land" ? "the borders" : "the long-run figures"}; run .\refresh.bat).</p>
        : <EChart option={option} height={360} label="Each power's share of the world over time" onReady={onReady} />}
      {zoom.tools}
      <p className="caption">{d?.note} Output is GDP (Maddison GDP per person times population) as a share of the world&apos;s;
        before 1820 the figures are rough estimates for a few years only. Lining powers up at their peak shows how fast they rose
        and fell; it does not predict when anyone declines. Hover a line for the year.</p>
    </div>
  );
}

// The eight factors, rebuilt from free data, and their average (the index).
export function Factors({ o }: { o: LongOverview }) {
  const [d, setD] = useState<LongFactors | null>(null);
  const [pick, setPick] = useState("index");
  const [start, setStart] = useState(1500);
  const { onReady: keep, save, ask } = useSavePicture();
  const zoom = useYearZoom();
  const onReady = useCallback((c: ECharts) => { keep(c); zoom.attach(c); }, [keep, zoom.attach]);
  useEffect(() => {
    let live = true;
    api.longFactors(start, 10).then((x) => live && setD(x)).catch(() => live && setD(null));
    return () => { live = false; };
  }, [start]);
  const lines = useMemo(() => (pick === "index" ? d?.index : d?.factors.find((f) => f.id === pick)?.lines) ?? [], [d, pick]);
  const option = useCallback((): EChartsOption => {
    const base = chrome();
    return zoom.apply({
      ...base,
      legend: { top: 0, left: 0, type: "scroll", textStyle: { color: cssVar("--ink-2") } },
      grid: { left: 8, right: 16, top: 56, bottom: 8, containLabel: true },
      yAxis: { axisLine: { onZero: false }, type: "value", max: (v: { max: number }) => Math.min(100, Math.ceil(v.max / 10) * 10), name: "% of the group",
        nameTextStyle: { color: cssVar("--muted"), align: "left" }, axisLabel: { color: cssVar("--muted") }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
      tooltip: { ...(base.tooltip as object), valueFormatter: (v: unknown) => `${Number(v).toFixed(1)}%` },
      series: lines.map((l, i) => ({ type: "line", name: l.name, showSymbol: false, lineStyle: { width: 2, color: seriesColor(i) },
        itemStyle: { color: seriesColor(i) }, data: l.points.map(([y, v]) => [y, 100 * v]) })),
    } as EChartsOption);
  }, [lines, zoom.apply]);
  const f = d?.factors.find((x) => x.id === pick);
  const title = `The eight factors: ${pick === "index" ? "the index" : f?.name}`;
  const note = d?.note ?? "";
  return (
    <div className="card">
      <div className="card-head">
        <h3>The eight factors of a country&apos;s strength</h3>
        <CardAsk onAsk={() => ask(title, `${note} ${f?.how ?? ""}`, ["owid_longrun"])} />
        <button className="link small" onClick={() => save(title, note, ["owid_longrun"], "eight-factors", pick)}>Save picture</button>
      </div>
      <div className="long-tools">
        <label className="small">Show <select value={pick} onChange={(e) => setPick(e.target.value)}>
          <option value="index">The index (average of the factors)</option>
          {(d?.factors ?? o.factors).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
        </select></label>
        <label className="small">From <select value={start} onChange={(e) => setStart(+e.target.value)}>
          {[1500, 1700, 1800, 1900].map((y) => <option key={y} value={y}>{y}</option>)}
        </select></label>
      </div>
      {!lines.length ? <p className="muted">{d && !d.years.length ? "No long-run figures loaded yet (run .\\refresh.bat)." : pick === "competitiveness" ? f?.how : "Working it out…"}</p>
        : <EChart option={option} height={340} label="Each country's share of the group on the chosen factor" onReady={onReady} />}
      {zoom.tools}
      <p className="caption">{d?.note} Each factor is a country&apos;s share of the total among {d?.countries.length ?? 10} countries
        (the Netherlands, Britain, the US, China, Spain, France, Germany, Japan, Russia and India), so the lines add up to 100%.
        {pick === "index" ? " The index averages the factors a country has figures for that year (at least three)."
          : ` How: ${f?.how ?? ""}`} Between known years values are drawn straight. </p>
      <details className="small">
        <summary>How each factor is rebuilt</summary>
        <ul>{o.factors.map((x) => <li key={x.id}><b>{x.name}</b>: {x.how}</li>)}</ul>
      </details>
    </div>
  );
}

// D. The big cycle: where today's countries might sit in the six stages of an internal order.
export function Cycle({ o }: { o: LongOverview }) {
  const [d, setD] = useState<LongCycle | null>(null);
  useEffect(() => { api.longCycle().then(setD).catch(() => setD(null)); }, []);
  if (!d) return <p className="muted">Loading…</p>;
  return (
    <div className="card">
      <div className="card-head"><h3>D. The big cycle: where countries might be now</h3></div>
      <div className="cycle">
        {d.stages.map((s) => (
          <div key={s.n} className="cycle-stage">
            <div className="cycle-n">{s.n}</div>
            <b>{s.name}</b>
            <p className="small muted">{s.about}</p>
            <div className="cycle-who">
              {d.countries.filter((c) => c.stage === s.n).map((c) => (
                <Link key={c.entity} href={`/entity/${c.entity}`} className="chip small"><Flag id={c.entity} />{c.name}</Link>
              ))}
            </div>
          </div>
        ))}
      </div>
      {d.countries.map((c) => (
        <details key={c.entity} className="small" open={c.entity === "NZL"}>
          <summary><b>{c.name}</b>: {c.stage ? `stage ${c.stage}, ${d.stages[c.stage - 1].name.toLowerCase()}` : "not placed"}</summary>
          <ul>{c.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        </details>
      ))}
      <p className="caption">A rough reading, worked out by simple rules from each country&apos;s latest figures: heavy and rising
        government debt, slow growth, high inflation and a wide gap between rich and poor push a country towards the later stages;
        a young order (counted from {Object.keys(d.countries).length ? "1945 for most, 1949 for China" : "its start"}) sits early.
        It copies the idea in Ray Dalio&apos;s <i>Changing World Order</i>, not his own placings, and it is something to argue with,
        not a forecast. The figures behind it are on each country&apos;s page (Debt, the economy charts).</p>
    </div>
  );
}
