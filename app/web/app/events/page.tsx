"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import type { ECharts, EChartsOption } from "echarts";
import EChart from "@/components/EChart";
import PlacePicker, { type Place } from "@/components/PlacePicker";
import Search from "@/components/Search";
import WorldMap from "@/components/WorldMap";
import { MilestoneForm } from "@/components/Timeline";
import { api, type Around, type EventKind, type EventRow, type Milestone } from "@/lib/api";
import { aroundOption } from "@/lib/charts";
import { KINDS, kindColor, kindLabel, kindVar, sizeText, when, yearOf } from "@/lib/events";
import { cssVar } from "@/lib/colors";
import { compact, formatValue, SOURCE_LABEL } from "@/lib/format";

// Events across countries: a year at a glance, an indicator in the years around a
// kind of event (World Cups, coups, disasters...) and your own milestones.
type Tab = "year" | "around" | "mine";
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

export default function EventsPage() {
  return (
    <Suspense fallback={<p className="muted">Loading…</p>}>
      <Events />
    </Suspense>
  );
}

function Events() {
  const params = useSearchParams();
  const router = useRouter();
  const tab = (params.get("tab") as Tab) || "year";
  const go = (t: Tab) => router.replace(`/events?tab=${t}`);
  return (
    <div className="grid">
      <div>
        <h1>Events</h1>
        <p className="ink-2" style={{ marginTop: 0 }}>
          Elections, coups, conflicts, sporting events, disasters and the recessions, booms and inflation spikes worked out from the
          data, plus your own milestones. They also show as bands and lines on the charts (<Link href="/settings#events">Settings</Link>).
          {" "}Conflict ratings month by month: <Link href="/crisiswatch">CrisisWatch map</Link>. Places no country owns: <Link href="/zones">Beyond borders</Link>.
        </p>
        <div className="tabs" role="tablist">
          {([["year", "Year at a glance"], ["around", "Around an event"], ["mine", "Your milestones"]] as [Tab, string][]).map(([t, l]) => (
            <button key={t} aria-pressed={tab === t} onClick={() => go(t)}>{l}</button>
          ))}
        </div>
      </div>
      {tab === "year" && <YearView />}
      {tab === "around" && <AroundView event={params.get("event")} entity={params.get("entity")} />}
      {tab === "mine" && <MineView />}
    </div>
  );
}

// ----------------------------------------------------------------------------- year at a glance
type Shape = "list" | "timeline" | "totals" | "map";
type Measure = "count" | "deaths" | "affected" | "damage";
const MEASURES: [Measure, string][] = [["count", "Number"], ["deaths", "Deaths"], ["affected", "People affected"], ["damage", "Damage (US$)"]];
const MIN_DEATHS = [0, 10, 100, 1000, 10000];
const LIMIT = 20000;

function YearView() {
  const [year, setYear] = useState(new Date().getFullYear() - 1);
  const [span, setSpan] = useState(1);  // how many years, ending at `year`
  const [rows, setRows] = useState<EventRow[] | null>(null);
  const [off, setOff] = useState<Set<string>>(new Set(["leader"]));
  const [places, setPlaces] = useState<Place[]>([]);
  const [words, setWords] = useState("");
  const [q, setQ] = useState("");
  const [minDeaths, setMinDeaths] = useState(0);
  const [source, setSource] = useState("");
  const [sources, setSources] = useState<string[]>([]);
  const [shape, setShape] = useState<Shape>("list");
  const [measure, setMeasure] = useState<Measure>("count");
  const first = year - span + 1;
  useEffect(() => { api.eventKinds().then((k) => setSources([...new Set(k.flatMap((x) => x.sources))].sort())).catch(() => {}); }, []);
  useEffect(() => { const t = setTimeout(() => setQ(words.trim()), 300); return () => clearTimeout(t); }, [words]);
  const placeKey = places.map((p) => p.id).join(",");
  useEffect(() => {
    setRows(null);
    api.events({ start: String(first), end: String(year), entities: placeKey ? placeKey.split(",") : undefined,
      members: places.some((p) => p.group), q: q || undefined, sources: source ? [source] : undefined, limit: span > 1 ? LIMIT : undefined })
      .then(setRows).catch(() => setRows([]));
  }, [first, year, span, placeKey, q, source]); // eslint-disable-line react-hooks/exhaustive-deps
  const kept = (rows ?? []).filter((r) => !minDeaths || (r.deaths ?? 0) >= minDeaths);
  const shown = kept.filter((r) => !off.has(r.kind));
  const kinds = KINDS.filter((k) => kept.some((r) => r.kind === k.kind));
  const toggle = (k: string) => setOff((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });
  const years = Array.from({ length: span }, (_, i) => year - i);  // newest first
  const where = places.length ? ` in ${places.map((p) => p.name).join(", ")}` : "";
  const range = span > 1 ? `${first} to ${year}` : String(year);

  return (
    <div className="card">
      <div className="chips-row">
        <button onClick={() => setYear(year - span)} aria-label={span > 1 ? "Earlier years" : "Year before"}>◀</button>
        {span > 1 && <span className="muted">{first} to</span>}
        <input type="number" value={year} min={1800} max={2100} onChange={(e) => setYear(+e.target.value || year)} style={{ width: 80 }} aria-label={span > 1 ? "Last year" : "Year"} />
        <button onClick={() => setYear(year + span)} aria-label={span > 1 ? "Later years" : "Year after"}>▶</button>
        <div className="seg" role="group" aria-label="How many years">
          {[1, 5, 10, 25, 50, 100].map((n) => (
            <button key={n} className={span === n ? "on" : ""} aria-pressed={span === n} onClick={() => setSpan(n)}>{n === 1 ? "1 year" : `${n} years`}</button>
          ))}
        </div>
        <label className="muted">From <input type="number" value={first} min={1800} max={year} style={{ width: 72 }}
          onChange={(e) => { const v = +e.target.value; if (v && v <= year) setSpan(Math.min(250, year - v + 1)); }} aria-label="First year" /></label>
      </div>
      <div className="chips-row events-filters">
        <PlacePicker value={places} onChange={setPlaces} placeholder="All countries: type or pick from the list" />
        <input type="search" placeholder="Words (title, place, type)" value={words} onChange={(e) => setWords(e.target.value)} style={{ width: 200 }} aria-label="Words" />
        <label className="muted">Deaths at least{" "}
          <select value={minDeaths} onChange={(e) => setMinDeaths(+e.target.value)}>
            {MIN_DEATHS.map((n) => <option key={n} value={n}>{n ? n.toLocaleString() : "any"}</option>)}
          </select>
        </label>
        <label className="muted">Source{" "}
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">all</option>
            {sources.map((x) => <option key={x} value={x}>{SOURCE_LABEL[x] ?? x}</option>)}
          </select>
        </label>
      </div>
      <div className="chips-row">
        {kinds.map((k) => (
          <button key={k.kind} className={`chip kind ${off.has(k.kind) ? "off" : ""}`} onClick={() => toggle(k.kind)} aria-pressed={!off.has(k.kind)}
            style={{ borderColor: kindVar(k.kind) }}>
            <i style={{ background: kindVar(k.kind) }} />{k.label} <span className="muted">{kept.filter((r) => r.kind === k.kind).length}</span>
          </button>
        ))}
        {kinds.length > 1 && <>
          <button className="link" onClick={() => setOff(new Set())}>All</button>
          <button className="link" onClick={() => setOff(new Set(kinds.map((k) => k.kind)))}>None</button>
        </>}
      </div>
      <div className="chips-row">
        <div className="seg" role="group" aria-label="Show as">
          {([["list", "List"], ["timeline", "Timeline"], ["totals", "Totals by period"], ["map", "Map"]] as [Shape, string][]).map(([v, l]) => (
            <button key={v} className={shape === v ? "on" : ""} aria-pressed={shape === v} onClick={() => setShape(v)}>{l}</button>
          ))}
        </div>
        {(shape === "totals" || shape === "map") && (
          <div className="seg" role="group" aria-label="Measure">
            {MEASURES.map(([v, l]) => <button key={v} className={measure === v ? "on" : ""} aria-pressed={measure === v} onClick={() => setMeasure(v)}>{l}</button>)}
          </div>
        )}
        {rows && <span className="muted small">{shown.length.toLocaleString()} events{where}, {range}</span>}
      </div>
      {rows && rows.length >= LIMIT && <p className="small warn-text">Only the first {LIMIT.toLocaleString()} events were fetched; narrow the years, places or words to see the rest.</p>}
      {rows === null && <p className="muted">Loading…</p>}
      {rows && shown.length === 0 && <p className="muted">No events match for {range}{where}.</p>}
      {rows && shown.length > 0 && shape === "timeline" && <EventTimeline rows={shown} places={places} first={first} last={year} />}
      {rows && shown.length > 0 && shape === "totals" && <EventTotals rows={shown} measure={measure} first={first} last={year} />}
      {rows && shown.length > 0 && shape === "map" && <EventMap rows={shown} measure={measure} range={range}
        onPick={(iso, name) => { if (!places.some((p) => p.id === iso)) setPlaces([...places, { id: iso, name, group: false }]); }} />}
      {rows && shown.length > 0 && shape === "list" && (span === 1
        ? <YearBlock year={year} rows={shown} />
        : years.map((y, i) => {
          const these = inYear(shown, y);
          return (
            <details key={y} className="year-block" open={i < 3}>
              <summary><b>{y}</b> <span className="muted small">{these.length ? `${these.length} events${where}` : `no events${where}`}</span></summary>
              {these.length > 0 && <YearBlock year={y} rows={these} compact />}
            </details>
          );
        }))}
    </div>
  );
}

const measureOf = (r: EventRow, m: Measure) => (m === "count" ? 1 : m === "deaths" ? r.deaths ?? 0 : m === "affected" ? r.affected ?? 0 : r.damage_usd ?? 0);
const MEASURE_UNIT: Record<Measure, string> = { count: "events", deaths: "deaths", affected: "people affected", damage: "US$ damage" };

// A labelled timeline like a history book's: one row per place (a few places picked) or per
// kind, points for dated events and bars for those that last; names shown when few enough.
const TIMELINE_MAX = 3000;
const LABEL_MAX = 60;
function EventTimeline({ rows, places, first, last }: { rows: EventRow[]; places: Place[]; first: number; last: number }) {
  const ents = [...new Set(rows.map((r) => r.entity_id))];
  const byPlace = ents.length <= 12 && (places.length > 0 || ents.length <= 6);
  const rowOf = (r: EventRow) => (byPlace ? r.entity_name ?? r.entity_id : kindLabel(r.kind));
  const lanes = [...new Set(rows.map(rowOf))].sort();
  const few = rows.length <= LABEL_MAX;
  const option = useCallback(() => {
    const today = new Date().toISOString().slice(0, 10);
    const seen = new Map<number, number>();  // names alternate above and below within each row
    const pts = rows.map((r) => {
      const x0 = yearOf(r.start_date), x1 = yearOf(r.end_date ?? r.start_date);
      const lane = lanes.indexOf(rowOf(r));
      const k = seen.get(lane) ?? 0;
      seen.set(lane, k + 1);
      return { r, x0, x1: Math.min(x1, yearOf(today)), lane, up: k % 2 === 0 };
    });
    const spans = pts.filter((p) => p.x1 - p.x0 > 0.15);
    const dots = pts.filter((p) => p.x1 - p.x0 <= 0.15);
    const tip = (r: EventRow) => `<b>${r.entity_name ?? r.entity_id}</b>: ${r.title}<br/>${when(r)} · ${kindLabel(r.kind)}${sizeText(r) ? ` · ${sizeText(r)}` : ""}`;
    const label = (r: EventRow) => (r.title.length > 38 ? `${r.title.slice(0, 36)}…` : r.title) + (byPlace ? "" : `\n${r.entity_name ?? r.entity_id}`);
    return {
      backgroundColor: "transparent",
      textStyle: { fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif", color: cssVar("--ink-2") },
      grid: { left: 8, right: 24, top: 16, bottom: 30, containLabel: true },
      tooltip: { trigger: "item" as const, backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"), textStyle: { color: cssVar("--ink") },
        formatter: (p: unknown) => { const r = (p as { data?: { r?: EventRow } }).data?.r; return r ? tip(r) : ""; } },
      xAxis: { type: "value" as const, min: first, max: last + 1, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => String(Math.floor(v)) },
        splitLine: { lineStyle: { color: cssVar("--border") } } },
      yAxis: { type: "category" as const, data: lanes, inverse: true, axisLabel: { color: cssVar("--ink-2") },
        splitLine: { show: true, lineStyle: { color: cssVar("--border") } }, axisTick: { show: false } },
      series: [
        { type: "custom" as const, name: "lasting", data: spans.map((p) => ({ value: [p.x0, p.lane, p.x1], r: p.r, itemStyle: { color: kindColor(p.r.kind) } })),
          renderItem: (_: unknown, api: { value: (i: number) => number; coord: (v: number[]) => number[]; size: (v: number[]) => number[]; style: () => object }) => {
            const a = api.coord([api.value(0), api.value(1)]), b = api.coord([api.value(2), api.value(1)]);
            const h = Math.max(4, api.size([0, 1])[1] * 0.18);
            return { type: "rect", shape: { x: a[0], y: a[1] - h / 2, width: Math.max(2, b[0] - a[0]), height: h, r: 2 }, style: { ...api.style(), opacity: 0.55 } };
          },
          encode: { x: [0, 2], y: 1 }, z: 1 },
        { type: "scatter" as const, name: "dated", symbolSize: few ? 10 : 6, z: 2,
          data: dots.map((p) => ({ value: [p.x0, p.lane], r: p.r, itemStyle: { color: kindColor(p.r.kind) },
            label: few ? { show: true, position: p.up ? "top" : "bottom", distance: 6, formatter: label(p.r), fontSize: 10, color: cssVar("--ink-2") } : undefined })) },
      ],
      labelLayout: { hideOverlap: true },
    } as EChartsOption;
  }, [rows, lanes.join("|")]); // eslint-disable-line react-hooks/exhaustive-deps
  const open = useCallback((c: ECharts) => {
    c.on("click", (p) => { const r = (p.data as { r?: EventRow } | undefined)?.r; if (r) window.open(`/entity/${r.entity_id}#timeline`, "_self"); });
  }, []);
  if (rows.length > TIMELINE_MAX) return <p className="muted">{rows.length.toLocaleString()} events are too many to draw as a timeline; narrow the years, places or kinds (up to {TIMELINE_MAX.toLocaleString()}).</p>;
  return (
    <>
      <EChart option={option} height={Math.max(220, lanes.length * (few ? 90 : 34) + 60)} label="Timeline of events" onReady={open} />
      <p className="caption">
        One row per {byPlace ? "place" : "kind of event"}; dots are dated events, bars are ones that lasted.
        {few ? " Names show where they fit." : ` Names show when ${LABEL_MAX} or fewer events match; hover for details.`} Click one for its country&apos;s timeline.
      </p>
    </>
  );
}

// Totals per decade (or per year, for 25 years or fewer), stacked by kind: how many events,
// or their deaths, people affected or damage.
function EventTotals({ rows, measure, first, last }: { rows: EventRow[]; measure: Measure; first: number; last: number }) {
  const step = last - first + 1 > 25 ? 10 : 1;
  const start = step === 10 ? Math.floor(first / 10) * 10 : first;
  const buckets = Array.from({ length: Math.floor((last - start) / step) + 1 }, (_, i) => start + i * step);
  const kinds = KINDS.filter((k) => rows.some((r) => r.kind === k.kind && measureOf(r, measure) > 0));
  const option = useCallback(() => {
    const at = (r: EventRow) => Math.floor((+r.start_date.slice(0, 4) - start) / step);
    const series = kinds.map((k) => {
      const sums = buckets.map(() => 0);
      rows.filter((r) => r.kind === k.kind).forEach((r) => { const i = at(r); if (i >= 0 && i < sums.length) sums[i] += measureOf(r, measure); });
      return { type: "bar" as const, name: k.label, stack: "all", data: sums.map((v) => v || null), color: kindColor(k.kind), barMaxWidth: 60 };
    });
    const totals = buckets.map((_, i) => series.reduce((a, s) => a + (s.data[i] ?? 0), 0));
    return {
      backgroundColor: "transparent",
      textStyle: { fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif", color: cssVar("--ink-2") },
      legend: { top: 0, left: 0, type: "scroll" as const, data: kinds.map((k) => k.label), textStyle: { color: cssVar("--ink-2") } },
      grid: { left: 8, right: 16, top: 40, bottom: 8, containLabel: true },
      tooltip: { trigger: "axis" as const, axisPointer: { type: "shadow" as const }, backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"),
        textStyle: { color: cssVar("--ink") }, valueFormatter: (v: unknown) => (typeof v === "number" ? compact(v) : "–") },
      xAxis: { type: "category" as const, data: buckets.map((b) => (step === 10 ? `${b}s` : String(b))), axisLabel: { color: cssVar("--muted") } },
      yAxis: { type: "value" as const, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => compact(v) }, splitLine: { lineStyle: { color: cssVar("--border") } } },
      series: [...series, { type: "bar" as const, name: "Total", stack: "all", data: buckets.map(() => 0), silent: true, tooltip: { show: false },
        label: { show: true, position: "top" as const, formatter: (p: { dataIndex: number }) => (totals[p.dataIndex] ? compact(totals[p.dataIndex]) : ""), color: cssVar("--ink") } }],
    };
  }, [rows, measure, first, last]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!kinds.length) return <p className="muted">None of these events has a figure for {MEASURE_UNIT[measure]}.</p>;
  return (
    <>
      <EChart option={option} height={380} label={`Events by ${step === 10 ? "decade" : "year"}`} />
      <p className="caption">
        {MEASURE_UNIT[measure].replace(/^./, (c) => c.toUpperCase())} per {step === 10 ? "decade" : "year"} the events started in, stacked by kind.
        {measure === "damage" ? " Damage is in US dollars of the day, not adjusted for inflation (EM-DAT and Wikidata)." : ""}
        {measure !== "count" ? " Events without a figure count as nothing." : ""}
      </p>
    </>
  );
}

// The events on a world map: each country shaded by how many (or their deaths, people
// affected or damage); click a country to add it to the filter.
function EventMap({ rows, measure, range, onPick }: { rows: EventRow[]; measure: Measure; range: string; onPick: (iso: string, name: string) => void }) {
  const values = useMemo(() => {
    const sums = new Map<string, number>();
    rows.forEach((r) => sums.set(r.entity_id, (sums.get(r.entity_id) ?? 0) + measureOf(r, measure)));
    return [...sums].filter(([, v]) => v > 0).map(([entity_id, value]) => ({ entity_id, value, status: "E" }));
  }, [rows, measure]);
  const names = useMemo(() => new Map(rows.map((r) => [r.entity_id, r.entity_name ?? r.entity_id])), [rows]);
  return (
    <>
      <div className="events-map">
        <WorldMap fill values={values} unit={measure === "count" ? "events" : measure === "damage" ? "US$" : "people"} decimals={0} diverging={false}
          onPick={(iso) => onPick(iso, names.get(iso) ?? iso)} />
      </div>
      <p className="caption">
        {MEASURE_UNIT[measure].replace(/^./, (c) => c.toUpperCase())} per country, {range}, for the events that match. Click a country to add it to the filter.
        Events of groups (the EU, the world) are not on the map.
      </p>
    </>
  );
}

// Events touching a year: starting in it, or begun earlier and still going on.
function inYear(rows: EventRow[], y: number): EventRow[] {
  const lo = `${y}-01-01`, hi = `${y}-12-31`;
  return rows.filter((r) => r.start_date <= hi && (r.end_date ?? r.start_date) >= lo);
}

// One year's events: those running through the year, then the dated ones by month.
// Compact (several years shown) leaves out the empty months.
function YearBlock({ year, rows, compact }: { year: number; rows: EventRow[]; compact?: boolean }) {
  const yearStart = `${year}-01-01`;
  const through = rows.filter((r) => r.start_date < yearStart || r.precision === "year");
  const dated = rows.filter((r) => !through.includes(r));
  const months = MONTHS.map((m, i) => ({ m, items: dated.filter((r) => +r.start_date.slice(5, 7) === i + 1) }))
    .filter((x) => !compact || x.items.length);
  return (
    <>
      {through.length > 0 && (
        <details open={through.length <= (compact ? 12 : 40)}>
          <summary><b>Through the year</b> <span className="muted small">({through.length}: episodes, conflicts and anything that started earlier)</span></summary>
          <div className="cal" style={{ marginTop: 6 }}>
            <div className="month" style={{ gridColumn: "1 / -1" }}>
              {through.map((r) => <Item key={`${r.event_id}|${r.entity_id}`} r={r} day={when(r)} wide />)}
            </div>
          </div>
        </details>
      )}
      <div className="cal" style={{ marginTop: 8 }}>
        {months.map(({ m, items }) => (
          <div className="month" key={m}>
            <h4>{m} <span className="muted small">{items.length || ""}</span></h4>
            {items.map((r) => <Item key={`${r.event_id}|${r.entity_id}`} r={r} day={r.precision === "day" ? String(+r.start_date.slice(8, 10)) : ""} />)}
          </div>
        ))}
      </div>
    </>
  );
}

function Item({ r, day, wide }: { r: EventRow; day: string; wide?: boolean }) {
  const size = sizeText(r);
  return (
    <div className="item" style={wide ? { gridTemplateColumns: "11em 10px minmax(0, 1fr)" } : undefined}
      title={[kindLabel(r.kind), r.subkind, size, r.place, r.detail].filter(Boolean).join(" · ")}>
      <span className="d">{day}</span>
      <span className="tag" style={{ background: kindVar(r.kind) }} />
      <span>
        <Link href={`/entity/${r.entity_id}#timeline`}>{r.entity_name ?? r.entity_id}</Link>: {r.title}
        {size ? <span className="muted"> · {size}</span> : null}
      </span>
    </div>
  );
}

// ----------------------------------------------------------------------------- around an event
const QUICK = [
  { label: "Summer Olympics", kind: "sport", subkind: "Summer Olympic Games" },
  { label: "FIFA World Cups", kind: "sport", subkind: "FIFA World Cup" },
  { label: "Successful coups", kind: "coup", subkind: "successful" },
  { label: "Recessions", kind: "recession" },
  { label: "Wars (UCDP)", kind: "conflict" },
  { label: "Earthquakes", kind: "disaster", subkind: "earthquake" },
];

function AroundView({ event, entity }: { event: string | null; entity: string | null }) {
  const [kinds, setKinds] = useState<EventKind[]>([]);
  const [indicator, setIndicator] = useState({ id: "gdp_growth", name: "GDP growth" });
  const [pick, setPick] = useState<{ kind?: string; subkind?: string; q?: string; event?: string; entity?: string }>(
    event ? { event, entity: entity ?? undefined } : { kind: "sport", subkind: "Summer Olympic Games" });
  const [before, setBefore] = useState(5);
  const [after, setAfter] = useState(5);
  const [compare, setCompare] = useState("world");
  const [data, setData] = useState<Around | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.eventKinds().then(setKinds).catch(() => setKinds([])); }, []);
  useEffect(() => {
    setError(null);
    api.around({ indicator: indicator.id, event_id: pick.event, entity: pick.entity, kind: pick.event ? undefined : pick.kind,
      subkind: pick.event ? undefined : pick.subkind, q: pick.q, before, after, compare })
      .then(setData).catch((e) => { setData(null); setError(String(e.message || e)); });
  }, [indicator.id, pick, before, after, compare]);
  const subkinds = kinds.find((k) => k.kind === pick.kind)?.subkinds ?? [];
  const option = useCallback(() => aroundOption(data!.offsets,
    data!.events.map((e) => ({ label: `${e.entity_name ?? e.entity_id} ${e.year}: ${e.title}`, values: e.values })),
    data!.mean, data!.mean_compare, compare === "region" ? "each one's region" : compare === "income" ? "each one's income group" : compare, data!.mode === "index" ? "index" : data!.indicator.unit), [data, compare]);
  const at = (k: number) => data ? data.offsets.indexOf(k) : -1;
  const fmt = (v: number | null | undefined) => (v === null || v === undefined ? "–" : data?.mode === "index" ? v.toFixed(1) : formatValue(v, data!.indicator.unit, 1));

  return (
    <div className="card">
      <div className="chips-row">
        {QUICK.map((qk) => (
          <button key={qk.label} className="chip" aria-pressed={!pick.event && pick.kind === qk.kind && pick.subkind === qk.subkind}
            onClick={() => setPick({ kind: qk.kind, subkind: qk.subkind })}>{qk.label}</button>
        ))}
      </div>
      <div className="chips-row">
        <label className="small">Events{" "}
          <select value={pick.event ? "" : pick.kind ?? ""} onChange={(e) => setPick({ kind: e.target.value })}>
            {pick.event && <option value="">One event</option>}
            {kinds.map((k) => <option key={k.kind} value={k.kind}>{kindLabel(k.kind)} ({k.n})</option>)}
          </select>
        </label>
        {!pick.event && subkinds.length > 0 && (
          <label className="small">Type{" "}
            <select value={pick.subkind ?? ""} onChange={(e) => setPick({ ...pick, subkind: e.target.value || undefined })}>
              <option value="">All</option>
              {subkinds.map((s) => <option key={s.subkind} value={s.subkind}>{s.subkind} ({s.n})</option>)}
            </select>
          </label>
        )}
        {!pick.event && <input type="search" placeholder="Words in the title" defaultValue={pick.q}
          onKeyDown={(e) => e.key === "Enter" && setPick({ ...pick, q: (e.target as HTMLInputElement).value || undefined })} />}
        <div style={{ width: 220 }}><Search placeholder={indicator.name} kinds={["indicator"]} onPick={(h) => setIndicator({ id: h.id, name: h.name })} /></div>
        <label className="small">Years before <select value={before} onChange={(e) => setBefore(+e.target.value)}>{[3, 5, 10].map((n) => <option key={n}>{n}</option>)}</select></label>
        <label className="small">after <select value={after} onChange={(e) => setAfter(+e.target.value)}>{[3, 5, 10].map((n) => <option key={n}>{n}</option>)}</select></label>
        <label className="small">Compare with <select value={compare} onChange={(e) => setCompare(e.target.value)}>
          <option value="world">the world</option><option value="region">its own region</option><option value="income">its income group</option>
          <option value="oecd">the OECD</option><option value="none">nothing</option></select></label>
      </div>
      {error && <p className="error">{error}</p>}
      {data && (
        <>
          <h3 style={{ marginBottom: 0 }}>{data.indicator.name} around {data.n === 1 ? data.events[0].title : `${data.n} events`}</h3>
          <EChart option={option} height={340} label={`${data.indicator.name} in the years around the events`} />
          <p className="caption">
            {data.note} Each thin line is one event, year 0 being the year it started; the bold line is their average.
            An average over a handful of events is a hint, not a proof: other things happen in those years too.
          </p>
          <div className="table-scroll">
            <table className="small">
              <thead><tr><th>Event</th><th>Country</th><th className="num">Year</th><th className="num">Year before</th><th className="num">Year 0</th>
                <th className="num">+1</th><th className="num">+2</th>{compare !== "none" && <th className="num">Year 0 vs {compare === "region" ? "its region" : compare === "income" ? "its income group" : compare}</th>}</tr></thead>
              <tbody>
                {data.events.map((e) => (
                  <tr key={`${e.event_id}|${e.entity_id}`}>
                    <td>{e.title}</td><td><Link href={`/entity/${e.entity_id}#timeline`}>{e.entity_name ?? e.entity_id}</Link></td><td className="num">{e.year}</td>
                    <td className="num">{fmt(e.values[at(-1)])}</td><td className="num">{fmt(e.values[at(0)])}</td>
                    <td className="num">{fmt(e.values[at(1)])}</td><td className="num">{fmt(e.values[at(2)])}</td>
                    {compare !== "none" && <td className="num">{e.diff?.[at(0)] === null || e.diff === null ? "–" : `${e.diff[at(0)]! > 0 ? "+" : ""}${e.diff[at(0)]!.toFixed(2)}`}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

// ----------------------------------------------------------------------------- your milestones
function MineView() {
  const [items, setItems] = useState<Milestone[] | null>(null);
  const [country, setCountry] = useState<{ id: string; name: string } | null>(null);
  const load = () => api.milestones().then(setItems).catch(() => setItems([]));
  useEffect(() => { load(); }, []);
  const byCountry = useMemo(() => [...(items ?? [])].reverse(), [items]);
  return (
    <div className="card">
      <p className="ink-2" style={{ marginTop: 0 }}>
        Your own dated events: a policy change, a deal, anything you want to see on the charts. Kept only on this computer.
      </p>
      <div className="chips-row">
        <div style={{ width: 240 }}><Search placeholder={country ? country.name : "Pick a country to add one"} kinds={["entity"]}
          onPick={(h) => setCountry({ id: h.id, name: h.name })} /></div>
      </div>
      {country && <MilestoneForm entity={country.id} done={() => { setCountry(null); load(); }} />}
      {items && items.length === 0 && <p className="muted">No milestones yet.</p>}
      {byCountry.length > 0 && (
        <table className="small">
          <thead><tr><th>Date</th><th>Country</th><th>What happened</th><th>Note</th><th /></tr></thead>
          <tbody>
            {byCountry.map((m) => (
              <tr key={m.id}>
                <td>{m.start_date}{m.end_date ? ` to ${m.end_date}` : ""}</td>
                <td><Link href={`/entity/${m.entity_id}#timeline`}>{m.entity_id}</Link></td>
                <td>{m.url ? <a href={m.url} target="_blank" rel="noreferrer">{m.title}</a> : m.title}</td>
                <td className="ink-2">{m.note}</td>
                <td><button className="link" onClick={() => window.confirm(`Delete "${m.title}"?`) && api.deleteMilestone(m.id).then(load)}>Delete</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
