"use client";

// Story steps added with the second set of stories: the US states (any country's regions),
// countries as moving dots, forecasts against outcomes, forecasters scored, and a war tracker.

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { EChartsOption } from "echarts";
import EChart from "@/components/EChart";
import RegionMap from "@/components/RegionMap";
import { Frame, notLoaded, type Props } from "@/components/story/Frame";
import { api, type MapRange, type Regions, type TrackRecord } from "@/lib/api";
import { chrome, scatterExtent, scatterOption, trackOption, type ScatterPoint } from "@/lib/charts";
import { cssVar } from "@/lib/colors";
import { entityColors, shortValue } from "@/lib/look";
import { areaOption, lossesOption, osintApi, type WarDetail } from "@/lib/osint";
import { crowdApi, pred } from "@/lib/predictions";
import { fmtOf, type BubbleData, type ScoresData, type StatesData, type Step } from "@/lib/story";

type Row = { id: string; name: string; v: number; ref?: boolean };

// Ranked bars, highest first, with some rows marked (key countries, or reference lines).
// `sides`: colours for values above and below zero (the Democrat and Republican leads).
function barsOption(rows: Row[], unit: string, decimals: number, colour: string, mark: Set<string>, signed = false, sides?: [string, string]): EChartsOption {
  const c = chrome();
  const cols = entityColors(rows.map((r) => r.id));
  return { ...c, grid: { left: 8, right: 64, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: "value", show: false }, yAxis: { type: "category", inverse: true, data: rows.map((r) => r.name), axisTick: { show: false },
      axisLine: { show: false }, axisLabel: { color: cssVar("--ink-2"), fontSize: 12, fontWeight: (v: string) => (rows.find((r) => r.name === v)?.ref ? 700 : 400) } as object },
    tooltip: { ...(c.tooltip as object), trigger: "item" },
    series: [{ type: "bar", barMaxWidth: 16, data: rows.map((r, k) => ({ value: r.v, name: r.name,
      itemStyle: { color: mark.has(r.id) ? cols[k] : sides ? sides[r.v >= 0 ? 0 : 1] : colour, opacity: mark.size && !mark.has(r.id) ? 0.6 : 1, borderRadius: 3 },
      label: { show: true, position: r.v < 0 ? "left" : "right", color: cssVar("--ink"), fontSize: 11, fontWeight: 600,
        formatter: () => `${signed && r.v > 0 ? "+" : ""}${shortValue(r.v, unit, decimals)}` } })) }],
  } as EChartsOption;
}

// ---------------------------------------------------------------- states
export function StatesStep(p: Props & { step: Extract<Step, { kind: "states" }> }) {
  const router = useRouter();
  const st = p.step;
  const country = st.country ?? "USA";
  const [data, setData] = useState<Regions | null>(null);
  const [shapes, setShapes] = useState<GeoJSON.FeatureCollection | null>(null);
  const [refs, setRefs] = useState<StatesData["refs"]>([]);
  useEffect(() => {
    api.regions(country).then(setData).catch(() => setData({ country, level: null, regions: [], measures: [] }));
    if (st.show !== "bars") api.regionShapes(country).then(setShapes).catch(() => setShapes(null));
  }, [country, st.show]);
  useEffect(() => {
    if (!st.refs) return;
    const want = st.refs.entities;
    api.ranking(st.refs.indicator).then((r) => setRefs(want.map((id) => r.rows.find((x) => x.entity_id === id))
      .filter((x): x is NonNullable<typeof x> => !!x).map((x) => ({ id: x.entity_id, name: x.name, value: x.value })))).catch(() => setRefs([]));
  }, [st.refs]);
  const d = useMemo((): StatesData | null => {
    const m = data?.measures.find((x) => x.indicator_id === st.indicator);
    if (!data || !m) return null;
    const less = st.minus ? data.measures.find((x) => x.indicator_id === st.minus) : null;
    const under = st.over ? data.measures.find((x) => x.indicator_id === st.over) : null;
    const pop = st.per ? data.measures.find((x) => x.indicator_id.endsWith("_population")) : null;
    // the latest year most regions have
    const year = [...m.years].reverse().find((y) => data.regions.filter((r) => m.values[r.entity_id]?.[String(y)] != null).length >= data.regions.length * 0.8)
      ?? m.years[m.years.length - 1];
    const value = (e: string) => {
      let v = m.values[e]?.[String(year)];
      if (v == null) return null;
      if (less) { const w = less.values[e]?.[String(year)]; if (w == null) return null; v -= w; }
      if (under) { const w = under.values[e]?.[String(year)]; if (!w) return null; v /= w; }
      if (pop) { const n = pop.values[e]?.[String(year)]; if (!n) return null; v = (1000 * v) / n; }
      return v;
    };
    const rows = data.regions.map((r) => ({ id: r.entity_id, name: r.name, value: value(r.entity_id) }))
      .filter((r): r is { id: string; name: string; value: number } => r.value !== null).sort((a, b) => b.value - a.value);
    const unit = st.per ? "per 1,000 people" : st.minus ? "points" : st.over ? "times" : m.unit;
    const fmt = (v: number | null | undefined) => (v == null ? "–" : st.minus ? `${v > 0 ? "+" : ""}${v.toFixed(1)} points`
      : st.per ? `${v > 0 ? "+" : ""}${v.toFixed(1)} per 1,000` : st.over ? `${v.toFixed(1)} times` : fmtOf({ ...m, indicator_id: m.indicator_id } as never)(v));
    return { name: st.label ?? m.name.replace(/ \(.*\)$/, ""), unit, year, rows, refs, fmt,
      row: (nm) => { const k = rows.findIndex((r) => r.name.toLowerCase() === nm.toLowerCase() || r.id === nm); return k < 0 ? undefined : { ...rows[k], rank: k + 1 }; } };
  }, [data, st, refs]);
  const option = useCallback((): EChartsOption => {
    if (!d) return {};
    const many = d.rows.length > 24;
    const pick: Row[] = (many ? [...d.rows.slice(0, 10), ...d.rows.slice(-10)] : d.rows).map((r) => ({ id: r.id, name: r.name, v: r.value }));
    const all = [...pick, ...d.refs.map((r) => ({ id: r.id, name: r.name, v: r.value, ref: true }))].sort((a, b) => b.v - a.v);
    const derived = !!(st.minus || st.per || st.over);
    const dec = derived ? 1 : p.inds.get(st.indicator)?.decimals ?? 1;
    return barsOption(all, derived ? "" : d.unit, dec, p.colour, new Set(d.refs.map((r) => r.id)), !!(st.minus || st.per),
      st.minus ? ["#2c4f9e", "#c0392b"] : undefined);
  }, [d, p.colour, p.inds, st.minus, st.per, st.over, st.indicator]);
  if (data && !d) return <Frame {...p} sentence={null} data="" missing={notLoaded([p.inds.get(st.indicator)?.name ?? `${st.indicator} (US states)`])} />;
  const values = d ? Object.fromEntries(d.rows.map((r) => [r.id, r.value])) : {};
  const map = st.show !== "bars" && !!shapes?.features.length;
  return (
    <Frame {...p} sentence={d ? st.say(d) : null} data={d ? [`Place,${d.name} (${d.unit}),${d.year}`, ...d.rows.map((r) => `"${r.name}",${+r.value.toPrecision(6)}`),
      ...d.refs.map((r) => `"${r.name} (whole country)",${+r.value.toPrecision(6)}`)].join("\n") : ""}>
      {d && (map
        ? <div className="story-map"><RegionMap shapes={shapes} values={values} unit={d.unit} decimals={st.per || st.minus || st.over ? 1 : p.inds.get(st.indicator)?.decimals ?? 0} height={440} onPick={(id) => router.push(`/entity/${id}`)} /></div>
        : <EChart option={option} height={Math.max(260, (Math.min(d.rows.length, 20) + d.refs.length) * 24 + 20)} label={p.title} />)}
      <p className="caption">{d?.name}{d && st.minus ? " (difference)" : ""}, {d?.year}.{map ? " Click a state for its page." : d && d.rows.length > 24 ? " The ten highest and ten lowest." : ""}
        {d?.refs.length ? " Bold rows are whole countries, for comparison." : ""}</p>
    </Frame>
  );
}

// ---------------------------------------------------------------- bubbles
const SHORT: Record<string, string> = { GBR: "United Kingdom", USA: "United States", RUS: "Russia", KOR: "South Korea", IRN: "Iran" };
export function BubblesStep(p: Props & { step: Extract<Step, { kind: "bubbles" }> }) {
  const st = p.step;
  const ix = p.inds.get(st.x), iy = p.inds.get(st.y);
  const [r, setR] = useState<{ x: MapRange; y: MapRange; s: MapRange; names: Record<string, string> } | null>(null);
  const [err, setErr] = useState(false);
  const [k, setK] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    Promise.all([api.mapRange(st.x, st.from), api.mapRange(st.y, st.from), api.mapRange("pop_total", st.from), api.entities()])
      .then(([x, y, s, es]) => setR({ x, y, s, names: { ...Object.fromEntries(es.filter((e) => e.type === "country").map((e) => [e.entity_id, e.name])), ...SHORT } }))
      .catch(() => setErr(true));
  }, [st.x, st.y, st.from]);
  const d = useMemo((): (BubbleData & { points: (y: number) => ScatterPoint[] }) | null => {
    if (!r || !ix || !iy) return null;
    const cap = Math.min(r.x.last_estimate_year ?? 9999, r.y.last_estimate_year ?? 9999);
    const years = r.x.years.filter((y) => r.y.years.includes(y) && y <= cap && (!st.from || y >= st.from));
    const val = (m: MapRange, e: string, y: number) => { const i = m.years.indexOf(y); return i < 0 ? null : m.rows[e]?.[i] ?? null; };
    const at = (e: string, y: number) => { const a = val(r.x, e, y), b = val(r.y, e, y); return a == null || b == null ? null : { x: a, y: b }; };
    const points = (y: number): ScatterPoint[] => Object.keys(r.names).flatMap((e): ScatterPoint[] => { const q = at(e, y); return q && (!st.logX || q.x > 0)
      ? [{ id: e, name: r.names[e], x: q.x, y: q.y, size: val(r.s, e, y) ?? undefined, proj: false }] : []; });
    // keep years with most countries (early years can be thin)
    const good = years.filter((y) => points(y).length >= 40);
    return { years: good, first: good[0], last: good[good.length - 1], at, names: r.names, points, fmtX: fmtOf(ix), fmtY: fmtOf(iy) };
  }, [r, ix, iy, st.from, st.logX]);
  const year = d ? d.years[k ?? d.years.length - 1] : null;
  useEffect(() => {
    if (!playing || !d) return;
    const t = setInterval(() => setK((cur) => { const n = (cur ?? -1) + 1; if (n >= d.years.length - 1) { setPlaying(false); return d.years.length - 1; } return n; }), 350);
    return () => clearInterval(t);
  }, [playing, d]);
  const hold = useMemo(() => (d ? scatterExtent(d.years.filter((_, i) => i % 5 === 0 || i === d.years.length - 1).flatMap((y) => d.points(y)), !!st.logX, false, false) : null), [d, st.logX]);
  const option = useCallback((): EChartsOption => {
    if (!d || year == null || !ix || !iy) return {};
    const o = scatterOption(d.points(year), { name: ix.name, unit: ix.unit, decimals: ix.decimals, log: !!st.logX },
      { name: iy.name, unit: iy.unit, decimals: iy.decimals, log: false }, { name: "People", unit: "persons", decimals: 0, log: false },
      st.highlight, { grouped: false, labelled: new Set(st.highlight), trim: false, hold, step: playing ? 350 : undefined });
    // the key countries in their fixed colours (New Zealand black, Australia gold, the UK red, the US blue)
    const cols = new Map(st.highlight.map((id, i) => [id, entityColors(st.highlight)[i]]));
    const series = (o.series as { data?: { name: string; itemStyle?: { color?: string } }[] }[]).map((x) => ({ ...x,
      data: x.data?.map((q) => (cols.has(q.name) ? { ...q, itemStyle: { ...q.itemStyle, color: cols.get(q.name) } } : q)) }));
    return { ...o, series: series as EChartsOption["series"], graphic: [{ type: "text", right: 24, bottom: 48, style: { text: String(year), fontSize: 48, fontWeight: 700, fill: cssVar("--grid"), fontFamily: "serif" } }] } as EChartsOption;
  }, [d, year, ix, iy, st, hold, playing]);
  const missing = !ix || !iy || err || (d && !d.years.length);
  if (missing) return <Frame {...p} sentence={null} data="" missing={notLoaded([ix?.name ?? st.x, iy?.name ?? st.y])} />;
  return (
    <Frame {...p} sentence={d ? st.say(d) : null} data={d && year ? [`Country,${ix.name},${iy.name} (${year})`, ...d.points(year).map((q) => `"${q.name}",${+q.x.toPrecision(5)},${+q.y.toPrecision(5)}`)].join("\n") : ""}>
      {d && <>
        <div className="chips-row small no-print" style={{ alignItems: "center" }}>
          <button onClick={() => { if (!playing && (k ?? d.years.length - 1) >= d.years.length - 1) setK(0); setPlaying(!playing); }}>{playing ? "Pause" : "Play"}</button>
          <input type="range" min={0} max={d.years.length - 1} value={k ?? d.years.length - 1} onChange={(e) => { setPlaying(false); setK(+e.target.value); }}
            aria-label="Year" style={{ flex: 1, minWidth: 120 }} />
          <span className="mono">{year}</span>
        </div>
        <EChart option={option} height={440} label={p.title} update="merge" />
      </>}
      <p className="caption">Each dot is a country, sized by its people; {st.highlight.length ? "named dots are picked out. " : ""}Press Play to run through the years.{st.logX ? " The across axis is on a log scale." : ""}</p>
    </Frame>
  );
}

// ---------------------------------------------------------------- forecasts against outcomes
export function TrackStep(p: Props & { step: Extract<Step, { kind: "track" }> }) {
  const st = p.step;
  const [t, setT] = useState<TrackRecord | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    api.trackRecord(st.indicator, st.show === "paths" ? st.entity : undefined, st.source ?? "imf_weo").then(setT).catch(() => setErr(true));
  }, [st.indicator, st.entity, st.show, st.source]);
  const rows = useMemo((): Row[] => {
    if (!t?.countries) return [];
    const ok = t.countries.filter((c) => c.mae != null && c.n >= 8).sort((a, b) => a.mae! - b.mae!);
    const hi = new Set(st.highlight ?? []);
    const pick = [...ok.slice(0, 6), ...ok.filter((c) => hi.has(c.entity_id)), ...ok.slice(-6)];
    const seen = new Set<string>();
    return pick.filter((c) => !seen.has(c.entity_id) && seen.add(c.entity_id)).sort((a, b) => a.mae! - b.mae!).map((c) => ({ id: c.entity_id, name: c.name, v: c.mae! }));
  }, [t, st.highlight]);
  const option = useCallback((): EChartsOption => {
    if (!t) return {};
    if (st.show === "paths") return trackOption(t.actual ?? [], t.paths ?? [], "percent", 1, 2000);
    return barsOption(rows, "%", 1, p.colour, new Set(st.highlight ?? []));
  }, [t, st, rows, p.colour]);
  const empty = err || (t && (st.show === "paths" ? !(t.paths?.length) : !rows.length));
  if (empty) return <Frame {...p} sentence={null} data="" missing={notLoaded(["past IMF forecasts (a refresh loads the IMF's file of every forecast since 1990)"])} />;
  return (
    <Frame {...p} sentence={t ? st.say(t) : null} data={t ? (st.show === "paths"
      ? ["Year,What happened", ...(t.actual ?? []).map(([y, v]) => `${y},${v}`)].join("\n")
      : ["Country,Typical miss (points),Forecasts", ...(t.countries ?? []).map((c) => `"${c.name}",${c.mae ?? ""},${c.n}`)].join("\n")) : ""}>
      {t && <EChart option={option} height={st.show === "paths" ? 380 : Math.max(260, rows.length * 24 + 20)} label={p.title} />}
      <p className="caption">{st.show === "paths"
        ? `Thin lines: what each ${t?.source_name ?? "IMF"} release forecast (darker is newer). Thick line: what happened.`
        : `Typical miss of next-year forecasts, in percentage points (lower is better): the six best and six worst, with the key countries.`}</p>
    </Frame>
  );
}

// ---------------------------------------------------------------- forecasters scored
export function ScoresStep(p: Props & { step: Extract<Step, { kind: "scores" }> }) {
  const st = p.step;
  const [d, setD] = useState<ScoresData | null>(null);
  const [none, setNone] = useState<string | null>(null);
  useEffect(() => {
    if (st.who === "crowd") {
      pred.scorecard().then((r) => {
        const rows = r.rows.filter((x) => x.brier != null && x.brier_n >= 5).map((x) => ({ name: x.name, kind: x.kind, n: x.brier_n, hit: x.hit_rate, brier: x.brier }));
        if (!rows.length) setNone("scored forecasts (crowd questions and your own predictions that have settled)"); else setD({ rows });
      }).catch(() => setNone("the predictions scorecard"));
    } else {
      crowdApi.pundits({ min_graded: 10, sort: "accuracy", limit: 400 }).then((v) => {
        const rows = v.people.filter((x) => x.accuracy != null).map((x) => ({ name: x.name, kind: "pundit", n: x.graded || (x.correct ?? 0) + (x.incorrect ?? 0), hit: x.accuracy, brier: null }));
        if (!v.loaded || !rows.length) setNone("pundits' records (save Prediction Archive pages: .\\verify.bat prediction_archive)"); else setD({ rows });
      }).catch(() => setNone("pundits' records"));
    }
  }, [st.who]);
  const option = useCallback((): EChartsOption => {
    if (!d) return {};
    const rows: Row[] = st.who === "crowd"
      ? [...d.rows].sort((a, b) => a.brier! - b.brier!).slice(0, 16).map((r) => ({ id: r.name, name: r.name, v: r.brier! }))
      : [...d.rows.slice(0, 8), ...d.rows.slice(-6)].map((r) => ({ id: r.name, name: r.name, v: 100 * r.hit! }));
    return barsOption(rows, st.who === "crowd" ? "" : "%", st.who === "crowd" ? 3 : 0, p.colour, new Set(d.rows.filter((r) => r.kind === "you").map((r) => r.name)));
  }, [d, st.who, p.colour]);
  if (none) return <Frame {...p} sentence={null} data="" missing={notLoaded([none])} />;
  return (
    <Frame {...p} sentence={d ? st.say(d) : null} data={d ? ["Who,Kind,Scored,Hit rate,Brier", ...d.rows.map((r) => `"${r.name}",${r.kind},${r.n},${r.hit ?? ""},${r.brier ?? ""}`)].join("\n") : ""}>
      {d && <EChart option={option} height={Math.max(240, Math.min(16, d.rows.length) * 26 + 20)} label={p.title} />}
      <p className="caption">{st.who === "crowd"
        ? "Brier score: 0 is perfect, 0.25 is what always saying 50% gets. Lower is better. Only forecasters with five or more settled questions."
        : "Share of graded calls that came true, as Prediction Archive grades them (an AI reader checking later news). The eight best and six worst with ten or more graded calls."}</p>
    </Frame>
  );
}

// ---------------------------------------------------------------- war tracker
const SIDE_NAMES: Record<string, string> = { RUS: "Russia", UKR: "Ukraine" };
export function WarStep(p: Props & { step: Extract<Step, { kind: "war" }> }) {
  const st = p.step;
  const [w, setW] = useState<WarDetail | null>(null);
  const [none, setNone] = useState(false);
  const once = useRef(false);
  useEffect(() => {
    if (once.current) return;
    once.current = true;
    osintApi.wars().then((l) => { const id = st.war ?? l.wars[0]?.id; if (!id) { setNone(true); return; }
      osintApi.war(id).then((x) => (x.areas.length || x.series.length ? setW(x) : setNone(true))).catch(() => setNone(true)); }).catch(() => setNone(true));
  }, [st.war]);
  const area = useCallback(() => (w ? areaOption(w.areas, `Land held by ${SIDE_NAMES[w.front?.holder ?? ""] ?? "the occupier"}`) : {}), [w]);
  const losses = useCallback(() => (w ? lossesOption(w, "tanks", SIDE_NAMES) : {}), [w]);
  if (none) return <Frame {...p} sentence={null} data="" missing={notLoaded(["the war trackers (Settings > Fighting, wars…: War trackers on)"])} />;
  return (
    <Frame {...p} sentence={w ? st.say({ w }) : null} data={w ? ["Day,Land held (km²)", ...w.areas.filter((_, i) => i % 30 === 0).map(([d, v]) => `${d},${Math.round(v)}`)].join("\n") : ""}>
      {w && <div className="grid two">
        {w.areas.length > 0 && <div><EChart option={area} height={300} label={`${p.title}: land held`} /><p className="caption">Land held, from DeepStateMap&apos;s daily front line.</p></div>}
        {w.series.length > 0 && <div><EChart option={losses} height={300} label={`${p.title}: tanks lost`} />
          <p className="caption">Tanks lost, running total. Solid: seen in photos or video (Oryx). Dashed: claimed by the other side.</p></div>}
      </div>}
    </Frame>
  );
}
