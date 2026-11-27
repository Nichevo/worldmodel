"use client";

// The Ships and planes tables, counts and cards: on the Ships and planes page and in a map page panel.

import Link from "next/link";
import { useEffect, useState } from "react";
import { get } from "@/lib/api";
import { PLANE_GROUPS, SHIP_GROUPS } from "@/lib/mapIcons";
import { journeyLines, journeyText, planeJourney, shipJourney, shipSize, useShipStatus, type Journey, type ShipSize } from "@/lib/ships";
import SpotMap from "@/components/SpotMap";
import { mapLayersHref } from "@/lib/workspace";
import { useSettings } from "@/lib/settings";
import { ON_TIME_STATES, OnTimePill, SchedulePart, SchedulesBoard, type OnTime } from "@/components/ShipSchedule";
import type { LiveTab } from "@/lib/workspace";
import type { CameraBus } from "@/lib/camera";

// A plane's flag (from the country that issued its transponder address) and its airline's logo.
function PlaneFlag({ code, title }: { code?: string | null; title?: string | null }) {
  const [bad, setBad] = useState(false);
  if (!code || bad) return null;
  return <img className="flag" src={`/flags/${code.toLowerCase()}.svg`} width={16} height={12} alt="" title={title ?? code} onError={() => setBad(true)}
    style={{ marginRight: 4, verticalAlign: "-1px" }} />;
}
function AirlineLogo({ code, size = 18 }: { code?: string | null; size?: number }) {
  const { planes_logos: on } = useSettings();
  const [bad, setBad] = useState(false);
  if (!code || bad || on === false) return null;
  return <img src={`/api/v1/live/planes/logo/${code}`} width={size} height={size} alt="" loading="lazy" onError={() => setBad(true)}
    style={{ marginRight: 4, verticalAlign: "middle", objectFit: "contain" }} />;
}

// Ships and planes: every ship the collector has seen (saved details from aisstream.io) and the
// planes from the last OpenSky request, as tables; a row opens all its details, with where it
// came from and where it is going.
type Ship = {
  id: number; name: string | null; imo: number | null; callsign: string | null; flag: string | null; flag_code: string | null;
  kind: number | null; type: string | null; group: string; length_m: number | null; width_m: number | null; draught_m: number | null;
  destination: string | null; eta: string | null; status: string | null; speed_kn: number | null; heading: number | null;
  lat: number | null; lon: number | null; first_seen: number | null; last_seen: number | null; sanctioned?: boolean;
  links?: { label: string; href: string }[]; to_port?: { name: string | null; country: string | null; locode: string | null } | null;
  last_port?: { name: string | null; country: string | null; locode: string | null } | null; last_port_at?: number | null; from_typed?: string | null;
  from_port?: { name: string | null; country: string | null; locode: string | null } | null;
  on_time?: OnTime | null; late_h?: number | null; eta_moved_h?: number | null; estimate_at?: number | null;
};
type Airport = { name: string | null; iata: string | null; icao: string | null; city: string | null; country: string | null };
const airport = (a?: Airport | null) => (a ? `${a.city || a.name || ""}${a.iata ? ` (${a.iata})` : ""}` : "");
// A matched port as "Name, Country" (the same way for every ship, whatever its crew typed).
function PortName({ p }: { p: { name: string | null; country: string | null; locode: string | null } }) {
  const name = p.name ? p.name.replace(/\b([A-Z])([A-Z]+)\b/g, (_, a: string, b: string) => a + b.toLowerCase()) : p.locode ?? "";
  return <>{name}{p.country ? <span className="muted">, {p.country}</span> : null}</>;
}

// A country drop-down for the From / To filters: the countries in the table, most first.
function CountryPick({ value, set, list, title }: { value: string; set: (v: string) => void; list?: [string, number][]; title: string }) {
  return (
    <label title={title}>Country <select value={value} onChange={(e) => set(e.target.value)} style={{ maxWidth: 170 }}>
      <option value="">Any</option>
      {value && !(list ?? []).some(([c]) => c === value) && <option value={value}>{value}</option>}
      {(list ?? []).map(([c, k]) => <option key={c} value={c}>{c} ({n(k)})</option>)}
    </select></label>
  );
}
const airportText = (a?: Airport | null) => (a ? [a.name, a.iata, a.icao, a.city, a.country].filter(Boolean).join(" ").toLowerCase() : "");
export type Plane = {
  id: string; callsign: string | null; country: string | null; altitude_m: number | null; speed_kmh: number | null; heading: number | null;
  climb_ms: number | null; squawk: string | null; seen: number | null; category: number | null; category_name: string | null; group: string;
  lat: number; lon: number; airline?: string | null; airline_code?: string | null;
  type?: string | null; model?: string | null; reg?: string | null; flag?: string | null; military?: boolean;
  from?: Airport | null; to?: Airport | null; route_plausible?: boolean;
};

const when = (t?: number | null) => (t ? new Date(t * 1000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");
const n = (v?: number | null, d = 0) => (typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: d }) : "");
const dot = (groups: { id: string; color: string }[], g: string) => (
  <i style={{ background: groups.find((x) => x.id === g)?.color ?? "#adb5bd", display: "inline-block", width: 9, height: 9, borderRadius: 5, marginRight: 6 }} />
);

type CountRow = { key: string; label: string; count: number; share: number };
type CountPart = { id: string; title: string; rows: CountRow[]; distinct: number; counted: number };
type CountsData = { total: number; hours: number; parts: CountPart[]; moving?: number; heard_last_hour?: number; first_seen_last_day?: number;
  airline?: number; military?: number };

// Counts of ships or planes by kind, flag, airline, where from and to; a row opens the list filtered to it.
export function Counts({ what, drill, box }: { what: "ships" | "planes"; drill: (t: "ships" | "planes", f: Record<string, string>) => void; box?: string }) {
  const [hours, setHours] = useState(24);
  const [d, setD] = useState<CountsData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [shown, setShown] = useState<Record<string, number>>({}); // rows per list: 25, 100 or 0 (all)
  const [find, setFind] = useState<Record<string, string>>({});
  // Filters narrowing what is counted (the same as the lists'); typed ones apply after a pause.
  const [f, setF] = useState<Record<string, string>>({});
  const [typed, setTyped] = useState<Record<string, string>>({});
  useEffect(() => { const t = setTimeout(() => setF((c) => ({ ...c, ...typed })), 500); return () => clearTimeout(t); }, [typed]);
  const fkey = JSON.stringify(f);
  // The options of the drop-downs: the kinds, flags and airlines counted with no filter on.
  const [opts, setOpts] = useState<CountsData | null>(null);
  useEffect(() => {
    let live = true;
    setErr(null);
    const load = () => get<CountsData>(`/live/${what}/stats`, { hours, top: 0, ...f, box: box || undefined }).then((x) => {
      if (!live) return;
      setD(x);
      if (!Object.values(f).some(Boolean)) setOpts(x);
    }).catch((e) => live && setErr(String(e.message ?? e)));
    load();
    const t = setInterval(() => { if (!document.hidden) load(); }, 120_000);
    return () => { live = false; clearInterval(t); };
  }, [what, hours, fkey, box]); // eslint-disable-line react-hooks/exhaustive-deps
  const optRows = (id: string) => (opts ?? d)?.parts.find((p) => p.id === id)?.rows ?? [];
  const pick = (k: string, v: string) => setF((c) => ({ ...c, [k]: v }));
  const type = (k: string, v: string) => setTyped((c) => ({ ...c, [k]: v }));
  const anyFilter = Object.values({ ...f, ...typed }).some(Boolean);
  const groups = what === "ships" ? SHIP_GROUPS : PLANE_GROUPS;
  const label = (part: CountPart, r: CountRow) => (part.id === "group" ? groups.find((g) => g.id === r.key)?.label ?? r.key : r.label);
  const place = (k: string) => k.split(",")[0].trim();
  const filterFor = (part: CountPart, r: CountRow): Record<string, string> | null => {
    if (r.key === "?" || r.label.startsWith("No airline") || r.key.startsWith("Not ")) return part.id === "airline" ? { airline: "-" } : null;
    if (what === "ships") {
      return ({ group: { group: r.key }, flag: { q: r.label }, came_from: { came: place(r.key) }, came_country: { came: r.key },
        going_to: { to: place(r.key) }, going_country: { to: r.key } } as Record<string, Record<string, string>>)[part.id] ?? null;
    }
    if (part.id === "route") {
      const [a, b] = r.key.split(" to ");
      return { from: place(a), to: place(b ?? "") };
    }
    return ({ group: { group: r.key }, airline: { airline: r.key }, flag: { q: r.label }, from: { from: place(r.key) }, to: { to: place(r.key) },
      model: { q: r.key } } as Record<string, Record<string, string>>)[part.id] ?? null;
  };
  const windows = what === "ships"
    ? [[1, "Heard in the last hour"], [24, "Last day"], [168, "Last 7 days"], [0, "Every ship kept"]]
    : [[1, "Heard in the last hour"], [6, "Last 6 hours"], [24, "Last day"], [168, "Last 7 days"]];
  return (
    <section className="card">
      <div className="table-tools small">
        <label>Count <select value={hours} onChange={(e) => setHours(+e.target.value)}>
          {windows.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select></label>
        <label>Kind <select value={f.group ?? ""} onChange={(e) => pick("group", e.target.value)}>
          <option value="">All</option>{groups.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
        </select></label>
        <label>{what === "ships" ? "Flag" : "Country"} <select value={f.flag ?? ""} onChange={(e) => pick("flag", e.target.value)} style={{ maxWidth: 180 }}>
          <option value="">All</option>{optRows("flag").filter((r) => r.key.length === 2).map((r) => <option key={r.key} value={r.key}>{r.label} ({n(r.count)})</option>)}
        </select></label>
        {what === "planes" && <label>Airline <select value={f.airline ?? ""} onChange={(e) => pick("airline", e.target.value)} style={{ maxWidth: 200 }}>
          <option value="">All</option><option value="-">No airline</option>
          {optRows("airline").filter((r) => !r.key.startsWith("No airline")).map((r) => <option key={r.key} value={r.key}>{r.label} ({n(r.count)})</option>)}
        </select></label>}
        <label>{what === "ships" ? "Came from" : "From"} <input value={typed[what === "ships" ? "came" : "from"] ?? ""} placeholder="Port, airport, city, country"
          onChange={(e) => type(what === "ships" ? "came" : "from", e.target.value)} style={{ width: 140 }} /></label>
        <label>{what === "ships" ? "Going to" : "To"} <input value={typed.to ?? ""} placeholder="Port, airport, city, country"
          onChange={(e) => type("to", e.target.value)} style={{ width: 140 }} /></label>
        <label>Find <input value={typed.q ?? ""} placeholder={what === "ships" ? "Name, MMSI, IMO, destination" : "Callsign, registration, model"}
          onChange={(e) => type("q", e.target.value)} style={{ width: 150 }} /></label>
        {anyFilter && <button className="link small" onClick={() => { setF({}); setTyped({}); }}>Clear filters</button>}
        {d && <span className="muted">
          {what === "ships"
            ? `${n(d.total)} ships; ${n(d.moving ?? 0)} moving, ${n(d.heard_last_hour ?? 0)} heard in the last hour, ${n(d.first_seen_last_day ?? 0)} first seen in the last day`
            : `${n(d.total)} planes; ${n(d.airline ?? 0)} on airline flights, ${n(d.military ?? 0)} military`}
        </span>}
      </div>
      {err && <p className="small" style={{ color: "#c92a2a" }}>{err}</p>}
      {!d ? <p className="small muted">Counting…</p> : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 16 }}>
          {d.parts.map((part) => {
            const top = Math.max(1, ...part.rows.map((r) => r.count));
            const want = shown[part.id] ?? 25;
            const fl = (find[part.id] ?? "").trim().toLowerCase();
            const matching = fl ? part.rows.filter((r) => label(part, r).toLowerCase().includes(fl)) : part.rows;
            const rows = want ? matching.slice(0, want) : matching;
            return (
              <div key={part.id}>
                <h3 className="small" style={{ margin: "4px 0" }}>{part.title}</h3>
                {part.rows.length > 25 && want !== 25 && (
                  <input className="small" placeholder={`Find in ${n(part.rows.length)}`} value={find[part.id] ?? ""} style={{ width: "100%", marginBottom: 4 }}
                    onChange={(e) => setFind((c) => ({ ...c, [part.id]: e.target.value }))} />)}
                {!part.rows.length ? <p className="small muted">Nothing known yet.</p> : (
                  <div style={{ maxHeight: want === 25 ? undefined : 480, overflowY: want === 25 ? undefined : "auto" }}>
                  <table className="small" style={{ width: "100%" }}>
                    <tbody>{rows.map((r) => {
                      const f = filterFor(part, r);
                      const text = label(part, r);
                      return (
                        <tr key={r.key} onClick={f ? () => drill(what, f) : undefined} style={{ cursor: f ? "pointer" : undefined }}
                          title={f ? `Show these ${what} in the list` : undefined}>
                          <td style={{ maxWidth: 170, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {part.id === "group" && dot(groups, r.key)}
                            {part.id === "flag" && r.key.length === 2 && <PlaneFlag code={r.key} title={r.label} />}
                            {what === "planes" && part.id === "airline" && <AirlineLogo code={airlineCode(d, r.key)} size={14} />}
                            {text}</td>
                          <td style={{ width: 90 }}><div style={{ height: 8, width: `${(r.count / top) * 100}%`, background: "var(--series-1, #1864ab)", borderRadius: 2 }} /></td>
                          <td style={{ textAlign: "right" }}>{n(r.count)}</td>
                          <td className="muted" style={{ textAlign: "right" }}>{(r.share * 100).toFixed(r.share < 0.01 ? 1 : 0)}%</td>
                        </tr>);
                    })}</tbody>
                  </table>
                  </div>)}
                {part.rows.length > 25 && (
                  <p className="caption">{want && rows.length < matching.length ? `Top ${n(rows.length)} of ${n(matching.length)}. ` : `All ${n(matching.length)}. `}
                    {want === 25 && <button className="link small" onClick={() => setShown((c) => ({ ...c, [part.id]: 100 }))}>Show 100</button>}
                    {want !== 0 && <> <button className="link small" onClick={() => setShown((c) => ({ ...c, [part.id]: 0 }))}>Show all</button></>}
                    {want !== 25 && <> <button className="link small" onClick={() => { setShown((c) => ({ ...c, [part.id]: 25 })); setFind((c) => ({ ...c, [part.id]: "" })); }}>Show top 25</button></>}
                  </p>)}
              </div>);
          })}
        </div>)}
      <p className="caption">Counted from the same ships and planes as the lists (saved while collecting is on, Settings &gt; Transport). Click a row to list them.</p>
    </section>
  );
}
const airlineCode = (d: CountsData, name: string) => (d as CountsData & { airline_codes?: Record<string, string> }).airline_codes?.[name] ?? null;

type SweepLog = {
  rows: { start: number; end: number; what: string; outcome: string; minutes: number; reports: number; new_ships: number | null; why: string | null }[];
  days: number; totals: { sweeps: number; finished: number; cut_short: number; reports: number; new_ships: number; drops: number };
};

// Each whole-world snapshot and each dropped aisstream connection (var\live\ships\sweeps.csv).
export function Sweeps() {
  const [days, setDays] = useState(7);
  const [d, setD] = useState<SweepLog | null>(null);
  useEffect(() => {
    let live = true;
    const load = () => get<SweepLog>("/live/ships/sweeps", { days }).then((x) => live && setD(x)).catch(() => {});
    load();
    const t = setInterval(() => { if (!document.hidden) load(); }, 120_000);
    return () => { live = false; clearInterval(t); };
  }, [days]);
  if (!d) return null;
  const t = d.totals;
  return (
    <section className="card">
      <details>
        <summary><b>World sweeps and dropped connections</b> <span className="small muted">
          last {days} days: {n(t.sweeps)} sweeps ({n(t.finished)} finished, {n(t.cut_short)} cut short), {n(t.reports)} reports,
          {" "}{n(t.new_ships)} ships not seen before; {n(t.drops)} dropped connections</span></summary>
        <div className="table-tools small">
          <label>Show <select value={days} onChange={(e) => setDays(+e.target.value)}>
            <option value={1}>Last day</option><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option>
          </select></label>
        </div>
        {d.rows.length ? (
          <div style={{ overflowX: "auto" }}>
            <table className="small">
              <thead><tr><th>Started</th><th>What</th><th>Outcome</th><th>Minutes</th><th>Reports</th><th>New ships</th><th>Why</th></tr></thead>
              <tbody>{d.rows.map((r) => (
                <tr key={`${r.what}${r.start}${r.end}`}>
                  <td>{new Date(r.start * 1000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</td>
                  <td>{r.what === "sweep" ? "Whole-world sweep" : "Connection"}</td>
                  <td style={{ color: r.outcome === "finished" ? undefined : "#c92a2a" }}>{r.outcome}</td>
                  <td>{r.minutes}</td><td>{n(r.reports)}</td><td>{r.new_ships == null ? "" : n(r.new_ships)}</td>
                  <td className="muted">{r.why ?? ""}</td>
                </tr>))}
              </tbody>
            </table>
          </div>
        ) : <p className="small muted">Nothing logged yet. Sweeps run with &quot;Save ships&quot; on and the South Pacific area (Settings &gt; Transport).</p>}
      </details>
    </section>
  );
}

export function Ships({ open, setOpen, init, box }: { open: string | null; setOpen: (id: string | null) => void; init: (k: string) => string; box?: string }) {
  const [q, setQ] = useState(init("q"));
  const [group, setGroup] = useState(init("group"));
  const [hours, setHours] = useState(0);
  const [to, setTo] = useState(init("to"));
  const [came, setCame] = useState(init("came"));
  const [fromC, setFromC] = useState(init("from_country"));
  const [toC, setToC] = useState(init("to_country"));
  const [ontime, setOntime] = useState(init("ontime"));
  const [sort, setSort] = useState("last_seen");
  const [limit, setLimit] = useState(200);
  const [d, setD] = useState<{ rows: Ship[]; total: number; groups: Record<string, number>; collecting: boolean;
    countries?: { from: [string, number][]; to: [string, number][] } } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const st = useShipStatus(true);
  useEffect(() => {
    let live = true;
    const qs = new URLSearchParams({ q, group, sort, limit: String(limit), hours: String(hours), to, came, ontime, from_country: fromC, to_country: toC, box: box ?? "" });
    const t = setTimeout(() => get<typeof d>(`/live/ships/table?${qs}`).then((x) => live && setD(x)).catch((e) => live && setErr(String(e.message ?? e))), 250);
    return () => { live = false; clearTimeout(t); };
  }, [q, group, sort, limit, hours, to, came, ontime, fromC, toC, box]);
  if (err) return <p className="error">{err}</p>;
  const head = (key: string, label: string) => (
    <th><button className="link small" onClick={() => setSort(sort === key ? `-${key}` : key)}>{label}{sort.replace("-", "") === key ? (sort.startsWith("-") ? " ▲" : " ▼") : ""}</button></th>
  );
  return (
    <section className="card">
      <p className="caption">
        {st?.collecting
          ? <>Every ship seen while collecting for {st.area}{st.world_every_hours ? ` (and the world every ${st.world_every_hours} hours)` : ""}, kept {st.keep_days} days.
            Names, types, sizes and destinations are what each ship&apos;s crew set in its AIS radio; the flag comes from its MMSI number.</>
          : <>Ships are not being saved, so this lists only those the map has seen in the last 20 minutes. Turn on Collect ships in <Link href="/settings#transport">Settings</Link>.</>}
      </p>
      <div className="table-tools small">
        <label>Find <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, MMSI, IMO, call sign, port, flag" style={{ width: 260 }} /></label>
        <label>Kind <select value={group} onChange={(e) => setGroup(e.target.value)}>
          <option value="">All ({n(d ? Object.values(d.groups).reduce((a, b) => a + b, 0) : 0)})</option>
          {SHIP_GROUPS.map((g) => <option key={g.id} value={g.id}>{g.label}{d?.groups[g.id] ? ` (${n(d.groups[g.id])})` : ""}</option>)}
        </select></label>
        <label>Came from <input value={came} onChange={(e) => setCame(e.target.value)} placeholder="Port or code" style={{ width: 120 }} /></label>
        <CountryPick value={fromC} set={setFromC} list={d?.countries?.from} title="The country of the port it came from" />
        <label>Going to <input value={to} onChange={(e) => setTo(e.target.value)} placeholder="Port or code" style={{ width: 120 }} /></label>
        <CountryPick value={toC} set={setToC} list={d?.countries?.to} title="The country of the port its destination names" />
        <label title="Cargo and container ships: against the line's schedule, the port's booking or the ship's own first ETA">On time? <select value={ontime} onChange={(e) => setOntime(e.target.value)}>
          <option value="">All</option><option value="any">Cargo ships with a measure</option>
          {ON_TIME_STATES.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select></label>
        <label>Seen <select value={hours} onChange={(e) => setHours(+e.target.value)}>
          <option value={0}>Any time</option><option value={0.25}>In the last 15 minutes</option><option value={1}>In the last hour</option><option value={24}>In the last day</option><option value={168}>In the last week</option>
        </select></label>
        <span className="muted">{d ? `${n(d.total)} ships` : "Loading…"}</span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="small">
          <thead><tr>{head("name", "Name")}{head("type", "Kind")}{head("flag", "Flag")}{head("length_m", "Length")}{head("speed_kn", "Speed")}
            <th title="The last port the ship was seen stopped at (while collecting), or the FROM of a destination typed as FROM>TO">Came from</th>
            {head("destination", "Going to")}<th title="Cargo ships: within a day of the line's schedule, the port's booking or the ship's own first ETA">On time?</th><th>Doing</th>{head("last_seen", "Last seen")}</tr></thead>
          <tbody>
            {(d?.rows ?? []).map((r) => (
              <tr key={r.id} onClick={() => setOpen(String(r.id))} style={{ cursor: "pointer" }} className={open === String(r.id) ? "selected" : undefined}>
                <td>{dot(SHIP_GROUPS, r.group)}{r.name ?? <span className="muted">MMSI {r.id}</span>}{r.sanctioned ? <b style={{ color: "#c92a2a" }}> sanctioned</b> : null}</td>
                <td>{r.type ?? <span className="muted">not said</span>}</td>
                <td>{r.flag ?? ""}</td>
                <td>{r.length_m ? `${r.length_m} m` : ""}</td>
                <td>{typeof r.speed_kn === "number" ? `${r.speed_kn} kn` : ""}</td>
                <td>{r.last_port ? <><PortName p={r.last_port} /><span className="muted"> {when(r.last_port_at)}</span></>
                  : r.from_port ? <span title={`Typed: ${r.from_typed}`}><PortName p={r.from_port} /></span>
                  : r.from_typed ? <span className="muted" title="As the crew typed it; not matched to a port">{r.from_typed}</span> : ""}</td>
                <td>{r.to_port ? <span title={r.destination ? `Typed: ${r.destination}` : undefined}><PortName p={r.to_port} /></span>
                  : r.destination ? <span className="muted" title="As the crew typed it; not matched to a port">{r.destination}</span> : ""}</td>
                <td><OnTimePill state={r.on_time} late={r.late_h} /></td>
                <td>{r.status ?? ""}</td>
                <td>{when(r.last_seen)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {d && d.total > limit && <button className="small" onClick={() => setLimit(limit + 500)}>Show more ({n(d.total - limit)} not shown)</button>}
      {open && <ShipCard id={open} onClose={() => setOpen(null)} />}
    </section>
  );
}

export function ShipCard({ id, onClose }: { id: string; onClose: () => void }) {
  const [s, setS] = useState<Ship | null>(null);
  const [j, setJ] = useState<Journey | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    get<Ship>(`/live/ships/detail/${encodeURIComponent(id)}`).then((x) => live && setS(x)).catch((e) => live && setErr(String(e.message ?? e)));
    shipJourney(id).then((x) => live && setJ(x)).catch(() => {});
    return () => { live = false; };
  }, [id]);
  const rows: [string, React.ReactNode][] = s ? [
    ["MMSI", s.id], ["IMO", s.imo ?? ""], ["Call sign", s.callsign ?? ""], ["Flag", s.flag ? `${s.flag} (${s.flag_code})` : ""],
    ["Kind", s.type ? `${s.type}${s.kind ? ` (AIS type ${s.kind})` : ""}` : "Not said yet"],
    ["Size", s.length_m ? `${s.length_m} m long, ${s.width_m ?? "?"} m wide` : ""], ["Draught", s.draught_m ? `${s.draught_m} m` : ""],
    ["Doing", s.status ?? ""], ["Speed", typeof s.speed_kn === "number" ? `${s.speed_kn} knots, heading ${n(s.heading)}°` : ""],
    ["Where", s.lat != null && s.lon != null ? `${s.lat.toFixed(3)}, ${s.lon.toFixed(3)}` : ""],
    ["Came from", s.last_port ? `${[s.last_port.name, s.last_port.country].filter(Boolean).join(", ")} (stopped there ${when(s.last_port_at)})` : s.from_typed ?? ""],
    ["Going to", [s.destination, s.eta ? `due ${s.eta}` : ""].filter(Boolean).join(", ")],
    ["First seen", when(s.first_seen)], ["Last seen", when(s.last_seen)],
  ] : [];
  return (
    <div className="find-big-back" onClick={onClose}>
      <div className="find-big card" role="dialog" aria-modal="true" aria-label={s?.name ?? `Ship ${id}`} style={{ maxWidth: 560 }} onClick={(e) => e.stopPropagation()}>
        <div className="row"><h2 style={{ margin: 0 }}>{s?.name ?? `Ship ${id}`}</h2><span className="spacer" /><button className="link" onClick={onClose} aria-label="Close">×</button></div>
        {err ? <p className="error">{err}</p> : !s ? <p className="muted">Loading…</p> : (
          <>
            {s.sanctioned && <p><b style={{ color: "#c92a2a" }}>On a sanctions list</b> (OpenSanctions); see <Link href="/sanctions">Sanctions now</Link>.</p>}
            {s.lat != null && s.lon != null && <SpotMap lon={s.lon} lat={s.lat} label={s.name ?? undefined}
              lines={j ? journeyLines(j, { lng: s.lon, lat: s.lat }, false) : null} />}
            <table className="small"><tbody>{rows.filter(([, v]) => v !== "" && v != null).map(([k, v]) => <tr key={k}><th style={{ textAlign: "left", paddingRight: 12 }}>{k}</th><td>{v}</td></tr>)}</tbody></table>
            <h3 className="small" style={{ marginBottom: 2 }}>Where from and to</h3>
            {j ? journeyText(j, false).map((l) => <p key={l} className="small" style={{ margin: "2px 0" }}>{l}</p>) : <p className="small muted">Loading…</p>}
            <SizePart id={id} />
            {s.group === "cargo" && <SchedulePart id={id} />}
            <OwnerPart id={id} />
            <p className="small"><Link href={mapLayersHref("S")}>Ships on the map</Link> (click the ship there to draw its path)
              {(s.links ?? []).map((l) => <span key={l.href}> · <a href={l.href} target="_blank" rel="noreferrer">{l.label}</a></span>)}</p>
          </>
        )}
      </div>
    </div>
  );
}

// Containers (TEU) and which canals, straits and its next port the ship is too big for.
function SizePart({ id }: { id: string }) {
  const [z, setZ] = useState<ShipSize | null>(null);
  useEffect(() => {
    let live = true;
    shipSize(id).then((x) => live && setZ(x)).catch(() => {});
    return () => { live = false; };
  }, [id]);
  if (!z) return null;
  const t = z.teu;
  const mark = (ok: boolean | null) => (ok === false ? <b style={{ color: "#c92a2a" }}>Too big</b> : ok ? "Fits" : <span className="muted">Can&apos;t tell</span>);
  const lim = (l: { length: number | null; beam: number | null; draught: number | null }) =>
    [l.length ? `${l.length} m long` : "", l.beam ? `${l.beam} m wide` : "", l.draught ? `${l.draught} m draught` : ""].filter(Boolean).join(", ");
  return (
    <>
      <h3 className="small" style={{ marginBottom: 2 }}>Containers and where it fits</h3>
      {t ? <p className="small" style={{ margin: "2px 0" }}>{t.estimated
        ? <>About <b>{t.teu.toLocaleString()} TEU</b>{t.container ? "" : " if it carries containers"}, estimated from its length and beam (about 20% either way; exact figures can be added in var\manual\ship_teu as a CSV of IMO and TEU).</>
        : <><b>{t.teu.toLocaleString()} TEU</b> ({t.source}).</>}</p>
        : <p className="small muted" style={{ margin: "2px 0" }}>Containers: not known (it has not sent its size, or it is not a container ship&apos;s shape).</p>}
      <table className="small"><tbody>
        {z.canals.map((c) => (
          <tr key={c.id} title={`${c.note}. Source: ${c.source}`}>
            <th style={{ textAlign: "left", paddingRight: 12, fontWeight: "normal" }}>{c.name}</th>
            <td style={{ paddingRight: 8 }}>{mark(c.ok)}</td>
            <td className="muted">{c.why.length ? c.why.join("; ") : lim(c.limits)}</td>
          </tr>
        ))}
        {z.port && (
          <tr title={`${z.port.note}. Source: ${z.port.source}`}>
            <th style={{ textAlign: "left", paddingRight: 12, fontWeight: "normal" }}>Next port: {z.port.name}</th>
            <td style={{ paddingRight: 8 }}>{mark(z.port.ok)}</td>
            <td className="muted">{z.port.why.length ? z.port.why.join("; ") : z.port.checked ? lim(z.port.limits) : z.port.note}</td>
          </tr>
        )}
      </tbody></table>
      <p className="caption">Draught is how deep it sits now{z.full_draught_m ? ` (${z.full_draught_m} m when full, from Wikidata)` : ""}; a part-loaded ship sits higher than when full. Port limits are from NGA&apos;s World Port Index and can be old.</p>
    </>
  );
}

type Owner = {
  imo: string | null; notes: string[];
  gfw: null | { error?: string; none?: boolean; name?: string | null; flag?: string | null; built?: number | string; gear?: string; tonnage_gt?: number; link?: string | null;
    owners?: { name: string; flag?: string; from?: string; to?: string }[]; flags?: { flag: string; from?: string; to?: string }[];
    authorisations?: { by?: string; from?: string; to?: string }[] };
  wikidata: null | { error?: string; none?: boolean; builder?: string[]; operator?: string[]; owner?: string[]; class?: string | null;
    launched?: string | null; entered_service?: string | null; image?: string | null; wikipedia?: string | null; link?: string | null };
  equasis: null | { href: string; how: string };
  photos?: { thumb: string; page?: string | null; title?: string; author?: string | null; licence?: string | null; date?: string | null }[] | null;
};

// Who owns, runs and built the ship (Settings > Transport picks the sources).
function OwnerPart({ id }: { id: string }) {
  const [o, setO] = useState<Owner | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    get<Owner>(`/live/ships/owner/${encodeURIComponent(id)}`).then((x) => live && setO(x)).catch((e) => live && setErr(String(e.message ?? e)));
    return () => { live = false; };
  }, [id]);
  if (err) return null;
  if (!o) return <><h3 className="small" style={{ marginBottom: 2 }}>Owner and builder</h3><p className="small muted">Asking Global Fishing Watch and Wikidata…</p></>;
  const span = (a?: string, b?: string) => (a || b ? ` (${a ?? "?"} to ${b ?? "now"})` : "");
  const g = o.gfw, w = o.wikidata;
  const lines: React.ReactNode[] = [];
  if (w && !w.error && !w.none) {
    if (w.builder?.length) lines.push(<>Built by {w.builder.join(", ")}{w.launched ? `, launched ${w.launched}` : ""}</>);
    else if (w.launched) lines.push(<>Launched {w.launched}</>);
    if (w.owner?.length) lines.push(<>Owner: {w.owner.join(", ")}</>);
    if (w.operator?.length) lines.push(<>Operator: {w.operator.join(", ")}</>);
    if (w.class) lines.push(<>Class: {w.class}</>);
  }
  if (g && !g.error && !g.none) {
    const since = (g.flags ?? [])[0]?.from;
    lines.push(<>Global Fishing Watch knows it as <b>{g.name ?? "(no name)"}</b>{g.flag || g.flags?.length ? `, flag ${g.flag ?? g.flags![g.flags!.length - 1].flag}` : ""}
      {since ? `, broadcasting since ${since.slice(0, 7)}` : ""}{!(g.owners ?? []).length ? "; no public registry or owner record" : ""}</>);
    for (const ow of (g.owners ?? []).slice(0, 4)) lines.push(<>Registered owner: {ow.name}{ow.flag ? ` [${ow.flag}]` : ""}{span(ow.from, ow.to)}</>);
    if (g.built && !(w && w.launched)) lines.push(<>Built {g.built}</>);
    if (g.gear) lines.push(<>Gear: {g.gear}</>);
    if ((g.flags ?? []).length > 1) lines.push(<>Flags over time: {g.flags!.map((f) => `${f.flag}${f.from ? ` from ${f.from.slice(0, 4)}` : ""}`).join(", ")}</>);
    if ((g.authorisations ?? []).length) lines.push(<>Authorised by: {[...new Set(g.authorisations!.map((a) => a.by).filter(Boolean))].join(", ")}</>);
  }
  const said: string[] = [];
  if (g?.none) said.push("Global Fishing Watch does not know this ship");
  if (g?.error) said.push(`Global Fishing Watch: ${g.error}`);
  if (w?.none) said.push("Wikidata has no ship with this IMO number");
  if (w?.error) said.push(`Wikidata ${w.error}`);
  if (!g && !w && !o.equasis && !o.notes.length) return null;
  return (
    <>
      <h3 className="small" style={{ marginBottom: 2 }}>Owner and builder</h3>
      {w?.image && !o.photos?.length && <img src={`${w.image.replace("http://", "https://")}?width=300`} alt="" style={{ maxWidth: 300, maxHeight: 160, display: "block", margin: "4px 0" }} />}
      {!!o.photos?.length && (
        <div style={{ display: "flex", gap: 6, overflowX: "auto", margin: "4px 0" }}>
          {o.photos.map((ph) => (
            <figure key={ph.thumb} style={{ margin: 0, flex: "0 0 auto", maxWidth: 200 }}>
              <a href={ph.page ?? ph.thumb} target="_blank" rel="noreferrer"><img src={ph.thumb} alt={ph.title ?? ""} loading="lazy" style={{ height: 110, display: "block" }} /></a>
              <figcaption className="caption" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                title={[ph.author, ph.licence, ph.date].filter(Boolean).join(", ")}>
                {[ph.date?.slice(0, 4), ph.author, ph.licence].filter(Boolean).join(" · ") || "Wikimedia Commons"}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
      {lines.map((l, i) => <p key={i} className="small" style={{ margin: "2px 0" }}>{l}</p>)}
      {!lines.length && <p className="small muted" style={{ margin: "2px 0" }}>Nothing found in the free sources.</p>}
      {[...said.map((t) => `${t}.`), ...o.notes].map((t) => <p key={t} className="caption" style={{ margin: "2px 0" }}>{t}</p>)}
      <p className="small" style={{ margin: "2px 0" }}>
        {[g?.link && <a key="g" href={g.link} target="_blank" rel="noreferrer">Global Fishing Watch</a>,
          w?.wikipedia && <a key="wp" href={w.wikipedia} target="_blank" rel="noreferrer">Wikipedia</a>,
          w?.link && <a key="w" href={w.link} target="_blank" rel="noreferrer">Wikidata</a>,
          o.imo && !!o.photos?.length && <a key="c" href={`https://commons.wikimedia.org/wiki/Category:IMO_${o.imo}`} target="_blank" rel="noreferrer">All photos (Commons)</a>,
          o.equasis && <span key="e"><a href={o.equasis.href} target="_blank" rel="noreferrer">Equasis</a> <span className="muted">({o.equasis.how})</span></span>]
          .filter(Boolean).flatMap((x, i) => (i ? [" · ", x] : [x]))}
      </p>
    </>
  );
}

// The planes table is worked out on the server (a day of planes is thousands of rows): the filters
// and sort are sent with each ask, and a page of rows comes back with how many matched.
const PLANES_PAGE = 500;

export function Planes({ open, setOpen, init, box }: { open: string | null; setOpen: (id: string | null) => void; init: (k: string) => string; box?: string }) {
  type Answer = { planes: Plane[]; at: number | null; note: string; route_note?: string | null; total?: number; all?: number; airlines?: [string, number][];
    countries?: { from: [string, number][]; to: [string, number][] } };
  const [d, setD] = useState<Answer | null>(null);
  const [q, setQ] = useState(init("q"));
  const [group, setGroup] = useState(init("group"));
  const [line, setLine] = useState(init("airline"));
  const [from, setFrom] = useState(init("from"));
  const [to, setTo] = useState(init("to"));
  const [fromC, setFromC] = useState(init("from_country"));
  const [toC, setToC] = useState(init("to_country"));
  const [mins, setMins] = useState(0);
  const [sort, setSort] = useState<keyof Plane>("altitude_m");
  const [more, setMore] = useState(1);
  // Typing waits a moment before asking; the list is asked again every minute while the page is in view.
  const [typed, setTyped] = useState({ q, from, to });
  useEffect(() => {
    const t = setTimeout(() => setTyped({ q, from, to }), 350);
    return () => clearTimeout(t);
  }, [q, from, to]);
  useEffect(() => setMore(1), [typed, group, line, mins, sort, fromC, toC]);
  useEffect(() => {
    let live = true;
    const load = () => get<Answer>("/live/planes/table", { hours: 24, q: typed.q.trim(), group, airline: line, from: typed.from.trim(), to: typed.to.trim(),
      from_country: fromC || undefined, to_country: toC || undefined, mins: mins || undefined, sort: String(sort), limit: PLANES_PAGE * more, box: box || undefined }).then((x) => live && setD(x)).catch(() => {});
    load();
    const t = setInterval(() => { if (!document.hidden) load(); }, 60_000);
    const back = () => { if (!document.hidden) load(); };
    document.addEventListener("visibilitychange", back);
    return () => { live = false; clearInterval(t); document.removeEventListener("visibilitychange", back); };
  }, [typed, group, line, mins, sort, more, fromC, toC, box]);
  const rows = d?.planes ?? [];
  const airlines = d?.airlines ?? [];
  const picked = rows.find((p) => p.id === open);
  const head = (key: keyof Plane, label: string) => <th><button className="link small" onClick={() => setSort(key)}>{label}{sort === key ? " ▼" : ""}</button></th>;
  return (
    <section className="card">
      <p className="caption">{d?.note ?? "Loading…"} {d?.at ? `Read ${when(d.at)}.` : ""} {d?.route_note ?? ""} Turn on Planes now on <Link href={mapLayersHref("F")}>the map</Link> and move it to where you want planes listed.</p>
      <div className="table-tools small">
        <label>Find <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Callsign, registration, model, airline" /></label>
        <label>Type <select value={group} onChange={(e) => setGroup(e.target.value)}>
          <option value="">All</option>{PLANE_GROUPS.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
        </select></label>
        <label>Airline <select value={line} onChange={(e) => setLine(e.target.value)} style={{ maxWidth: 220 }}>
          <option value="">All</option><option value="-">No airline (private, military, other)</option>
          {airlines.map(([a, k]) => <option key={a} value={a}>{a} ({n(k)})</option>)}
        </select></label>
        <label>From <input value={from} onChange={(e) => setFrom(e.target.value)} placeholder="Airport, code or city" style={{ width: 130 }} /></label>
        <CountryPick value={fromC} set={setFromC} list={d?.countries?.from} title="The country of the airport it took off from" />
        <label>To <input value={to} onChange={(e) => setTo(e.target.value)} placeholder="Airport, code or city" style={{ width: 130 }} /></label>
        <CountryPick value={toC} set={setToC} list={d?.countries?.to} title="The country of the airport it is flying to" />
        <label>Seen <select value={mins} onChange={(e) => setMins(+e.target.value)}>
          <option value={0}>In the last day</option><option value={10}>In the last 10 minutes</option><option value={60}>In the last hour</option><option value={360}>In the last 6 hours</option>
        </select></label>
        <span className="muted">{n(d?.total ?? rows.length)} planes{d?.all !== undefined && d.all !== d.total ? ` of ${n(d.all)}` : ""}</span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="small">
          <thead><tr>{head("callsign", "Callsign")}{head("airline", "Airline")}<th>From</th><th>To</th>{head("model", "Aircraft")}{head("reg", "Registration")}{head("country", "Registered in")}{head("altitude_m", "Height")}
            {head("speed_kmh", "Speed")}{head("climb_ms", "Climbing")}{head("squawk", "Squawk")}{head("seen", "Last heard")}</tr></thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id} onClick={() => setOpen(p.id)} style={{ cursor: "pointer" }} className={open === p.id ? "selected" : undefined}>
                <td>{dot(PLANE_GROUPS, p.group)}{p.callsign ?? <span className="muted">{p.id}</span>}</td>
                <td><AirlineLogo code={p.airline ? p.airline_code : null} />{p.airline ?? ""}</td>
                <td title={p.from?.name ?? undefined}>{airport(p.from)}{p.from?.country ? <span className="muted"> {p.from.country}</span> : null}</td>
                <td title={p.to?.name ?? undefined}>{airport(p.to)}{p.to?.country ? <span className="muted"> {p.to.country}</span> : null}{p.route_plausible === false ? <span className="muted"> ?</span> : null}</td>
                <td title={[p.type, p.category_name].filter(Boolean).join(", ") || undefined}>{p.model ?? p.category_name ?? <span className="muted">not known</span>}
                  {p.military ? <span className="muted"> (military)</span> : null}</td>
                <td>{p.reg ?? ""}</td>
                <td><PlaneFlag code={p.flag} title={p.country} />{p.country ?? ""}</td>
                <td>{p.altitude_m != null ? `${n(p.altitude_m)} m` : ""}</td>
                <td>{p.speed_kmh != null ? `${n(p.speed_kmh)} km/h` : ""}</td>
                <td>{p.climb_ms != null ? `${p.climb_ms > 0 ? "+" : ""}${p.climb_ms} m/s` : ""}</td>
                <td>{p.squawk ?? ""}{["7500", "7600", "7700"].includes(String(p.squawk)) ? <b style={{ color: "#c92a2a" }}> emergency</b> : null}</td>
                <td>{when(p.seen)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(d?.total ?? 0) > rows.length && (
        <p className="small">Showing {n(rows.length)} of {n(d?.total ?? 0)}. <button className="link small" onClick={() => setMore((m) => m + 1)}>Show {n(PLANES_PAGE)} more</button></p>
      )}
      {open && <PlaneCard id={open} plane={picked} onClose={() => setOpen(null)} />}
    </section>
  );
}

type Flight = { icao: string; callsign: string | null; start: number; end: number; minutes: number; points: number; top_m: number | null;
  from: Airport | null; to: Airport | null; airline: string | null };

// The flights saved here for this aircraft, or for every aircraft that flew this callsign.
function FlightsPart({ icao, callsign }: { icao: string; callsign: string | null }) {
  const [by, setBy] = useState<"plane" | "callsign">("plane");
  const [days, setDays] = useState(30);
  const [d, setD] = useState<{ flights: Flight[]; note: string } | null>(null);
  useEffect(() => {
    let live = true;
    setD(null);
    get<{ flights: Flight[]; note: string }>("/live/planes/flights", by === "plane" ? { icao, days } : { callsign: callsign ?? "", days })
      .then((x) => live && setD(x)).catch(() => live && setD({ flights: [], note: "Could not read the saved flights." }));
    return () => { live = false; };
  }, [icao, callsign, by, days]);
  const day = (t: number) => new Date(t * 1000).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const hm = (t: number) => new Date(t * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  return (
    <>
      <div className="row small" style={{ gap: 8, alignItems: "baseline" }}>
        <h3 className="small" style={{ margin: "8px 0 2px" }}>Flights saved here</h3>
        <select value={by} onChange={(e) => setBy(e.target.value as typeof by)} aria-label="Flights of">
          <option value="plane">this aircraft</option>{callsign && <option value="callsign">callsign {callsign}, any aircraft</option>}
        </select>
        <select value={days} onChange={(e) => setDays(+e.target.value)} aria-label="Over">
          <option value={3}>last 3 days</option><option value={30}>last 30 days</option><option value={400}>all kept</option>
        </select>
      </div>
      {!d ? <p className="small muted">Reading…</p> : !d.flights.length ? <p className="small muted">None saved yet.</p> : (
        <div style={{ maxHeight: 220, overflowY: "auto" }}>
          <table className="small">
            <thead><tr><th>Took off (first heard)</th><th>Callsign</th>{by === "callsign" && <th>Aircraft</th>}<th>From</th><th>To</th><th>Last heard</th><th>Highest</th></tr></thead>
            <tbody>{d.flights.map((f) => (
              <tr key={`${f.icao}${f.start}`}>
                <td>{day(f.start)}</td><td>{f.callsign ?? ""}</td>{by === "callsign" && <td>{f.icao}</td>}
                <td title={f.from?.name ?? undefined}>{airport(f.from)}</td><td title={f.to?.name ?? undefined}>{airport(f.to)}</td>
                <td>{hm(f.end)} <span className="muted">({Math.floor(f.minutes / 60)} h {f.minutes % 60} min)</span></td>
                <td>{f.top_m != null ? `${n(f.top_m)} m` : ""}</td>
              </tr>))}
            </tbody>
          </table>
        </div>)}
      {d && d.flights.length > 0 && <p className="caption">{n(d.flights.length)} flights. {d.note}</p>}
    </>
  );
}

export function PlaneCard({ id, plane, onClose }: { id: string; plane?: Plane; onClose: () => void }) {
  const [j, setJ] = useState<Journey | null>(null);
  useEffect(() => {
    let live = true;
    planeJourney(id, plane?.callsign, plane?.lon, plane?.lat).then((x) => live && setJ(x)).catch(() => {});
    return () => { live = false; };
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  const a = j?.aircraft;
  const rows: [string, React.ReactNode][] = [
    ["Hex code (ICAO 24-bit)", id], ["Callsign", plane?.callsign ?? ""],
    ["Airline", plane?.airline ? <><AirlineLogo code={plane.airline_code} size={28} />{plane.airline}</> : ""],
    ["Registered in", plane?.country ? <><PlaneFlag code={plane.flag} />{plane.country}</> : ""],
    ["Registration", a?.registration ?? plane?.reg ?? ""],
    ["Aircraft", [a?.description ?? plane?.model, a?.type ?? plane?.type].filter(Boolean).join(" ") + (plane?.military || a?.military ? " (military)" : "")], ["Operator", a?.operator ?? ""],
    ["Built", a?.year ?? ""], ["Type (ADS-B)", plane?.category_name ?? ""],
    ["Height", plane?.altitude_m != null ? `${n(plane.altitude_m)} m` : ""], ["Speed", plane?.speed_kmh != null ? `${n(plane.speed_kmh)} km/h, heading ${n(plane.heading)}°` : ""],
    ["Climbing", plane?.climb_ms != null ? `${plane.climb_ms} m/s` : ""], ["Squawk", plane?.squawk ?? a?.squawk ?? ""],
    ["Where", plane ? `${plane.lat.toFixed(3)}, ${plane.lon.toFixed(3)}` : ""], ["Last heard", when(plane?.seen)],
  ];
  return (
    <div className="find-big-back" onClick={onClose}>
      <div className="find-big card" role="dialog" aria-modal="true" aria-label={plane?.callsign ?? id} style={{ maxWidth: 560 }} onClick={(e) => e.stopPropagation()}>
        <div className="row"><h2 style={{ margin: 0 }}>{plane?.callsign ?? id}</h2><span className="spacer" /><button className="link" onClick={onClose} aria-label="Close">×</button></div>
        {plane && <SpotMap lon={plane.lon} lat={plane.lat} label={plane.callsign ?? id}
          lines={j ? journeyLines(j, { lng: plane.lon, lat: plane.lat }, true) : null} />}
        <table className="small"><tbody>{rows.filter(([, v]) => v !== "" && v != null).map(([k, v]) => <tr key={k}><th style={{ textAlign: "left", paddingRight: 12 }}>{k}</th><td>{v}</td></tr>)}</tbody></table>
        <FlightsPart icao={id} callsign={plane?.callsign ?? null} />
        <h3 className="small" style={{ marginBottom: 2 }}>Where from and to</h3>
        {j ? journeyText(j, true).map((l) => <p key={l} className="small" style={{ margin: "2px 0" }}>{l}</p>) : <p className="small muted">Asking OpenSky and adsb.lol…</p>}
        <p className="small"><Link href={mapLayersHref("F")}>Planes on the map</Link> (click the plane there to draw its path)
          {" · "}<a href={`https://globe.adsb.lol/?icao=${id}`} target="_blank" rel="noreferrer">adsb.lol</a>
          {" · "}<a href={`https://opensky-network.org/aircraft-profile?icao24=${id}`} target="_blank" rel="noreferrer">OpenSky</a></p>
      </div>
    </div>
  );
}

const LIVE_LABEL: Record<LiveTab, string> = { ships: "Ships", planes: "Planes", "ship-counts": "Ship counts", "plane-counts": "Plane counts", schedules: "Schedules" };

// A map page panel showing one of the Ships and planes tables; a counts row opens the list with that filter.
export function LivePanel({ tab, setTab, cameraBus }: { tab: LiveTab; setTab: (t: LiveTab) => void; cameraBus?: CameraBus }) {
  const [filter, setFilter] = useState<Record<string, string>>({});
  // Only what is in the map's view (the map moved last), on by default; remembered in this browser.
  const [inView, setInView] = useState(() => { try { return localStorage.getItem("wm-live-in-view") !== "0"; } catch { return true; } });
  const [box, setBox] = useState(cameraBus?.lastView ?? "");
  useEffect(() => cameraBus?.onView(setBox), [cameraBus]);
  const keepInView = (on: boolean) => { setInView(on); try { localStorage.setItem("wm-live-in-view", on ? "1" : "0"); } catch { /* not kept */ } };
  const area = inView && cameraBus ? box : "";
  const [open, setOpen] = useState<string | null>(null);
  const init = (k: string) => filter[k] ?? "";
  const key = Object.entries(filter).map(([k, v]) => `${k}=${v}`).join("&");
  const go = (t: LiveTab, f: Record<string, string> = {}) => { setFilter(f); setOpen(null); setTab(t); };
  return (
    <div className="live-panel" style={{ padding: "4px 8px", overflow: "auto", height: "100%" }}>
      <div className="seg" role="group" aria-label="Which table" style={{ marginBottom: 6 }}>
        {(Object.keys(LIVE_LABEL) as LiveTab[]).map((t) => (
          <button key={t} className={t === tab ? "on" : ""} aria-pressed={t === tab} onClick={() => go(t)}>{LIVE_LABEL[t]}</button>
        ))}
        <Link className="small" href={`/live?tab=${tab}`} style={{ marginLeft: 8 }}>Open full page</Link>
        {cameraBus && tab !== "schedules" && (
          <label className="small" style={{ marginLeft: 10 }} title="List and count only the ships or planes inside the area the map shows (the map you moved last); they follow the map as you pan and zoom">
            <input type="checkbox" checked={inView} onChange={(e) => keepInView(e.target.checked)} /> Only what&apos;s in the map view
          </label>
        )}
      </div>
      {tab === "ships" && <Ships key={key} init={init} open={open} setOpen={setOpen} box={area} />}
      {tab === "planes" && <Planes key={key} init={init} open={open} setOpen={setOpen} box={area} />}
      {tab === "ship-counts" && <Counts what="ships" drill={(t, f) => go(t, f)} box={area} />}
      {tab === "plane-counts" && <Counts what="planes" drill={(t, f) => go(t, f)} box={area} />}
      {tab === "schedules" && <><SchedulesBoard openShip={setOpen} />{open && <ShipCard id={open} onClose={() => setOpen(null)} />}</>}
    </div>
  );
}
