"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ECharts } from "echarts";
import CardAsk from "@/components/CardAsk";
import CountryChoice from "@/components/CountryChoice";
import EChart from "@/components/EChart";
import Flag from "@/components/Flag";
import { openAsk } from "@/lib/ai";
import { useSavePicture } from "@/lib/cards";
import { type Arcs, type Clock, type DebtCycle, type ShortCycle, type Stages, STAGE_COLOR, arcsOption, cyclesApi, debtOption, shortOption } from "@/lib/cycles";
import { entityVar } from "@/lib/look";

// Long history > Big cycles: rise and decline, stage over time, the long-term debt cycle and
// the short-term cycle clock. Copies of Ray Dalio's ideas rebuilt from free data.
export default function BigCycles() {
  return (
    <>
      <RiseAndDecline />
      <StageOverTime />
      <LongDebtCycle start="GBR" />
      <CycleClock />
      <p className="caption">These pieces copy the ideas in Ray Dalio&apos;s <i>Principles for Dealing with the Changing World Order</i> and
        his work on debt cycles, rebuilt from free data with simple rules shown on each card. They are not his figures or placings,
        and they are something to argue with, not forecasts. Big episodes are on the <Link href="/episodes">Episodes</Link> page.</p>
    </>
  );
}

function RiseAndDecline() {
  const [d, setD] = useState<Arcs | null>(null);
  const [shown, setShown] = useState<string[]>(["NLD", "GBR", "USA", "CHN"]);
  const [pick, setPick] = useState<string | null>("GBR");
  const [aligned, setAligned] = useState(false);
  const { onReady: keep, save, ask } = useSavePicture();
  const byName = useRef<Map<string, string>>(new Map());
  const onReady = useCallback((c: ECharts) => {
    keep(c);
    // Clicking a power's line shades its rise, top and decline.
    c.on("click", (p) => {
      const q = p as { seriesType?: string; seriesName?: string };
      const ent = q.seriesType === "line" && q.seriesName ? byName.current.get(q.seriesName) : undefined;
      if (ent) setPick(ent);
    });
  }, [keep]);
  useEffect(() => { cyclesApi.arcs().then(setD).catch(() => setD({ lines: [], note: null, how: null })); }, []);
  useEffect(() => { byName.current = new Map((d?.lines ?? []).map((l) => [l.name, l.entity])); }, [d]);
  const lines = useMemo(() => (d?.lines ?? []).filter((l) => shown.includes(l.entity)), [d, shown]);
  const option = useCallback(() => arcsOption(lines, pick, aligned), [lines, pick, aligned]);
  const p = d?.lines.find((l) => l.entity === pick);
  const title = "Rise and decline of the great powers";
  const note = `${d?.how ?? ""} ${d?.note ?? ""}`;
  const toggle = (e: string) => setShown(shown.includes(e) ? shown.filter((x) => x !== e) : [...shown, e]);
  return (
    <div className="card">
      <div className="card-head"><h3>Rise and decline: each power&apos;s strength over 500 years</h3>
        <CardAsk onAsk={() => ask(title, note, ["owid_longrun", "crisis_history"])} />
        <button className="link small" onClick={() => save(title, note, ["owid_longrun", "crisis_history"], "rise-and-decline")}>Save picture</button></div>
      {!d ? <p className="muted">Working it out…</p> : !d.lines.length ? <p className="muted">No long-run figures loaded yet (run .\refresh.bat).</p> : <>
        <div className="chips-row small">{d.lines.map((l) => (
          <button key={l.entity} className={`chip${shown.includes(l.entity) ? " on" : ""}`} aria-pressed={shown.includes(l.entity)} onClick={() => toggle(l.entity)}>
            <Flag id={l.entity} />{l.name}</button>))}</div>
        <div className="long-tools">
          <label className="small">Shade the rise, top and decline of <select value={pick ?? ""} onChange={(e) => setPick(e.target.value || null)}>
            <option value="">none</option>{lines.map((l) => <option key={l.entity} value={l.entity}>{l.name}</option>)}</select></label>
          <label className="small"><input type="checkbox" checked={aligned} onChange={(e) => setAligned(e.target.checked)} /> Line up at each peak</label>
        </div>
        <EChart option={option} height={380} label="Each power's eight-factor index over time, with its rise, top and decline" onReady={onReady} />
        {p && p.peak && <p className="small">
          <b>{p.name}</b>: {p.phases.map((x) => `${x.phase} ${x.from}-${x.to}`).join(", ")}; peak {p.peak[0]} at {(100 * p.peak[1]).toFixed(0)}% of the
          ten powers&apos; total. {p.now === "decline" ? "Now past its top." : "Still at or near its top."} {p.crises.length} crisis spells and {p.wars.length} big wars marked.</p>}
      </>}
      <p className="caption">{d?.how} Shading: blue the rise, gold the top, red the decline. Triangles: crises; grey blocks: wars.</p>
    </div>
  );
}

function StageOverTime() {
  const [d, setD] = useState<Stages | null>(null);
  const [hover, setHover] = useState<{ name: string; year: number; stage: number | null; reasons: string[] } | null>(null);
  useEffect(() => { cyclesApi.stages(["USA", "GBR", "CHN", "NZL", "AUS", "JPN", "DEU", "FRA", "IND", "RUS"]).then(setD).catch(() => setD(null)); }, []);
  if (!d) return <div className="card"><h3>Stage over time</h3><p className="muted">Working it out…</p></div>;
  const ask = () => openAsk({ title: "The big cycle's stage, decade by decade", parts: [
    { key: "description", kind: "description", label: "How it is worked out", text: d.how },
    { key: "data", kind: "data", label: "Stage by decade", text: d.countries.map((c) => `${c.name}: ${c.cells.map((x) => `${x.year} ${x.stage ?? "–"}`).join(", ")}`).join("\n") }] });
  return (
    <div className="card">
      <div className="card-head"><h3>Stage over time, decade by decade</h3><CardAsk onAsk={ask} /></div>
      <div className="ep-scroll"><div className="stage-grid" style={{ gridTemplateColumns: `minmax(96px, 160px) repeat(${d.years.length}, minmax(34px, 1fr))` }}>
        <span />{d.years.map((y) => <span key={y} className="small muted stage-year">{y}</span>)}
        {d.countries.map((c) => [
          <span key={c.entity} className="small stage-name"><Flag id={c.entity} />{c.name}</span>,
          ...c.cells.map((x) => (
            <button key={`${c.entity}${x.year}`} className="stage-cell" aria-label={`${c.name} ${x.year}: stage ${x.stage ?? "none"}`}
              style={{ background: x.stage ? `var(${STAGE_COLOR[x.stage - 1]})` : "var(--surface-2)", color: x.stage === 2 || x.stage === 3 ? "var(--ink)" : "#fff" }}
              onMouseEnter={() => setHover({ name: c.name, ...x })} onFocus={() => setHover({ name: c.name, ...x })} onClick={() => setHover({ name: c.name, ...x })}>
              {x.stage ?? ""}</button>)),
        ])}
      </div></div>
      <div className="chips-row small stage-key">{d.stages.map((s, i) => (
        <span key={s.n} title={s.about}><i style={{ background: `var(${STAGE_COLOR[i]})` }} />{s.n} {s.name}</span>))}</div>
      <div className="small stage-why">{hover ? <><b>{hover.name}, {hover.year}</b>: {hover.stage ? `stage ${hover.stage}, ${d.stages[hover.stage - 1].name.toLowerCase()}` : "not placed"}.
        <ul>{hover.reasons.map((r) => <li key={r}>{r}</li>)}</ul></> : <span className="muted">Hover or tap a block for the reasons that decade.</span>}</div>
      <p className="caption">{d.how} Stages are coarse, so expect argument.</p>
    </div>
  );
}

// The long-term debt cycle for one country; also used on the country page (fixed country).
export function LongDebtCycle({ start, fixed, name }: { start: string; fixed?: boolean; name?: string }) {
  const [ent, setEnt] = useState(start);
  const [d, setD] = useState<DebtCycle | null>(null);
  const [rate, setRate] = useState(false);
  const { onReady, save, ask } = useSavePicture();
  useEffect(() => { setEnt(start); }, [start]);
  useEffect(() => {
    let live = true;
    setD(null);
    cyclesApi.debt(ent).then((x) => live && setD(x)).catch(() => live && setD(null));
    return () => { live = false; };
  }, [ent]);
  const option = useCallback(() => (d ? debtOption(d, rate) : {}), [d, rate]);
  if (fixed && d && !d.debt.length) return null;
  const title = `Long-term debt cycle: ${d?.name ?? name ?? ent}${d?.since ? ` since ${d.since}` : ""}`;
  const note = d?.how ?? "";
  return (
    <div className="card" id={fixed ? "debt-cycle" : undefined}>
      <div className="card-head"><h3>{title}</h3>
        <CardAsk onAsk={() => ask(title, note, ["imf_gdd", "imf_weo", "crisis_history"], ent)} />
        <button className="link small" onClick={() => save(title, note, ["imf_gdd", "imf_weo", "crisis_history"], "debt-cycle", ent)}>Save picture</button>
        {fixed && <Link className="small" href="/long?tab=bigcycles">More</Link>}</div>
      <div className="long-tools">
        {!fixed && <CountryChoice value={ent} onChange={setEnt} />}
        <label className="small"><input type="checkbox" checked={rate} onChange={(e) => setRate(e.target.checked)} /> Add real interest rates</label>
      </div>
      {!d ? <p className="muted">Loading…</p> : !d.debt.length ? <p className="muted">No government debt figures for {d.name} yet (run .\refresh.bat; the long series comes from the IMF).</p> : <>
        <EChart option={option} height={300} label={`Government debt as a share of GDP for ${d.name}, with wars and crises`} onReady={onReady} />
        <p className="small">{d.peak && <>Highest: <b>{d.peak.value}%</b> of GDP in {d.peak.year}. </>}{d.latest && <>Latest: <b>{d.latest.value}%</b> ({d.latest.year}).</>}
          {!d.debt_from_long && " Only the recent figures are loaded; the series back to 1800 comes with the next refresh."}</p>
      </>}
      <p className="caption">{d?.how}</p>
    </div>
  );
}

function CycleClock() {
  const [d, setD] = useState<Clock | null>(null);
  const [pick, setPick] = useState("NZL");
  useEffect(() => { cyclesApi.clock(["NZL", "AUS", "GBR", "USA"]).then(setD).catch(() => setD(null)); }, []);
  if (!d) return <div className="card"><h3>Short-term debt cycle</h3><p className="muted">Working it out…</p></div>;
  const ask = () => openAsk({ title: "Short-term debt cycle clock", parts: [
    { key: "description", kind: "description", label: "How the phase is placed", text: d.how },
    { key: "data", kind: "data", label: "Phases", text: d.countries.map((c) => `${c.name}: ${c.phase ?? "not placed"}. ${c.reasons.join(" ")}`).join("\n") }] });
  return (
    <div className="card">
      <div className="card-head"><h3>Short-term debt cycle: where each country is now</h3><CardAsk onAsk={ask} /></div>
      <div className="clock-wrap">
        <ClockFace clock={d} />
        <div className="small clock-list">
          {d.countries.map((c) => (
            <details key={c.entity} open={c.entity === "NZL"}>
              <summary><Flag id={c.entity} /><b>{c.name}</b>: {c.phase ? c.phase.toLowerCase() : "not placed"}</summary>
              <ul>{c.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            </details>))}
        </div>
      </div>
      <ShortCycleChart entity={pick} onPick={setPick} />
      <p className="caption">{d.how} {d.note}</p>
    </div>
  );
}

// Six phases around a circle, each country a dot in its phase.
export function ClockFace({ clock, size = 240 }: { clock: Clock; size?: number }) {
  const pad = 44, w = size + 2 * pad;
  const r = size / 2 - 30, cx = w / 2, cy = size / 2;
  const at = (deg: number, rr: number) => [cx + rr * Math.sin((deg * Math.PI) / 180), cy - rr * Math.cos((deg * Math.PI) / 180)];
  const arc = (a0: number, a1: number) => {
    const [x0, y0] = at(a0, r), [x1, y1] = at(a1, r);
    return `M ${cx} ${cy} L ${x0} ${y0} A ${r} ${r} 0 0 1 ${x1} ${y1} Z`;
  };
  const tones = ["--div-pos-1", "--div-pos-2", "--c-aus", "--div-neg-1", "--div-neg-2", "--div-pos-1"];
  return (
    <svg width={w} height={size} viewBox={`0 0 ${w} ${size}`} style={{ maxWidth: "100%" }} role="img" aria-label="The six phases of the short-term debt cycle, with each country placed">
      {clock.phases.map((p, i) => {
        const [lx, ly] = at(i * 60 + 30, r + 18);
        return (<g key={p.name}>
          <path d={arc(i * 60, i * 60 + 60)} fill={`var(${tones[i]})`} opacity={0.35} stroke="var(--surface)" strokeWidth={2}><title>{`${p.name}: ${p.about}`}</title></path>
          <text x={lx} y={ly} fontSize={10} textAnchor="middle" dominantBaseline="middle" fill="var(--ink-2)">{p.name}</text>
        </g>);
      })}
      {clock.countries.filter((c) => c.angle !== null).map((c, i, all) => {
        const same = all.filter((x) => x.angle === c.angle);
        const k = same.indexOf(c);
        const [x, y] = at(c.angle! + 30 + (k - (same.length - 1) / 2) * 12, r * 0.62);
        return (<g key={c.entity}>
          <circle cx={x} cy={y} r={9} fill={entityVar(c.entity, i)} stroke="var(--surface)" strokeWidth={1.5} />
          <text x={x} y={y + 1} fontSize={8} fill="#fff" textAnchor="middle" dominantBaseline="middle">{c.entity}</text>
          <title>{`${c.name}: ${c.phase}`}</title>
        </g>);
      })}
    </svg>
  );
}

function ShortCycleChart({ entity, onPick }: { entity: string; onPick: (e: string) => void }) {
  const [d, setD] = useState<ShortCycle | null>(null);
  const { onReady, save, ask } = useSavePicture();
  useEffect(() => {
    let live = true;
    cyclesApi.short(entity).then((x) => live && setD(x)).catch(() => live && setD(null));
    return () => { live = false; };
  }, [entity]);
  const option = useCallback(() => (d ? shortOption(d) : {}), [d]);
  const title = `Short-term debt cycles: ${entity}`;
  const note = "Yearly growth (bars), the central bank rate and private credit as a share of GDP, recessions shaded.";
  return (
    <>
      <div className="long-tools"><span className="small">Over time:</span>
        <div className="seg small" role="group">{["NZL", "AUS", "GBR", "USA"].map((e) => (
          <button key={e} className={entity === e ? "on" : ""} onClick={() => onPick(e)}><Flag id={e} />{e}</button>))}</div>
        <button className="link small" onClick={() => ask(title, note, ["bis", "world_bank_wdi"], entity)}>Ask AI about the chart</button>
        <button className="link small" onClick={() => save(title, note, ["bis", "world_bank_wdi"], "short-cycle", entity)}>Save picture</button>
      </div>
      {d && (d.growth.length || d.rate.length) ? <EChart option={option} height={260} label="Growth, the central bank rate and private credit over time, recessions shaded" onReady={onReady} />
        : <p className="muted small">No figures for this country yet.</p>}
    </>
  );
}

// The country page's card: the long-term debt cycle and where the short-term cycle stands.
export function DebtCycleCard({ entity, name }: { entity: string; name: string }) {
  const [c, setC] = useState<Clock | null>(null);
  useEffect(() => { cyclesApi.clock([entity]).then(setC).catch(() => setC(null)); }, [entity]);
  const me = c?.countries[0];
  return (
    <>
      <LongDebtCycle start={entity} fixed name={name} />
      {me && me.phase && (
        <div className="card">
          <div className="card-head"><h3>Short-term debt cycle: {me.phase.toLowerCase()}</h3>
            <CardAsk onAsk={() => openAsk({ title: `${name}: short-term debt cycle`, entity, parts: [
              { key: "data", kind: "data", label: "Phase and reasons", text: `${me.phase}. ${me.reasons.join(" ")}` },
              { key: "description", kind: "description", label: "How it is placed", text: c!.how }] })} /></div>
          <div className="clock-wrap"><ClockFace clock={c!} size={200} />
            <ul className="small">{me.reasons.map((r) => <li key={r}>{r}</li>)}</ul></div>
          <p className="caption">Simple rules on growth, the central bank rate, the leading indicator, inflation and credit; a copy of Dalio&apos;s idea, not a forecast.</p>
        </div>)}
    </>
  );
}
