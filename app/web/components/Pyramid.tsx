"use client";

import { useCallback, useEffect, useState } from "react";
import EChart from "@/components/EChart";
import { api, type Pyramid as PyramidData } from "@/lib/api";
import { pyramidOption } from "@/lib/charts";

export default function Pyramid({ entity, name }: { entity: string; name: string }) {
  const [data, setData] = useState<PyramidData | null>(null);
  const [year, setYear] = useState<number | null>(null);

  useEffect(() => {
    // Ask for a recent year first; the reply lists the years that exist.
    api.pyramid(entity, year ?? 2023).then((d) => {
      if (!d.groups.length && d.years_available.length && year === null) {
        setYear(d.years_available[d.years_available.length - 1]);
      } else {
        setData(d);
        if (year === null) setYear(d.year);
      }
    });
  }, [entity, year]);

  const option = useCallback(() => pyramidOption(data?.groups ?? []), [data]);
  if (!data) return null;
  if (!data.years_available.length) return <p className="muted">No age breakdown for {name}.</p>;
  const years = data.years_available;
  return (
    <div>
      <div className="controls">
        <label style={{ display: "flex", gap: 8, alignItems: "center", flex: 1 }}>
          Year
          <input type="range" min={0} max={years.length - 1} value={Math.max(0, years.indexOf(year ?? years[0]))}
            onChange={(e) => setYear(years[+e.target.value])} style={{ flex: 1 }} aria-label="Pyramid year" />
          <b>{year}</b>
        </label>
      </div>
      <EChart option={option} height={360} label={`Population pyramid of ${name}, ${year}`} />
    </div>
  );
}
