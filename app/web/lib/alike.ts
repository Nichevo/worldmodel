// Countries like this one, countries that move alike, and the synthetic comparison
// (the API's /alike, /alike/move and /synthetic).
import { get } from "@/lib/api";

export type AlikePreset = { id: string; name: string; indicators: string[] };
export type AlikeRow = {
  entity_id: string; name: string; distance: number; likeness: number; shared: number;
  closest_on: string[]; furthest_on: string[]; values: Record<string, number | null>;
};
export type AlikeDecade = { year: number; used: number; nearest: { entity_id: string; name: string; likeness: number }[] };
export type Alike = {
  entity_id: string; name: string; year: number; note?: string;
  used: { indicator_id: string; logged: boolean; countries: number }[];
  own: Record<string, number>; nearest: AlikeRow[]; indicator_names: Record<string, string>; decades?: AlikeDecade[];
};
export type MoveGroup = { group: number; size: number; together: number; countries: string[]; line: (number | null)[] };
export type MoveAlike = {
  indicator_id: string; start: number; end: number; years: number[]; groups: MoveGroup[];
  members: Record<string, number>; names: Record<string, string>; note?: string;
};
export type Synthetic = {
  entity_id: string; name: string; indicator_id: string; event_year: number; years: number[];
  actual: number[]; synthetic: number[]; weights: { entity_id: string; name: string; weight: number }[];
  pre_rmspe: number; post_rmspe: number; fit_share: number; mean_gap_after: number; ratio: number | null;
  placebos: { entity_id: string; ratio: number | null; pre_rmspe: number; gap: number[] }[];
  rank: number | null; p_value: number | null; verdict: string; pool_size: number;
};

export const alikeApi = {
  presets: () => get<AlikePreset[]>("/alike/presets"),
  like: (entity: string, preset: string, year?: number, n = 10, decades = false) =>
    get<Alike>("/alike", { entity, preset, year, n, decades: decades ? "true" : undefined }),
  move: (indicator: string, start: number, end?: number, groups = 6) => get<MoveAlike>("/alike/move", { indicator, start, end, groups }),
  synthetic: (entity: string, indicator: string, year: number, start?: number, pool?: string) =>
    get<Synthetic>("/synthetic", { entity, indicator, year, start, pool }),
};

// Six group colours that stay apart in light and dark themes.
export const GROUP_COLORS = ["#2a78c6", "#d9822b", "#3b9e5d", "#b8457a", "#7a5cc2", "#a08a2b", "#3aa6a6", "#c4473c", "#6b7a8f", "#8a5a2b", "#5aa02b", "#c25ca8"];
