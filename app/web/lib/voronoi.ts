// A Voronoi treemap: a convex shape (here a circle) cut into cells whose areas match given
// weights, each cell a power-diagram region (Nocaj & Brandes 2012, in the plain form that
// d3-voronoi-map uses): sites move to their cell's centre and weights grow or shrink until
// every cell has its share. Cells of a convex shape are convex, so each is found by cutting
// the outer polygon with one half-plane per other site. Fine for a few dozen cells.

export type Pt = [number, number];
export type Poly = Pt[];

export function polyArea(p: Poly): number {
  let a = 0;
  for (let i = 0, j = p.length - 1; i < p.length; j = i++) a += p[j][0] * p[i][1] - p[i][0] * p[j][1];
  return Math.abs(a) / 2;
}

export function polyCentroid(p: Poly): Pt {
  let a = 0, x = 0, y = 0;
  for (let i = 0, j = p.length - 1; i < p.length; j = i++) {
    const f = p[j][0] * p[i][1] - p[i][0] * p[j][1];
    a += f; x += (p[j][0] + p[i][0]) * f; y += (p[j][1] + p[i][1]) * f;
  }
  if (Math.abs(a) < 1e-12) return p[0] ?? [0, 0];
  return [x / (3 * a), y / (3 * a)];
}

// Keep the part of a convex polygon where a·x + b·y <= c.
function clip(p: Poly, a: number, b: number, c: number): Poly {
  const out: Poly = [];
  for (let i = 0; i < p.length; i++) {
    const s = p[i], e = p[(i + 1) % p.length];
    const ds = a * s[0] + b * s[1] - c, de = a * e[0] + b * e[1] - c;
    if (ds <= 0) out.push(s);
    if ((ds < 0 && de > 0) || (ds > 0 && de < 0)) {
      const t = ds / (ds - de);
      out.push([s[0] + t * (e[0] - s[0]), s[1] + t * (e[1] - s[1])]);
    }
  }
  return out;
}

// Each site's power cell inside the outer polygon.
function powerCells(outer: Poly, sites: Pt[], w: number[]): Poly[] {
  return sites.map((p, i) => {
    let cell = outer;
    for (let j = 0; j < sites.length && cell.length >= 3; j++) {
      if (j === i) continue;
      const q = sites[j];
      // |x-p|² - wi <= |x-q|² - wj  =>  2(q-p)·x <= |q|² - |p|² - wj + wi
      cell = clip(cell, 2 * (q[0] - p[0]), 2 * (q[1] - p[1]), q[0] ** 2 + q[1] ** 2 - p[0] ** 2 - p[1] ** 2 - w[j] + w[i]);
    }
    return cell.length >= 3 ? cell : [];
  });
}

// A small seeded random generator, so the same data always gives the same picture.
export function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function inside(p: Poly, x: number, y: number): boolean {
  for (let i = 0; i < p.length; i++) {
    const s = p[i], e = p[(i + 1) % p.length];
    if ((e[0] - s[0]) * (y - s[1]) - (e[1] - s[1]) * (x - s[0]) < 0) return false;
  }
  return true;
}

// Make the polygon counter-clockwise (in screen terms, y down, that is the "inside" test above).
function ccw(p: Poly): Poly {
  let a = 0;
  for (let i = 0, j = p.length - 1; i < p.length; j = i++) a += p[j][0] * p[i][1] - p[i][0] * p[j][1];
  return a < 0 ? [...p].reverse() : p;
}

type Opts = { seed?: number; start?: (Pt | null)[]; iterations?: number };

// Cut `outer` into cells with areas in proportion to `weights` (all > 0). `start` gives
// optional starting points (e.g. continents roughly where they are on the globe). Now and
// then a start leaves a small cell trapped between big ones; then a few other starts are
// tried and the closest fit kept.
export function voronoiTreemap(outer: Poly, weights: number[], opts: Opts = {}): Poly[] {
  let best: { cells: Poly[]; worst: number } | null = null;
  for (let k = 0; k < 4; k++) {
    const got = attempt(outer, weights, { ...opts, seed: (opts.seed ?? 7) + k * 101, start: k === 0 ? opts.start : undefined });
    if (!best || got.worst < best.worst) best = got;
    if (best.worst < 0.12) break;
  }
  return best!.cells;
}

function attempt(outer: Poly, weights: number[], opts: Opts): { cells: Poly[]; worst: number } {
  const n = weights.length;
  if (n === 0) return { cells: [], worst: 0 };
  outer = ccw(outer);
  if (n === 1) return { cells: [outer], worst: 0 };
  const total = weights.reduce((s, v) => s + v, 0);
  const area = polyArea(outer);
  const target = weights.map((v) => (v / total) * area);
  const rand = seeded(opts.seed ?? 7);
  const xs = outer.map((p) => p[0]), ys = outer.map((p) => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const c = polyCentroid(outer);
  const sites: Pt[] = weights.map((_, i) => {
    const s = opts.start?.[i];
    if (s && inside(outer, s[0], s[1])) return [s[0] + (rand() - 0.5) * 1e-3, s[1] + (rand() - 0.5) * 1e-3];
    for (let k = 0; k < 200; k++) {
      const x = x0 + rand() * (x1 - x0), y = y0 + rand() * (y1 - y0);
      if (inside(outer, x, y)) return [x, y];
    }
    return [c[0] + (rand() - 0.5), c[1] + (rand() - 0.5)];
  });
  // Start with equal weights a little under the mean cell's size, so no cell is empty.
  const w = weights.map(() => (area / n) * 0.1);
  const maxIt = opts.iterations ?? 250;
  let cells = powerCells(outer, sites, w);
  let worst = Infinity;
  for (let it = 0; it < maxIt; it++) {
    // move each site to its cell's centre
    cells.forEach((cell, i) => { if (cell.length) sites[i] = polyCentroid(cell); });
    // grow or shrink each weight by how far its cell is from its share
    cells = powerCells(outer, sites, w);
    let err = 0;
    worst = 0;
    for (let i = 0; i < n; i++) {
      const a = cells[i].length ? polyArea(cells[i]) : 0;
      err += Math.abs(a - target[i]);
      worst = Math.max(worst, Math.abs(a - target[i]) / target[i]);
      const ratio = a > 0 ? target[i] / a : 2;
      w[i] = Math.max(1e-6 * area, w[i] * Math.min(2, Math.max(0.5, ratio)));
    }
    // a site whose weight swallows a near neighbour's site would leave that cell empty
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
      if (i === j) continue;
      const d2 = (sites[i][0] - sites[j][0]) ** 2 + (sites[i][1] - sites[j][1]) ** 2;
      if (w[i] - w[j] > d2) w[i] = w[j] + d2 * 0.999;
    }
    cells = powerCells(outer, sites, w);
    if (err / area < 0.005 && worst < 0.04 && it > 20) break;
  }
  return { cells, worst };
}

// The point inside a convex polygon farthest from its edges, and that distance: where a
// label fits best, and how big it can be.
export function labelSpot(p: Poly): { at: Pt; r: number } {
  if (p.length < 3) return { at: p[0] ?? [0, 0], r: 0 };
  const q = ccw(p);
  const edges = q.map((s, i) => {
    const e = q[(i + 1) % q.length];
    const len = Math.hypot(e[0] - s[0], e[1] - s[1]) || 1;
    return { s, nx: -(e[1] - s[1]) / len, ny: (e[0] - s[0]) / len };
  });
  const dist = (x: number, y: number) => Math.min(...edges.map(({ s, nx, ny }) => (x - s[0]) * nx + (y - s[1]) * ny));
  let best = polyCentroid(q), bestD = dist(best[0], best[1]);
  const xs = q.map((v) => v[0]), ys = q.map((v) => v[1]);
  let span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) / 2;
  // a coarse search round the best point so far, narrowing each time
  for (let round = 0; round < 6; round++) {
    const [cx, cy] = best;
    for (let i = -4; i <= 4; i++) for (let j = -4; j <= 4; j++) {
      const x = cx + (i / 4) * span, y = cy + (j / 4) * span;
      const d = dist(x, y);
      if (d > bestD) { bestD = d; best = [x, y]; }
    }
    span /= 2.5;
  }
  return { at: best, r: Math.max(0, bestD) };
}

// A circle as a polygon with `n` corners.
export function circlePoly(cx: number, cy: number, r: number, n = 160): Poly {
  return Array.from({ length: n }, (_, i) => {
    const a = (i / n) * Math.PI * 2;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)] as Pt;
  });
}
