"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { EChartsOption } from "echarts";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import ElectricityMap from "@/components/ElectricityMap";
import LargestCities from "@/components/LargestCities";
import SeaIceCard from "@/components/SeaIceCard";
import WorldMap from "@/components/WorldMap";
import { openAsk } from "@/lib/ai";
import { api, get, type Indicator, type MapRange, type Ranking, type RankingRow, type SeriesRow } from "@/lib/api";
import { chrome, linesOption } from "@/lib/charts";
import { cssVar } from "@/lib/colors";
import { formatValue } from "@/lib/format";
import { entityColors, shortValue } from "@/lib/look";
import { fmtOf, type CityData, type CountData, type RankData, type SeriesData, type Step, type TilesData } from "@/lib/story";

type Props = { step: Step & { kicker?: string }; i: number; total: number; inds: Map<string, Indicator>; colour: string; title: string };

// One step of a story: its number, the sentence (from its own figures), the chart and Ask AI.
export default function StoryStep(p: Props) {
  const s = p.step;
  if (s.kind === "map") return <MapStep {...p} step={s} />;
  if (s.kind === "lines") return <LinesStep {...p} step={s} />;
  if (s.kind === "count") return <CountStep {...p} step={s} />;
  if (s.kind === "bars") return <BarsStep {...p} step={s} />;
  if (s.kind === "tiles") return <TilesStep {...p} step={s} />;
  if (s.kind === "cities") return <CitiesStep {...p} step={s} />;
  return <Frame {...p} sentence={s.say} data="">{s.view === "seaice" ? <SeaIceCard /> : s.view === "electricity" ? <ElectricityMap /> : <LargestCities />}</Frame>;
}

function Frame({ i, total, colour, title, step, sentence, data, missing, children }: Props & { sentence: string | null; data: string; missing?: string | null;
  children?: React.ReactNode }) {
  const box = useRef<HTMLElement>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => { // fade in as it scrolls into view
    const el = box.current;
    if (!el || typeof IntersectionObserver === "undefined") { setSeen(true); return; }
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { setSeen(true); io.disconnect(); } }, { threshold: 0.15 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  const ask = () => openAsk({ title: `${title}, step ${i + 1}`, parts: [
    { key: "say", kind: "highlight", label: "What this step says", text: sentence ?? "" },
    ...(data ? [{ key: "data", kind: "data" as const, label: "The figures behind it", text: data }] : []),
  ] });
  return (
    <section ref={box} className={`story-step${seen ? " seen" : ""}`} style={{ ["--story" as string]: colour }}>
      <div className="story-say">
        <span className="story-num">{i + 1}<span>/{total}</span></span>
        <div>
          {step.kicker && <div className="story-kicker">{step.kicker}</div>}
          <p className="story-sentence">{missing ? <span className="muted">{missing}</span> : sentence ?? <span className="muted">Working it out…</span>}</p>
        </div>
        <span className="story-ask"><CardAsk onAsk={ask} /></span>
      </div>
      {!missing && <div className="story-visual">{children}</div>}
    </section>
  );
}

const notLoaded = (ids: string[]) => `Not loaded yet: ${ids.join(", ")}. A refresh fetches it, and this step fills in by itself.`;

// ---------------------------------------------------------------- map
function MapStep(p: Props & { step: Extract<Step, { kind: "map" }> }) {
  const router = useRouter();
  const ind = p.inds.get(p.step.indicator);
  const [ranking, setRanking] = useState<Ranking | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => { api.ranking(p.step.indicator, p.step.year).then(setRanking).catch(() => setErr(true)); }, [p.step.indicator, p.step.year]);
  const d = useMemo(() => (ind && ranking ? rankData(ind, ranking) : null), [ind, ranking]);
  if (!ind || err || (ranking && !ranking.rows.length)) return <Frame {...p} sentence={null} data="" missing={notLoaded([ind?.name ?? p.step.indicator])} />;
  const values = (ranking?.rows ?? []).map((r) => ({ entity_id: r.entity_id, value: r.value, status: r.status }));
  return (
    <Frame {...p} sentence={d ? p.step.say(d) : null} data={ranking ? rankText(ind, ranking) : ""}>
      <div className="story-map">
        <WorldMap fill values={values} unit={ind.unit} decimals={ind.decimals} diverging={!!p.step.diverging} onPick={(id) => router.push(`/entity/${id}`)} />
      </div>
      <p className="caption">{ind.name}, {ranking?.year}. Click a country for its page.</p>
    </Frame>
  );
}

function rankData(ind: Indicator, ranking: Ranking): RankData {
  const by = new Map(ranking.rows.map((r) => [r.entity_id, r]));
  return { ind, ranking, row: (id) => (id === "world" ? ranking.world ?? undefined : by.get(id)), count: (t) => ranking.rows.filter((r) => t(r.value)).length, fmt: fmtOf(ind) };
}
const rankText = (ind: Indicator, r: Ranking) => [`Rank,Country,${ind.name} (${ind.unit}),Ten years before`,
  ...r.rows.map((x) => `${x.rank},"${x.name}",${+x.value.toPrecision(6)},${x.ten_years_before ?? ""}`)].join("\n");

// ---------------------------------------------------------------- lines
function LinesStep(p: Props & { step: Extract<Step, { kind: "lines" }> }) {
  const st = p.step;
  const ids = st.indicators ?? [st.indicator];
  const inds = ids.map((id) => p.inds.get(id)).filter((x): x is Indicator => !!x);
  const [rows, setRows] = useState<SeriesRow[][] | null>(null);
  const ents = st.entities.map((e) => e.id).join(",");
  useEffect(() => {
    Promise.all(ids.map((id) => api.series(id, ents.split(","), st.from, st.to).catch(() => [] as SeriesRow[]))).then(setRows);
  }, [ids.join(","), ents, st.from, st.to]); // eslint-disable-line react-hooks/exhaustive-deps
  const d = useMemo((): SeriesData | null => {
    if (!rows || !inds.length) return null;
    const pick = (e: string, l = 0) => (rows[l] ?? []).filter((r) => r.entity_id === e).sort((a, b) => +a.period - +b.period);
    return {
      inds, rows,
      last: (e, l = 0) => { const r = pick(e, l).filter((x) => x.status === "E").at(-1); return r ? { year: +r.period, value: r.value } : null; },
      end: (e, l = 0) => { const r = pick(e, l).at(-1); return r ? { year: +r.period, value: r.value } : null; },
      at: (e, y, l = 0) => pick(e, l).find((x) => +x.period === y)?.value ?? null,
      fmt: (v, l = 0) => fmtOf(inds[l] ?? inds[0])(v),
    };
  }, [rows, inds.map((x) => x.indicator_id).join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  const option = useCallback((): EChartsOption => {
    if (!rows) return {};
    if (ids.length === 1) return linesOption([{ id: ids[0], name: inds[0].name, unit: inds[0].unit, decimals: inds[0].decimals, rows: rows[0] }], st.entities);
    // several measures for one place: one line each, named by `labels`, coloured by `colors`
    const layers = inds.map((ind, k) => ({ id: ind.indicator_id, name: st.labels?.[k] ?? ind.name, unit: ind.unit, decimals: ind.decimals, rows: rows[k] ?? [] }));
    const o = linesOption(layers, st.entities);
    if (st.colors) {
      o.series = (o.series as { id: string; color?: string; endLabel?: { color?: string } }[]).map((x) => {
        const k = layers.findIndex((l) => x.id.includes(`|${l.id}:`));
        const c = k >= 0 ? st.colors![k] : undefined;
        return c ? { ...x, color: c, endLabel: x.endLabel ? { ...x.endLabel, color: c } : undefined } : x;
      }) as typeof o.series;
    }
    return o;
  }, [rows, st, ids.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!inds.length || (rows && rows.every((r) => !r.length))) return <Frame {...p} sentence={null} data="" missing={notLoaded(st.about ? [st.about] : ids.map((id) => p.inds.get(id)?.name ?? id))} />;
  const data = rows ? inds.map((ind, k) => `${ind.name} (${ind.unit})\n` + (rows[k] ?? []).map((r) => `${r.entity_id},${r.period},${+r.value.toPrecision(6)}${r.status === "P" ? ",projection" : ""}`).join("\n")).join("\n\n") : "";
  return (
    <Frame {...p} sentence={d ? st.say(d) : null} data={data}>
      {rows && <EChart option={option} height={400} label={p.title} />}
      <p className="caption">{inds.map((x) => x.name).join(", ")}. Dashed lines are projections.</p>
    </Frame>
  );
}

// ---------------------------------------------------------------- count
function CountStep(p: Props & { step: Extract<Step, { kind: "count" }> }) {
  const st = p.step;
  const ind = p.inds.get(st.indicator);
  const [range, setRange] = useState<MapRange | null>(null);
  const [countries, setCountries] = useState<Set<string> | null>(null);
  useEffect(() => {
    api.mapRange(st.indicator).then(setRange).catch(() => setRange({ indicator: st.indicator, years: [], last_estimate_year: null, rows: {} }));
    api.entities().then((es) => setCountries(new Set(es.filter((e) => e.type === "country").map((e) => e.entity_id)))).catch(() => setCountries(new Set()));
  }, [st.indicator]);
  const d = useMemo((): CountData | null => {
    if (!ind || !range || !countries) return null;
    const keep = range.years.map((y, i) => [y, i] as const).filter(([y]) => !st.to || y <= st.to);
    const rowsC = Object.entries(range.rows).filter(([id]) => countries.has(id));
    const counts = keep.map(([, i]) => rowsC.filter(([, vs]) => vs[i] !== null && st.test(vs[i]!)).length);
    const totals = keep.map(([, i]) => rowsC.filter(([, vs]) => vs[i] !== null).length);
    const years = keep.map(([y]) => y);
    return { ind, years, counts, totals, lastEstimate: range.last_estimate_year,
      at: (y) => { const k = years.indexOf(y); return k < 0 ? null : { count: counts[k], total: totals[k] }; }, fmt: fmtOf(ind) };
  }, [ind, range, countries, st]);
  const option = useCallback((): EChartsOption => {
    if (!d) return {};
    const c = chrome();
    return { ...c, grid: { ...(c.grid as object), top: 24 },
      xAxis: { ...(c.xAxis as object) },
      yAxis: { type: "value", axisLabel: { color: cssVar("--muted") }, splitLine: { lineStyle: { color: cssVar("--grid") } }, name: "countries", nameTextStyle: { color: cssVar("--muted"), align: "left" } },
      tooltip: { ...(c.tooltip as object), formatter: (ps: unknown) => { const x = (ps as { dataIndex: number }[])[0]; return `<b>${d.years[x.dataIndex]}</b><br/>${d.counts[x.dataIndex]} of ${d.totals[x.dataIndex]} countries ${st.label}`; } },
      series: [{ type: "bar", barMaxWidth: 8, data: d.years.map((y, k) => ({ value: [y, d.counts[k]],
        itemStyle: { color: p.colour, opacity: d.lastEstimate && y > d.lastEstimate ? 0.35 : 1, borderRadius: [2, 2, 0, 0] },
        label: { show: k === d.years.length - 1 || (y % 25 === 0), position: "top", color: cssVar("--ink-2"), fontSize: 11, formatter: () => String(d.counts[k]) } })) }],
    } as EChartsOption;
  }, [d, p.colour, st.label]);
  if (!ind || (range && !range.years.length)) return <Frame {...p} sentence={null} data="" missing={notLoaded([ind?.name ?? st.indicator])} />;
  return (
    <Frame {...p} sentence={d ? st.say(d) : null} data={d ? ["Year,Countries " + st.label + ",Countries with figures", ...d.years.map((y, k) => `${y},${d.counts[k]},${d.totals[k]}`)].join("\n") : ""}>
      {d && <EChart option={option} height={340} label={p.title} />}
      <p className="caption">Countries {st.label}, each year ({ind.name}).{d?.lastEstimate ? " Faded bars are projections." : ""}</p>
    </Frame>
  );
}

// ---------------------------------------------------------------- bars
function BarsStep(p: Props & { step: Extract<Step, { kind: "bars" }> }) {
  const st = p.step;
  const ind = p.inds.get(st.indicator);
  const [ranking, setRanking] = useState<Ranking | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => { api.ranking(st.indicator, st.year).then(setRanking).catch(() => setErr(true)); }, [st.indicator, st.year]);
  const d = useMemo(() => (ind && ranking ? rankData(ind, ranking) : null), [ind, ranking]);
  const shown = useMemo((): (RankingRow & { v: number })[] => {
    if (!ranking) return [];
    const val = (r: RankingRow) => (st.by === "change" ? (r.ten_years_before === null ? null : r.value - r.ten_years_before) : r.value);
    const all = ranking.rows.map((r) => ({ ...r, v: val(r) })).filter((r): r is RankingRow & { v: number } => r.v !== null);
    all.sort((a, b) => (st.order === "asc" ? a.v - b.v : b.v - a.v));
    const top = all.slice(0, st.top ?? 10);
    for (const id of st.also ?? []) { const r = all.find((x) => x.entity_id === id); if (r && !top.includes(r)) top.push(r); }
    // with no "top" (only chosen countries), keep them in rank order
    return st.top === 0 ? top.sort((a, b) => (st.order === "asc" ? a.v - b.v : b.v - a.v)) : top;
  }, [ranking, st]);
  const option = useCallback((): EChartsOption => {
    if (!ind) return {};
    const hi = new Set([...(st.highlight ?? []), ...(st.also ?? [])]);
    const cols = entityColors(shown.map((r) => r.entity_id));
    const c = chrome();
    return { ...c, grid: { left: 8, right: 60, top: 8, bottom: 8, containLabel: true },
      xAxis: { type: "value", show: false }, yAxis: { type: "category", inverse: true, data: shown.map((r) => r.name), axisTick: { show: false },
        axisLine: { show: false }, axisLabel: { color: cssVar("--ink-2"), fontSize: 12 } },
      tooltip: { ...(c.tooltip as object), trigger: "item" },
      series: [{ type: "bar", barMaxWidth: 18, data: shown.map((r, k) => ({ value: r.v, name: r.name,
        itemStyle: { color: hi.has(r.entity_id) ? cols[k] : p.colour, opacity: hi.size && !hi.has(r.entity_id) ? 0.55 : 1, borderRadius: 3 },
        label: { show: true, position: "right", color: cssVar("--ink"), fontSize: 11, fontWeight: 600,
          formatter: () => `${st.by === "change" && r.v > 0 ? "+" : ""}${shortValue(r.v, ind.unit, ind.decimals)}` } })) }],
    } as EChartsOption;
  }, [shown, ind, st, p.colour]);
  if (!ind || err || (ranking && !ranking.rows.length)) return <Frame {...p} sentence={null} data="" missing={notLoaded([ind?.name ?? st.indicator])} />;
  return (
    <Frame {...p} sentence={d ? st.say(d) : null} data={ranking ? rankText(ind, ranking) : ""}>
      {ranking && <EChart option={option} height={Math.max(220, shown.length * 30 + 20)} label={p.title} />}
      <p className="caption">{ind.name}{st.by === "change" ? ", change over ten years to" : ","} {ranking?.year}.</p>
    </Frame>
  );
}

// ---------------------------------------------------------------- tiles
function TilesStep(p: Props & { step: Extract<Step, { kind: "tiles" }> }) {
  const st = p.step;
  const [got, setGot] = useState<TilesData["rows"] | null>(null);
  useEffect(() => {
    const want = st.indicators.filter((id) => p.inds.get(id)?.available);
    Promise.all(want.map((id) => api.ranking(id).then((r) => {
      const row = r.rows.find((x) => x.entity_id === st.entity);
      return row ? { ind: p.inds.get(id)!, row, of: r.rows.length } : null;
    }).catch(() => null))).then((xs) => setGot(xs.filter((x): x is TilesData["rows"][number] => !!x).slice(0, st.max ?? 20)));
  }, [st, p.inds]);
  const d: TilesData | null = got ? { rows: got, fmt: (ind, v) => fmtOf(ind)(v) } : null;
  if (got && !got.length) return <Frame {...p} sentence={null} data="" missing={notLoaded(["the headline figures"])} />;
  return (
    <Frame {...p} sentence={d ? st.say(d) : null} data={got ? ["Measure,Value,Unit,Year,Rank,Of,Ten years before", ...got.map((g) => `"${g.ind.name}",${g.row.value},"${g.ind.unit}",${"?"},${g.row.rank},${g.of},${g.row.ten_years_before ?? ""}`)].join("\n") : ""}>
      <div className="story-tiles">
        {(got ?? []).map((g) => {
          const before = g.row.ten_years_before;
          const up = before !== null && g.row.value > before;
          const share = 1 - (g.row.rank - 1) / Math.max(1, g.of - 1); // 1 = top
          return (
            <Link key={g.ind.indicator_id} href={`/indicator/${g.ind.indicator_id}`} className="story-tile">
              <span className="label">{g.ind.name}</span>
              <span className="value">{shortValue(g.row.value, g.ind.unit, g.ind.decimals)}</span>
              <span className="rankbar" title={`${g.row.rank} of ${g.of}, highest first`}><i style={{ left: `${(1 - share) * 100}%` }} /></span>
              <span className="meta">#{g.row.rank} of {g.of}{before !== null ? ` · ${up ? "▲" : g.row.value < before ? "▼" : "="} from ${shortValue(before, g.ind.unit, g.ind.decimals)}` : ""}</span>
            </Link>
          );
        })}
      </div>
      <p className="caption">Each figure in its latest year; the bar shows where it sits among countries (left = highest). Click one for its page.</p>
    </Frame>
  );
}

// ---------------------------------------------------------------- cities
type CityRow = { city_id: string; name: string; country: string; pts: [number, number, boolean][] };
function CitiesStep(p: Props & { step: Extract<Step, { kind: "cities" }> }) {
  const st = p.step;
  const [rows, setRows] = useState<CityRow[] | null>(null);
  useEffect(() => { get<{ rows: CityRow[] }>("/cities/largest", { limit: 3000 }).then((r) => setRows(r.rows)).catch(() => setRows([])); }, []);
  const picked = useMemo(() => st.names.map((nm) => (rows ?? []).find((r) => r.name.toLowerCase() === nm.toLowerCase())
    ?? (rows ?? []).find((r) => r.name.toLowerCase().startsWith(nm.toLowerCase()))).filter((r): r is CityRow => !!r), [rows, st.names]);
  const d: CityData | null = picked.length ? { cities: picked.map((c) => ({ name: c.name, country: c.country, pts: c.pts })),
    first: Math.min(...picked.map((c) => c.pts[0]?.[0] ?? 9999)), last: Math.max(...picked.map((c) => c.pts.at(-1)?.[0] ?? 0)) } : null;
  const option = useCallback((): EChartsOption => {
    const c = chrome();
    const cols = picked.map((_, k) => cssVar(`--series-${(k % 8) + 1}`));
    return { ...c, grid: { ...(c.grid as object), right: 130, top: 24 },
      yAxis: { type: "value", axisLabel: { color: cssVar("--muted"), formatter: (v: number) => shortValue(v, "persons", 0) }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
      series: picked.map((city, k) => ({ type: "line", name: city.name, showSymbol: false, color: cols[k], lineStyle: { width: 2.2 },
        data: city.pts.map((q) => [q[0], q[1]]),
        endLabel: { show: true, color: cols[k], fontWeight: 600, fontSize: 11, formatter: () => `${city.name}  ${shortValue(city.pts.at(-1)?.[1] ?? 0, "persons", 0)}` },
        labelLayout: { moveOverlap: "shiftY" } })),
      tooltip: { ...(c.tooltip as object), valueFormatter: (v: unknown) => formatValue(Number(v), "persons") },
    } as EChartsOption;
  }, [picked]);
  if (rows && !picked.length) return <Frame {...p} sentence={null} data="" missing={notLoaded(["city populations (GHSL urban centres)"])} />;
  return (
    <Frame {...p} sentence={d ? st.say(d) : null} data={picked.map((c) => `${c.name} (${c.country}): ${c.pts.map((q) => `${q[0]} ${Math.round(q[1])}`).join(", ")}`).join("\n")}>
      {d && <EChart option={option} height={400} label={p.title} />}
      <p className="caption">People in each city&apos;s built-up area (GHSL urban centres); years after the latest estimate are projections.</p>
    </Frame>
  );
}
