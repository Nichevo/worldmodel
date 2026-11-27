"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import RegionMap from "@/components/RegionMap";
import { api, type Regions } from "@/lib/api";
import { useSavePicture } from "@/lib/cards";
import { cssVar, seriesColor } from "@/lib/colors";
import { formatValue } from "@/lib/format";
import { short } from "@/lib/sectors";

// The regions inside a country or state (New Zealand's 16 regions, the US states, a state's
// counties): one figure at a time on a map of their outlines, as bars for a year or lines over
// the years, and a table of every figure's latest year. Counts of people can be shown as a share
// of each region's population. The US can switch between its states and all its counties.
export const plainName = (n: string) => n.replace(/ \((NZ regions|US states and counties|US states|Australian states)\)$/, "");
const POPULATION = ["nzreg_population", "usreg_population"];
const LEVEL_NAME: Record<string, [string, string]> = { state: ["State", "States"], county: ["County", "Counties"], region: ["Region", "Regions"] };
const MANY = 30; // bars beyond this show the highest and lowest only
const LINES = 10; // lines drawn when there are more regions than this: the biggest

export default function RegionsCard({ entity, name, levels, emptyNote }: { entity: string; name: string; levels?: string[]; emptyNote?: string }) {
  const router = useRouter();
  const [level, setLevel] = useState<string | undefined>(undefined);
  const [data, setData] = useState<Regions | null>(null);
  const [shapes, setShapes] = useState<GeoJSON.FeatureCollection | null>(null);
  const [pick, setPick] = useState<string | null>(null);
  const [year, setYear] = useState<number | null>(null);
  const [view, setView] = useState<"map" | "bars" | "lines">("map");
  const [share, setShare] = useState(false);
  const { onReady, save, ask } = useSavePicture();
  const sub = level && levels && level !== levels[0] ? level : undefined; // a lower level (every US county) loads one figure at a time
  const wanted = sub ? pick ?? "usreg_population" : undefined;

  useEffect(() => {
    let live = true;
    api.regions(entity, { level: sub, indicator: wanted }).then((d) => live && setData(d)).catch(() => live && setData(null));
    return () => { live = false; };
  }, [entity, sub, wanted]);
  useEffect(() => {
    let live = true;
    setShapes(null);
    api.regionShapes(entity, sub).then((s) => live && setShapes(s)).catch(() => live && setShapes(null));
    return () => { live = false; };
  }, [entity, sub]);

  const m = data?.measures.find((x) => x.indicator_id === pick) ?? data?.measures.find((x) => POPULATION.includes(x.indicator_id)) ?? data?.measures[0];
  const y = year && m?.years.includes(year) ? year : m?.years[m.years.length - 1];
  const popM = data?.measures.find((x) => x.indicator_id === "nzreg_census_population") ?? null;
  const popE = data?.measures.find((x) => POPULATION.includes(x.indicator_id)) ?? null;
  // Population to divide by: the census count in a census year, else the estimate for that year.
  const pop = useCallback((e: string, yr: number) => popM?.values[e]?.[String(yr)] ?? popE?.values[e]?.[String(yr)] ?? null, [popM, popE]);
  const canShare = !!m && m.unit === "people" && !POPULATION.includes(m.indicator_id) && m.indicator_id !== "nzreg_census_population" && !sub;
  const asShare = share && canShare;
  const val = useCallback((e: string, yr: number) => {
    const v = m?.values[e]?.[String(yr)];
    if (v == null) return null;
    if (!asShare) return v;
    const p = pop(e, yr);
    return p ? (100 * v) / p : null;
  }, [m, asShare, pop]);
  const unit = asShare ? "% of people" : m?.unit ?? "";
  const regions = useMemo(() => data?.regions ?? [], [data]);
  const mapValues = useMemo(() => Object.fromEntries(regions.map((r) => [r.entity_id, y == null ? null : val(r.entity_id, y)])), [regions, y, val]);
  const hasMap = !!shapes?.features.length;
  const shown = view === "map" && !hasMap ? "bars" : view;

  const option = useCallback(() => {
    if (!m || y == null) return {};
    const base = { backgroundColor: "transparent", textStyle: { color: cssVar("--ink-2") },
      tooltip: { trigger: "axis" as const, confine: true, backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"), textStyle: { color: cssVar("--ink") },
        valueFormatter: (v: unknown) => (typeof v === "number" ? `${formatValue(v, unit, asShare ? 1 : m.decimals)} ${unit}` : String(v)) } };
    if (shown === "bars") {
      let rows = regions.map((r) => ({ name: r.name, v: val(r.entity_id, y) })).filter((r) => r.v != null).sort((a, b) => a.v! - b.v!);
      if (rows.length > MANY) rows = [...rows.slice(0, 10), ...rows.slice(-20)];
      return { ...base, grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
        xAxis: { type: "value", axisLabel: { color: cssVar("--muted"), formatter: short }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
        yAxis: { type: "category", data: rows.map((r) => r.name), axisLabel: { color: cssVar("--ink-2") } },
        series: [{ type: "bar", data: rows.map((r) => r.v), itemStyle: { color: seriesColor(0) }, label: { show: true, position: "right", color: cssVar("--muted"),
          formatter: (p: { value: number }) => (asShare ? `${p.value.toFixed(1)}%` : short(p.value)) } }] };
    }
    const last = m.years[m.years.length - 1];
    const drawn = regions.length <= LINES ? regions
      : [...regions].sort((a, b) => (val(b.entity_id, last) ?? -Infinity) - (val(a.entity_id, last) ?? -Infinity)).slice(0, LINES);
    return { ...base, grid: { left: 8, right: 16, top: 48, bottom: 8, containLabel: true }, legend: { top: 0, type: "scroll", textStyle: { color: cssVar("--ink-2") } },
      xAxis: { type: "value", min: "dataMin", max: "dataMax", minInterval: 1, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => String(v) } },
      yAxis: { type: "value", scale: true, axisLabel: { color: cssVar("--muted"), formatter: short }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
      series: drawn.map((r, i) => ({ type: "line", name: r.name, showSymbol: m.years.length < 6, lineStyle: { color: seriesColor(i), width: 1.5 }, itemStyle: { color: seriesColor(i) },
        data: m.years.map((yr) => [yr, val(r.entity_id, yr)]).filter((p) => p[1] != null) })) };
  }, [m, y, shown, regions, val, unit, asShare]);

  if (!data?.measures.length || !m) {
    if (!emptyNote || !data) return null;
    return (
      <div className="card" id="regions">
        <h3>Regions of {name}</h3>
        <p className="small muted">{emptyNote}</p>
        {shapes?.features.length ? <RegionMap shapes={shapes} values={{}} unit="" decimals={0} onPick={(id) => router.push(`/entity/${id}`)} /> : null}
      </div>
    );
  }
  const lv = LEVEL_NAME[data.level ?? "region"] ?? LEVEL_NAME.region;
  const title = `${plainName(m.name)}${asShare ? " (share of people)" : ""}, ${shown === "lines" ? `${m.years[0]}–${m.years[m.years.length - 1]}` : y}`;
  const latest = (mm: Regions["measures"][number], e: string) => { const ys = mm.years.filter((yr) => mm.values[e]?.[String(yr)] != null); return ys.length ? mm.values[e][String(ys[ys.length - 1])] : null; };
  const sources = [...new Set(data.measures.map((x) => x.source_id).filter((s): s is string => !!s))];
  const sourceNames = [...new Set(data.measures.map((x) => x.source).filter(Boolean))];
  const ranked = shown !== "lines" && y != null ? regions.map((r) => ({ r, v: val(r.entity_id, y) })).filter((x) => x.v != null).sort((a, b) => b.v! - a.v!) : [];
  return (
    <div className="card" id="regions">
      <div className="card-head">
        <h3>{lv[1]} of {name}</h3>
        <span>
          <CardAsk onAsk={() => ask(title, "", sources, entity)} />{" "}
          <button className="link small" onClick={() => save(title, "", sources, "regions", m.indicator_id, entity)}>Save picture</button>
        </span>
      </div>
      <div className="chips-row small" style={{ flexWrap: "wrap" }}>
        {levels && levels.length > 1 && (
          <div className="seg" role="group" aria-label="Level">
            {levels.map((l) => (
              <button key={l} className={(level ?? levels[0]) === l ? "on" : ""} aria-pressed={(level ?? levels[0]) === l}
                onClick={() => { setLevel(l); setYear(null); }}>{LEVEL_NAME[l]?.[1] ?? l}</button>))}
          </div>
        )}
        <label>Figure <select value={m.indicator_id} onChange={(e) => { setPick(e.target.value); setShare(false); }}>
          {data.measures.map((x) => <option key={x.indicator_id} value={x.indicator_id}>{plainName(x.name)}</option>)}</select></label>
        <div className="seg" role="group" aria-label="Chart">
          {hasMap && <button className={shown === "map" ? "on" : ""} aria-pressed={shown === "map"} onClick={() => setView("map")}>Map</button>}
          <button className={shown === "bars" ? "on" : ""} aria-pressed={shown === "bars"} onClick={() => setView("bars")}>One year</button>
          <button className={shown === "lines" ? "on" : ""} aria-pressed={shown === "lines"} disabled={m.years.length < 2} onClick={() => setView("lines")}>Over time</button>
        </div>
        {shown !== "lines" && <label>Year <select value={y} onChange={(e) => setYear(+e.target.value)}>{m.years.map((yr) => <option key={yr}>{yr}</option>)}</select></label>}
        {canShare && <label><input type="checkbox" checked={share} onChange={(e) => setShare(e.target.checked)} /> As a share of people</label>}
      </div>
      {shown === "map"
        ? <RegionMap shapes={shapes} values={mapValues} unit={unit} decimals={asShare ? 1 : m.decimals} onPick={(id) => router.push(`/entity/${id}`)} />
        : <EChart option={option} height={shown === "bars" ? Math.max(300, Math.min(MANY, regions.length) * 17 + 40) : 320} label={title} onReady={onReady} />}
      {ranked.length > 0 && (
        <p className="small ink-2" style={{ margin: "6px 0 0" }}>
          Highest: {ranked.slice(0, 3).map((x) => `${x.r.name} ${formatValue(x.v!, unit, asShare ? 1 : m.decimals)}`).join(", ")}.
          {" "}Lowest: {ranked.slice(-3).reverse().map((x) => `${x.r.name} ${formatValue(x.v!, unit, asShare ? 1 : m.decimals)}`).join(", ")}.
          {shown === "bars" && ranked.length > MANY ? ` Bars show the highest 20 and lowest 10 of ${ranked.length}.` : ""}
          {shown === "lines" && regions.length > LINES ? ` Lines show the ${LINES} highest.` : ""}
        </p>
      )}
      {!sub && (
        <details>
          <summary className="small">Every figure, latest year</summary>
          <div style={{ overflowX: "auto", maxHeight: 420 }}>
            <table className="small">
              <thead><tr><th>{lv[0]}</th>{data.measures.map((x) => <th key={x.indicator_id} className="num">{plainName(x.name)}</th>)}</tr></thead>
              <tbody>{regions.map((r) => (
                <tr key={r.entity_id}><td><Link href={`/entity/${r.entity_id}`}>{r.name}</Link></td>
                  {data.measures.map((x) => { const v = latest(x, r.entity_id); return <td key={x.indicator_id} className="num">{v == null ? "" : formatValue(v, x.unit, x.decimals)}</td>; })}</tr>
              ))}</tbody>
            </table>
          </div>
        </details>
      )}
      <p className="caption">{sourceNames.length ? `${sourceNames.slice(0, 5).join("; ")}${sourceNames.length > 5 ? " and more" : ""}. ` : ""}{regions.length} {lv[1].toLowerCase()}.
        {hasMap ? " Click a place on the map for its page." : ""}</p>
    </div>
  );
}
