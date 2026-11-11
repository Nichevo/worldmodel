// Shared bits of the Briefing: the build last seen there (so the app can open on the
// Briefing once after each refresh), month names, and the weekly digest.
import { get, type BriefCard } from "@/lib/api";

export const BRIEFING_SEEN = "wm.briefingBuild";

export function monthName(m: string): string {
  const [y, mo] = m.split("-").map(Number);
  return new Date(Date.UTC(y, mo - 1, 1)).toLocaleString("en-NZ", { month: "long", year: "numeric", timeZone: "UTC" });
}

// ----------------------------------------------------------------------------- the weekly digest (Briefing > Week)

export type Digest = {
  week: string; from: string; to: string; made: string; complete: boolean; kept: boolean; key_countries: string[];
  sources: { source_id: string; vintage: string; day: string; rows: number }[];
  changed: { entity_id: string; indicator_id: string; name: string; unit: string; source_id: string; y: number; now: number; before: number | null }[];
  finds: BriefCard[]; crisiswatch: BriefCard[]; events: BriefCard[]; news: BriefCard[];
  crowd: { key: string; title: string; site: string; chance: number; change: number; url: string; countries: string[] }[];
  predictions: { id: string; question: string; who: string; state: "due" | "settled"; day: string; score?: { hit?: boolean; brier?: number } }[];
  notes: string[]; names: Record<string, string>;
};
export const digestApi = {
  get: (week?: string) => get<Digest>("/digest", { week }),
  list: () => get<{ kept: string[]; last_complete: string; this_week: string }>("/digests"),
};
