"use client";

// A plane card's Schedule and Seat prices parts: the flight's published times (AeroDataBox, free
// key) and the fares people found lately for its route (Travelpayouts, free token), with links
// to check fares by hand. Asked only when the card is open.
import { useEffect, useState } from "react";
import { get } from "@/lib/api";
import type { Journey } from "@/lib/ships";

type T = { utc?: string | null; local?: string | null } | null;
type End = {
  airport: { name?: string | null; city?: string | null; iata?: string | null; icao?: string | null; country?: string | null; tz?: string | null };
  scheduled: T; revised: T; predicted: T; runway: T; terminal?: string | null; gate?: string | null; check_in?: string | null;
  baggage?: string | null; late_min?: number | null;
};
type Flight = {
  number?: string | null; callsign?: string | null; status?: string | null; airline?: { name?: string | null; iata?: string | null };
  aircraft?: { reg?: string | null; model?: string | null }; cargo?: boolean; departure?: End | null; arrival?: End | null;
};
type Schedule = { flight: Flight | null; found: number; used_month: number; cap_month: number; note?: string; error?: string; needs_key?: string; kept_at?: number };
type Fare = { price: number; date?: string | null; airline?: string | null; flight?: string | null; transfers?: number | null; link?: string | null };
type Fares = {
  from: string; to: string; day?: string | null; currency: string; links: { label: string; href: string }[]; count: number;
  cheapest_month: Fare | null; cheapest_day: Fare | null; this_flight: Fare | null; note?: string; error?: string; needs_key?: string; kept_at?: number;
};

// "2026-11-28 14:05+13:00" -> "14:05 Sat 28 Nov" (the airport's own clock)
function localTime(t: T): string {
  const s = t?.local ?? "";
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!m) return t?.utc ?? "";
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  const day = d.toLocaleDateString("en-NZ", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
  return `${m[4]}:${m[5]} ${day}`;
}
const lateText = (min?: number | null) =>
  min == null ? "" : Math.abs(min) < 5 ? "on time" : min > 0 ? `${min >= 90 ? `${Math.floor(min / 60)} h ${min % 60} min` : `${min} min`} late` : `${-min} min early`;
const STATUS: Record<string, string> = { EnRoute: "In the air", Approaching: "Approaching", Departed: "Departed", Arrived: "Arrived",
  Expected: "Expected", CheckIn: "Check-in open", Boarding: "Boarding", GateClosed: "Gate closed", Delayed: "Delayed",
  Canceled: "Cancelled", CanceledUncertain: "Maybe cancelled", Diverted: "Diverted", Unknown: "" };
type Route = { from: string; to: string; day: string | null; airline?: string | null; number?: string | null };
const money = (n: number, cur: string) => `${cur} ${Math.round(n).toLocaleString()}`;

function EndRow({ label, e, arrive }: { label: string; e: End; arrive: boolean }) {
  const actual = e.runway, expected = e.revised ?? e.predicted;
  const where = [e.airport.city || e.airport.name, e.airport.iata ? `(${e.airport.iata})` : ""].filter(Boolean).join(" ");
  const extra = [e.terminal && `Terminal ${e.terminal}`, e.gate && `Gate ${e.gate}`, !arrive && e.check_in && `Check-in ${e.check_in}`,
    arrive && e.baggage && `Bags at belt ${e.baggage}`].filter(Boolean).join(", ");
  return (
    <tr>
      <th style={{ textAlign: "left", paddingRight: 10, verticalAlign: "top" }}>{label}</th>
      <td>
        <b>{where}</b><br />
        Scheduled {localTime(e.scheduled)}
        {expected && !actual && localTime(expected) !== localTime(e.scheduled) && <>, expected {localTime(expected)}</>}
        {actual && <>, {arrive ? "landed" : "took off"} {localTime(actual)}</>}
        {e.late_min != null && <span className={e.late_min >= 15 ? "tone bad" : "muted"}> ({lateText(e.late_min)})</span>}
        {extra && <><br /><span className="muted">{extra}</span></>}
      </td>
    </tr>
  );
}

export function FlightSchedule({ id, callsign, onRoute }: { id: string; callsign?: string | null;
  onRoute?: (r: Route | null) => void }) {
  const [s, setS] = useState<Schedule | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    let live = true;
    const q = callsign ? `?callsign=${encodeURIComponent(callsign)}` : "";
    get<Schedule>(`/live/planes/schedule/${encodeURIComponent(id)}${q}`).then((x) => {
      if (!live) return;
      setS(x);
      const f = x.flight, d = f?.departure, a = f?.arrival;
      const num = (f?.number ?? "").replace(/\s+/g, "");
      onRoute?.(d?.airport.iata && a?.airport.iata
        ? { from: d.airport.iata, to: a.airport.iata, day: (d.scheduled?.local ?? "").slice(0, 10) || null, airline: f?.airline?.iata ?? num.slice(0, 2), number: num.slice(2) }
        : null);
    }).catch(() => { if (live) { setErr(true); onRoute?.(null); } });
    return () => { live = false; };
  }, [id, callsign]); // eslint-disable-line react-hooks/exhaustive-deps
  const f = s?.flight;
  return (
    <>
      <h3 className="small" style={{ marginBottom: 2 }}>Schedule</h3>
      {err ? <p className="small muted">Could not ask for the schedule.</p> : !s ? <p className="small muted">Asking AeroDataBox…</p> : (
        <>
          {f && (
            <>
              <p className="small" style={{ margin: "2px 0" }}>
                <b>{f.number ?? f.callsign}</b>{f.airline?.name ? `, ${f.airline.name}` : ""}{f.cargo ? " (cargo)" : ""}
                {f.status && STATUS[f.status] !== "" && <> · {STATUS[f.status] ?? f.status}</>}
                {f.aircraft?.model && <span className="muted"> · {f.aircraft.model}{f.aircraft.reg ? ` ${f.aircraft.reg}` : ""}</span>}
              </p>
              <table className="small"><tbody>
                {f.departure && <EndRow label="Leaves" e={f.departure} arrive={false} />}
                {f.arrival && <EndRow label="Arrives" e={f.arrival} arrive />}
              </tbody></table>
            </>
          )}
          {(s.error || s.note) && <p className="small muted" style={{ margin: "2px 0" }}>{s.error ?? s.note}</p>}
          <p className="caption">Times are each airport&apos;s local time. From AeroDataBox{s.kept_at ? ", kept from an earlier look" : ""}; {s.used_month} of {s.cap_month} look-ups used this month.</p>
        </>
      )}
    </>
  );
}

export function SeatPrices({ route }: { route: Route | null }) {
  const [d, setD] = useState<Fares | null>(null);
  const key = route ? `${route.from}-${route.to}-${route.day}-${route.airline}-${route.number}` : "";
  useEffect(() => {
    if (!route) return;
    let live = true;
    setD(null);
    get<Fares>("/live/planes/fares", { from: route.from, to: route.to, date: route.day ?? undefined, airline: route.airline ?? undefined, number: route.number ?? undefined })
      .then((x) => live && setD(x)).catch(() => {});
    return () => { live = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!route) return (
    <>
      <h3 className="small" style={{ marginBottom: 2 }}>Seat prices</h3>
      <p className="small muted">Shown once the flight&apos;s route is known (airline flights only).</p>
    </>
  );
  const day = (iso?: string | null) => iso ? new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-NZ", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }) : "";
  const fareLine = (label: string, f: Fare | null, withDate = true) => f && (
    <p className="small" style={{ margin: "2px 0" }}>
      {label}: <b>{money(f.price, d!.currency)}</b>
      <span className="muted"> {[withDate ? day(f.date) : "", f.airline && f.flight ? `${f.airline}${f.flight}` : f.airline, f.transfers ? `${f.transfers} stop${f.transfers > 1 ? "s" : ""}` : "non-stop"].filter(Boolean).join(", ")}</span>
      {f.link && <> · <a href={f.link} target="_blank" rel="noreferrer">see it</a></>}
    </p>
  );
  return (
    <>
      <h3 className="small" style={{ marginBottom: 2 }}>Seat prices {route.from} to {route.to}</h3>
      {!d ? <p className="small muted">Asking Travelpayouts…</p> : (
        <>
          {fareLine("This flight", d.this_flight, false)}
          {fareLine(`Cheapest on ${d.day ? day(d.day) : "that day"}`, d.cheapest_day, false)}
          {fareLine("Cheapest this month", d.cheapest_month)}
          {(d.error || d.note) && <p className="small muted" style={{ margin: "2px 0" }}>{d.error ?? d.note}</p>}
          <p className="small" style={{ margin: "4px 0" }}>Check fares: {d.links.map((l, i) => <span key={l.href}>{i ? " · " : ""}<a href={l.href} target="_blank" rel="noreferrer">{l.label}</a></span>)}</p>
          {d.count > 0 && <p className="caption">One-way fares people found on Aviasales in the last few days ({d.count} seen this month), not a live price for a seat. From Travelpayouts.</p>}
        </>
      )}
    </>
  );
}

// Both parts, with the route taken from the schedule, else from the route list (adsbdb) in the journey.
export default function FlightInfo({ id, callsign, journey }: { id: string; callsign?: string | null; journey: Journey | null }) {
  // undefined while the schedule is still being asked, so fares are asked once, for the best-known route
  const [fromSchedule, setFromSchedule] = useState<Route | null | undefined>(undefined);
  const r = journey?.route?.airports ?? [];
  const first = r[0]?.iata, last = r[r.length - 1]?.iata;
  const today = new Date().toISOString().slice(0, 10);
  const listed: Route | null = first && last && r.length >= 2
    ? { from: first, to: last, day: today, airline: journey?.airline?.iata, number: (callsign ?? "").replace(/^[A-Z]{3}/, "") } : null;
  const route = fromSchedule === undefined ? null : fromSchedule ?? listed;
  return (
    <>
      <FlightSchedule id={id} callsign={callsign} onRoute={setFromSchedule} />
      {fromSchedule !== undefined && <SeatPrices route={route} />}
    </>
  );
}
