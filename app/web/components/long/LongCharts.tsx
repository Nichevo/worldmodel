"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ECharts, EChartsOption } from "echarts";
import CardAsk from "@/components/CardAsk";
import CountryChoice from "@/components/CountryChoice";
import EChart from "@/components/EChart";
import { useYearZoom } from "@/components/long/useYearZoom";
import { api, type LongEvent, type LongLine, type LongOverview, type LongRegionPop } from "@/lib/api";
import { useSavePicture } from "@/lib/cards";
import { chrome } from "@/lib/charts";
import { cssVar, seriesColor } from "@/lib/colors";
import { compact } from "@/lib/format";
import { axisYear, eventLine, FROM_CHOICES, GROUP_LABEL, interp, KIND_GROUP, kindColor, yl } from "@/lib/long";
import { useSettings } from "@/lib/settings";

// Figures over centuries: people since 10,000 BC (with the eight regions and events far
// back as marks), and "reach back" lines for any country and long-run series.
export default function LongCharts({ o }: { o: LongOverview }) {
  const settings = useSettings();
  if (!o.counts.long_series) {
    return (
      <div className="card">
        <h3>No long-run figures yet</h3>
        <p>Population since 10,000 BC, GDP per person since AD 1 and the other long series come from Our World in Data&apos;s
          chart files. Run <code>.\refresh.bat</code> with <i>Settings &gt; Long history &gt; Long-run figures</i> on (it is on unless
          you switched it off).</p>
      </div>
    );
  }
  return (
    <>
      <PeopleCard o={o} marks={settings.history_events_on_charts} />
      <ReachBack o={o} />
    </>
  );
}

function PeopleCard({ o, marks }: { o: LongOverview; marks: boolean }) {
  const [from, setFrom] = useState(-10000);
  const [log, setLog] = useState(true);
  const [regions, setRegions] = useState(false);
  const [showEvents, setShowEvents] = useState(marks);
  const [world, setWorld] = useState<LongLine | null>(null);
  const [regs, setRegs] = useState<LongRegionPop[]>([]);
  const [events, setEvents] = useState<LongEvent[]>([]);
  const { onReady: keep, save, ask } = useSavePicture();
  const zoom = useYearZoom();
  const onReady = useCallback((c: ECharts) => { keep(c); zoom.attach(c); }, [keep, zoom.attach]);
  useEffect(() => {
    api.longSeries(["world"], ["population"]).then((l) => setWorld(l[0] ?? null)).catch(() => setWorld(null));
    api.longRegions().then(setRegs).catch(() => setRegs([]));
  }, []);
  useEffect(() => {
    if (!showEvents || !o.counts.history_events) { setEvents([]); return; }
    // The best-known only: they are marks on a line, not a list.
    api.longEvents({ start: from, kind: "epidemic,famine,war,earthquake,volcano,tsunami", limit: 60 }).then(setEvents).catch(() => setEvents([]));
  }, [showEvents, from, o.counts.history_events]);
  const option = useCallback((): EChartsOption => {
    const base = chrome();
    const pts = (world?.points ?? []).filter((p) => p[0] >= from);
    const series: EChartsOption["series"] = [{
      type: "line", name: "World", showSymbol: false, lineStyle: { width: 2.5, color: cssVar("--ink") }, itemStyle: { color: cssVar("--ink") },
      data: pts, z: 3,
    }];
    if (regions) {
      regs.forEach((r, i) => (series as object[]).push({
        type: "line", name: r.name, showSymbol: false, lineStyle: { width: 1.5, color: seriesColor(i) }, itemStyle: { color: seriesColor(i) },
        data: r.points.filter((p) => p[0] >= from),
      }));
    }
    if (events.length && pts.length) {
      const w = pts as [number, number | null][];
      (series as object[]).push({
        type: "scatter", name: "Events", z: 4,
        data: events.map((e) => ({ value: [e.year, interp(w, e.year) ?? w[0][1]], ev: e, itemStyle: { color: kindColor(e.kind) },
          symbolSize: 6 + Math.min(10, Math.log10(1 + (e.deaths ?? 0)) * 1.4) })).filter((d) => d.value[1] !== null),
        symbol: "diamond",
        tooltip: { trigger: "item", formatter: (p: unknown) => eventLine((p as { data: { ev: LongEvent } }).data.ev) },
      });
    }
    return zoom.apply({
      ...base,
      legend: regions ? { top: 0, left: 0, type: "scroll", textStyle: { color: cssVar("--ink-2") } } : undefined,
      grid: { left: 8, right: 16, top: regions ? 56 : 30, bottom: 8, containLabel: true },
      xAxis: { ...(base.xAxis as object), min: from, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => axisYear(v) } },
      yAxis: { axisLine: { onZero: false }, type: log ? "log" : "value", axisLabel: { color: cssVar("--muted"), formatter: (v: number) => compact(v) },
        splitLine: { lineStyle: { color: cssVar("--grid") } } },
      tooltip: { ...(base.tooltip as object), formatter: (ps: unknown) => {
        const list = (Array.isArray(ps) ? ps : [ps]) as { seriesName: string; value: [number, number]; color: string; seriesType: string }[];
        const lines = list.filter((p) => p.seriesType === "line");
        if (!lines.length) return "";
        return [`<b>${yl(lines[0].value[0])}</b>`, ...lines.map((p) => `<span style="color:${p.color}">●</span> ${p.seriesName}: <b>${compact(p.value[1])}</b>`)].join("<br/>");
      } },
      series,
    } as EChartsOption);
  }, [world, regs, regions, from, log, events, zoom.apply]);
  if (!world) return null;
  const title = "People since 10,000 BC";
  const note = `${o.series.population.source}. ${o.series.population.note ?? ""}`;
  return (
    <div className="card">
      <div className="card-head">
        <h3>{title}</h3>
        <CardAsk onAsk={() => ask(title, note, ["owid_longrun"])} />
        <button className="link small" onClick={() => save(title, note, ["owid_longrun"], "people-since-10000-bc")}>Save picture</button>
      </div>
      <div className="long-tools">
        <label className="small">From <select value={from} onChange={(e) => { zoom.reset(); setFrom(+e.target.value); }}>
          {FROM_CHOICES.map((c) => <option key={c.year} value={c.year}>{c.label}</option>)}
        </select></label>
        <label className="small"><input type="checkbox" checked={log} onChange={(e) => setLog(e.target.checked)} /> Log scale</label>
        <label className="small"><input type="checkbox" checked={regions} onChange={(e) => setRegions(e.target.checked)} /> The eight regions and the Pacific</label>
        {o.counts.history_events > 0 && (
          <label className="small"><input type="checkbox" checked={showEvents} onChange={(e) => setShowEvents(e.target.checked)} /> Events</label>
        )}
      </div>
      <EChart option={option} height={360} label="World population since 10,000 BC" onReady={onReady} />
      {zoom.tools}
      {events.length > 0 && (
        <div className="legend small" style={{ marginTop: 4 }}>
          {(Object.keys(GROUP_LABEL) as (keyof typeof GROUP_LABEL)[]).map((g) => (
            <span key={g} style={{ marginRight: 12 }}><i className="dot" style={{ background: kindColor(Object.keys(KIND_GROUP).find((k) => KIND_GROUP[k] === g)!) }} /> {GROUP_LABEL[g]}</span>
          ))}
        </div>
      )}
      <p className="caption">{o.series.population.note} Log scale: each step up is ten times more people, so the slow
        thousands of years before farming and the last two centuries both show. Regions add up today&apos;s countries in them
        (the Pacific is Australia, New Zealand and the islands). Marks are the best-known events in the years shown (Settings &gt;
        Long history sets how well known). Source: {o.series.population.source}.</p>
    </div>
  );
}

const PICKS = ["NZL", "AUS", "GBR", "USA", "CHN", "IND"];

function ReachBack({ o }: { o: LongOverview }) {
  const [ents, setEnts] = useState<string[]>(["GBR", "CHN", "IND", "USA"]);
  const [series, setSeries] = useState("gdp_per_capita");
  const [from, setFrom] = useState(1);
  const [log, setLog] = useState(true);
  const [lines, setLines] = useState<LongLine[] | null>(null);
  const { onReady: keep, save, ask } = useSavePicture();
  const zoom = useYearZoom();
  const onReady = useCallback((c: ECharts) => { keep(c); zoom.attach(c); }, [keep, zoom.attach]);
  useEffect(() => {
    let live = true;
    api.longSeries(ents, [series], from).then((l) => live && setLines(l)).catch(() => live && setLines([]));
    return () => { live = false; };
  }, [ents, series, from]);
  const meta = o.series[series];
  const option = useCallback((): EChartsOption => {
    const base = chrome();
    return zoom.apply({
      ...base,
      legend: { top: 0, left: 0, type: "scroll", textStyle: { color: cssVar("--ink-2") } },
      grid: { left: 8, right: 16, top: 56, bottom: 8, containLabel: true },
      xAxis: { ...(base.xAxis as object), axisLabel: { color: cssVar("--muted"), formatter: (v: number) => axisYear(v) } },
      yAxis: { axisLine: { onZero: false }, type: log ? "log" : "value", name: meta?.unit, nameTextStyle: { color: cssVar("--muted"), align: "left" },
        axisLabel: { color: cssVar("--muted"), formatter: (v: number) => compact(v) }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
      tooltip: { ...(base.tooltip as object), formatter: (ps: unknown) => {
        const list = (Array.isArray(ps) ? ps : [ps]) as { seriesName: string; value: [number, number]; color: string }[];
        if (!list.length) return "";
        return [`<b>${yl(list[0].value[0])}</b>`, ...list.map((p) => `<span style="color:${p.color}">●</span> ${p.seriesName}: <b>${compact(p.value[1])}</b> ${meta?.unit ?? ""}`)].join("<br/>");
      } },
      series: (lines ?? []).map((l, i) => ({ type: "line", name: l.entity_name, showSymbol: l.points.length < 30, symbolSize: 4, connectNulls: true,
        lineStyle: { width: 2, color: seriesColor(i) }, itemStyle: { color: seriesColor(i) }, data: l.points })),
    } as EChartsOption);
  }, [lines, log, meta, zoom.apply]);
  const title = `${meta?.name ?? series} over the centuries`;
  const note = `${meta?.unit ?? ""}. ${meta?.source ?? ""}. ${meta?.note ?? ""}`;
  return (
    <div className="card">
      <div className="card-head">
        <h3>Reach back: {meta?.name ?? series}</h3>
        <CardAsk onAsk={() => ask(title, note, ["owid_longrun"])} />
        <button className="link small" onClick={() => save(title, note, ["owid_longrun"], "reach-back", series)}>Save picture</button>
      </div>
      <div className="long-tools">
        <label className="small">Figure <select value={series} onChange={(e) => setSeries(e.target.value)}>
          {Object.entries(o.series).map(([id, s]) => <option key={id} value={id}>{s.name} (from {s.from})</option>)}
        </select></label>
        <label className="small">From <select value={from} onChange={(e) => { zoom.reset(); setFrom(+e.target.value); }}>
          {FROM_CHOICES.map((c) => <option key={c.year} value={c.year}>{c.label}</option>)}
        </select></label>
        <label className="small"><input type="checkbox" checked={log} onChange={(e) => setLog(e.target.checked)} /> Log scale</label>
      </div>
      <div className="long-tools">
        {ents.map((e) => (
          <button key={e} className="chip small" title="Remove" onClick={() => setEnts(ents.filter((x) => x !== e))}>
            {(lines ?? []).find((l) => l.entity === e)?.entity_name ?? e} ×</button>
        ))}
        <CountryChoice value="" label="Add" onChange={(id) => id && !ents.includes(id) && setEnts([...ents, id])} />
        {PICKS.filter((p) => !ents.includes(p)).slice(0, 3).map((p) => (
          <button key={p} className="link small" onClick={() => setEnts([...ents, p])}>+ {p}</button>
        ))}
      </div>
      {lines && !lines.length ? <p className="muted">None of these countries has this figure.</p>
        : <EChart option={option} height={320} label={`${meta?.name} for chosen countries`} onReady={onReady} />}
      {zoom.tools}
      <p className="caption">{meta?.note ? `${meta.note} ` : ""}Unit: {meta?.unit}. Source: {meta?.source}. Points are the years the
        source gives; lines join them straight, so a gap of centuries shows as a long straight stretch. Today&apos;s countries&apos;
        borders throughout. For the same figures since 1960 from other sources, see the country pages and <Link href="/compare">Compare</Link>.</p>
    </div>
  );
}

export function useLongOverview() {
  const [o, setO] = useState<LongOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.longOverview().then(setO).catch((e) => setError(String(e.message || e))); }, []);
  const byId = useMemo(() => new Map((o?.powers ?? []).map((p) => [p.id, p])), [o]);
  return { o, error, byId };
}
