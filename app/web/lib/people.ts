import type { CardLine } from "@/lib/charts";
import type { RelPoint } from "@/lib/api";
import { seriesColor } from "@/lib/colors";

// One colour per religious group, the same on every chart and map.
export const REL_COLOR_INDEX: Record<string, number> = { christian: 0, muslim: 2, none: 7, hindu: 5, buddhist: 6, folk: 3, jewish: 4, other: 1 };
export const relColor = (g: string) => seriesColor(REL_COLOR_INDEX[g] ?? 1);

// Stacked lines (shares adding up to 100) from one source's points; projected years dashed.
export function religionLines(points: RelPoint[], groups: { id: string; name: string }[]): CardLine[] {
  return groups.map((g) => ({
    key: g.id, label: g.name, color: relColor(g.id),
    points: points.filter((p) => p.shares[g.id] !== undefined).map((p) => [p.year, p.shares[g.id], p.projected ? "P" : "E"] as [number, number, string]),
  })).filter((l) => l.points.length);
}

export const SOURCE_NOTE: Record<string, string> = {
  pew_religion: "Pew Research Center: censuses and surveys, every 10 years, projected to 2050 (dashed).",
  cow_religion: "Correlates of War World Religion Data: every 5 years from 1945 to 2010.",
  cia_factbook: "Each CIA Factbook edition's religions line, dated by the census or estimate it quotes (exploratory: wording varies).",
};

export function people(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)} billion`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e8 ? 0 : 1)} million`;
  if (n >= 1e3) return `${Math.round(n / 1e3)} thousand`;
  return String(Math.round(n));
}
