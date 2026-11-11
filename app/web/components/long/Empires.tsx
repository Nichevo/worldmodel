"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ECharts, EChartsOption } from "echarts";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import { useYearZoom } from "@/components/long/useYearZoom";
import { api, type LongOverview, type LongPower, type LongRuled, type LongSize } from "@/lib/api";
import { useSavePicture } from "@/lib/cards";
import { chrome } from "@/lib/charts";
import { cssVar } from "@/lib/colors";
import { axisYear, hueColor, SQ_KM, yl } from "@/lib/long";

const WORLD_LAND = 134e6;
type Group = "then" | "now" | "china" | "mine";
const GROUPS: { id: Group; label: string }[] = [
  { id: "then", label: "Powers then" }, { id: "now", label: "Powers now" }, { id: "china", label: "China's dynasties" }, { id: "mine", label: "Your picks" },
];

// A. How big each power got, and when: land ruled year by year from Cliopatria's borders.
export function AgeOfEmpires({ o }: { o: LongOverview }) {
  const router = useRouter();
  const [group, setGroup] = useState<Group>("then");
  const [mine, setMine] = useState<string[]>(["rome", "britain", "usa", "china"]);
  const [share, setShare] = useState(false);
  const [sizes, setSizes] = useState<LongSize[] | null>(null);
  const { onReady: keep, save, ask } = useSavePicture();
  const zoom = useYearZoom();
  const ids = useMemo(() => {
    const ps = o.powers.filter((p) => p.has_borders);
    if (group === "china") return o.dynasties.filter((d) => ps.some((p) => p.id === d));
    if (group === "mine") return mine;
    return ps.filter((p) => p.era === group).map((p) => p.id);
  }, [o, group, mine]);
  useEffect(() => {
    let live = true;
    if (!ids.length) { setSizes([]); return; }
    api.longSizes(ids).then((s) => live && setSizes(s)).catch(() => live && setSizes([]));
    return () => { live = false; };
  }, [ids]);
  const byId = useMemo(() => new Map(o.powers.map((p) => [p.id, p])), [o]);
  const option = useCallback((): EChartsOption => {
    const base = chrome();
    const v = (x: number | null) => (x === null ? null : share ? (100 * x) / WORLD_LAND : x / 1e6);
    return zoom.apply({
      ...base,
      legend: { top: 0, left: 0, type: "scroll", textStyle: { color: cssVar("--ink-2") } },
      grid: { left: 8, right: 16, top: 56, bottom: 8, containLabel: true },
      xAxis: { ...(base.xAxis as object), axisLabel: { color: cssVar("--muted"), formatter: (y: number) => axisYear(y) } },
      yAxis: { axisLine: { onZero: false }, type: "value", name: share ? "% of world land" : "million km²", nameTextStyle: { color: cssVar("--muted"), align: "left" },
        axisLabel: { color: cssVar("--muted") }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
      tooltip: { trigger: "item", backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"), textStyle: { color: cssVar("--ink") },
        formatter: (p: unknown) => {
          const q = p as { seriesId: string; seriesName: string; value: [number, number] };
          const pw = byId.get(q.seriesId);
          const peak = pw?.peak_km2 ? `<br/>Peak ${SQ_KM(pw.peak_km2)} in ${yl(pw.peak_year)}` : "";
          return `<b>${q.seriesName}</b><br/>${yl(q.value[0])}: ${q.value[1]?.toFixed(share ? 1 : 2)} ${share ? "% of world land" : "million km²"}${peak}`
            + `<br/><span style="opacity:.7">Click for its map over time</span>`;
        } },
      series: (sizes ?? []).map((s) => ({
        id: s.id, type: "line", name: s.name, step: "end", showSymbol: false, connectNulls: false, triggerLineEvent: true,
        lineStyle: { width: 2, color: s.colour ?? undefined }, itemStyle: { color: s.colour ?? undefined },
        areaStyle: { opacity: 0.08, color: s.colour ?? undefined },
        emphasis: { focus: "series" },
        data: s.points.map(([y, a]) => [y, v(a)]),
      })),
    } as EChartsOption);
  }, [sizes, share, byId, zoom.apply]);
  const onReady = useCallback((c: ECharts) => {
    keep(c);
    zoom.attach(c);
    c.on("click", (p) => { if (p.seriesId) router.push(`/long/empire/${p.seriesId}`); });
  }, [keep, router, zoom.attach]);
  if (!o.counts.polities) return <NoBorders />;
  const title = `Age of empires: land ruled (${GROUPS.find((g) => g.id === group)?.label})`;
  const note = "Land ruled year by year from Seshat's Cliopatria borders (3400 BC to 2024). Thin before 500 BC.";
  return (
    <div className="card">
      <div className="card-head">
        <h3>A. Age of empires: how big each one got, and when</h3>
        <CardAsk onAsk={() => ask(title, note, ["cliopatria"])} />
        <button className="link small" onClick={() => save(title, note, ["cliopatria"], "age-of-empires", group)}>Save picture</button>
      </div>
      <div className="long-tools">
        <div className="seg small" role="group" aria-label="Which powers">
          {GROUPS.map((g) => <button key={g.id} className={group === g.id ? "on" : ""} aria-pressed={group === g.id} onClick={() => setGroup(g.id)}>{g.label}</button>)}
        </div>
        <div className="seg small" role="group" aria-label="Measure">
          <button className={!share ? "on" : ""} onClick={() => setShare(false)}>Million km²</button>
          <button className={share ? "on" : ""} onClick={() => setShare(true)}>Share of world land</button>
        </div>
      </div>
      {group === "mine" && <PowerPicker o={o} value={mine} onChange={setMine} />}
      <EChart option={option} height={380} label="Land ruled by each power over time" onReady={onReady} />
      {zoom.tools}
      <PowerList powers={ids.map((i) => byId.get(i)).filter((p): p is LongPower => !!p)} />
      <p className="caption">Each line follows the power&apos;s land year by year from Seshat&apos;s Cliopatria borders, so growth in
        jumps and sudden collapse show as they happened. Where an empire has a composite outline (its colonies and protectorates
        joined, the names in brackets in the source) that one is used. Before 500 BC the borders are thin and rough. Click a line
        or a name for the power&apos;s card: its borders on a map with a year slider, and its size alongside.
        {group === "china" && " China's dynasties follow one another; rival states of the split periods are left out here (the East Asia strip in B shows them)."}</p>
    </div>
  );
}

function PowerPicker({ o, value, onChange }: { o: LongOverview; value: string[]; onChange: (v: string[]) => void }) {
  const ps = o.powers.filter((p) => p.has_borders);
  return (
    <div className="long-tools">
      {ps.map((p) => (
        <label key={p.id} className="small"><input type="checkbox" checked={value.includes(p.id)}
          onChange={(e) => onChange(e.target.checked ? [...value, p.id] : value.filter((x) => x !== p.id))} /> {p.name}</label>
      ))}
    </div>
  );
}

function PowerList({ powers }: { powers: LongPower[] }) {
  return (
    <div className="long-powers">
      {powers.map((p) => (
        <Link key={p.id} href={`/long/empire/${p.id}`} className="long-power">
          <i className="dot" style={{ background: p.colour ?? "var(--muted)" }} /> <b>{p.name}</b>
          {p.from !== undefined && <span className="muted small"> {yl(p.from)} to {p.to && p.to >= 2024 ? "now" : yl(p.to)}</span>}
          {p.peak_km2 ? <span className="muted small"> · peak {SQ_KM(p.peak_km2)}, {yl(p.peak_year)}</span> : null}
        </Link>
      ))}
    </div>
  );
}

export function NoBorders() {
  return (
    <div className="card">
      <h3>No borders loaded yet</h3>
      <p>The empires&apos; borders come from Seshat&apos;s Cliopatria (a 46 MB download from GitHub, checked twice a year). Run
        <code> .\refresh.bat</code> with <i>Settings &gt; Long history &gt; Borders of states and empires</i> on.</p>
    </div>
  );
}

// B. Who ruled where: one strip per region, coloured by the state holding most of its land.
export function WhoRuled({ o }: { o: LongOverview }) {
  const [step, setStep] = useState(10);
  const [from, setFrom] = useState(-1000);
  const [d, setD] = useState<LongRuled | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.longRuled(step).then((x) => live && setD(x)).catch(() => live && setD(null));
    return () => { live = false; };
  }, [step]);
  if (!o.counts.polities) return <NoBorders />;
  if (!d) return <p className="muted">Working out who ruled where…</p>;
  const to = 2024, span = to - from + 1;
  const ticks = [-3000, -2000, -1000, -500, 1, 500, 1000, 1500, 1800, 2000].filter((t) => t >= from && t <= to);
  return (
    <div className="card">
      <div className="card-head"><h3>B. Who ruled where: each region down the centuries</h3></div>
      <div className="long-tools">
        <label className="small">From <select value={from} onChange={(e) => setFrom(+e.target.value)}>
          {[-3000, -1000, -500, 1, 1000, 1500].map((y) => <option key={y} value={y}>{yl(y)}</option>)}
        </select></label>
        <label className="small">Detail <select value={step} onChange={(e) => setStep(+e.target.value)}>
          <option value={5}>every 5 years</option><option value={10}>every 10 years</option><option value={25}>every 25 years</option><option value={50}>every 50 years</option>
        </select></label>
        {hover && <span className="small"><b>{hover}</b></span>}
      </div>
      <div className="ruled">
        <div className="ruled-row axis">
          <span />
          <div style={{ position: "relative", height: 14 }}>
            {ticks.map((t) => <span key={t} className="small muted" style={{ position: "absolute", left: `${((t - from) / span) * 100}%`, transform: "translateX(-50%)" }}>{axisYear(t)}</span>)}
          </div>
        </div>
        {d.regions.map((r) => (
          <div key={r.id} className={`ruled-row${r.id === "pacific" ? " pacific" : ""}`}>
            <span className="small"><b>{r.name}</b></span>
            <svg viewBox={`0 0 ${span} 10`} preserveAspectRatio="none" role="img" aria-label={`${r.name}: who held most land`}>
              <rect x={0} y={0} width={span} height={10} className="track" />
              {r.segments.filter((s) => s.to >= from).map((s, i) => (
                <rect key={i} x={Math.max(0, s.from - from)} width={s.to - Math.max(s.from, from) + 1} y={s.china ? 0 : 1} height={s.china ? 10 : 8}
                  fill={hueColor(s.hue)} stroke={s.china ? "var(--ink)" : "none"} strokeWidth={s.china ? 0.4 : 0}
                  vectorEffect="non-scaling-stroke"
                  onMouseEnter={() => setHover(`${r.name}: ${s.name}, ${yl(s.from)} to ${yl(s.to)} (${SQ_KM(s.area_km2)} in the region)`)}
                  onMouseLeave={() => setHover(null)}>
                  <title>{`${s.name}: ${yl(s.from)} to ${yl(s.to)}`}</title>
                </rect>
              ))}
              {ticks.map((t) => <line key={t} x1={t - from} x2={t - from} y1={0} y2={10} className="tick" />)}
            </svg>
          </div>
        ))}
      </div>
      <p className="caption">Each strip is coloured by the state that held the most land in the region at the time (by where its
        largest piece sits), from Cliopatria&apos;s borders. Parts of an empire count as the empire (British India as the British
        Empire). Outlined bands in East Asia are China&apos;s dynasties. Hover a band for the state and years. Gaps are years with no
        state recorded there, which before about 500 BC is most of the world. {o.pacific.note}</p>
    </div>
  );
}
