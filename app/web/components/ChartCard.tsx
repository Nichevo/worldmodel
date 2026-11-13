"use client";

import Help from "@/components/Help";
import type { ECharts } from "echarts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import EChart from "@/components/EChart";
import { api, type EventRow, type Indicator, type SeriesRow } from "@/lib/api";
import { barOption, lineOption, type Named } from "@/lib/charts";
import { credits, fileName, saveUrl, sourcesOf, titledPng } from "@/lib/download";
import { eventMarks, linkBands, withEventTooltip } from "@/lib/events";
import { useRouter } from "next/navigation";
import { withParties, type Term } from "@/lib/parties";
import { SOURCE_LABEL } from "@/lib/format";
import { forecastCaption, useForecasts, withForecast } from "@/lib/forecast";
import { useSettings } from "@/lib/settings";
import { chartParts, keep, openAsk, seriesTable, sourcesLine, toast, useRegisterChart } from "@/lib/ai";
import PredictDialog from "@/components/PredictDialog";
import MoreMenu from "@/components/MoreMenu";
import { finding } from "@/lib/finding";
import { chartPredictions, forgetChartPredictions, type Prediction, predictionSeries } from "@/lib/predictions";

type Props = { indicator: Indicator; entities: Named[]; kind?: "line" | "bar"; start?: number; end?: number; height?: number;
  events?: EventRow[]; parties?: Term[]; forecast?: boolean; hideEmpty?: boolean };

// One indicator for one or more entities, with its source line underneath, and
// dated events (Settings: Events on charts) as bands and lines, optionally coloured
// by the party in government, and a button to save it as a picture.
export default function ChartCard({ indicator, entities, kind = "line", start, end, height = 260, events = [], parties = [], forecast = false, hideEmpty = false }: Props) {
  const [allRows, setRows] = useState<SeriesRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ids = entities.map((e) => e.id).join(",");
  const [forecastOn, setForecastOn] = useState(forecast);
  const settings = useSettings();
  const forecasts = useForecasts(indicator.indicator_id, entities.map((e) => e.id), forecastOn && kind === "line");
  // Your number predictions on this indicator and these countries, as dots (Settings: Predictions on charts).
  const [preds, setPreds] = useState<Prediction[]>([]);
  const [predicting, setPredicting] = useState(false);
  const [predTick, setPredTick] = useState(0);
  useEffect(() => {
    if (!settings.predictions_on_charts || kind !== "line") { setPreds([]); return; }
    let live = true;
    const want = new Set(ids.split(","));
    chartPredictions().then((all) => live && setPreds(all.filter((p) => p.kind === "number" && p.indicator === indicator.indicator_id
      && p.year != null && p.value != null && want.has(p.entity ?? ""))));
    return () => { live = false; };
  }, [indicator.indicator_id, ids, kind, settings.predictions_on_charts, predTick]);

  useEffect(() => {
    setRows(null);
    api.series(indicator.indicator_id, ids.split(","), start, end).then(setRows).catch((e) => setError(String(e.message || e)));
  }, [indicator.indicator_id, ids, start, end]);

  // Projected years (UN population projections and the like) can be left off.
  const rows = useMemo(() => (allRows && !settings.projections_on_charts ? allRows.filter((r) => r.status !== "P") : allRows),
    [allRows, settings.projections_on_charts]);
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
    if (forecasts) o = withForecast(o, forecasts, entities, settings.forecast_ranges, rows?.[0]?.source_id);
    if (preds.length) o = { ...o, series: [...(o.series as object[]), ...predictionSeries(preds, new Map(entities.map((e) => [e.id, e.name])))] } as typeof o;
    if (!inView.length) return o;
    const shownNames = new Map(entities.map((e) => [e.id, e.name]));
    return withEventTooltip({ ...o, series: [...(o.series as object[]), eventMarks(inView, shownNames)] } as typeof o, inView, shownNames);
  }, [rows, entities, indicator, kind, inView.length, parties, forecasts, settings.forecast_ranges, preds]); // eslint-disable-line react-hooks/exhaustive-deps
  const chart = useRef<ECharts | null>(null);
  const router = useRouter();
  const onReady = useCallback((c: ECharts) => { chart.current = c; linkBands(c, (u) => router.push(u)); }, [router]);
  const [saveError, setSaveError] = useState<string | null>(null);
  const title = `${indicator.name}: ${entities.map((e) => e.name).join(", ")}`;
  const picture = async (): Promise<string | null> => {
    const c = chart.current;
    if (!c || c.isDisposed()) return null;
    const footer = await credits([...sourcesOf(indicator, rows ?? []), ...inView.map((e) => e.source_id),
      ...(parties.length ? ["wikidata"] : []),
      ...(forecasts ? [...forecasts.byEntity.values()].flatMap((f) => f.official.map((x) => x.source_id)) : [])]);
    return titledPng(c.getDataURL({ type: "svg" }), c.getWidth(), c.getHeight(), title, years ? `${years[0]}–${years[1]}.` : "", footer);
  };
  const savePicture = async () => {
    try {
      const url = await picture();
      if (url) saveUrl(url, `${fileName(indicator.indicator_id, ...entities.map((e) => e.id))}.png`);
      setSaveError(null);
    } catch (e) {
      setSaveError(String((e as Error).message || e));
    }
  };
  const names = new Map(entities.map((e) => [e.id, e.name]));
  useRegisterChart(() => ({ title, parts: () => chartParts(indicator, rows ?? [], names, inView), picture }));
  const askAI = () => openAsk({ title, parts: chartParts(indicator, rows ?? [], names, inView), indicator: indicator.indicator_id,
    entity: entities.length === 1 ? entities[0].id : undefined, picture });
  // Keep: the chart stays live (it reopens on the map page with these settings) and a picture of it as it looks now.
  const keepChart = async () => {
    let pic: string | null = null;
    try { pic = await picture(); } catch { /* kept without a picture */ }
    const t = seriesTable(rows ?? [], names);
    await keep({ kind: "chart", title, indicator: indicator.indicator_id, entities: entities.map((e) => e.id),
      query: `l=1&p=chart.${indicator.indicator_id}&s=${entities.map((e) => e.id).join(",")}`,
      table: { ...t, unit: indicator.unit }, sources: sourcesLine(rows ?? []), picture: pic ?? undefined });
  };

  const vintages = [...new Set((rows ?? []).map((r) => `${SOURCE_LABEL[r.source_id] ?? r.source_id} ${r.vintage}`))];
  const hasProjection = (rows ?? []).some((r) => r.status === "P");
  const agg = (rows ?? []).filter((r) => r.is_aggregate && r.status === "E");
  const lastAgg = agg[agg.length - 1];

  // The public API address of these figures (Settings > API access); says so when the API is off.
  const copyApiLink = () => {
    const q = new URLSearchParams({ indicator: indicator.indicator_id, entities: ids, format: "csv" });
    if (start) q.set("from", String(start));
    if (end) q.set("to", String(end));
    const link = `${window.location.origin}/api/public/v1/data?${q}`;
    navigator.clipboard?.writeText(link).then(() => toast(settings.api_public_on ? "API link copied"
      : "API link copied, but the public API is switched off: switch it on in Settings > API access"))
      .catch(() => toast(link));
  };
  // A country page leaves out a chart with nothing to show (or that failed) rather than an empty card.
  if (hideEmpty && ((rows && rows.length === 0 && !error) || error)) return null;
  // The headline says what the chart shows (Settings > Look of charts); the measure's name sits above it.
  const headline = settings.chart_findings && rows?.length ? finding(rows, entities, indicator.unit, indicator.decimals) : null;
  return (
    <div className="card">
      <div className="card-head">
        <h3 className={headline ? "sub" : undefined}>{indicator.name}{settings.quality_on_titles && indicator.grade && <> <span className={`grade grade-${indicator.grade}`} title="Quality grade (Indicators page)">{indicator.grade}</span></>} <Help indicator={indicator} /></h3>
        {rows && rows.length > 0 && (
          <span className="card-actions">
            {settings.ai_enabled && <button className="link small" onClick={askAI} title="Ask the local AI about this chart; its figures go with the question">Ask AI</button>}
            <MoreMenu items={[
              { label: forecastOn ? "Hide forecast" : "Forecast", on: forecastOn, hidden: kind !== "line", onClick: () => setForecastOn(!forecastOn),
                title: "Extend each line with a statistical forecast and its ranges (Settings: Forecasts)" },
              { label: "Predict…", onClick: () => setPredicting(true), title: "Add your prediction for this figure to the Predictions log; it is checked when the figure arrives" },
              { label: "Keep on Highlights", onClick: keepChart, title: "Keep this chart on the Highlights page" },
              { label: "Save picture", onClick: savePicture, title: "Save this chart as a picture, with its sources" },
              { label: "Copy API link", onClick: copyApiLink, title: "Copy the address of these figures in the public API (CSV), for Excel, PowerShell or a script" },
            ]} />
          </span>
        )}
      </div>
      {headline && <p className="finding">{headline}</p>}
      {saveError && <p className="error small">{saveError}</p>}
      {error && <p className="error">{error}</p>}
      {rows && rows.length === 0 && <p className="muted">No data for this indicator yet.</p>}
      {rows && rows.length > 0 && <EChart option={option} height={height} label={`${indicator.name} chart`} onReady={onReady} />}
      {predicting && <PredictDialog title={`Predict: ${indicator.name}`} onClose={() => setPredicting(false)}
        onSaved={() => { forgetChartPredictions(); setPredTick((t) => t + 1); }}
        initial={{ kind: "number", indicator: indicator.indicator_id, entity: entities[0]?.id, unit: indicator.unit,
          year: Math.max((years?.[1] ?? 0) + 1, new Date().getFullYear()),
          due: `${Math.max((years?.[1] ?? 0) + 1, new Date().getFullYear()) + 1}-06-30`,
          question: `${indicator.name}, ${entities[0]?.name ?? ""}, ${Math.max((years?.[1] ?? 0) + 1, new Date().getFullYear())}` }} />}
      {rows && rows.length > 0 && (
        <p className="caption">
          Source: {vintages.join("; ")}.{hasProjection ? (kind === "bar" ? " Faded bars are projections." : " Dashed lines are projections.") : ""}
          {events.length > 0 ? " Shaded bands and dotted lines are events; hover one for its name." : ""}
          {parties.length > 0 && entities.length === 1 ? " Coloured by the party in government (Wikidata)." : ""}
          {forecastOn && forecasts ? ` ${forecastCaption(forecasts, entities, settings.forecast_ranges)}` : ""}
          {forecastOn && !forecasts ? " Working out the forecast…" : ""}
          {preds.length ? " Diamonds are predictions in your log." : ""}
          {lastAgg && lastAgg.coverage !== null
            ? ` Built from member countries; ${Math.round(lastAgg.coverage * 100)}% of the group's population reported in ${lastAgg.period}.`
            : ""}
        </p>
      )}
    </div>
  );
}
