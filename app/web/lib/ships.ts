// Saved ships: the time the map's Ships layer shows (null: now), the collector's status, and
// where a clicked ship or plane has come from and is going.
import { useEffect, useState, useSyncExternalStore } from "react";
import { get } from "@/lib/api";

let shipsAt: number | null = null; // seconds since 1970
const subs = new Set<() => void>();

export function setShipsAt(t: number | null) {
  if (t === shipsAt) return;
  shipsAt = t;
  subs.forEach((f) => f());
  // the map's window layers are asked again on this event (WorldMap follow())
  if (typeof window !== "undefined") window.dispatchEvent(new Event("wm-layer-window"));
}
export function useShipsAt(): number | null {
  return useSyncExternalStore((f) => { subs.add(f); return () => { subs.delete(f); }; }, () => shipsAt, () => null);
}
export const shipsAtQuery = () => (shipsAt ? `&at=${Math.round(shipsAt)}` : "");

export type ShipStatus = {
  collecting: boolean; area: string; connected: boolean; error: string | null; days: number; bytes: number;
  first: number | null; last: number | null; ships?: number; keep_days: number; in_memory: number;
  world_every_hours: number; world_note: string | null;
};
export function useShipStatus(on: boolean): ShipStatus | null {
  const [st, setSt] = useState<ShipStatus | null>(null);
  useEffect(() => {
    if (!on) return;
    let live = true;
    const load = () => get<ShipStatus>("/live/ships/status").then((s) => live && setSt(s)).catch(() => {});
    load();
    const t = setInterval(load, 60_000);
    return () => { live = false; clearInterval(t); };
  }, [on]);
  return st;
}

export type PlaneStatus = { collecting: boolean; days: number; bytes: number; first: number | null; last: number | null; planes?: number; keep_days: number };
export function usePlaneStatus(on: boolean): PlaneStatus | null {
  const [st, setSt] = useState<PlaneStatus | null>(null);
  useEffect(() => {
    if (!on) return;
    let live = true;
    const load = () => get<PlaneStatus>("/live/planes/status").then((s) => live && setSt(s)).catch(() => {});
    load();
    const t = setInterval(load, 60_000);
    return () => { live = false; clearInterval(t); };
  }, [on]);
  return st;
}

type Place = { name: string | null; lon: number; lat: number; iata?: string | null; icao?: string | null; city?: string | null; country?: string | null; locode?: string | null };
export type Journey = {
  track: (GeoJSON.FeatureCollection & { from?: number | null; points?: number }) | null;
  // ships
  destination?: string | null; eta?: string | null; port?: Place | null; note?: string | null;
  // planes
  route?: { codes: string; plausible: boolean; airports: Place[] } | null; from_airport?: Place | null;
  airline?: { code: string; name: string; country: string; iata: string } | null;
  kept_at?: number; // when the path was asked of OpenSky, if this answer was kept from then
  aircraft?: { registration?: string; type?: string; description?: string; operator?: string; year?: string; emergency?: string | null;
    squawk?: string; target_altitude_m?: number | null; military?: boolean } | null;
};

export function shipJourney(mmsi: string | number) {
  return get<Journey>(`/live/ships/journey/${encodeURIComponent(String(mmsi))}`);
}
export function planeJourney(icao24: string, callsign?: string | null, lng?: number, lat?: number) {
  const q = new URLSearchParams();
  if (callsign) q.set("callsign", callsign);
  if (lng !== undefined && lat !== undefined) { q.set("lon", lng.toFixed(3)); q.set("lat", lat.toFixed(3)); }
  return get<Journey>(`/live/planes/journey/${encodeURIComponent(icao24)}?${q.toString()}`);
}

// The lines to draw for a journey: the path so far (solid) and a straight line on to where it
// says it is going (dashed), as one collection with a "part" property.
export function journeyLines(j: Journey, at: { lng: number; lat: number }, plane: boolean): GeoJSON.FeatureCollection {
  const feats: GeoJSON.Feature[] = [];
  for (const f of j.track?.features ?? []) feats.push({ ...f, properties: { part: "path" } });
  const to = plane ? j.route?.airports?.[j.route.airports.length - 1] : j.port;
  if (to && typeof to.lon === "number") {
    feats.push({ type: "Feature", properties: { part: "ahead" }, geometry: { type: "LineString", coordinates: [[at.lng, at.lat], [to.lon, to.lat]] } });
  }
  const from = plane ? (j.route?.airports?.[0] ?? j.from_airport) : null;
  if (from && typeof from.lon === "number") feats.push({ type: "Feature", properties: { part: "end" }, geometry: { type: "Point", coordinates: [from.lon, from.lat] } });
  if (to && typeof to.lon === "number") feats.push({ type: "Feature", properties: { part: "end" }, geometry: { type: "Point", coordinates: [to.lon, to.lat] } });
  return { type: "FeatureCollection", features: feats };
}

const place = (p?: Place | null) => (p ? [p.name, p.iata ? `(${p.iata})` : p.locode ? `(${p.locode})` : ""].filter(Boolean).join(" ") : "");
const ago = (t?: number | null) => {
  if (!t) return "";
  const h = (Date.now() / 1000 - t) / 3600;
  return h < 1 ? `${Math.max(1, Math.round(h * 60))} min ago` : h < 48 ? `${Math.round(h)} h ago` : `${Math.round(h / 24)} days ago`;
};

// The card's lines for a clicked ship or plane.
export function journeyText(j: Journey, plane: boolean): string[] {
  const out: string[] = [];
  if (plane) {
    const a = j.aircraft;
    if (j.airline) out.push(`Airline: ${j.airline.name}${j.airline.country ? ` (${j.airline.country})` : ""}`);
    if (a && (a.type || a.registration)) out.push([a.description || a.type, a.registration].filter(Boolean).join(", ") + (a.operator ? ` (${a.operator})` : ""));
    if (a?.emergency) out.push(`Emergency: ${a.emergency}`);
    const r = j.route?.airports ?? [];
    if (r.length >= 2) out.push(`Route: ${place(r[0])} to ${place(r[r.length - 1])}${r.length > 2 ? ` via ${r.slice(1, -1).map(place).join(", ")}` : ""}${j.route?.plausible === false ? " (may not be this flight)" : ""}`);
    else if (j.from_airport) out.push(`Took off near ${place(j.from_airport)}`);
    else out.push("Route not known (only airline flights are in the route list)");
    if (typeof a?.target_altitude_m === "number") out.push(`Climbing or descending to ${a.target_altitude_m.toLocaleString()} m`);
    if (j.track?.from) out.push(`Path drawn from ${ago(j.track.from)}${j.kept_at ? ` (asked of OpenSky ${ago(j.kept_at)}; asked again after 30 min)` : ""}`);
  } else {
    if (j.destination) out.push(`Going to: ${j.destination}${j.port ? ` (${place(j.port)})` : ""}${j.eta ? `, due ${j.eta}` : ""}`);
    else out.push("No destination given");
    if (j.track?.points) out.push(`Path saved from ${ago(j.track.from)} (${j.track.points} positions)`);
  }
  if (j.note) out.push(j.note);
  return out;
}
