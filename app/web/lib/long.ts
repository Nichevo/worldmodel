// Shared pieces of the Long history page: year labels (negative years are BC, there is no
// year 0), colours for event kinds and empires, and a straight-line value between known years.

import type { LongEvent } from "@/lib/api";
import { seriesColor } from "@/lib/colors";
import { compact } from "@/lib/format";

export function yl(y: number | null | undefined): string {
  if (y === null || y === undefined || !Number.isFinite(y)) return "";
  const r = Math.round(y);
  if (r < 0) return `${(-r).toLocaleString("en")} BC`;
  return r < 1000 ? `AD ${r}` : String(r);
}

// Axis labels: short, no "AD" clutter on a crowded axis.
export function axisYear(y: number): string {
  const r = Math.round(y);
  return r < 0 ? `${(-r).toLocaleString("en")} BC` : r === 0 ? "AD 1" : String(r);
}

export const KIND_GROUP: Record<string, "war" | "disaster" | "plague"> = {
  war: "war", battle: "war", siege: "war", revolution: "war", treaty: "war",
  epidemic: "plague", famine: "plague", earthquake: "disaster", volcano: "disaster", tsunami: "disaster",
};
export const GROUP_LABEL = { war: "Wars, battles, revolutions, treaties", plague: "Plagues and famines", disaster: "Earthquakes, eruptions, tsunamis" };

export function kindColor(kind: string): string {
  const g = KIND_GROUP[kind] ?? "war";
  return g === "war" ? seriesColor(7) : g === "plague" ? seriesColor(4) : seriesColor(6);  // red, pink, purple
}

// A colour per empire name (the API gives a hue), the same in every view.
export function hueColor(hue: number, light = false): string {
  const dark = typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches
    && document.documentElement.dataset.theme !== "light";
  return `hsl(${hue} ${light ? 45 : 55}% ${dark ? (light ? 32 : 45) : (light ? 78 : 58)}%)`;
}

export function interp(points: [number, number | null][], year: number): number | null {
  for (let i = 0; i + 1 < points.length; i++) {
    const [y0, v0] = points[i], [y1, v1] = points[i + 1];
    if (y0 <= year && year <= y1 && v0 !== null && v1 !== null) return y1 === y0 ? v0 : v0 + ((v1 - v0) * (year - y0)) / (y1 - y0);
  }
  return null;
}

export function eventLine(e: LongEvent): string {
  const deaths = e.deaths ? `, about ${compact(e.deaths)} deaths` : "";
  const size = e.size ? `, ${e.size_unit === "magnitude" ? `magnitude ${e.size}` : e.size_unit === "VEI" ? `VEI ${e.size}` : `${e.size} m waves`}` : "";
  return `${e.title} (${e.when}${deaths}${size})`;
}

export const SQ_KM = (v: number | null | undefined) => (v === null || v === undefined ? "" : `${(v / 1e6).toFixed(v >= 1e7 ? 1 : 2)} million km²`);

export const FROM_CHOICES: { label: string; year: number }[] = [
  { label: "10,000 BC", year: -10000 }, { label: "3000 BC", year: -3000 }, { label: "1000 BC", year: -1000 },
  { label: "AD 1", year: 1 }, { label: "1000", year: 1000 }, { label: "1500", year: 1500 }, { label: "1800", year: 1800 },
];
