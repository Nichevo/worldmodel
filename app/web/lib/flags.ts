// Flags beside country names: each country's two-letter code from the entities list
// (fetched once per page), and the few groups that have a flag of their own. Groups,
// regions and old countries without one get a small lettered badge instead.

import { useEffect, useState } from "react";
import { api, type Entity } from "@/lib/api";

const GROUP_FLAGS: Record<string, string> = { eu: "eu", "euro-area": "eu", asean: "asean", un: "un", "arab-league": "arab", eac: "eac" };

export type FlagInfo = { code: string | null; badge: string; name: string; type: string };

let index: Promise<Map<string, FlagInfo>> | null = null;

function badgeFor(e: Entity): string {
  const s = e.short_name || e.entity_id;
  if (s.length <= 5 && !s.includes(" ")) return s.toUpperCase();
  return s.split(/[\s-]+/).filter((w) => /^[A-Za-z]/.test(w) && !["and", "of", "the"].includes(w.toLowerCase()))
    .map((w) => w[0].toUpperCase()).join("").slice(0, 4);
}

export function flagIndex(): Promise<Map<string, FlagInfo>> {
  index ??= api.entities().then((list) => new Map(list.map((e) => {
    const iso2 = (e as Entity & { iso2?: string | null }).iso2;
    const code = e.type === "country" && iso2 ? iso2.toLowerCase() : GROUP_FLAGS[e.entity_id] ?? null;
    return [e.entity_id, { code, badge: badgeFor(e), name: e.short_name, type: e.type }];
  }))).catch((err) => { index = null; throw err; });
  return index;
}

// Flags that flag-icons draws (ISO 3166 two-letter codes plus a few groups); anything else gets the badge.
export const flagUrl = (code: string) => `/flags/${code}.svg`;

// Each entity's flag code once the list has arrived (empty until then), for charts that draw flags.
export function useFlagCodes(on: boolean): Map<string, string> {
  const [codes, setCodes] = useState<Map<string, string>>(new Map());
  useEffect(() => {
    if (!on) return;
    let live = true;
    flagIndex().then((m) => live && setCodes(new Map([...m].flatMap(([id, f]) => (f.code ? [[id, f.code] as [string, string]] : []))))).catch(() => {});
    return () => { live = false; };
  }, [on]);
  return on ? codes : EMPTY;
}
const EMPTY = new Map<string, string>();
