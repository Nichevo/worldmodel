// Map shapes worked out on this PC: true size (a country moved north or south keeps its real
// size, so it swells on the usual Mercator map as it nears a pole), the Equal Earth projection
// (every country at its true area), areas in km², and circle cartograms (Dorling style: one
// circle per country, sized by a figure, nudged apart so none overlap).

type Ring = number[][];
type Poly = Ring[];

export const polygons = (g: GeoJSON.Geometry | null): Poly[] =>
  !g ? [] : g.type === "Polygon" ? [g.coordinates as Poly] : g.type === "MultiPolygon" ? (g.coordinates as Poly[]) : [];

const RAD = Math.PI / 180;
const R_KM = 6371.0088;
const wrap = (d: number) => ((((d + 180) % 360) + 360) % 360) - 180;

// ---------------------------------------------------------------------------- true size
// Each point keeps its distance north-south and east-west (in km) from the country's centre,
// so the outline drawn at the new centre is the country's real size there.
export function moveTo(polys: Poly[], from: [number, number], to: [number, number]): Poly[] {
  const [lon0, lat0] = from;
  const [lon1, lat1] = to;
  return polys.map((poly) => poly.map((ring) => ring.map(([lon, lat]) => {
    const dy = lat - lat0;
    const dxKm = wrap(lon - lon0) * Math.cos(lat * RAD);
    const nlat = Math.max(-85, Math.min(85, lat1 + dy));
    const nlon = lon1 + dxKm / Math.max(0.01, Math.cos(nlat * RAD));
    return [nlon, nlat];
  })));
}

// How many times bigger a shape at this latitude looks on a Mercator map than at the equator.
export const mercatorStretch = (lat: number) => 1 / Math.cos(Math.max(-85, Math.min(85, lat)) * RAD) ** 2;

// ---------------------------------------------------------------------------- area
function ringArea(ring: Ring): number {
  let sum = 0;
  for (let i = 0; i < ring.length - 1; i++) {
    const [l1, p1] = ring[i];
    const [l2, p2] = ring[i + 1];
    sum += wrap(l2 - l1) * RAD * (2 + Math.sin(p1 * RAD) + Math.sin(p2 * RAD));
  }
  return Math.abs((sum * R_KM * R_KM) / 2);
}

export function areaKm2(polys: Poly[]): number {
  return polys.reduce((a, poly) => a + ringArea(poly[0]) - poly.slice(1).reduce((h, r) => h + ringArea(r), 0), 0);
}

// ---------------------------------------------------------------------------- Equal Earth
const A1 = 1.340264, A2 = -0.081106, A3 = 0.000893, A4 = 0.003796, M = Math.sqrt(3) / 2;

export function equalEarth(lon: number, lat: number, centre = 0): [number, number] {
  const l = wrap(lon - centre) * RAD;
  const t = Math.asin(M * Math.sin(lat * RAD));
  const t2 = t * t, t6 = t2 * t2 * t2;
  const x = (l * Math.cos(t)) / (M * (A1 + 3 * A2 * t2 + t6 * (7 * A3 + 9 * A4 * t2)));
  const y = t * (A1 + A2 * t2 + t6 * (A3 + A4 * t2));
  return [x, -y];
}
export const EE_W = 2 * Math.abs(equalEarth(180, 0)[0]);
export const EE_H = 2 * Math.abs(equalEarth(0, 90)[1]);

// An SVG path for polygons in Equal Earth, scaled to `scale` px per unit, with the origin at the
// map's centre. Rings that cross the map's edge are kept on one side (the clip trims the rest).
export function eePath(polys: Poly[], centre: number, scale: number, ox: number, oy: number): string {
  const parts: string[] = [];
  for (const poly of polys) {
    for (const ring of poly) {
      const ls = ring.map(([lon]) => wrap(lon - centre));
      const span = Math.max(...ls) - Math.min(...ls);
      const side = ls.reduce((a, b) => a + b, 0) >= 0 ? 1 : -1;
      let d = "";
      ring.forEach(([lon, lat], i) => {
        let l = ls[i];
        if (span > 180 && Math.sign(l) !== side) l += 360 * side; // keep the ring whole on its main side
        const t = Math.asin(M * Math.sin(lat * RAD));
        const t2 = t * t, t6 = t2 * t2 * t2;
        const x = (l * RAD * Math.cos(t)) / (M * (A1 + 3 * A2 * t2 + t6 * (7 * A3 + 9 * A4 * t2)));
        const y = -t * (A1 + A2 * t2 + t6 * (A3 + A4 * t2));
        d += `${i ? "L" : "M"}${(ox + x * scale).toFixed(1)},${(oy + y * scale).toFixed(1)}`;
      });
      parts.push(d + "Z");
    }
  }
  return parts.join("");
}

// The outline of the whole Earth in Equal Earth (for the sea and the clip).
export function eeOutline(scale: number, ox: number, oy: number): string {
  const pts: [number, number][] = [];
  for (let lat = -90; lat <= 90; lat += 2) pts.push(equalEarth(179.999, lat));
  for (let lat = 90; lat >= -90; lat -= 2) pts.push(equalEarth(-179.999, lat));
  return pts.map(([x, y], i) => `${i ? "L" : "M"}${(ox + x * scale).toFixed(1)},${(oy + y * scale).toFixed(1)}`).join("") + "Z";
}

// ---------------------------------------------------------------------------- circle cartogram
export type Bubble = { id: string; x: number; y: number; r: number; value: number };

// Circles start at each country's centre (in Equal Earth, px) with area in proportion to the
// figure, then are pushed apart a little at a time until they no longer overlap.
export function dorling(items: { id: string; x: number; y: number; value: number }[], maxR: number, rounds = 120, box?: [number, number], fixedTop?: number): Bubble[] {
  const top = fixedTop ?? Math.max(...items.map((i) => i.value), 1);
  const b: Bubble[] = items.filter((i) => i.value > 0).map((i) => ({ ...i, r: Math.max(1.2, maxR * Math.sqrt(i.value / top)) }));
  const home = b.map((c) => [c.x, c.y]);
  for (let k = 0; k < rounds; k++) {
    let moved = 0;
    for (let i = 0; i < b.length; i++) {
      for (let j = i + 1; j < b.length; j++) {
        const dx = b[j].x - b[i].x, dy = b[j].y - b[i].y;
        const d = Math.hypot(dx, dy) || 0.01;
        const gap = b[i].r + b[j].r + 0.5 - d;
        if (gap > 0) {
          const wi = b[j].r / (b[i].r + b[j].r), wj = 1 - wi; // the small one moves more
          const ux = dx / d, uy = dy / d;
          b[i].x -= ux * gap * wi; b[i].y -= uy * gap * wi;
          b[j].x += ux * gap * wj; b[j].y += uy * gap * wj;
          moved += gap;
        }
      }
    }
    for (let i = 0; i < b.length; i++) { // a gentle pull home keeps the world's shape
      b[i].x += (home[i][0] - b[i].x) * 0.05;
      b[i].y += (home[i][1] - b[i].y) * 0.05;
      if (box) { // keep inside the picture
        b[i].x = Math.min(box[0] - b[i].r, Math.max(b[i].r, b[i].x));
        b[i].y = Math.min(box[1] - b[i].r, Math.max(b[i].r, b[i].y));
      }
    }
    if (moved < 0.5) break;
  }
  return b;
}
