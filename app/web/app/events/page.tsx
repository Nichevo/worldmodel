"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import EChart from "@/components/EChart";
import Search from "@/components/Search";
import { MilestoneForm } from "@/components/Timeline";
import { api, type Around, type EventKind, type EventRow, type Milestone } from "@/lib/api";
import { aroundOption } from "@/lib/charts";
import { KINDS, kindLabel, kindVar, sizeText, when } from "@/lib/events";
import { formatValue } from "@/lib/format";

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
function YearView() {
  const [year, setYear] = useState(new Date().getFullYear() - 1);
  const [rows, setRows] = useState<EventRow[] | null>(null);
  const [off, setOff] = useState<Set<string>>(new Set(["leader"]));
  const [country, setCountry] = useState<{ id: string; name: string } | null>(null);
  useEffect(() => {
    setRows(null);
    api.events({ start: String(year), end: String(year), entities: country ? [country.id] : undefined })
      .then(setRows).catch(() => setRows([]));
  }, [year, country]);
  const shown = (rows ?? []).filter((r) => !off.has(r.kind));
  const yearStart = `${year}-01-01`;
  // Through the year: anything that started before it, or is dated only to the year.
  const through = shown.filter((r) => r.start_date < yearStart || r.precision === "year");
  const dated = shown.filter((r) => !through.includes(r));
  const kinds = KINDS.filter((k) => (rows ?? []).some((r) => r.kind === k.kind));
  const toggle = (k: string) => setOff((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });

  return (
    <div className="card">
      <div className="chips-row">
        <button onClick={() => setYear(year - 1)} aria-label="Year before">◀</button>
        <input type="number" value={year} min={1800} max={2100} onChange={(e) => setYear(+e.target.value || year)} style={{ width: 80 }} aria-label="Year" />
        <button onClick={() => setYear(year + 1)} aria-label="Year after">▶</button>
        <div style={{ width: 220 }}>
          <Search placeholder={country ? country.name : "All countries (pick one)"} kinds={["entity"]} onPick={(h) => setCountry({ id: h.id, name: h.name })} />
        </div>
        {country && <button onClick={() => setCountry(null)}>All countries</button>}
      </div>
      <div className="chips-row">
        {kinds.map((k) => (
          <button key={k.kind} className={`chip kind ${off.has(k.kind) ? "off" : ""}`} onClick={() => toggle(k.kind)} aria-pressed={!off.has(k.kind)}
            style={{ borderColor: kindVar(k.kind) }}>
            <i style={{ background: kindVar(k.kind) }} />{k.label} <span className="muted">{(rows ?? []).filter((r) => r.kind === k.kind).length}</span>
          </button>
        ))}
      </div>
      {rows === null && <p className="muted">Loading…</p>}
      {rows && shown.length === 0 && <p className="muted">No events stored for {year}{country ? ` in ${country.name}` : ""}.</p>}
      {through.length > 0 && (
        <details open={through.length <= 40}>
          <summary><b>Through the year</b> <span className="muted small">({through.length}: episodes, conflicts and anything that started earlier)</span></summary>
          <div className="cal" style={{ marginTop: 6 }}>
            <div className="month" style={{ gridColumn: "1 / -1" }}>
              {through.map((r) => <Item key={`${r.event_id}|${r.entity_id}`} r={r} day={when(r)} wide />)}
            </div>
          </div>
        </details>
      )}
      <div className="cal" style={{ marginTop: 8 }}>
        {MONTHS.map((m, i) => {
          const items = dated.filter((r) => +r.start_date.slice(5, 7) === i + 1);
          return (
            <div className="month" key={m}>
              <h4>{m} <span className="muted small">{items.length || ""}</span></h4>
              {items.map((r) => <Item key={`${r.event_id}|${r.entity_id}`} r={r} day={r.precision === "day" ? String(+r.start_date.slice(8, 10)) : ""} />)}
            </div>
          );
        })}
      </div>
    </div>
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
    data!.mean, data!.mean_compare, compare, data!.mode === "index" ? "index" : data!.indicator.unit), [data, compare]);
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
          <option value="world">the world</option><option value="none">nothing</option></select></label>
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
                <th className="num">+1</th><th className="num">+2</th>{compare !== "none" && <th className="num">Year 0 vs {compare}</th>}</tr></thead>
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
