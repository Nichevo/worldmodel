// The shared look: colours that mean something and stay the same everywhere.
// Values live as CSS variables in globals.css (light and dark each have their own),
// so every colour here is read at draw time.

import { cssVar, seriesColor } from "@/lib/colors";
import { compact, formatValue } from "@/lib/format";

// Switches from Settings > Look of charts, kept here so the chart builders (plain functions)
// can read them; lib/settings.ts updates them whenever the settings change.
export const look = { endLabels: true, values: true, findings: true, eventLabels: true };

// A value short enough for a label on a chart: 4.95M, $48.2k, 1.56, 3.4%.
export function shortValue(v: number, unit: string, decimals = 1): string {
  if (Math.abs(v) < 1e4) return formatValue(v, unit, decimals).replace(/ (people|persons)$/, "");
  const c = compact(v);
  return unit === "US dollars" || unit === "US dollars per person" ? `$${c}` : c;
}

// The four countries this app watches most always draw in the same colour, as do the
// world and the main groups; anyone else takes the next free series colour.
export const FIXED_ENTITY: Record<string, string> = {
  NZL: "--c-nzl", AUS: "--c-aus", GBR: "--c-gbr", USA: "--c-usa",
  world: "--c-world", oecd: "--c-oecd", g20: "--c-g20", eu: "--c-eu",
};
// Series colours too close to a fixed one, skipped while that one is on the chart.
const NEAR: Record<string, number[]> = { "--c-usa": [0], "--c-aus": [3], "--c-gbr": [7], "--c-nzl": [], "--c-world": [], "--c-oecd": [6], "--c-g20": [1], "--c-eu": [] };

// A colour per entity id, in order.
export function entityColors(ids: string[]): string[] {
  const fixed = ids.map((id) => FIXED_ENTITY[id] ?? FIXED_ENTITY[id.replace(/:.*$/, "")]);
  const skip = new Set(fixed.filter(Boolean).flatMap((v) => NEAR[v!] ?? []));
  let next = 0;
  return fixed.map((v) => {
    if (v) return cssVar(v);
    while (skip.has(next % 8) && skip.size < 8) next++;
    return seriesColor(next++);
  });
}
export const entityVar = (id: string, i: number) => (FIXED_ENTITY[id] ? `var(${FIXED_ENTITY[id]})` : `var(--series-${(i % 8) + 1})`);

// Continents (and the UN regions named after them) by name.
const CONTINENT: [RegExp, string][] = [
  [/africa/i, "--cont-africa"], [/america|caribbean/i, "--cont-americas"], [/asia/i, "--cont-asia"],
  [/europe/i, "--cont-europe"], [/oceania|australia|pacific|melanesia|polynesia|micronesia/i, "--cont-oceania"], [/antarc/i, "--cont-antarctica"],
];
export function continentVar(name: string | undefined): string {
  const hit = CONTINENT.find(([re]) => re.test(name ?? ""));
  return hit ? hit[1] : "--muted";
}
export const continentColor = (name: string | undefined) => cssVar(continentVar(name));

// A change for the better or worse, given which way is better.
export function changeTone(delta: number, better: string | undefined): "good" | "bad" | "flat" {
  if (!delta || !better || better === "neither") return "flat";
  return (delta > 0) === (better === "higher") ? "good" : "bad";
}

// An SVG path for a small sparkline through [x, y] points, filling w x h.
export function sparkPath(pts: [number, number][], w: number, h: number, pad = 2): string {
  if (pts.length < 2) return "";
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const sx = (x: number) => pad + ((x - x0) / (x1 - x0 || 1)) * (w - 2 * pad);
  const sy = (y: number) => h - pad - ((y - y0) / (y1 - y0 || 1)) * (h - 2 * pad);
  return pts.map((p, i) => `${i ? "L" : "M"}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join("");
}
