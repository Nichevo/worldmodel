"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import EChart from "@/components/EChart";
import WorldMap from "@/components/WorldMap";
import { api, type Indicator, type SeriesRow } from "@/lib/api";
import { lineOption } from "@/lib/charts";
import { DIVERGING } from "@/lib/colors";
import { SOURCE_SHORT, formatValue } from "@/lib/format";
import type { Action, Panel as PanelState, View } from "@/lib/workspace";

type Props = {
  panel: PanelState;
  indicators: Indicator[];
  names: Map<string, string>;
  selection: string[];
  dispatch: (a: Action) => void;
  canDuplicate: boolean;
  canClose: boolean;
  maximised: boolean;
  style?: React.CSSProperties;
};

const VIEW_LABEL: Record<View, string> = { map: "Map", chart: "Chart", table: "Table" };

// The panel's year: its own if inside the indicator's range, else the last estimate.
export function effectiveYear(panel: PanelState, ind: Indicator | undefined): number | null {
  if (!ind || ind.first_year === null || ind.last_year === null) return null;
  if (panel.year !== null && panel.year >= ind.first_year && panel.year <= ind.last_year) return panel.year;
  return ind.last_estimate_year ?? ind.last_year;
}

export default function Panel({ panel, indicators, names, selection, dispatch, canDuplicate, canClose, maximised, style }: Props) {
  const indicator = indicators.find((i) => i.indicator_id === panel.indicator);
  const year = effectiveYear(panel, indicator);
  const set = (patch: Partial<Omit<PanelState, "id">>) => dispatch({ type: "panel", id: panel.id, patch });
  const domains = useMemo(() => [...new Set(indicators.map((i) => i.domain))], [indicators]);
  const isProjection = indicator && year !== null && indicator.last_estimate_year !== null && year > indicator.last_estimate_year;

  return (
    <section className="panel" style={style} aria-label={`${indicator?.name ?? "Panel"} ${VIEW_LABEL[panel.view].toLowerCase()}`}>
      <header className="panel-head">
        <div className="seg" role="group" aria-label="View">
          {(Object.keys(VIEW_LABEL) as View[]).map((v) => (
            <button key={v} className={v === panel.view ? "on" : ""} aria-pressed={v === panel.view} onClick={() => set({ view: v })}>
              {VIEW_LABEL[v]}
            </button>
          ))}
        </div>
        <select value={panel.indicator} onChange={(e) => set({ indicator: e.target.value })} aria-label="Indicator">
          {domains.map((d) => (
            <optgroup key={d} label={d[0].toUpperCase() + d.slice(1)}>
              {indicators.filter((i) => i.domain === d).map((i) => (
                <option key={i.indicator_id} value={i.indicator_id}>{i.name}</option>
              ))}
            </optgroup>
          ))}
        </select>
        {indicator && year !== null && panel.view !== "chart" && (
          <label className="year">
            <input
              type="range"
              min={indicator.first_year!}
              max={indicator.last_year!}
              value={year}
              onChange={(e) => set({ year: +e.target.value })}
              aria-label="Year"
            />
            <b>{year}</b>
            {isProjection && <span className="chip">projection</span>}
          </label>
        )}
        <span className="spacer" />
        <div className="panel-actions">
          <button title="Duplicate panel" aria-label="Duplicate panel" disabled={!canDuplicate}
            onClick={() => dispatch({ type: "duplicate", id: panel.id })}>⧉</button>
          <button title={maximised ? "Restore layout" : "Maximise panel"} aria-label={maximised ? "Restore layout" : "Maximise panel"}
            onClick={() => dispatch({ type: "maximise", id: maximised ? null : panel.id })}>{maximised ? "⤡" : "⤢"}</button>
          <button title="Close panel" aria-label="Close panel" disabled={!canClose}
            onClick={() => dispatch({ type: "close", id: panel.id })}>×</button>
        </div>
      </header>
      <div className="panel-body">
        {!indicator && <p className="muted">Loading…</p>}
        {indicator && panel.view === "map" && year !== null && (
          <MapView indicator={indicator} year={year} selection={selection} dispatch={dispatch} />
        )}
        {indicator && panel.view === "table" && year !== null && (
          <TableView indicator={indicator} year={year} names={names} selection={selection} dispatch={dispatch} />
        )}
        {indicator && panel.view === "chart" && <ChartView indicator={indicator} names={names} selection={selection} />}
      </div>
    </section>
  );
}

type Value = { entity_id: string; value: number; status: string };

function useMapValues(indicator: string, year: number) {
  const [values, setValues] = useState<Value[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.map(indicator, year)
      .then((v) => { if (live) { setValues(v); setError(null); } })
      .catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [indicator, year]);
  return { values, error };
}

function sourceLine(indicator: Indicator) {
  const s = indicator.sources[0]?.source_id;
  return s ? (SOURCE_SHORT[s] ?? s) : "";
}

function MapView({ indicator, year, selection, dispatch }: { indicator: Indicator; year: number; selection: string[]; dispatch: (a: Action) => void }) {
  const { values, error } = useMapValues(indicator.indicator_id, year);
  return (
    <>
      {error && <p className="error">{error}</p>}
      <WorldMap
        fill
        values={values}
        unit={indicator.unit}
        decimals={indicator.decimals}
        diverging={DIVERGING.has(indicator.indicator_id)}
        selected={selection}
        onPick={(iso) => dispatch({ type: "toggleSelect", entity: iso })}
      />
      <p className="caption">
        {sourceLine(indicator)}. {values.length} countries with data. Click a country to select it.
      </p>
    </>
  );
}

function TableView({ indicator, year, names, selection, dispatch }: {
  indicator: Indicator; year: number; names: Map<string, string>; selection: string[]; dispatch: (a: Action) => void;
}) {
  const { values, error } = useMapValues(indicator.indicator_id, year);
  const [sort, setSort] = useState<{ by: "name" | "value"; desc: boolean }>({ by: "value", desc: true });
  const rows = useMemo(() => {
    const named = values.map((v) => ({ ...v, name: names.get(v.entity_id) ?? v.entity_id }));
    const dir = sort.desc ? -1 : 1;
    named.sort((a, b) => dir * (sort.by === "name" ? a.name.localeCompare(b.name) : a.value - b.value));
    return named;
  }, [values, names, sort]);
  const ranks = useMemo(() => new Map([...values].sort((a, b) => b.value - a.value).map((v, i) => [v.entity_id, i + 1])), [values]);
  const head = (by: "name" | "value", label: string, cls?: string) => (
    <th className={cls} aria-sort={sort.by === by ? (sort.desc ? "descending" : "ascending") : "none"}>
      <button className="th-sort" onClick={() => setSort({ by, desc: sort.by === by ? !sort.desc : by === "value" })}>
        {label}{sort.by === by ? (sort.desc ? " ↓" : " ↑") : ""}
      </button>
    </th>
  );
  return (
    <>
      {error && <p className="error">{error}</p>}
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th className="num">Rank</th>{head("name", "Country")}{head("value", `${indicator.name}, ${year}`, "num")}</tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const on = selection.includes(r.entity_id);
              return (
                <tr key={r.entity_id} className={on ? "selected" : ""} onClick={() => dispatch({ type: "toggleSelect", entity: r.entity_id })}
                  aria-selected={on}>
                  <td className="num">{ranks.get(r.entity_id)}</td>
                  <td>{r.name}</td>
                  <td className="num">{formatValue(r.value, indicator.unit, indicator.decimals)}{r.status === "P" ? " *" : ""}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="caption">
        {sourceLine(indicator)}. {rows.length} countries. Click a row to select it.
        {rows.some((r) => r.status === "P") ? " * projection." : ""}
      </p>
    </>
  );
}

function ChartView({ indicator, names, selection }: { indicator: Indicator; names: Map<string, string>; selection: string[] }) {
  // With nothing selected, show the world so the panel is never empty.
  const ids = selection.length ? selection : ["world"];
  const key = ids.join(",");
  const [rows, setRows] = useState<SeriesRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setRows(null);
    api.series(indicator.indicator_id, key.split(","))
      .then((r) => { if (live) { setRows(r); setError(null); } })
      .catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [indicator.indicator_id, key]);
  const entities = useMemo(() => key.split(",").map((id) => ({ id, name: names.get(id) ?? id })), [key, names]);
  const option = useCallback(() => lineOption(rows ?? [], entities, indicator.unit, indicator.decimals), [rows, entities, indicator]);
  return (
    <>
      {error && <p className="error">{error}</p>}
      {rows && rows.length === 0 && <p className="muted">No data for this indicator yet.</p>}
      {rows && rows.length > 0 && <div className="chart-fill"><EChart option={option} height="100%" label={`${indicator.name} chart`} /></div>}
      <p className="caption">
        {sourceLine(indicator)}. {selection.length ? "Selected countries." : "World shown; select countries on a map or table to compare."}
        {rows?.some((r) => r.status === "P") ? " Dashed lines are projections." : ""}
      </p>
    </>
  );
}
