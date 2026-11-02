"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import Help from "@/components/Help";
import WorldMap from "@/components/WorldMap";
import { api, type CityRow } from "@/lib/api";
import { cityPoints, cityPopulation, growth, people } from "@/lib/cities";

// A country's biggest cities: a short table and a map of them. Hidden until a
// refresh has loaded the city list.
export default function CitiesCard({ entity, name }: { entity: string; name: string }) {
  const [rows, setRows] = useState<CityRow[] | null>(null);
  useEffect(() => {
    setRows(null);
    api.cities({ country: entity, limit: 40 }).then((r) => setRows(r.rows)).catch(() => setRows([]));
  }, [entity]);
  const points = useMemo(() => cityPoints(rows ?? []), [rows]);
  if (!rows || rows.length === 0) return null;
  const top = rows.slice(0, 10);
  const hasCost = top.some((r) => r.wn_cost_index !== null);
  return (
    <div className="card" id="cities">
      <div className="card-head">
        <h3>Major cities <Help note="cities" /></h3>
        <Link className="small" href={`/cities?country=${entity}`}>All {rows.length >= 40 ? "" : `${rows.length} `}cities of {name}</Link>
      </div>
      <div className="grid two" style={{ alignItems: "start" }}>
        <table className="summary-table city-table">
          <thead><tr><th>City</th><th className="num">People</th><th className="num">Change to 2035</th>{hasCost && <th className="num">Cost index</th>}</tr></thead>
          <tbody>
            {top.map((r) => {
              const pop = cityPopulation(r);
              const g = growth(r);
              return (
                <tr key={r.city_id}>
                  <td className="name"><Link href={`/city/${r.city_id}`}>{r.name}</Link>{r.capital === "national" && <span className="city-tag">capital</span>}</td>
                  <td className="num" title={pop.note}>{people(pop.value)}{r.population === null ? <span className="muted">*</span> : null}</td>
                  <td className="num">{g === null ? "–" : `${g > 0 ? "+" : ""}${g.toFixed(0)}%`}</td>
                  {hasCost && <td className="num">{r.wn_cost_index !== null ? Math.round(r.wn_cost_index) : "–"}</td>}
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="city-map small">
          <WorldMap fill values={[]} unit="" decimals={0} diverging={false} onPick={() => {}} points={points} fitPoints />
        </div>
      </div>
      <p className="caption">
        People: the UN&apos;s figure for the city and its suburbs where there is one (* otherwise GeoNames&apos; figure for the city itself).
        Change to 2035: UN projection.{hasCost ? " Cost index: WhereNext cost of living (higher is dearer)." : ""}
      </p>
    </div>
  );
}
