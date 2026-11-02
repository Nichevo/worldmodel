"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import AskButton from "@/components/AskButton";
import WorldMap from "@/components/WorldMap";
import { api, type CityRow, type Entity } from "@/lib/api";
import { cityPoints, cityPopulation, growth, people } from "@/lib/cities";
import { logHistory } from "@/lib/history";

// Major cities: a table and a map of the world's cities (or one country's), with
// population now and in 2035 and the cost of living where WhereNext or Numbeo have it.
export default function CitiesPage() {
  return (
    <Suspense fallback={<p className="muted">Loading…</p>}>
      <Cities />
    </Suspense>
  );
}

const SORTS = [["population", "Population"], ["growth", "Growth to 2035"], ["cost", "Cost of living"], ["name", "Name"]] as const;
const SIZES = [[0, "Any size"], [100_000, "100 k+"], [500_000, "500 k+"], [1_000_000, "1 m+"], [5_000_000, "5 m+"]] as const;

function Cities() {
  const params = useSearchParams();
  const router = useRouter();
  const country = params.get("country") ?? "";
  const sort = params.get("sort") ?? "population";
  const min = Number(params.get("min") ?? (country ? 0 : 1_000_000));
  const [q, setQ] = useState(params.get("q") ?? "");
  const [rows, setRows] = useState<CityRow[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [countries, setCountries] = useState<Entity[]>([]);

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params.toString());
    if (v) next.set(k, v); else next.delete(k);
    router.replace(`/cities${next.toString() ? `?${next}` : ""}`);
  };

  useEffect(() => { api.entities("country").then((e) => setCountries(e.sort((a, b) => a.short_name.localeCompare(b.short_name)))).catch(() => {}); }, []);
  useEffect(() => {
    const t = setTimeout(() => {
      setError(null);
      api.cities({ country: country || undefined, q: q || undefined, min_population: min, sort, limit: country ? 500 : 300 })
        .then((r) => { setRows(r.rows); setNote(r.note); }).catch((e) => setError(String(e.message || e)));
    }, q ? 250 : 0);
    return () => clearTimeout(t);
  }, [country, q, min, sort]);
  const countryName = countries.find((c) => c.entity_id === country)?.short_name;
  useEffect(() => { logHistory({ kind: "page", title: countryName ? `Cities of ${countryName}` : "Major cities", url: `/cities${country ? `?country=${country}` : ""}`, entity: country || undefined }); }, [country, countryName]);

  const points = useMemo(() => cityPoints(rows ?? []), [rows]);
  const hasCost = (rows ?? []).some((r) => r.wn_cost_index !== null || r.numbeo_cost_index !== null);
  const title = countryName ? `Cities of ${countryName}` : "Major cities";
  const csv = () => ["City,Country,Population,Population year,Population 2035,Cost of living index (WhereNext),Monthly cost one person US$ (WhereNext),Cost of living index (Numbeo)",
    ...(rows ?? []).map((r) => [r.name, r.country, cityPopulation(r).value, r.population_year, r.population_2035, r.wn_cost_index, r.wn_monthly_cost_usd, r.numbeo_cost_index]
      .map((v) => (v === null || v === undefined ? "" : typeof v === "string" ? `"${v}"` : +(+v).toPrecision(6))).join(","))].join("\n");

  return (
    <div className="grid">
      <div className="title-row">
        <h1 style={{ marginBottom: 4 }}>{title}</h1>
        <AskButton title={title} entity={country || undefined} parts={() => [{ key: "data", kind: "data", label: `${title} (table)`, text: csv() }]} />
      </div>
      <p className="ink-2" style={{ marginTop: 0 }}>
        Population is the UN&apos;s figure for the city and its suburbs (World Urbanization Prospects) where there is one, otherwise
        GeoNames&apos; figure for the city itself. Cost of living comes from WhereNext (about 370 cities) and Numbeo&apos;s rankings
        (saved by hand, see the README). Click a city for its page.
      </p>
      <div className="chips-row small">
        <select value={country} onChange={(e) => set("country", e.target.value)} aria-label="Country">
          <option value="">Every country</option>
          {countries.map((c) => <option key={c.entity_id} value={c.entity_id}>{c.short_name}</option>)}
        </select>
        <input type="search" placeholder="Find a city" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 180 }} />
        <div className="seg" role="group" aria-label="Size">
          {SIZES.map(([v, label]) => <button key={v} className={min === v ? "on" : ""} onClick={() => set("min", String(v))}>{label}</button>)}
        </div>
        <div className="seg" role="group" aria-label="Sort by">
          {SORTS.map(([v, label]) => <button key={v} className={sort === v ? "on" : ""} onClick={() => set("sort", v)}>{label}</button>)}
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {note && <p className="ink-2">{note}</p>}
      {!rows && !error && <p className="muted">Loading…</p>}
      {rows && !note && (
        <div className="cities-grid">
          <section className="card">
            <div style={{ maxHeight: 640, overflow: "auto" }}>
              <table className="summary-table city-table">
                <thead><tr>
                  <th className="num">#</th><th>City</th>{!country && <th>Country</th>}<th className="num">People</th>
                  <th className="num">Change to 2035</th>
                  {hasCost && <th className="num" title="WhereNext cost of living index (higher is dearer)">Cost index</th>}
                  {hasCost && <th className="num" title="WhereNext: one person's monthly costs including rent, US$">Monthly cost</th>}
                </tr></thead>
                <tbody>
                  {rows.map((r, i) => {
                    const pop = cityPopulation(r);
                    const g = growth(r);
                    return (
                      <tr key={r.city_id}>
                        <td className="num muted">{i + 1}</td>
                        <td className="name"><Link href={`/city/${r.city_id}`}>{r.name}</Link>
                          {r.capital === "national" && <span className="city-tag">capital</span>}
                          {country && r.admin1 && r.admin1 !== r.name && <span className="small muted"> {r.admin1}</span>}</td>
                        {!country && <td><Link href={`/cities?country=${r.country_id}`} className="ink-2">{r.country ?? r.country_id}</Link></td>}
                        <td className="num" title={pop.note}>{people(pop.value)}{r.population === null && pop.value !== null ? <span className="muted">*</span> : null}</td>
                        <td className="num">{g === null ? "–" : `${g > 0 ? "+" : ""}${g.toFixed(0)}%`}</td>
                        {hasCost && <td className="num">{r.wn_cost_index !== null ? Math.round(r.wn_cost_index) : "–"}</td>}
                        {hasCost && <td className="num">{r.wn_monthly_cost_usd !== null ? `$${Math.round(r.wn_monthly_cost_usd).toLocaleString()}` : "–"}</td>}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {rows.length === 0 && <p className="muted">No cities match.</p>}
            </div>
            <p className="caption">
              {rows.length} cities. * GeoNames&apos; figure for the city itself, where the UN has no figure for its built-up area.
              Change to 2035 is the UN projection (2018 edition).
            </p>
          </section>
          <section className="card">
            <div className="city-map">
              <WorldMap fill values={[]} unit="" decimals={0} diverging={false} onPick={(iso) => set("country", iso)}
                points={points} fitPoints={!!country} />
            </div>
            <p className="caption">Dots sized by population; capitals outlined. Click a country to list its cities, a dot to open the city.</p>
          </section>
        </div>
      )}
    </div>
  );
}
