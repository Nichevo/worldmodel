"use client";

import type { ECharts } from "echarts";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import EChart from "@/components/EChart";
import WorldMap, { type Scale } from "@/components/WorldMap";
import { api, type Indicator, type Pyramid as PyramidData, type SeriesRow } from "@/lib/api";
import type { CameraBus } from "@/lib/camera";
import { linesOption, pyramidCompareOption, scatterOption, type ScatterPoint } from "@/lib/charts";
import { DIVERGING, cssVar } from "@/lib/colors";
import { SOURCE_SHORT, formatValue } from "@/lib/format";
import { CHANGE_COL, LINKS, pyramidOptions, pyramidString, scatterOptions, scatterString, type Action, type Group, type Panel as PanelState, type View } from "@/lib/workspace";

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

const VIEW_LABEL: Record<View, string> = { map: "Map", chart: "Chart", table: "Table", pyramid: "Pyramid", scatter: "Scatter" };

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
  // A pyramid has no indicator of its own; its years follow total population.
  const chosen = indicators.find((i) => i.indicator_id === panel.indicator);
  const indicator = panel.view === "pyramid" ? (indicators.find((i) => i.indicator_id === "pop_total") ?? chosen) : chosen;
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
        {panel.view !== "pyramid" && (
          <select value={panel.indicator} onChange={(e) => set({ indicator: e.target.value })} aria-label="Indicator">
            {domains.map((d) => (
              <optgroup key={d} label={d[0].toUpperCase() + d.slice(1)}>
                {indicators.filter((i) => i.domain === d).map((i) => (
                  <option key={i.indicator_id} value={i.indicator_id}>{i.name}</option>
                ))}
              </optgroup>
            ))}
          </select>
        )}
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
            <button className="today" title="Jump to this year" disabled={year === todayIn(indicator)}
              onClick={(e) => { e.preventDefault(); set({ year: todayIn(indicator) }); }}>Today</button>
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
          <TableView panel={panel} indicator={indicator} indicators={indicators} year={year} names={names} selection={selection} dispatch={dispatch}
            hovered={hovered} onHover={onHover} />
        )}
        {indicator && panel.view === "chart" && (
          <ChartView panel={panel} indicator={indicator} indicators={indicators} year={year} names={names} selection={selection}
            dispatch={dispatch} hovered={hovered} onHover={onHover} />
        )}
        {indicator && panel.view === "scatter" && year !== null && (
          <ScatterView panel={panel} indicator={indicator} indicators={indicators} year={year} names={names} selection={selection}
            dispatch={dispatch} hovered={hovered} onHover={onHover} />
        )}
        {indicator && panel.view === "pyramid" && year !== null && (
          <PyramidView panel={panel} year={year} names={names} selection={selection} dispatch={dispatch} />
        )}
      </div>
    </section>
  );
}

// This calendar year, held inside the indicator's range.
function todayIn(ind: Indicator): number {
  return Math.min(ind.last_year!, Math.max(ind.first_year!, new Date().getFullYear()));
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
    mapValues(indicator, year)
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

// Values for one indicator and year, shared by every panel that asks (a page load's worth).
const mapCache = new Map<string, Promise<Value[]>>();
function mapValues(indicator: string, year: number): Promise<Value[]> {
  const key = `${indicator}|${year}`;
  if (!mapCache.has(key)) {
    const p = api.map(indicator, year);
    p.catch(() => mapCache.delete(key));
    mapCache.set(key, p);
  }
  return mapCache.get(key)!;
}

type Column = { key: string; label: string; unit: string; decimals: number; values: Map<string, Value> };
type Sort = { by: string; desc: boolean };

function TableView({ panel, indicator, indicators, year, names, selection, dispatch, hovered, onHover }: {
  panel: PanelState; indicator: Indicator; indicators: Indicator[]; year: number; names: Map<string, string>;
  selection: string[]; dispatch: (a: Action) => void; hovered: string | null; onHover: (e: string | null) => void;
}) {
  // The panel's indicator, any extra indicators picked for this table (same year),
  // and optionally its change over ten years.
  const extra = panel.cols.filter((c) => c !== panel.indicator && (c === CHANGE_COL || indicators.some((i) => i.indicator_id === c)));
  const wanted = useMemo(() => [
    { id: panel.indicator, year },
    ...extra.filter((c) => c !== CHANGE_COL).map((id) => ({ id, year })),
    ...(extra.includes(CHANGE_COL) ? [{ id: panel.indicator, year: year - 10 }] : []),
  ], [panel.indicator, year, extra.join(",")]);
  const [loaded, setLoaded] = useState<Map<string, Value[]>>(new Map());
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    Promise.all(wanted.map((w) => mapValues(w.id, w.year).catch(() => [] as Value[]).then((v) => [`${w.id}|${w.year}`, v] as const)))
      .then((pairs) => { if (live) { setLoaded(new Map(pairs)); setError(null); } })
      .catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [wanted]);

  const byId = (rows: Value[] | undefined) => new Map((rows ?? []).map((v) => [v.entity_id, v]));
  const main = byId(loaded.get(`${panel.indicator}|${year}`));
  const columns: Column[] = [
    { key: "main", label: `${indicator.name}, ${year}`, unit: indicator.unit, decimals: indicator.decimals, values: main },
    ...extra.map((c): Column => {
      if (c === CHANGE_COL) {
        const before = byId(loaded.get(`${panel.indicator}|${year - 10}`));
        const diff = new Map<string, Value>();
        main.forEach((v, id) => {
          const b = before.get(id);
          if (b) diff.set(id, { entity_id: id, value: v.value - b.value, status: v.status });
        });
        return { key: c, label: `Change since ${year - 10}`, unit: indicator.unit === "percent" ? "points" : indicator.unit,
          decimals: indicator.decimals, values: diff };
      }
      const ind = indicators.find((i) => i.indicator_id === c)!;
      return { key: c, label: ind.name, unit: ind.unit, decimals: ind.decimals, values: byId(loaded.get(`${c}|${year}`)) };
    }),
  ];

  const [sort, setSort] = useState<Sort>({ by: "main", desc: true });
  const [pin, setPin] = useState(true);
  const sortCol = columns.find((c) => c.key === sort.by) ?? columns[0];
  const rows = useMemo(() => {
    const ids = [...main.keys()];
    const dir = sort.desc ? -1 : 1;
    const name = (id: string) => names.get(id) ?? id;
    ids.sort((a, b) => {
      if (sort.by === "name") return dir * name(a).localeCompare(name(b));
      const va = sortCol.values.get(a)?.value, vb = sortCol.values.get(b)?.value;
      if (va === undefined || vb === undefined) return va === undefined ? (vb === undefined ? 0 : 1) : -1; // blanks last
      return dir * (va - vb);
    });
    // Selected countries first, in the sort order, so they're easy to compare.
    if (pin && selection.length) ids.sort((a, b) => Number(selection.includes(b)) - Number(selection.includes(a)));
    return ids;
  }, [main, sort, sortCol, names, pin, selection]);
  const ranks = useMemo(() => {
    const ranked = [...sortCol.values.values()].sort((a, b) => (sort.desc ? b.value - a.value : a.value - b.value));
    return new Map(ranked.map((v, i) => [v.entity_id, i + 1]));
  }, [sortCol, sort.desc]);

  const head = (by: string, label: string, cls?: string) => (
    <th key={by} className={cls} aria-sort={sort.by === by ? (sort.desc ? "descending" : "ascending") : "none"}>
      <button className="th-sort" onClick={() => setSort({ by, desc: sort.by === by ? !sort.desc : by !== "name" })}>
        {label}{sort.by === by ? (sort.desc ? " ↓" : " ↑") : ""}
      </button>
    </th>
  );
  const fmt = (c: Column, v: Value | undefined) =>
    v === undefined ? "–" : `${c.key === CHANGE_COL && v.value > 0 ? "+" : ""}${formatValue(v.value, c.unit === "points" ? "" : c.unit, c.decimals)}${c.key === CHANGE_COL && c.unit === "points" ? " pts" : ""}${v.status === "P" ? " *" : ""}`;

  return (
    <>
      {error && <p className="error">{error}</p>}
      <div className="table-tools">
        <ColumnsMenu panel={panel} indicators={indicators} dispatch={dispatch} />
        <label className="small"><input type="checkbox" checked={pin} onChange={(e) => setPin(e.target.checked)} /> Selected first</label>
        <span className="small muted">Rank by {sort.by === "name" ? indicator.name : sortCol.label}</span>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th className="num">Rank</th>
              {head("name", "Country")}
              {columns.map((c) => head(c.key, c.label, "num"))}
            </tr>
          </thead>
          <tbody onMouseLeave={() => onHover(null)}>
            {rows.map((id) => {
              const on = selection.includes(id);
              return (
                <tr key={id} className={[on ? "selected" : "", hovered === id ? "hovered" : ""].join(" ")}
                  onClick={() => dispatch({ type: "toggleSelect", entity: id, panel: panel.id })}
                  onMouseEnter={() => onHover(id)} aria-selected={on}>
                  <td className="num">{ranks.get(id) ?? "–"}</td>
                  <td>{names.get(id) ?? id}</td>
                  {columns.map((c) => <td key={c.key} className="num">{fmt(c, c.values.get(id))}</td>)}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="caption">
        {sourceLine(indicator)}. {rows.length} countries. Click a row to select it; click a heading to sort.
        {[...main.values()].some((r) => r.status === "P") ? " * projection." : ""}
      </p>
    </>
  );
}

// Extra indicators drawn as lines on a chart: up to MAX_LINES, in at most two units.
const MAX_LINES = 4;
function lineExtras(panel: PanelState, indicator: Indicator, indicators: Indicator[]): Indicator[] {
  const units = new Set([indicator.unit]);
  const out: Indicator[] = [];
  for (const c of panel.cols) {
    const i = indicators.find((x) => x.indicator_id === c);
    if (!i?.available || i.indicator_id === indicator.indicator_id || out.length >= MAX_LINES - 1) continue;
    if (!units.has(i.unit) && units.size >= 2) continue;
    units.add(i.unit);
    out.push(i);
  }
  return out;
}

// Pick extra indicators: table columns, or extra lines on a chart (`lines`), which
// allow only indicators that fit the chart's two axes.
function ColumnsMenu({ panel, indicators, dispatch, lines = false, units = [] }: {
  panel: PanelState; indicators: Indicator[]; dispatch: (a: Action) => void; lines?: boolean; units?: string[];
}) {
  const box = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (box.current?.open && !box.current.contains(e.target as Node)) box.current.open = false;
    };
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, []);
  const toggle = (id: string, on: boolean) =>
    dispatch({ type: "panel", id: panel.id, patch: { cols: on ? [...panel.cols.filter((c) => c !== id), id] : panel.cols.filter((c) => c !== id) } });
  const domains = [...new Set(indicators.map((i) => i.domain))];
  const main = indicators.find((i) => i.indicator_id === panel.indicator);
  const shownIds = new Set(lines && main ? lineExtras(panel, main, indicators).map((i) => i.indicator_id) : []);
  const lineCount = shownIds.size;
  return (
    <details className="links cols" ref={box}>
      <summary>{lines ? "Lines" : "Columns"} <span className="muted">+{lines ? lineCount : panel.cols.length}</span></summary>
      <div className="links-menu">
        {lines ? <p className="caption">Add indicators to this chart. Up to {MAX_LINES} lines per country, in at most two units.</p> : (
          <label>
            <input type="checkbox" checked={panel.cols.includes(CHANGE_COL)} onChange={(e) => toggle(CHANGE_COL, e.target.checked)} />
            Change over 10 years
          </label>
        )}
        {domains.map((d) => (
          <Fragment key={d}>
            <div className="menu-head">{d[0].toUpperCase() + d.slice(1)}</div>
            {indicators.filter((i) => i.domain === d && i.indicator_id !== panel.indicator && (i.available || panel.cols.includes(i.indicator_id))).map((i) => {
              const on = lines ? shownIds.has(i.indicator_id) : panel.cols.includes(i.indicator_id);
              const blocked = lines && !on && (lineCount >= MAX_LINES - 1 || (units.length >= 2 && !units.includes(i.unit)));
              return (
                <label key={i.indicator_id} className={blocked ? "muted" : undefined}
                  title={blocked ? (lineCount >= MAX_LINES - 1 ? `At most ${MAX_LINES} lines` : `The chart already uses two units: ${units.join(", ")}`) : i.unit}>
                  <input type="checkbox" checked={on} disabled={blocked} onChange={(e) => toggle(i.indicator_id, e.target.checked)} />
                  {i.name}
                </label>
              );
            })}
          </Fragment>
        ))}
      </div>
    </details>
  );
}

function ChartView({ panel, indicator, indicators, year, names, selection, dispatch, hovered, onHover }: {
  panel: PanelState; indicator: Indicator; indicators: Indicator[]; year: number | null; names: Map<string, string>;
  selection: string[]; dispatch: (a: Action) => void; hovered: string | null; onHover: (e: string | null) => void;
}) {
  // With nothing selected, show the world so the panel is never empty.
  const ids = selection.length ? selection : ["world"];
  const key = ids.join(",");
  // The panel's indicator plus any extra lines picked in the Lines menu (shared with the table's columns).
  const shown = useMemo(() => [indicator, ...lineExtras(panel, indicator, indicators)], [panel, indicator, indicators]);
  const showKey = shown.map((i) => i.indicator_id).join(",");
  const [rows, setRows] = useState<SeriesRow[][] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setRows(null);
    Promise.all(showKey.split(",").map((ind) => api.series(ind, key.split(","))))
      .then((r) => { if (live) { setRows(r); setError(null); } })
      .catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [showKey, key]);
  const entities = useMemo(() => key.split(",").map((id) => ({ id, name: names.get(id) ?? id })), [key, names]);
  const option = useCallback(() => {
    const layers = shown.map((i, n) => ({ id: i.indicator_id, name: i.name, unit: i.unit, decimals: i.decimals, rows: rows?.[n] ?? [] }));
    const o = linesOption(layers, entities);
    if (year === null) return o;
    // A thin rule at the panel's year, so a linked or playing year shows here too.
    const marker = {
      type: "line" as const, id: "year-marker", data: [], silent: true,
      markLine: { symbol: "none", silent: true, animation: false, label: { show: false },
        lineStyle: { color: cssVar("--muted"), type: "solid" as const, width: 1 }, data: [{ xAxis: year }] },
    };
    return { ...o, series: [...(o.series as object[]), marker] } as typeof o;
  }, [rows, entities, shown, year]);
  const hasRows = rows?.some((r) => r.length > 0);
  const units = [...new Set(shown.map((i) => i.unit))];

  // Hover in either direction: a linked hover emphasises that line; hovering a line tells the others.
  const chart = useRef<ECharts | null>(null);
  const hoverRef = useRef(onHover);
  hoverRef.current = onHover;
  const onReady = useCallback((c: ECharts) => {
    chart.current = c;
    c.on("mouseover", (p) => { if (p.seriesName && p.seriesName !== "year-marker") hoverRef.current(String(p.seriesName).split("|")[0]); });
    c.on("mouseout", () => hoverRef.current(null));
  }, []);
  useEffect(() => {
    const c = chart.current;
    if (!c || !hovered || !key.split(",").includes(hovered)) return;
    const seriesId = showKey.split(",").flatMap((ind) => [`${hovered}|${ind}:E`, `${hovered}|${ind}:P`]);
    c.dispatchAction({ type: "highlight", seriesId });
    return () => { if (!c.isDisposed()) c.dispatchAction({ type: "downplay", seriesId }); };
  }, [hovered, key, rows, showKey]);
  return (
    <>
      {error && <p className="error">{error}</p>}
      <div className="table-tools">
        <ColumnsMenu panel={panel} indicators={indicators} dispatch={dispatch} lines units={units} />
        {units.length > 1 && <span className="small muted">Right axis: {units[1]}</span>}
      </div>
      {rows && !hasRows && <p className="muted">No data for this indicator yet.</p>}
      {rows && hasRows && <div className="chart-fill"><EChart option={option} height="100%" label={`${indicator.name} chart`} onReady={onReady} /></div>}
      <p className="caption">
        {sourceLine(indicator)}. {selection.length ? "Selected countries." : "World shown; select countries on a map or table to compare."}
        {rows?.some((r) => r.some((x) => x.status === "P")) ? " Dashed lines are projections." : ""}
      </p>
    </>
  );
}

// One dot per country: the panel's indicator across, a second one up, and
// optionally a third as bubble size. Click a dot to select the country.
function ScatterView({ panel, indicator, indicators, year, names, selection, dispatch, hovered, onHover }: {
  panel: PanelState; indicator: Indicator; indicators: Indicator[]; year: number; names: Map<string, string>;
  selection: string[]; dispatch: (a: Action) => void; hovered: string | null; onHover: (e: string | null) => void;
}) {
  const opts = scatterOptions(panel.xy);
  const usable = indicators.filter((i) => i.available);
  const yInd = usable.find((i) => i.indicator_id === opts.y && i.indicator_id !== indicator.indicator_id)
    ?? usable.find((i) => i.indicator_id === (indicator.indicator_id === "life_expectancy" ? "tfr" : "life_expectancy"))
    ?? usable.find((i) => i.indicator_id !== indicator.indicator_id) ?? indicator;
  const sizeInd = usable.find((i) => i.indicator_id === opts.size) ?? null;
  const setOpts = (o: Partial<typeof opts>) =>
    dispatch({ type: "panel", id: panel.id, patch: { xy: scatterString({ ...opts, y: yInd.indicator_id, ...o }) } });

  const xs = useMapValues(indicator.indicator_id, year);
  const ys = useMapValues(yInd.indicator_id, year);
  const sizes = useMapValues(sizeInd?.indicator_id ?? indicator.indicator_id, year);
  const error = xs.error ?? ys.error ?? (sizeInd ? sizes.error : null);
  const points = useMemo(() => {
    const yBy = new Map(ys.values.map((v) => [v.entity_id, v]));
    const sBy = new Map(sizes.values.map((v) => [v.entity_id, v]));
    const out: ScatterPoint[] = [];
    for (const v of xs.values) {
      const w = yBy.get(v.entity_id);
      if (!w || (opts.logX && v.value <= 0) || (opts.logY && w.value <= 0)) continue;
      const z = sizeInd ? sBy.get(v.entity_id) : undefined;
      if (sizeInd && !z) continue;
      out.push({ id: v.entity_id, name: names.get(v.entity_id) ?? v.entity_id, x: v.value, y: w.value, size: z?.value,
        proj: v.status === "P" || w.status === "P" });
    }
    return out;
  }, [xs.values, ys.values, sizes.values, sizeInd, opts.logX, opts.logY, names]);

  const option = useCallback(() => scatterOption([...points],
    { name: indicator.name, unit: indicator.unit, decimals: indicator.decimals, log: opts.logX },
    { name: yInd.name, unit: yInd.unit, decimals: yInd.decimals, log: opts.logY },
    sizeInd ? { name: sizeInd.name, unit: sizeInd.unit, decimals: sizeInd.decimals, log: false } : null,
    selection, hovered), [points, indicator, yInd, sizeInd, opts.logX, opts.logY, selection, hovered]);

  const hoverRef = useRef(onHover);
  hoverRef.current = onHover;
  const pickRef = useRef((id: string) => dispatch({ type: "toggleSelect", entity: id, panel: panel.id }));
  pickRef.current = (id: string) => dispatch({ type: "toggleSelect", entity: id, panel: panel.id });
  const onReady = useCallback((c: ECharts) => {
    c.on("mouseover", (p) => { if (p.name) hoverRef.current(String(p.name)); });
    c.on("mouseout", () => hoverRef.current(null));
    c.on("click", (p) => { if (p.name) pickRef.current(String(p.name)); });
  }, []);

  const domains = [...new Set(usable.map((i) => i.domain))];
  const choices = (skip: string) => domains.map((d) => (
    <optgroup key={d} label={d[0].toUpperCase() + d.slice(1)}>
      {usable.filter((i) => i.domain === d && i.indicator_id !== skip).map((i) => (
        <option key={i.indicator_id} value={i.indicator_id}>{i.name}</option>
      ))}
    </optgroup>
  ));
  return (
    <>
      <div className="table-tools">
        <span className="small muted">Across: {indicator.name}</span>
        <label className="small">
          Up
          <select value={yInd.indicator_id} onChange={(e) => setOpts({ y: e.target.value })}>{choices(indicator.indicator_id)}</select>
        </label>
        <label className="small">
          Bubble size
          <select value={sizeInd?.indicator_id ?? ""} onChange={(e) => setOpts({ size: e.target.value })}>
            <option value="">none (dots)</option>
            {choices("")}
          </select>
        </label>
        <label className="small"><input type="checkbox" checked={opts.logX} onChange={(e) => setOpts({ logX: e.target.checked })} /> Log across</label>
        <label className="small"><input type="checkbox" checked={opts.logY} onChange={(e) => setOpts({ logY: e.target.checked })} /> Log up</label>
      </div>
      {error && <p className="error">{error}</p>}
      {!error && points.length === 0 && <p className="muted">No countries have both values for {year}.</p>}
      {points.length > 0 && (
        <div className="chart-fill"><EChart option={option} height="100%" label={`${yInd.name} against ${indicator.name}, ${year}`} onReady={onReady} /></div>
      )}
      <p className="caption">
        {points.length} countries in {year}.{sizeInd ? ` Bubble area shows ${sizeInd.name.toLowerCase()}.` : ""}
        {points.some((p) => p.proj) ? " Faded dots are projections." : ""} Click a dot to select the country; press ▶ to play through the years.
      </p>
    </>
  );
}

// One population pyramid, optionally with a second drawn over it as an outline:
// the second selected country in the same year, or the same country in another year.
function PyramidView({ panel, year, names, selection, dispatch }: {
  panel: PanelState; year: number; names: Map<string, string>; selection: string[]; dispatch: (a: Action) => void;
}) {
  const opts = pyramidOptions(panel.pyr);
  const setOpts = (o: Partial<typeof opts>) =>
    dispatch({ type: "panel", id: panel.id, patch: { pyr: pyramidString({ ...opts, ...o }) } });
  const base = selection[0] ?? "world";
  const other = opts.compare === "auto" ? (selection[1] ? { entity: selection[1], year } : null)
    : opts.compare === "none" ? null : { entity: base, year: opts.compare };

  const [a, setA] = useState<PyramidData | null>(null);
  const [b, setB] = useState<PyramidData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.pyramid(base, year).then((d) => live && setA(d)).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [base, year]);
  const otherKey = other ? `${other.entity}|${other.year}` : "";
  useEffect(() => {
    let live = true;
    if (!otherKey) { setB(null); return; }
    const [e, y] = otherKey.split("|");
    api.pyramid(e, +y).then((d) => live && setB(d)).catch(() => live && setB(null));
    return () => { live = false; };
  }, [otherKey]);

  const label = (d: PyramidData) => `${names.get(d.entity) ?? d.entity} ${d.year}`;
  const option = useCallback(() => pyramidCompareOption(
    { label: a ? label(a) : "", groups: a?.groups ?? [] },
    b && b.groups.length ? { label: label(b), groups: b.groups } : null,
    opts.absolute,
  ), [a, b, opts.absolute, names]);
  const years = a?.years_available ?? [];

  return (
    <>
      <div className="table-tools">
        <label className="small">
          Compare with
          <select value={opts.compare === "auto" ? "auto" : opts.compare === "none" ? "none" : "year"}
            onChange={(e) => setOpts({ compare: e.target.value === "auto" ? "auto" : e.target.value === "none" ? "none"
              : (years.find((y) => y <= year - 40) ?? years[0] ?? 1950) })}>
            <option value="auto">second selected country</option>
            <option value="year">another year</option>
            <option value="none">nothing</option>
          </select>
        </label>
        {typeof opts.compare === "number" && (
          <select className="small" value={opts.compare} aria-label="Comparison year" onChange={(e) => setOpts({ compare: +e.target.value })}>
            {years.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        )}
        <div className="seg" role="group" aria-label="Scale">
          <button className={!opts.absolute ? "on" : ""} aria-pressed={!opts.absolute} onClick={() => setOpts({ absolute: false })}>% of population</button>
          <button className={opts.absolute ? "on" : ""} aria-pressed={opts.absolute} onClick={() => setOpts({ absolute: true })}>People</button>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {a && !a.groups.length && <p className="muted">No age breakdown for {names.get(base) ?? base}.</p>}
      {a && a.groups.length > 0 && (
        <div className="chart-fill"><EChart option={option} height="100%" label={`Population pyramid of ${label(a)}`} /></div>
      )}
      <p className="caption">
        UN WPP. {selection.length ? "" : "World shown; select a country to see its pyramid. "}
        {a && a.year !== year ? `Age data is every few years; showing ${a.year}. ` : ""}
        {opts.compare === "auto" && selection.length < 2 ? "Select a second country to overlay it. " : ""}
        {b && b.groups.length ? "The outline is the comparison." : ""}
      </p>
    </>
  );
}
