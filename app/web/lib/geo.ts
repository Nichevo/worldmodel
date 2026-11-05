// Country shapes, fetched once and shared by every map on the page.

let shapes: Promise<GeoJSON.FeatureCollection> | null = null;

export function countryShapes(): Promise<GeoJSON.FeatureCollection> {
  if (!shapes) {
    shapes = fetch("/geo/countries.json").then((r) => {
      if (!r.ok) throw new Error(`country shapes: ${r.status}`);
      return r.json();
    });
    shapes.catch(() => { shapes = null; });
  }
  return shapes;
}

// A point inside each country to draw trade routes from: the centre of its largest
// polygon (area-weighted), so France's lines start in France rather than between it
// and French Guiana. Worked out once per page.
let centres: Promise<Record<string, [number, number]>> | null = null;

function ringCentre(ring: number[][]): { area: number; c: [number, number] } {
  let a = 0, cx = 0, cy = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const f = ring[j][0] * ring[i][1] - ring[i][0] * ring[j][1];
    a += f; cx += (ring[j][0] + ring[i][0]) * f; cy += (ring[j][1] + ring[i][1]) * f;
  }
  if (!a) return { area: 0, c: [ring[0][0], ring[0][1]] };
  return { area: Math.abs(a / 2), c: [cx / (3 * a), cy / (3 * a)] };
}

export function countryCentres(): Promise<Record<string, [number, number]>> {
  if (!centres) {
    centres = countryShapes().then((fc) => {
      const out: Record<string, [number, number]> = {};
      for (const f of fc.features) {
        const iso = (f.properties as { iso3?: string } | null)?.iso3;
        const g = f.geometry;
        if (!iso || !g) continue;
        const polys = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
        let best: { area: number; c: [number, number] } | null = null;
        for (const p of polys) {
          const r = ringCentre(p[0] as number[][]);
          if (!best || r.area > best.area) best = r;
        }
        if (best) out[iso] = best.c;
      }
      return out;
    });
    centres.catch(() => { centres = null; });
  }
  return centres;
}

// A gently curved line between two points (a quadratic curve bowed to one side), so
// two-way routes between the same countries do not sit on top of each other.
export function arc(a: [number, number], b: [number, number], steps = 24): [number, number][] {
  let [x1, y1] = a;
  const [x2, y2] = b;
  if (Math.abs(x2 - x1) > 180) x1 += x2 > x1 ? 360 : -360; // the short way round
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
  const dx = x2 - x1, dy = y2 - y1;
  const cx = mx - dy * 0.2, cy = my + dx * 0.2;
  const out: [number, number][] = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    out.push([(1 - t) * (1 - t) * x1 + 2 * (1 - t) * t * cx + t * t * x2, (1 - t) * (1 - t) * y1 + 2 * (1 - t) * t * cy + t * t * y2]);
  }
  return out;
}
