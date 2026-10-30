"use client";

import { useCallback, useEffect, useState } from "react";
import EChart from "@/components/EChart";
import { api, type EventRow, type Indicator, type SeriesRow } from "@/lib/api";
import { barOption, lineOption, type Named } from "@/lib/charts";
import { eventMarks, withEventTooltip } from "@/lib/events";
import { SOURCE_LABEL } from "@/lib/format";

type Props = { indicator: Indicator; entities: Named[]; kind?: "line" | "bar"; start?: number; end?: number; height?: number;
  events?: EventRow[] };

// One indicator for one or more entities, with its source line underneath, and
// dated events (Settings: Events on charts) as bands and lines.
export default function ChartCard({ indicator, entities, kind = "line", start, end, height = 260, events = [] }: Props) {
  const [rows, setRows] = useState<SeriesRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ids = entities.map((e) => e.id).join(",");

  useEffect(() => {
    setRows(null);
    api.series(indicator.indicator_id, ids.split(","), start, end).then(setRows).catch((e) => setError(String(e.message || e)));
  }, [indicator.indicator_id, ids, start, end]);

  const option = useCallback(() => {
    const o = kind === "bar" && entities.length === 1
      ? barOption(rows ?? [], entities[0], indicator.unit, indicator.decimals)
      : lineOption(rows ?? [], entities, indicator.unit, indicator.decimals);
    if (!events.length || !rows?.length) return o;
    // Only events inside the years shown, so a band never stretches the axis.
    const ys = rows.map((r) => +r.period);
    const lo = Math.min(...ys), hi = Math.max(...ys) + 1;
    const inView = events.filter((e) => +e.start_date.slice(0, 4) <= hi && +(e.end_date ?? e.start_date).slice(0, 4) >= lo);
    const shownNames = new Map(entities.map((e) => [e.id, e.name]));
    return withEventTooltip({ ...o, series: [...(o.series as object[]), eventMarks(inView, shownNames)] } as typeof o, inView, shownNames);
  }, [rows, entities, indicator, kind, events]);

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
          {events.length > 0 ? " Shaded bands and dotted lines are events; hover one for its name." : ""}
          {lastAgg && lastAgg.coverage !== null
            ? ` Built from member countries; ${Math.round(lastAgg.coverage * 100)}% of the group's population reported in ${lastAgg.period}.`
            : ""}
        </p>
      )}
    </div>
  );
}
