"use client";

import { useCallback, useEffect, useState } from "react";
import EChart from "@/components/EChart";
import { api, type Indicator, type SeriesRow } from "@/lib/api";
import { barOption, lineOption, type Named } from "@/lib/charts";
import { SOURCE_LABEL } from "@/lib/format";

type Props = { indicator: Indicator; entities: Named[]; kind?: "line" | "bar"; start?: number; end?: number; height?: number };

// One indicator for one or more entities, with its source line underneath.
export default function ChartCard({ indicator, entities, kind = "line", start, end, height = 260 }: Props) {
  const [rows, setRows] = useState<SeriesRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ids = entities.map((e) => e.id).join(",");

  useEffect(() => {
    setRows(null);
    api.series(indicator.indicator_id, ids.split(","), start, end).then(setRows).catch((e) => setError(String(e.message || e)));
  }, [indicator.indicator_id, ids, start, end]);

  const option = useCallback(
    () => (kind === "bar" && entities.length === 1
      ? barOption(rows ?? [], entities[0], indicator.unit, indicator.decimals)
      : lineOption(rows ?? [], entities, indicator.unit, indicator.decimals)),
    [rows, entities, indicator, kind],
  );

  const vintages = [...new Set((rows ?? []).map((r) => `${SOURCE_LABEL[r.source_id] ?? r.source_id} ${r.vintage}`))];
  const hasProjection = (rows ?? []).some((r) => r.status === "P");
  const agg = (rows ?? []).filter((r) => r.is_aggregate && r.status === "E");
  const lastAgg = agg[agg.length - 1];

  return (
    <div className="card">
      <h3>{indicator.name}</h3>
      {error && <p className="error">{error}</p>}
      {rows && rows.length === 0 && <p className="muted">No data for this indicator yet.</p>}
      {rows && rows.length > 0 && <EChart option={option} height={height} label={`${indicator.name} chart`} />}
      {rows && rows.length > 0 && (
        <p className="caption">
          Source: {vintages.join("; ")}.{hasProjection ? (kind === "bar" ? " Faded bars are projections." : " Dashed lines are projections.") : ""}
          {lastAgg && lastAgg.coverage !== null
            ? ` Built from member countries; ${Math.round(lastAgg.coverage * 100)}% of the group's population reported in ${lastAgg.period}.`
            : ""}
        </p>
      )}
    </div>
  );
}
