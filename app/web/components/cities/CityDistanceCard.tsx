"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import WorldMap, { type MapPath, type MapPoint } from "@/components/WorldMap";
import { openAsk } from "@/lib/ai";
import { api, type CityDistances, type CityLeg, type CityRow } from "@/lib/api";
import { people } from "@/lib/cities";
import { cssVar } from "@/lib/colors";
import { flightTime, fmtDistance, UNIT_LABEL, type Units } from "@/lib/measure";

// Distance to…: how far a city is from your key cities (Settings > City pages) and from any
// city you add, with a rough flight time, today's time difference and the bearing to set
// off on, plus the nearest big cities. Distances are great-circle (the shortest way over
// the globe), drawn as arcs on the small map.
const POINTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const compass = (b: number) => `${String(b).padStart(3, "0")}° ${POINTS[Math.round(b / 45) % 8]}`;

// Minutes ahead of UTC in a time zone today (daylight saving included); null when unknown.
export function utcOffset(tz: string | null, when = new Date()): number | null {
  if (!tz) return null;
  try {
    const part = new Intl.DateTimeFormat("en-US", { timeZone: tz, timeZoneName: "longOffset" })
      .formatToParts(when).find((p) => p.type === "timeZoneName")?.value ?? "";
    const m = part.match(/GMT([+-])(\d{1,2})(?::(\d{2}))?/);
    if (!m) return part === "GMT" ? 0 : null;
    return (m[1] === "-" ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3] ?? 0));
  } catch {
    return null;
  }
}

export function timeDiff(from: string | null, to: string | null): string {
  const a = utcOffset(from), b = utcOffset(to);
  if (a === null || b === null) return "–";
  const d = b - a;
  if (d === 0) return "same";
  const h = Math.trunc(Math.abs(d) / 60), m = Math.abs(d) % 60;
  return `${d > 0 ? "+" : "−"}${h}${m ? `:${String(m).padStart(2, "0")}` : ""} h`;
}

const ADDED_KEY = "worldmodel.distance.added";

function loadAdded(): string[] {
  try { return JSON.parse(localStorage.getItem(ADDED_KEY) || "[]").filter((x: unknown) => typeof x === "string").slice(0, 20); }
  catch { return []; }
}

export default function CityDistanceCard({ cityId, name }: { cityId: string; name: string }) {
  const [added, setAdded] = useState<string[]>([]);
  const [d, setD] = useState<CityDistances | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [units, setUnits] = useState<Units>("km");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<CityRow[]>([]);

  useEffect(() => { setAdded(loadAdded()); }, []);
  useEffect(() => {
    setError(null);
    api.cityDistances(cityId, added).then(setD).catch((e) => setError(String(e.message || e)));
  }, [cityId, added]);
  useEffect(() => {
    if (q.trim().length < 2) { setHits([]); return; }
    const t = setTimeout(() => api.cities({ q: q.trim(), limit: 8 }).then((r) => setHits(r.rows)).catch(() => setHits([])), 250);
    return () => clearTimeout(t);
  }, [q]);

  const keep = (ids: string[]) => {
    setAdded(ids);
    try { localStorage.setItem(ADDED_KEY, JSON.stringify(ids)); } catch { /* private window: kept for this visit only */ }
  };

  const legs = useMemo(() => (d ? [...d.key, ...d.added] : []), [d]);
  const paths = useMemo<MapPath[]>(() => (d ? legs.map((l) => ({
    key: l.city_id, color: cssVar("--accent") || "#0f6e6a", label: `${d.city.name} to ${l.name}: ${fmtDistance(l.km, units)}`, curve: true,
    stops: [{ lng: d.city.lon, lat: d.city.lat, label: d.city.name }, { lng: l.lon, lat: l.lat, label: l.name }] })) : []), [d, legs, units]);
  const points = useMemo<MapPoint[]>(() => (d ? [
    { id: d.city.city_id, name: d.city.name, lng: d.city.lon, lat: d.city.lat, size: 3, capital: true },
    ...legs.map((l) => ({ id: l.city_id, name: l.name, lng: l.lon, lat: l.lat, size: 1 }))] : []), [d, legs]);

  if (error) return <section className="card"><h3>Distance to…</h3><p className="small ink-2">{error}</p></section>;
  if (!d) return <section className="card"><h3>Distance to…</h3><p className="muted small">Loading…</p></section>;

  const row = (l: CityLeg) => (
    <tr key={l.city_id}>
      <td><Link href={`/city/${l.city_id}`}>{l.name}</Link> <span className="small muted">{l.country ?? l.country_id}</span></td>
      <td className="num">{fmtDistance(l.km, units)}</td>
      <td className="num">{l.km < 300 ? "–" : flightTime(l.km)}</td>
      <td className="num">{timeDiff(d.city.timezone, l.timezone)}</td>
      <td className="num">{compass(l.bearing)}</td>
      <td>{l.kind === "added" && <button type="button" className="link small" onClick={() => keep(added.filter((x) => x !== l.city_id))}
        title="Take this city off the list">remove</button>}</td>
    </tr>
  );
  const text = () => [`From,${name}`, "City,Country,km,Bearing,Time difference",
    ...[...legs, ...d.nearest].map((l) => `${l.name},${l.country ?? l.country_id},${Math.round(l.km)},${l.bearing},${timeDiff(d.city.timezone, l.timezone)}`)].join("\n");

  return (
    <section className="card">
      <div className="title-row">
        <h3>Distance to…</h3>
        <span className="small">
          <span className="seg" role="group" aria-label="Units">
            {(Object.keys(UNIT_LABEL) as Units[]).map((u) => (
              <button key={u} type="button" className={u === units ? "on" : ""} onClick={() => setUnits(u)}>{UNIT_LABEL[u]}</button>))}
          </span>{" "}
          <CardAsk onAsk={() => openAsk({ title: `Distances from ${name}`, entity: d.city.country_id,
            parts: [{ key: "data", kind: "data", label: "Distances", text: text() }] })} />
        </span>
      </div>
      <div className="grid two">
        <div style={{ minWidth: 0 }}>
          <div className="table-wrap">
            <table className="summary-table">
              <thead><tr><th>City</th><th className="num">Distance</th><th className="num">Flight</th><th className="num">Time diff.</th><th className="num">Set off</th><th /></tr></thead>
              <tbody>{legs.map(row)}</tbody>
            </table>
          </div>
          <label className="small" style={{ display: "block", marginTop: 8 }}>
            Add a city{" "}
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Type a city name" style={{ width: 200 }} />
          </label>
          {hits.length > 0 && (
            <p className="small" style={{ margin: "4px 0" }}>
              {hits.filter((h) => h.city_id !== cityId).map((h, i) => (
                <span key={h.city_id}>{i > 0 && " · "}
                  <button type="button" className="link" onClick={() => { keep([...added.filter((x) => x !== h.city_id), h.city_id].slice(-20)); setQ(""); setHits([]); }}>
                    {h.name}</button> <span className="muted">{h.country ?? h.country_id}</span></span>))}
            </p>
          )}
          {d.missing.length > 0 && <p className="caption">Not found among the cities: {d.missing.join(", ")} (Settings &gt; City pages).</p>}
          <p className="caption">
            Straight over the globe (great circle). Flight time is a rough guide: 850 km/h plus half an hour.
            Time difference is for today, so daylight saving is counted. &ldquo;Set off&rdquo; is the compass bearing at the start.
            Key cities are set in <Link href="/settings#city-pages">Settings</Link>; cities you add are remembered in this browser.
          </p>
        </div>
        <div style={{ minWidth: 0 }}>
          <div className="city-map small">
            <WorldMap fill values={[]} unit="" decimals={0} diverging={false} onPick={() => {}} points={points} fitPoints paths={paths} />
          </div>
          {d.nearest.length > 0 && (
            <>
              <h4 style={{ margin: "10px 0 4px" }}>Nearest big cities</h4>
              <table className="summary-table">
                <thead><tr><th>City</th><th className="num">Distance</th><th className="num">People</th></tr></thead>
                <tbody>{d.nearest.map((l) => (
                  <tr key={l.city_id}><td><Link href={`/city/${l.city_id}`}>{l.name}</Link>
                    {l.country_id !== d.city.country_id && <span className="small muted"> {l.country ?? l.country_id}</span>}</td>
                    <td className="num">{fmtDistance(l.km, units)}</td><td className="num">{people(l.population)}</td></tr>))}</tbody>
              </table>
              <p className="caption">Cities of 100,000 people or more (GeoNames).</p>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
