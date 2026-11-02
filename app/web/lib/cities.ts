// Small helpers shared by the Cities page, city pages and the country page's city card.
import type { CityRow } from "@/lib/api";
import { cssVar } from "@/lib/colors";
import type { MapPoint } from "@/components/WorldMap";

export function people(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  if (v >= 1e6) return `${(v / 1e6).toFixed(v >= 1e7 ? 1 : 2)} m`;
  if (v >= 1e3) return `${Math.round(v / 1e3).toLocaleString()} k`;
  return Math.round(v).toLocaleString();
}

// The best population figure: the UN agglomeration (city and suburbs) where there is one,
// else GeoNames' figure for the city itself.
export function cityPopulation(c: CityRow): { value: number | null; note: string } {
  if (c.population !== null) return { value: c.population, note: `UN, city and suburbs, ${c.population_year}${c.population_year && c.population_year > 2015 ? " projection" : ""}` };
  return { value: c.geonames_population, note: "GeoNames (the city itself)" };
}

export function growth(c: CityRow): number | null {
  return c.population && c.population_2035 ? (c.population_2035 / c.population - 1) * 100 : null;
}

export function cityPoints(rows: CityRow[], current?: string): MapPoint[] {
  return rows.filter((c) => c.lat !== null && c.lon !== null).map((c) => {
    const pop = cityPopulation(c).value;
    return { id: c.city_id, name: c.name, lng: c.lon, lat: c.lat, size: pop ?? 0, capital: c.capital === "national",
      color: c.city_id === current ? cssVar("--series-2") : undefined,
      text: [pop ? `${people(pop)} people` : "", c.wn_cost_index !== null ? `cost of living index ${Math.round(c.wn_cost_index)}` : ""]
        .filter(Boolean).join(" · ") };
  });
}
