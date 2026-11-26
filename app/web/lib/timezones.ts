// Time zones and day and night for the map. The zone outlines come from the server
// (timezone-boundary-builder, named by IANA zone); each zone's offset, daylight saving and
// local time are worked out here with the browser's own time zone rules, so they are right
// on the day you look. The night shade is worked out here from the Sun's position.

const formats = new Map<string, Intl.DateTimeFormat | null>();
function parts(tz: string): Intl.DateTimeFormat | null {
  if (!formats.has(tz)) {
    try {
      formats.set(tz, new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric" }));
    } catch {
      formats.set(tz, null); // a zone this browser doesn't know
    }
  }
  return formats.get(tz)!;
}

// Minutes ahead of UTC in zone tz at time t (ms), or null for a zone the browser doesn't know.
export function offsetMinutes(tz: string, t: number = Date.now()): number | null {
  const f = parts(tz);
  if (!f) return null;
  const p: Record<string, number> = {};
  for (const x of f.formatToParts(new Date(t))) if (x.type !== "literal") p[x.type] = Number(x.value);
  const local = Date.UTC(p.year, p.month - 1, p.day, p.hour % 24, p.minute);
  return Math.round((local - Math.floor(t / 60000) * 60000) / 60000);
}

// "UTC+13", "UTC+5:30", "UTC−3", "UTC".
export function offsetLabel(min: number, utc = true): string {
  if (!min) return utc ? "UTC" : "±0";
  const h = Math.floor(Math.abs(min) / 60), m = Math.abs(min) % 60;
  return `${utc ? "UTC" : ""}${min > 0 ? "+" : "−"}${h}${m ? `:${String(m).padStart(2, "0")}` : ""}`;
}

type Rules = { dst: boolean; std: number; next: { at: number; to: number } | null; until: number };
const rules = new Map<string, Rules>();
// Whether zone tz is on daylight saving now, its standard offset, and when its clocks next change
// (within a year), kept until that change or for a day.
export function zoneRules(tz: string, t: number = Date.now()): Rules | null {
  const kept = rules.get(tz);
  if (kept && t < kept.until) return kept;
  const now = offsetMinutes(tz, t);
  if (now === null) return null;
  const y = new Date(t).getUTCFullYear();
  const jan = offsetMinutes(tz, Date.UTC(y, 0, 1))!, jul = offsetMinutes(tz, Date.UTC(y, 6, 1))!;
  const std = Math.min(jan, jul);
  // The next change: a day at a time for a year, then to the minute.
  const DAY = 86_400_000;
  let next: Rules["next"] = null;
  for (let d = 1; d <= 370; d++) {
    if (offsetMinutes(tz, t + d * DAY) !== now) {
      let lo = t + (d - 1) * DAY, hi = t + d * DAY;
      while (hi - lo > 60_000) {
        const mid = Math.floor((lo + hi) / 2);
        if (offsetMinutes(tz, mid) === now) lo = mid; else hi = mid;
      }
      next = { at: hi, to: offsetMinutes(tz, hi)! };
      break;
    }
  }
  const r: Rules = { dst: jan !== jul && now > std, std, next, until: Math.min(next?.at ?? Infinity, t + DAY) };
  rules.set(tz, r);
  return r;
}

// The clock in zone tz now: "Fri 14:05".
export function localClock(tz: string, t: number = Date.now()): string {
  try {
    return new Intl.DateTimeFormat("en-GB", { timeZone: tz, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(t));
  } catch {
    return "";
  }
}

// A zone's name as people say it: "Pacific/Auckland" -> "Auckland"; "Etc/GMT+12" -> "Sea zone".
export function zoneName(tz: string): string {
  if (tz.startsWith("Etc/")) return "Open sea (nautical time)";
  return tz.split("/").slice(1).join(" / ").replace(/_/g, " ") || tz;
}

// The hover text for a zone: its name, local time, offset, daylight saving and the next change.
export function zoneText(tz: string, esc: (v: unknown) => string, t: number = Date.now()): string {
  const off = offsetMinutes(tz, t);
  if (off === null) return `<b>${esc(tz)}</b><br/><span class="muted">This browser doesn't know this zone</span>`;
  const r = zoneRules(tz, t);
  const when = (ms: number) => new Intl.DateTimeFormat("en-GB", { timeZone: tz, weekday: "short", day: "numeric", month: "short", year: "numeric" }).format(new Date(ms));
  const change = r?.next
    ? `<br/>Clocks go ${r.next.to > off ? "forward" : "back"} ${offsetLabel(Math.abs(r.next.to - off), false).replace(/^[+−]/, "")} hour${Math.abs(r.next.to - off) === 60 ? "" : "s"} on ${when(r.next.at)}`
    : "<br/>No daylight saving";
  return `<b>${esc(localClock(tz, t))}</b> ${esc(zoneName(tz))}<br/>${offsetLabel(off)}${r?.dst ? ` (daylight saving; standard ${offsetLabel(r.std)})` : ""}`
    + `${change}<br/><span class="muted">${esc(tz)}</span>`;
}

// Each zone's offset now, for the colours and labels: hours ahead of UTC, daylight saving, and a label.
export function withOffsets(fc: GeoJSON.FeatureCollection, t: number = Date.now()): GeoJSON.FeatureCollection {
  for (const f of fc.features) {
    const p = (f.properties ??= {});
    const tz = String(p.tz ?? p.name ?? "");
    const off = offsetMinutes(tz, t);
    if (off === null) continue;
    const r = zoneRules(tz, t);
    p.offset = off / 60;
    p.dst = Boolean(r?.dst);
    p.half = off % 60 !== 0;
    p.label = `${offsetLabel(off, false)}${r?.dst ? "\nDST" : ""}`;
  }
  return fc;
}

// ---------------------------------------------------------------------------- day and night
// The Sun's position at time t: the latitude and longitude it is straight overhead (degrees).
export function subsolar(t: number = Date.now()): { lat: number; lng: number } {
  const d = t / 86_400_000 + 2440587.5 - 2451545.0; // days since J2000
  const rad = Math.PI / 180;
  const g = (357.529 + 0.98560028 * d) * rad;
  const q = 280.459 + 0.98564736 * d;
  const L = (q + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * rad;
  const e = (23.439 - 0.00000036 * d) * rad;
  const ra = Math.atan2(Math.cos(e) * Math.sin(L), Math.cos(L)) / rad;
  const dec = Math.asin(Math.sin(e) * Math.sin(L)) / rad;
  const eqt = (((q - ra) % 360) + 540) % 360 - 180; // equation of time, degrees
  const utcMin = ((t % 86_400_000) + 86_400_000) % 86_400_000 / 60000;
  const lng = ((-((utcMin - 720) / 4) - eqt) % 360 + 540) % 360 - 180;
  return { lat: dec, lng };
}

// The part of the globe where the Sun is more than `below` degrees under the horizon, as a
// polygon: worked meridian by meridian (half a degree apart), so it never needs to cross the
// date line or a pole the hard way.
function shadow(sun: { lat: number; lng: number }, below: number): GeoJSON.Polygon[] {
  const rad = Math.PI / 180;
  const a = -sun.lat * rad, b = sun.lng + 180; // the point opposite the Sun
  const c = Math.cos((90 - below) * rad); // inside: cos(distance to it) >= c
  const pole = (lat: number) => Math.sin(lat * rad) * Math.sin(a) >= c; // pole inside?
  const north = pole(90), south = pole(-90);
  const spans: ([number, number] | null)[] = [];
  const lngs: number[] = [];
  for (let lng = -180; lng <= 180; lng += 0.5) {
    const dl = (lng - b) * rad;
    const A = Math.sin(a), B = Math.cos(a) * Math.cos(dl);
    const R = Math.hypot(A, B), alpha = Math.atan2(B, A);
    lngs.push(lng);
    if (c / R > 1) { spans.push(null); continue; }
    const s = Math.asin(c / R);
    // sin(phi + alpha) >= c/R: phi + alpha in [s, pi - s], on this meridian (phi in [-90, 90])
    let lo = s - alpha, hi = Math.PI - s - alpha;
    const shift = Math.round(((lo + hi) / 2) / (2 * Math.PI)) * 2 * Math.PI;
    lo -= shift; hi -= shift;
    const L = Math.max(lo, -Math.PI / 2), H = Math.min(hi, Math.PI / 2);
    spans.push(L <= H ? [L / rad, H / rad] : null);
  }
  if (north || south) {
    // A cap round a pole: its edge along every meridian, then round by the pole.
    const edge = lngs.map((lng, i) => [lng, spans[i] ? (north ? spans[i]![0] : spans[i]![1]) : (north ? 90 : -90)]);
    const p = north ? 90 : -90;
    return [{ type: "Polygon", coordinates: [[...edge, [180, p], [-180, p], edge[0]]] }];
  }
  // A cap clear of both poles: the meridians it covers, unrolled past 180 when it crosses the date line.
  const on = spans.map((s) => s !== null);
  if (!on.some(Boolean)) return [];
  let start = on.findIndex((x, i) => x && !on[(i - 1 + on.length) % on.length]);
  if (start < 0) start = 0;
  const run: { lng: number; s: [number, number] }[] = [];
  for (let k = 0; k < on.length; k++) {
    const i = (start + k) % on.length;
    if (!on[i]) break;
    run.push({ lng: lngs[i] + (start + k >= on.length ? 360 : 0), s: spans[i]! });
  }
  const ring = [...run.map((r) => [r.lng, r.s[1]]), ...run.reverse().map((r) => [r.lng, r.s[0]])];
  ring.push(ring[0]);
  const shifted = (dx: number): GeoJSON.Polygon => ({ type: "Polygon", coordinates: [ring.map(([x, y]) => [x + dx, y])] });
  return [shifted(0), shifted(-360)];
}

// Night now, in bands: twilight (Sun just under the horizon) to full night (18° under).
export const NIGHT_BANDS = [
  { below: 0.833, label: "Sun down" },
  { below: 6, label: "Civil twilight over" },
  { below: 12, label: "Nautical twilight over" },
  { below: 18, label: "Full night" },
];
export function nightNow(t: number = Date.now()): GeoJSON.FeatureCollection & { loaded?: boolean } {
  const sun = subsolar(t);
  const features: GeoJSON.Feature[] = [];
  NIGHT_BANDS.forEach((band, i) => {
    for (const g of shadow(sun, band.below)) features.push({ type: "Feature", geometry: g, properties: { band: i, label: band.label } });
  });
  return { type: "FeatureCollection", features };
}
