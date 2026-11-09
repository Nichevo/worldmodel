"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import EChart from "@/components/EChart";
import Flag from "@/components/Flag";
import { api, type Crises } from "@/lib/api";
import type { EChartsOption } from "echarts";
import { chrome } from "@/lib/charts";
import { cssVar, seriesColor } from "@/lib/colors";
import { useEntityNames } from "@/lib/flags";

// Two centuries of financial crises (Reinhart and Rogoff): the waves (share of countries in
// crisis each year) and one strip per country with its crisis spells, on the same years.
const KEY = ["NZL", "AUS", "GBR", "USA"];
const COLOR: Record<string, number> = { banking: 0, systemic: 7, default_external: 2, default_domestic: 3, currency: 4,
  inflation: 5, stock_crash: 6, any: 1 };
const kindColor = (k: string) => seriesColor(COLOR[k] ?? 1);
const STARTS = [1800, 1870, 1914, 1945, 1970, 2000];

function CrisesPage() {
  const router = useRouter();
  const params = useSearchParams();
  const nameOf = useEntityNames();
  const [kind, setKind] = useState(params.get("kind") || "");
  const [start, setStart] = useState(+(params.get("start") || 1800));
  const [all, setAll] = useState(false);
  const [d, setD] = useState<Crises | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.crises(kind || undefined, start).then((x) => { if (live) { setD(x); setError(null); } })
      .catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [kind, start]);
  useEffect(() => {
    const q = new URLSearchParams({ ...(kind ? { kind } : {}), ...(start !== 1800 ? { start: String(start) } : {}) });
    router.replace(`/crises${q.toString() ? `?${q}` : ""}`, { scroll: false });
  }, [kind, start]); // eslint-disable-line react-hooks/exhaustive-deps
  const names = useMemo(() => Object.fromEntries((d?.kinds ?? []).map((k) => [k.id, k.name])), [d]);
  const shown = kind ? [kind] : ["any", "banking", "default_external", "currency", "inflation"];
  const option = useCallback((): EChartsOption => {
    const base = chrome();
    return {
      ...base,
      legend: { top: 0, left: 0, textStyle: { color: cssVar("--ink-2") } },
      grid: { left: 8, right: 16, top: 40, bottom: 8, containLabel: true },
      yAxis: { type: "value", max: 100, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => `${v}%` }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
      tooltip: { ...(base.tooltip as object), valueFormatter: (v: unknown) => `${Number(v).toFixed(0)}%` },
      series: shown.map((k) => ({
        type: "line", name: k === "any" ? "Any of these" : names[k] ?? k, showSymbol: false, smooth: false,
        lineStyle: { width: k === "any" ? 2.5 : 1.5, color: kindColor(k) }, itemStyle: { color: kindColor(k) },
        areaStyle: k === "any" ? { opacity: 0.08 } : undefined,
        data: (d?.waves[k] ?? []).map((p) => [p.year, p.share]),
      })),
    } as EChartsOption;
  }, [d, names, kind]); // eslint-disable-line react-hooks/exhaustive-deps
  if (error) return <p className="error">{error}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  if (!d.years) {
    return (
      <div>
        <h1>Financial crises</h1>
        <p>No crisis years loaded yet. Download Reinhart and Rogoff&apos;s <i>Global Crises Data by Country</i> workbook
          (Data status has the link), save it in <code>var\manual\crisis_history</code> and run <code>.\load.bat</code>.</p>
      </div>
    );
  }
  const [y0, y1] = d.years;
  const span = Math.max(1, y1 - y0 + 1);
  const strips = [...d.strips.filter((s) => KEY.includes(s.entity_id)), ...d.strips.filter((s) => !KEY.includes(s.entity_id))];
  const list = all ? strips : strips.slice(0, 40);
  const ticks = Array.from({ length: Math.floor((y1 - y0) / 25) + 1 }, (_, i) => Math.ceil(y0 / 25) * 25 + i * 25).filter((t) => t <= y1);
  return (
    <div className="grid">
      <div className="title-row">
        <h1>Financial crises</h1>
        <span className="muted small">Banking crises, defaults, currency crashes and runaway inflation since {y0}</span>
      </div>
      <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <div className="seg">
          <button className={!kind ? "on" : ""} onClick={() => setKind("")}>All kinds</button>
          {d.kinds.map((k) => <button key={k.id} className={kind === k.id ? "on" : ""} onClick={() => setKind(k.id)}>{k.name}</button>)}
        </div>
        <label>From <select value={start} onChange={(e) => setStart(+e.target.value)}>
          {STARTS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select></label>
      </div>
      <div className="card">
        <h3>The waves: share of countries in crisis each year</h3>
        <EChart option={option} height={300} label="Share of countries in crisis by year" />
        <p className="caption">Out of the {d.countries} countries Reinhart and Rogoff cover (fewer before 1900: the share is of those with
          data that year). Crises bunch: the 1830s, the 1870s and 1890s, the 1930s, the debt crises of the 1980s, and 2008.
          See also the <Link href="/topic/crises">Financial crises topic</Link> and <Link href="/topic/debt">Debt</Link>.</p>
      </div>
      <div className="card">
        <h3>Country by country, {kind ? names[kind] : "every kind"}</h3>
        <div className="legend" style={{ marginBottom: 8 }}>
          {(kind ? [kind] : d.kinds.map((k) => k.id)).map((k) => (
            <span key={k} style={{ marginRight: 12 }}><i className="dot" style={{ background: kindColor(k) }} /> {names[k]}</span>
          ))}
        </div>
        <div className="crisis-strips">
          <div className="crisis-row axis">
            <span />
            <svg viewBox={`0 0 ${span} 10`} preserveAspectRatio="none" aria-hidden>
              {ticks.map((t) => <line key={t} x1={t - y0} x2={t - y0} y1={0} y2={10} className="tick" />)}
            </svg>
            <span />
          </div>
          <div className="crisis-row axis labels">
            <span />
            <div style={{ position: "relative", height: 14 }}>
              {ticks.map((t) => <span key={t} style={{ position: "absolute", left: `${((t - y0) / span) * 100}%`, transform: "translateX(-50%)" }}>{t}</span>)}
            </div>
            <span />
          </div>
          {list.map((s) => (
            <div key={s.entity_id} className={`crisis-row${KEY.includes(s.entity_id) ? " key" : ""}${kind ? "" : " lanes"}`}>
              <Link href={`/entity/${s.entity_id}`}><Flag id={s.entity_id} />{nameOf(s.entity_id)}</Link>
              <svg viewBox={`0 0 ${span} 10`} preserveAspectRatio="none" role="img"
                aria-label={`${nameOf(s.entity_id)}: ${s.spells.length} crisis spells`}>
                <rect x={0} y={0} width={span} height={10} className="track" />
                {ticks.map((t) => <line key={t} x1={t - y0} x2={t - y0} y1={0} y2={10} className="tick" />)}
                {s.spells.map((p, i) => {
                  const lanes = kind ? 1 : d.kinds.length;
                  const lane = kind ? 0 : d.kinds.findIndex((k) => k.id === p.kind);
                  return (
                    <rect key={i} x={p.from - y0} width={p.to - p.from + 1} y={(lane * 10) / lanes} height={10 / lanes}
                      fill={kindColor(p.kind)}><title>{`${names[p.kind]}, ${p.from}${p.to > p.from ? `–${p.to}` : ""}`}</title></rect>
                  );
                })}
              </svg>
              <span className="muted small">{s.years ? `${s.years} yrs` : "none"}</span>
            </div>
          ))}
        </div>
        {strips.length > 40 && (
          <button className="link" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${strips.length} countries`}</button>
        )}
        <p className="caption">New Zealand, Australia, the UK and the US first, then most crisis years. Years in crisis add up each kind,
          so a year with a banking crisis and a default counts twice. Hover a bar for its years. Source: Reinhart and Rogoff,
          Global Crises Data by Country.</p>
      </div>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><CrisesPage /></Suspense>;
}
