// Circles packed into round clusters (the largest cities by continent), and clusters kept apart.
// No library: circles start on a sunflower spiral, biggest in the middle (or where they were last
// time, so a change of year moves them a little instead of shuffling), then are pushed apart and
// drawn together until none overlap.

export type Circ = { id: string; r: number; x: number; y: number };

const GOLDEN = Math.PI * (3 - Math.sqrt(5));

export function packCluster(items: { id: string; r: number }[], prev?: Map<string, { x: number; y: number }>, rounds = 160): Circ[] {
  const cs: Circ[] = [...items].sort((a, b) => b.r - a.r).map((c) => ({ ...c, x: 0, y: 0 }));
  let area = 0;
  cs.forEach((c, i) => {
    const p = prev?.get(c.id);
    if (p) { c.x = p.x; c.y = p.y; } else {
      const d = Math.sqrt(area / Math.PI) * 1.1 + (i ? c.r : 0);
      c.x = d * Math.cos(i * GOLDEN); c.y = d * Math.sin(i * GOLDEN);
    }
    area += Math.PI * c.r * c.r;
  });
  const gap = 0.6;
  for (let k = 0; k < rounds; k++) {
    let moved = 0;
    for (let i = 0; i < cs.length; i++) {
      const a = cs[i];
      for (let j = i + 1; j < cs.length; j++) {
        const b = cs[j];
        const dx = b.x - a.x, dy = b.y - a.y;
        const lim = a.r + b.r + gap;
        if (Math.abs(dx) > lim || Math.abs(dy) > lim) continue;
        const d = Math.hypot(dx, dy) || 0.01;
        const over = lim - d;
        if (over > 0) {
          const wa = b.r / (a.r + b.r), ux = dx / d, uy = dy / d;
          a.x -= ux * over * wa; a.y -= uy * over * wa;
          b.x += ux * over * (1 - wa); b.y += uy * over * (1 - wa);
          moved += over;
        }
      }
    }
    const pull = k < rounds - 20 ? 0.04 : 0; // the last rounds only separate
    for (const c of cs) { c.x -= c.x * pull; c.y -= c.y * pull; }
    if (pull === 0 && moved < 0.1) break;
  }
  // centre the cluster on its own middle
  const mx = cs.reduce((s, c) => s + c.x * c.r * c.r, 0) / Math.max(1e-9, cs.reduce((s, c) => s + c.r * c.r, 0));
  const my = cs.reduce((s, c) => s + c.y * c.r * c.r, 0) / Math.max(1e-9, cs.reduce((s, c) => s + c.r * c.r, 0));
  for (const c of cs) { c.x -= mx; c.y -= my; }
  return cs;
}

export function clusterRadius(cs: Circ[]): number {
  return Math.max(1, ...cs.map((c) => Math.hypot(c.x, c.y) + c.r));
}

// Clusters (each a circle round its packed cities) near their anchors without overlapping.
export function placeClusters(cl: { key: string; r: number; ax: number; ay: number }[], gap = 26): Record<string, { x: number; y: number }> {
  const p = cl.map((c) => ({ ...c, x: c.ax, y: c.ay }));
  for (let k = 0; k < 300; k++) {
    let moved = 0;
    for (let i = 0; i < p.length; i++) for (let j = i + 1; j < p.length; j++) {
      const a = p[i], b = p[j];
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 0.01;
      const over = a.r + b.r + gap - d;
      if (over > 0) {
        const wa = b.r / (a.r + b.r);
        a.x -= (dx / d) * over * wa; a.y -= (dy / d) * over * wa;
        b.x += (dx / d) * over * (1 - wa); b.y += (dy / d) * over * (1 - wa);
        moved += over;
      }
    }
    for (const c of p) { c.x += (c.ax - c.x) * 0.03; c.y += (c.ay - c.y) * 0.03; }
    if (moved < 0.1 && k > 20) break;
  }
  return Object.fromEntries(p.map((c) => [c.key, { x: c.x, y: c.y }]));
}
