// The Scorecard page's data (the API's /scorecard): life in the countries picked, measure by
// measure, each cell ranked among them.
import { get } from "@/lib/api";

export type ScoreCell = { value: number; year: number; rank: number; position: number; best: boolean; world_rank: number | null };
export type ScoreRow = {
  id: string; label: string; unit: string; better: "higher" | "lower"; decimals: number; percent: boolean;
  indicator_id: string | null; indicator_name: string | null; source: string | null; get: string | null;
  year: number | null; world_of: number | null; cells: Record<string, ScoreCell>;
};
export type Scorecard = {
  countries: { entity_id: string; name: string; wins: number; measures: number }[];
  groups: { name: string; rows: ScoreRow[] }[];
  missing: { id: string; label: string; get: string | null; source: string | null; tried: string[] }[];
  measures: number;
  sets: { name: string; ids: string[] }[];
  default_countries: string[];
};

export const scorecardApi = {
  get: (countries: string[]) => get<Scorecard>("/scorecard", { countries: countries.length ? countries.join(",") : undefined }),
};

// Six steps from worst (red) to best (green), as the cells are coloured.
export const STEPS = 6;
export const stepOf = (position: number) => Math.min(STEPS - 1, Math.max(0, Math.round(position * (STEPS - 1))));

export function cellText(r: ScoreRow, v: number): string {
  // 99.9% is not shown as 100%: a share just short of everyone keeps a decimal, so the star
  // never seems to skip a cell that reads the same.
  const d = r.percent && v >= 99.5 && v < 99.95 ? 1 : r.percent && Math.abs(v - Math.round(v)) < 0.05 ? 0 : r.decimals;
  const s = v.toLocaleString("en-NZ", { minimumFractionDigits: d, maximumFractionDigits: d });
  return r.percent ? `${s}%` : s;
}

// Sources saved by hand, which the Missing card says to save rather than refresh.
export const BY_HAND = new Set(["walkfree_gsi", "wid_gender"]);
