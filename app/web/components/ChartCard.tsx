"use client";

import type { ECharts } from "echarts";
import { useCallback, useEffect, useRef, useState } from "react";
import EChart from "@/components/EChart";
import { api, type EventRow, type Indicator, type SeriesRow } from "@/lib/api";
import { barOption, lineOption, type Named } from "@/lib/charts";
import { credits, fileName, saveUrl, sourcesOf, titledPng } from "@/lib/download";
import { eventMarks, withEventTooltip } from "@/lib/events";
import { withParties, type Term } from "@/lib/parties";
import { SOURCE_LABEL } from "@/lib/format";

type Props = { indicator: Indicator; entities: Named[]; kind?: "line" | "bar"; start?: number; end?: number; height?: number;
  events?: EventRow[]; parties?: Term[] };

// One indicator for one or more entities, with its source line underneath, and
// dated events (Settings: Events on charts) as bands and lines, optionally coloured
// by the party in government, and a button to save it as a picture.
export default function ChartCard({ indicator, entities, kind = "line", start, end, height = 260, events = [], parties = [] }: Props) {
  const [rows, setRows] = useState<SeriesRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ids = entities.map((e) => e.id).join(",");

  useEffect(() => {
    setRows(null);
    api.series(indicator.indicator_id, ids.split(","), start, end).then(setRows).catch((e) => setError(String(e.message || e)));
  }, [indicator.indicator_id, ids, start, end]);

  const ys = (rows ?? []).map((r) => +r.period);
  const years: [number, number] | null = ys.length ? [Math.min(...ys), Math.max(...ys)] : null;
  const lo = years?.[0], hi = years ? years[1] + 1 : undefined;
  // Only events inside the years shown, so a band never stretches the axis.
  const inView = years ? events.filter((e) => +e.start_date.slice(0, 4) <= hi! && +(e.end_date ?? e.start_date).slice(0, 4) >= lo!) : [];
  const option = useCallback(() => {
    let o = kind === "bar" && entities.length === 1
      ? barOption(rows ?? [], entities[0], indicator.unit, indicator.decimals)
      : lineOption(rows ?? [], entities, indicator.unit, indicator.decimals);
    if (parties.length && entities.length === 1) o = withParties(o, parties, years);
    if (!inView.length) return o;
    const shownNames = new Map(entities.map((e) => [e.id, e.name]));
    return withEventTooltip({ ...o, series: [...(o.series as object[]), eventMarks(inView, shownNames)] } as typeof o, inView, shownNames);
  }, [rows, entities, indicator, kind, inView.length, parties]); // eslint-disable-line react-hooks/exhaustive-deps
  const chart = useRef<ECharts | null>(null);
  const onReady = useCallback((c: ECharts) => { chart.current = c; }, []);
  const [saveError, setSaveError] = useState<string | null>(null);
  const savePicture = async () => {
    const c = chart.current;
    if (!c || c.isDisposed()) return;
    try {
      const footer = await credits([...sourcesOf(indicator, rows ?? []), ...inView.map((e) => e.source_id),
        ...(parties.length ? ["wikidata"] : [])]);
      const url = await titledPng(c.getDataURL({ type: "svg" }), c.getWidth(), c.getHeight(),
        `${indicator.name}: ${entities.map((e) => e.name).join(", ")}`, years ? `${years[0]}–${years[1]}.` : "", footer);
      saveUrl(url, `${fileName(indicator.indicator_id, ...entities.map((e) => e.id))}.png`);
      setSaveError(null);
    } catch (e) {
      setSaveError(String((e as Error).message || e));
    }
  };

  const vintages = [...new Set((rows ?? []).map((r) => `${SOURCE_LABEL[r.source_id] ?? r.source_id} ${r.vintage}`))];
  const hasProjection = (rows ?? []).some((r) => r.status === "P");
  const agg = (rows ?? []).filter((r) => r.is_aggregate && r.status === "E");
  const lastAgg = agg[agg.length - 1];

  return (
    <div className="card">
      <div className="card-head">
        <h3>{indicator.name}</h3>
        {rows && rows.length > 0 && <button className="link small" onClick={savePicture} title="Save this chart as a picture, with its sources">Save picture</button>}
      </div>
      {saveError && <p className="error small">{saveError}</p>}
      {error && <p className="error">{error}</p>}
      {rows && rows.length === 0 && <p className="muted">No data for this indicator yet.</p>}
      {rows && rows.length > 0 && <EChart option={option} height={height} label={`${indicator.name} chart`} onReady={onReady} />}
      {rows && rows.length > 0 && (
        <p className="caption">
          Source: {vintages.join("; ")}.{hasProjection ? (kind === "bar" ? " Faded bars are projections." : " Dashed lines are projections.") : ""}
          {events.length > 0 ? " Shaded bands and dotted lines are events; hover one for its name." : ""}
          {parties.length > 0 && entities.length === 1 ? " Coloured by the party in government (Wikidata)." : ""}
          {lastAgg && lastAgg.coverage !== null
            ? ` Built from member countries; ${Math.round(lastAgg.coverage * 100)}% of the group's population reported in ${lastAgg.period}.`
            : ""}
        </p>
      )}
    </div>
  );
}
