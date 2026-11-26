"use client";

// Are cargo ships on schedule (the API's schedules.py): a pill for the ships table, the Schedule
// part of a ship's card (how late, three ways; the ETA over time; port calls; learned route) and
// the Live page's Schedules tab (the ports' arrival lists as a board, and on-time
// shares by line and port).
import Link from "next/link";
import { useEffect, useState } from "react";
import { get } from "@/lib/api";

export type OnTime = "on_time" | "early" | "slipping" | "late" | "none";
const PILL: Record<OnTime, { label: string; color: string }> = {
  on_time: { label: "On time", color: "#2b8a3e" },
  early: { label: "Early", color: "#1c7ed6" },
  slipping: { label: "Slipping", color: "#d9480f" },
  late: { label: "Late", color: "#c92a2a" },
  none: { label: "No ETA", color: "#868e96" },
};
export const ON_TIME_STATES = Object.entries(PILL).map(([id, p]) => ({ id: id as OnTime, label: p.label }));

const hrs = (h?: number | null) => {
  if (typeof h !== "number") return "";
  const a = Math.abs(h), sign = h < 0 ? "−" : "+";
  if (a < 1) return "on the hour";
  return a >= 24 ? `${sign}${Math.floor(a / 24)} d ${Math.round(a % 24)} h` : `${sign}${Math.round(a)} h`;
};
const when = (t?: number | null) => (t ? new Date(t * 1000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");
const BY: Record<string, string> = { line: "against the line's schedule", port: "against the port's booking", ship: "against its own first ETA" };

export function OnTimePill({ state, late, by }: { state?: OnTime | null; late?: number | null; by?: string | null }) {
  if (!state) return null;
  const p = PILL[state] ?? PILL.none;
  return (
    <span title={by ? `${hrs(late)} ${BY[by] ?? ""}` : undefined} style={{ whiteSpace: "nowrap" }}>
      <span style={{ display: "inline-block", padding: "0 7px", borderRadius: 999, fontSize: "0.85em", fontWeight: 600, color: p.color,
        background: `color-mix(in srgb, ${p.color} 15%, transparent)` }}>{p.label}</span>
      {state !== "none" && typeof late === "number" ? <span className="muted"> {hrs(late)}</span> : null}
    </span>
  );
}

type Voyage = { destination: string | null; started: number; history: [number, number][]; first_eta: number | null; eta: number | null; moved_h: number | null };
type PortRef = { name: string | null; country?: string | null; locode?: string | null };
type Schedule = {
  id: number; name: string | null; imo: number | null; line: string | null; on: boolean;
  state: OnTime; late_h: number | null; moved_h: number | null; measured_by: "line" | "port" | "ship" | null; arrived_at: number | null;
  voyage: Voyage | null; voyages: Voyage[];
  estimate: { at: number; nm: number; speed_kn: number; port: string | null } | null;
  booking: { port: string; first: [number, number]; versions: [number, number, number | null][]; arrival: number | null; arrived_at?: number;
    voyage?: string; prev?: string; next?: string; cargo?: string } | null;
  carrier: { carrier: string; service?: string | null; error?: string; at: number; calls?: { port: string; locode: string; arr_planned?: number; arr_estimated?: number; arr_actual?: number }[] } | null;
  line_call?: { port: string; arr_planned?: number; arr_estimated?: number; arr_actual?: number };
  calls: { port: PortRef; arrived: number; left: number | null }[];
  route: { ports: string[]; loop: string[] | null; times: number; round_days: number | null };
};

// The ETA a ship sent over time: a step line (each step is a new ETA), the first ETA dashed.
function EtaChart({ v }: { v: Voyage }) {
  const h = v.history;
  if (h.length < 1 || v.first_eta == null) return null;
  const W = 400, H = 170, L = 96, R = 10, T = 14, B = 26;
  const now = Date.now() / 1000;
  const x0 = h[0][0], x1 = Math.max(now, h[h.length - 1][0] + 3600);
  const ys = h.map((p) => p[1]);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (y1 - y0 < 12 * 3600) { const m = (y0 + y1) / 2; y0 = m - 6 * 3600; y1 = m + 6 * 3600; }
  const pad = (y1 - y0) * 0.12; y0 -= pad; y1 += pad;
  const X = (t: number) => L + ((t - x0) / (x1 - x0 || 1)) * (W - L - R);
  const Y = (t: number) => T + (1 - (t - y0) / (y1 - y0)) * (H - T - B);
  let d = "";
  h.forEach(([s, e], i) => { d += i === 0 ? `M${X(s)},${Y(e)}` : `H${X(s)}V${Y(e)}`; });
  d += `H${X(x1)}`;
  const day = (t: number) => new Date(t * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" });
  const tick = (t: number) => (y1 - y0 < 4 * 86400
    ? `${day(t)} ${new Date(t * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false })}` : day(t));
  const ticks = [y0 + pad, (y0 + y1) / 2, y1 - pad];
  const late = (v.moved_h ?? 0) >= 12;
  const col = late ? "#d9480f" : "#2b8a3e";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", maxWidth: 460, height: "auto" }} role="img"
      aria-label={`ETA to ${v.destination ?? "destination"} over time: first ${when(v.first_eta)}, now ${when(v.eta)}`}>
      {ticks.map((t) => <g key={t}><line x1={L} x2={W - R} y1={Y(t)} y2={Y(t)} stroke="var(--line, #dde2e7)" />
        <text x={L - 6} y={Y(t) + 4} textAnchor="end" fontSize="11" fill="var(--muted, #6b7785)">{tick(t)}</text></g>)}
      <text x={L} y={H - 6} fontSize="11" fill="var(--muted, #6b7785)">{day(x0)}</text>
      <text x={W - R} y={H - 6} fontSize="11" textAnchor="end" fill="var(--muted, #6b7785)">now</text>
      <line x1={L} x2={W - R} y1={Y(v.first_eta)} y2={Y(v.first_eta)} stroke="var(--muted, #6b7785)" strokeDasharray="4 4" />
      <path d={d} fill="none" stroke={col} strokeWidth={2.5} />
      <circle cx={X(x1)} cy={Y(h[h.length - 1][1])} r={4} fill={col} />
    </svg>
  );
}

export function SchedulePart({ id }: { id: string }) {
  const [s, setS] = useState<Schedule | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    get<Schedule>(`/live/ships/schedule/${encodeURIComponent(id)}`).then((x) => live && setS(x)).catch((e) => live && setErr(String(e.message ?? e)));
    return () => { live = false; };
  }, [id]);
  if (err) return null; // not a cargo ship
  if (!s) return <p className="small muted">Loading the schedule…</p>;
  const v = s.voyage;
  const b = s.booking;
  const rows: [string, React.ReactNode][] = [
    ["How late", s.measured_by ? <><OnTimePill state={s.state} late={s.late_h} /> <span className="muted">{BY[s.measured_by]}</span></> : <span className="muted">No ETA, booking or line schedule yet</span>],
    ["Their ETA", v?.eta ? <>{when(v.eta)}{v.destination ? ` to ${v.destination}` : ""}{(v.moved_h ?? 0) !== 0 ? <span className="muted"> (moved {hrs(v.moved_h)} since first sent)</span> : null}</> : ""],
    ["Our estimate", s.estimate ? `${when(s.estimate.at)} at ${s.estimate.speed_kn} kn, about ${s.estimate.nm.toLocaleString()} NM to ${s.estimate.port ?? "go"}` : ""],
    ["Port's booking", b ? <>{b.port} {when(b.arrival)}{b.versions.length > 1 ? <span className="muted"> (first booked {when(b.versions[0][1])}, changed {b.versions.length - 1}×)</span> : null}
      {b.arrived_at ? <span className="muted">, arrived {when(b.arrived_at)}</span> : null}</> : ""],
    ["Line's schedule", s.carrier?.error ? <span className="muted">{s.carrier.error}</span>
      : s.line_call ? <>{s.line_call.port} planned {when(s.line_call.arr_planned)}{s.line_call.arr_estimated ? `, now expected ${when(s.line_call.arr_estimated)}` : ""}{s.carrier?.service ? <span className="muted"> ({s.carrier.service})</span> : null}</>
      : s.line ? <span className="muted">{s.line}: add its free key in <Link href="/settings#keys">Settings › Keys</Link> to compare with its schedule</span> : ""],
    ["Arrived", s.arrived_at ? when(s.arrived_at) : ""],
  ];
  const r = s.route;
  return (
    <>
      <h3 className="small" style={{ marginBottom: 2 }}>Schedule</h3>
      <table className="small"><tbody>{rows.filter(([, x]) => x !== "" && x != null).map(([k, x]) => <tr key={k}><th style={{ textAlign: "left", paddingRight: 12 }}>{k}</th><td>{x}</td></tr>)}</tbody></table>
      {v && v.history.length > 0 && <>
        <p className="small muted" style={{ margin: "6px 0 0" }}>ETA{v.destination ? ` to ${v.destination}` : ""} as the ship sent it (each step is a new ETA; dashed: the first one)</p>
        <EtaChart v={v} />
      </>}
      <p className="small" style={{ margin: "4px 0" }}>
        <b>Route: </b>{r.loop ? <>{r.loop.join(" → ")} <span className="muted">(seen {r.times}×{r.round_days ? `, about ${r.round_days} days a round` : ""})</span></>
          : r.ports.length ? <>{r.ports.join(" → ")} <span className="muted">(learning: the loop shows once the same ports come round twice)</span></>
          : <span className="muted">no port calls seen yet</span>}
      </p>
      {s.calls.length > 0 && <details className="small"><summary>Port calls we saw ({s.calls.length})</summary>
        <table className="small"><tbody>{[...s.calls].reverse().map((c) => <tr key={`${c.arrived}`}><td>{[c.port.name, c.port.country].filter(Boolean).join(", ")}</td>
          <td className="muted">{when(c.arrived)} to {c.left ? when(c.left) : "now"}</td></tr>)}</tbody></table></details>}
      {!s.on && <p className="small muted">Schedules are off or ships aren&apos;t being collected (Settings › Transport), so nothing new is kept.</p>}
    </>
  );
}

type BoardRow = { name: string; imo: number | null; id: number | null; port: string; booked: number; first_booked: number; moved_h: number; changes: number;
  own_eta: number | null; estimate: number | null; arrived_at: number | null; in_port: boolean; state: OnTime; late_h: number | null; measured_by: string;
  prev: string | null; next: string | null; cargo: string | null; voyage: string | null; line: string | null };
type Rel = { days: number; lines: { name: string; calls: number; on_time: number; share: number; avg_late_h: number }[];
  ports: { name: string; calls: number; on_time: number; share: number; avg_late_h: number }[] };

export function SchedulesBoard({ openShip }: { openShip: (id: string) => void }) {
  const [port, setPort] = useState("");
  const [days, setDays] = useState(7);
  const [d, setD] = useState<{ rows: BoardRow[]; ports: string[]; notes: Record<string, string>; on: boolean; lists_on: boolean } | null>(null);
  const [rel, setRel] = useState<Rel | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    get<typeof d>(`/live/schedules?${new URLSearchParams({ port, days: String(days) })}`).then((x) => live && setD(x)).catch((e) => live && setErr(String(e.message ?? e)));
    return () => { live = false; };
  }, [port, days]);
  useEffect(() => { get<Rel>("/live/schedules/reliability?days=30").then(setRel).catch(() => {}); }, []);
  if (err) return <p className="error">{err}</p>;
  return (
    <section className="card">
      <p className="caption">Cargo and container ships booked into Auckland, Tauranga, the NSW ports, Melbourne and Singapore (with its key), from the ports&apos; own arrival lists (read every hour, every change kept),
        beside what each ship says (its ETA) and our estimate from its position and speed. On time means within a day of the first booking, as the shipping industry counts it.
        Open a ship for its ETA over time and its route.</p>
      <div className="table-tools small">
        <label>Port <select value={port} onChange={(e) => setPort(e.target.value)}>
          <option value="">Both</option>{(d?.ports ?? []).map((p) => <option key={p} value={p}>{p}</option>)}
        </select></label>
        <label>Arriving in the next <select value={days} onChange={(e) => setDays(+e.target.value)}>
          <option value={2}>2 days</option><option value={7}>week</option><option value={30}>month</option>
        </select></label>
        <span className="muted">{d ? `${d.rows.length} ships` : "Loading…"}</span>
      </div>
      {d && (!d.on || !d.lists_on) && <p className="small muted">The port lists are only read while ships are collected and schedules are on (Settings › Transport).</p>}
      {d && Object.values(d.notes).length > 0 && <p className="small muted">{Object.values(d.notes).join(" ")}</p>}
      <div style={{ overflowX: "auto" }}>
        <table className="small">
          <thead><tr><th>Ship</th><th>Port</th><th>Booked arrival</th><th title="How far the port's booking has moved since we first saw it">Booking moved</th>
            <th>Ship&apos;s own ETA</th><th>Our estimate</th><th>On time?</th><th>From → next</th><th>Cargo</th></tr></thead>
          <tbody>
            {(d?.rows ?? []).map((r) => (
              <tr key={`${r.port}|${r.imo ?? r.name}|${r.first_booked}`} onClick={() => r.id && openShip(String(r.id))} style={{ cursor: r.id ? "pointer" : undefined }}>
                <td>{r.name}{r.line ? <span className="muted"> · {r.line}</span> : null}{!r.id ? <span className="muted" title="Not heard on AIS yet, or no IMO match"> (not heard yet)</span> : null}</td>
                <td>{r.port}</td>
                <td>{when(r.booked)}{r.in_port ? <span className="muted"> (in port)</span> : r.arrived_at ? <span className="muted"> (arrived {when(r.arrived_at)})</span> : null}</td>
                <td>{Math.abs(r.moved_h) >= 1 ? <>{hrs(r.moved_h)}{r.changes > 1 ? <span className="muted"> ({r.changes} changes)</span> : null}</> : <span className="muted">—</span>}</td>
                <td>{when(r.own_eta)}</td>
                <td>{when(r.estimate)}</td>
                <td><OnTimePill state={r.state} late={r.late_h} by={r.measured_by} /></td>
                <td>{[r.prev, r.next].filter(Boolean).join(" → ")}</td>
                <td>{r.cargo ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {d && !d.rows.length && <p className="small muted">No bookings kept yet: the lists are read an hour or so after the app starts.</p>}
      {rel && (rel.lines.length > 0 || rel.ports.length > 0) && (
        <>
          <h3 className="small">Lines and ports, last {rel.days} days</h3>
          <p className="small muted">Share of the calls we saw arrive within a day of their first booking. Our own small sample from two ports, not an industry table.</p>
          <div className="row" style={{ gap: 24, alignItems: "flex-start", flexWrap: "wrap" }}>
            {([["Line", rel.lines], ["Port", rel.ports]] as const).map(([label, list]) => (
              <table key={label} className="small"><thead><tr><th>{label}</th><th>Calls</th><th>On time</th><th>Average late</th></tr></thead>
                <tbody>{list.map((x) => <tr key={x.name}><td>{x.name}</td><td>{x.calls}</td><td>{Math.round(x.share * 100)}%</td><td>{x.avg_late_h} h</td></tr>)}</tbody></table>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
