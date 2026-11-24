"use client";

import { stripX, STRIP_KNEE, type IndicatorYears } from "@/lib/years";

// A small strip of an indicator's years on one shared scale (1700-1950 squeezed at the left,
// 1950-2100 across the rest): grey for history, orange for the source's own forecasts, darker
// where more countries have figures. A thin line marks this year.
export default function YearStrip({ years, first, last, lastHist, width = 84, title }: {
  years?: IndicatorYears; first?: number | null; last?: number | null; lastHist?: number | null; width?: number; title?: string;
}) {
  const h = 10;
  const now = new Date().getFullYear();
  const bars: { x: number; w: number; o: number; p: boolean }[] = [];
  if (years) {
    const peak = Math.max(1, ...years.e, ...years.p);
    // Figures every few years (censuses, five-year projections) run on to the next figure,
    // up to five years, so they read as one stretch; longer gaps stay empty.
    const add = (list: number[], p: boolean) => list.forEach((n, k) => {
      if (!n) return;
      let next = k + 1;
      while (next < list.length && next - k < 5 && !list[next]) next++;
      const to = next < list.length && list[next] ? next : k + 1;
      const x = stripX(years.from + k, width);
      bars.push({ x, w: Math.max(0.8, stripX(years.from + to, width) - x), o: 0.3 + 0.7 * (n / peak), p });
    });
    // In a year where some countries have figures and others only forecasts (the IMF's
    // latest year, say), the colour goes with whichever covers more countries.
    add(years.e.map((n, k) => (n >= (years.p[k] ?? 0) ? n : 0)), false);
    add(years.p.map((n, k) => (n > (years.e[k] ?? 0) ? n : 0)), true);
  } else if (first != null) {
    const end = lastHist ?? last ?? first;
    bars.push({ x: stripX(first, width), w: Math.max(1, stripX(end + 1, width) - stripX(first, width)), o: 0.8, p: false });
    if (last != null && last > end) bars.push({ x: stripX(end + 1, width), w: stripX(last + 1, width) - stripX(end + 1, width), o: 0.8, p: true });
  }
  return (
    <svg className="ystrip" shapeRendering="crispEdges" width={width} height={h} viewBox={`0 0 ${width} ${h}`} role="img" aria-label={title} >
      {title && <title>{title}</title>}
      <rect x={0} y={h / 2 - 0.5} width={width} height={1} className="ystrip-track" />
      <line x1={stripX(STRIP_KNEE, width)} x2={stripX(STRIP_KNEE, width)} y1={1} y2={h - 1} className="ystrip-knee" />
      {bars.map((b, k) => <rect key={k} x={b.x} y={1} width={b.w} height={h - 2} className={b.p ? "ystrip-p" : "ystrip-e"} opacity={b.o} />)}
      <line x1={stripX(now, width)} x2={stripX(now, width)} y1={0} y2={h} className="ystrip-now" />
    </svg>
  );
}
