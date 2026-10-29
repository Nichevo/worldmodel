"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import WorldMap from "@/components/WorldMap";
import { api, type Indicator } from "@/lib/api";
import { DIVERGING } from "@/lib/colors";
import { SOURCE_LABEL } from "@/lib/format";

export default function ExplorePage() {
  const router = useRouter();
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [indicatorId, setIndicatorId] = useState("tfr");
  const [year, setYear] = useState<number | null>(null);
  const [values, setValues] = useState<{ entity_id: string; value: number; status: string }[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.indicators()
      .then((list) => setIndicators(list.filter((i) => i.available && !i.breakdowns)))
      .catch((e) => setError(String(e.message || e)));
  }, []);

  const indicator = useMemo(() => indicators.find((i) => i.indicator_id === indicatorId), [indicators, indicatorId]);

  useEffect(() => {
    if (indicator && (year === null || year < indicator.first_year! || year > indicator.last_year!)) {
      setYear(indicator.last_estimate_year ?? indicator.last_year);
    }
  }, [indicator, year]);

  useEffect(() => {
    if (!indicator || year === null) return;
    api.map(indicator.indicator_id, year).then(setValues).catch((e) => setError(String(e.message || e)));
  }, [indicator, year]);

  const domains = useMemo(() => [...new Set(indicators.map((i) => i.domain))], [indicators]);
  const isProjection = indicator && year !== null && indicator.last_estimate_year !== null && year > indicator.last_estimate_year;
  const source = indicator?.sources[0]?.source_id;

  return (
    <div>
      <h1>{indicator ? indicator.name : "World map"}{year !== null ? `, ${year}` : ""}</h1>
      <p className="ink-2" style={{ marginTop: 0 }}>{indicator?.description}</p>
      <div className="controls">
        <label>
          Indicator{" "}
          <select value={indicatorId} onChange={(e) => setIndicatorId(e.target.value)}>
            {domains.map((d) => (
              <optgroup key={d} label={d[0].toUpperCase() + d.slice(1)}>
                {indicators.filter((i) => i.domain === d).map((i) => (
                  <option key={i.indicator_id} value={i.indicator_id}>{i.name}</option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
        {indicator && year !== null && (
          <label style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 260 }}>
            Year
            <input
              type="range"
              min={indicator.first_year!}
              max={indicator.last_year!}
              value={year}
              onChange={(e) => setYear(+e.target.value)}
              style={{ flex: 1 }}
              aria-label="Year"
            />
            <b style={{ minWidth: 40 }}>{year}</b>
            {isProjection && <span className="chip">projection</span>}
          </label>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {indicator && (
        <WorldMap
          values={values}
          unit={indicator.unit}
          decimals={indicator.decimals}
          diverging={DIVERGING.has(indicator.indicator_id)}
          onPick={(iso) => router.push(`/entity/${iso}`)}
        />
      )}
      {indicator && (
        <p className="caption">
          Source: {SOURCE_LABEL[source ?? ""] ?? source}. {values.length} countries with data.
          {indicator.last_estimate_year ? ` Values after ${indicator.last_estimate_year} are the source's projections.` : ""}
          {" "}Click a country for its profile.
        </p>
      )}
    </div>
  );
}
