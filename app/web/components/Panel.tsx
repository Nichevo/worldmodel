"use client";

import type { ECharts } from "echarts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import EChart from "@/components/EChart";
import WorldMap, { type Scale } from "@/components/WorldMap";
import { api, type Indicator, type SeriesRow } from "@/lib/api";
import type { CameraBus } from "@/lib/camera";
import { lineOption } from "@/lib/charts";
import { DIVERGING, cssVar } from "@/lib/colors";
import { SOURCE_SHORT, formatValue } from "@/lib/format";
import { LINKS, type Action, type Group, type Panel as PanelState, type View } from "@/lib/workspace";

export type Value = { entity_id: string; value: number; status: string };

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
  hovered: string | null; // hovered in a linked panel
  onHover: (entity: string | null) => void;
  scale?: Scale; // shared colour scale, when linked maps show the same indicator
  onValues: (id: string, values: Value[] | null) => void;
  cameraBus: CameraBus;
};

const VIEW_LABEL: Record<View, string> = { map: "Map", chart: "Chart", table: "Table" };

// The panel's year, held inside the indicator's range; unset means the last estimate.
export function effectiveYear(panel: PanelState, ind: Indicator | undefined): number | null {
  if (!ind || ind.first_year === null || ind.last_year === null) return null;
  if (panel.year === null) return ind.last_estimate_year ?? ind.last_year;
  return Math.min(ind.last_year, Math.max(ind.first_year, panel.year));
}

export default function Panel({
  panel, indicators, names, selection, dispatch, canDuplicate, canClose, maximised, style,
  hovered, onHover, scale, onValues, cameraBus,
}: Props) {
  const indicator = indicators.find((i) => i.indicator_id === panel.indicator);
  const year = effectiveYear(panel, indicator);
  const set = (patch: Extract<Action, { type: "panel" }>["patch"]) => dispatch({ type: "panel", id: panel.id, patch });
  const playing = usePlay(year, indicator?.first_year ?? null, indicator?.last_year ?? null, (y) => set({ year: y }));
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
        {indicator && year !== null && (
          <label className="year">
            <button className="play" aria-label={playing.on ? "Pause" : "Play through the years"} title={playing.on ? "Pause" : "Play"}
              onClick={(e) => { e.preventDefault(); playing.toggle(); }}>{playing.on ? "❚❚" : "▶"}</button>
            <input
              type="range"
              min={indicator.first_year!}
              max={indicator.last_year!}
              value={year}
              onChange={(e) => set({ year: +e.target.value })}
              aria-label="Year"
            />
            <b>{year}</b>
            {isProjection && <span className="chip" title="The source's projection, not an estimate">proj.</span>}
          </label>
        )}
        <span className="spacer" />
        <LinksMenu panel={panel} dispatch={dispatch} />
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
          <MapView panel={panel} indicator={indicator} year={year} selection={selection} dispatch={dispatch}
            hovered={hovered} onHover={onHover} scale={scale} onValues={onValues} cameraBus={cameraBus} />
        )}
        {indicator && panel.view === "table" && year !== null && (
          <TableView panel={panel} indicator={indicator} year={year} names={names} selection={selection} dispatch={dispatch}
            hovered={hovered} onHover={onHover} />
        )}
        {indicator && panel.view === "chart" && (
          <ChartView indicator={indicator} year={year} names={names} selection={selection} hovered={hovered} onHover={onHover} />
        )}
      </div>
    </section>
  );
}

// Steps the year forward once every 400 ms until the indicator's last year.
function usePlay(year: number | null, first: number | null, last: number | null, step: (y: number) => void) {
  const [on, setOn] = useState(false);
  const cur = useRef({ year, last, step });
  cur.current = { year, last, step };
  useEffect(() => {
    if (!on) return;
    const t = setInterval(() => {
      const { year: y, last: l, step: s } = cur.current;
      if (y === null || l === null || y >= l) setOn(false);
      else s(y + 1);
    }, 400);
    return () => clearInterval(t);
  }, [on]);
  const toggle = () => {
    // Playing from the end starts again from the indicator's first year.
    if (!on && first !== null && year !== null && last !== null && year >= last) step(first);
    setOn(!on);
  };
  return { on, toggle };
}

function LinksMenu({ panel, dispatch }: { panel: PanelState; dispatch: (a: Action) => void }) {
  const box = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (box.current?.open && !box.current.contains(e.target as Node)) box.current.open = false;
    };
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, []);
  const n = LINKS.filter((l) => panel.links[l.key]).length;
  return (
    <details className="links" ref={box}>
      <summary title="How this panel links to the others" className={`group-${panel.group}`}>
        Links <b>{panel.group}</b><span className="muted"> {n}/{LINKS.length}</span>
      </summary>
      <div className="links-menu">
        <div className="row">
          Group
          <div className="seg" role="group" aria-label="Link group">
            {(["A", "B"] as Group[]).map((g) => (
              <button key={g} className={g === panel.group ? "on" : ""} aria-pressed={g === panel.group}
                onClick={() => dispatch({ type: "panel", id: panel.id, patch: { group: g } })}>{g}</button>
            ))}
          </div>
        </div>
        {LINKS.map((l) => (
          <label key={l.key} title={l.hint}>
            <input type="checkbox" checked={panel.links[l.key]}
              onChange={(e) => dispatch({ type: "link", id: panel.id, key: l.key, on: e.target.checked })} />
            {l.label}
          </label>
        ))}
        <label title="Show the group's year plus this many years, e.g. -20 for a generation earlier">
          Year offset
          <input type="number" value={panel.offset} min={-200} max={200} step={1} disabled={!panel.links.year}
            onChange={(e) => dispatch({ type: "panel", id: panel.id, patch: { offset: Math.trunc(+e.target.value) || 0 } })} />
        </label>
        <p className="caption">Selection is shared by every panel that links it; the rest link within the group.</p>
      </div>
    </details>
  );
}

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

function MapView({ panel, indicator, year, selection, dispatch, hovered, onHover, scale, onValues, cameraBus }: {
  panel: PanelState; indicator: Indicator; year: number; selection: string[]; dispatch: (a: Action) => void;
  hovered: string | null; onHover: (e: string | null) => void; scale?: Scale;
  onValues: (id: string, v: Value[] | null) => void; cameraBus: CameraBus;
}) {
  const { values, error } = useMapValues(indicator.indicator_id, year);
  useEffect(() => { onValues(panel.id, values); }, [panel.id, values, onValues]);
  useEffect(() => () => onValues(panel.id, null), [panel.id, onValues]);
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
        onPick={(iso) => dispatch({ type: "toggleSelect", entity: iso, panel: panel.id })}
        scale={scale}
        hovered={hovered}
        onHover={onHover}
        camera={panel.links.camera ? { bus: cameraBus, id: panel.id, group: panel.group } : null}
      />
      <p className="caption">
        {sourceLine(indicator)}. {values.length} countries with data.{scale ? " Colour scale shared with linked maps." : ""} Click a country to select it.
      </p>
    </>
  );
}

function TableView({ panel, indicator, year, names, selection, dispatch, hovered, onHover }: {
  panel: PanelState; indicator: Indicator; year: number; names: Map<string, string>; selection: string[];
  dispatch: (a: Action) => void; hovered: string | null; onHover: (e: string | null) => void;
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
          <tbody onMouseLeave={() => onHover(null)}>
            {rows.map((r) => {
              const on = selection.includes(r.entity_id);
              return (
                <tr key={r.entity_id} className={[on ? "selected" : "", hovered === r.entity_id ? "hovered" : ""].join(" ")}
                  onClick={() => dispatch({ type: "toggleSelect", entity: r.entity_id, panel: panel.id })}
                  onMouseEnter={() => onHover(r.entity_id)} onMouseLeave={() => onHover(null)} aria-selected={on}>
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

function ChartView({ indicator, year, names, selection, hovered, onHover }: {
  indicator: Indicator; year: number | null; names: Map<string, string>; selection: string[];
  hovered: string | null; onHover: (e: string | null) => void;
}) {
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
  const option = useCallback(() => {
    const o = lineOption(rows ?? [], entities, indicator.unit, indicator.decimals);
    if (year === null) return o;
    // A thin rule at the panel's year, so a linked or playing year shows here too.
    const marker = {
      type: "line" as const, id: "year-marker", data: [], silent: true,
      markLine: { symbol: "none", silent: true, animation: false, label: { show: false },
        lineStyle: { color: cssVar("--muted"), type: "solid" as const, width: 1 }, data: [{ xAxis: year }] },
    };
    return { ...o, series: [...(o.series as object[]), marker] } as typeof o;
  }, [rows, entities, indicator, year]);

  // Hover in either direction: a linked hover emphasises that line; hovering a line tells the others.
  const chart = useRef<ECharts | null>(null);
  const hoverRef = useRef(onHover);
  hoverRef.current = onHover;
  const onReady = useCallback((c: ECharts) => {
    chart.current = c;
    c.on("mouseover", (p) => { if (p.seriesName && p.seriesName !== "year-marker") hoverRef.current(String(p.seriesName)); });
    c.on("mouseout", () => hoverRef.current(null));
  }, []);
  useEffect(() => {
    const c = chart.current;
    if (!c || !hovered || !key.split(",").includes(hovered)) return;
    const seriesId = [`${hovered}:E`, `${hovered}:P`];
    c.dispatchAction({ type: "highlight", seriesId });
    return () => { if (!c.isDisposed()) c.dispatchAction({ type: "downplay", seriesId }); };
  }, [hovered, key, rows]);
  return (
    <>
      {error && <p className="error">{error}</p>}
      {rows && rows.length === 0 && <p className="muted">No data for this indicator yet.</p>}
      {rows && rows.length > 0 && <div className="chart-fill"><EChart option={option} height="100%" label={`${indicator.name} chart`} onReady={onReady} /></div>}
      <p className="caption">
        {sourceLine(indicator)}. {selection.length ? "Selected countries." : "World shown; select countries on a map or table to compare."}
        {rows?.some((r) => r.status === "P") ? " Dashed lines are projections." : ""}
      </p>
    </>
  );
}
