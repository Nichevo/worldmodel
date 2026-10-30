"use client";

import type { ECharts } from "echarts";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import EChart from "@/components/EChart";
import type * as maplibregl from "maplibre-gl";
import WorldMap, { type Overlay, type Scale, type Spark } from "@/components/WorldMap";
import { api, type Entity, type Indicator, type MapRange, type Pyramid as PyramidData, type SeriesRow } from "@/lib/api";
import type { CameraBus } from "@/lib/camera";
import { eventMarks, useChartEvents, withEventTooltip } from "@/lib/events";
import { useGovernments, withParties } from "@/lib/parties";
import { useSettings } from "@/lib/settings";
import { linesOption, outlierFence, pyramidCompareOption, scatterExtent, scatterOption, type Extent, type ScatterPoint } from "@/lib/charts";
import { DIVERGING, cssVar, seriesVar } from "@/lib/colors";
import { credits, csvText, fileName, saveText, saveUrl, sourcesOf, tablePng, titledPng, type Exporter } from "@/lib/download";
import { SOURCE_SHORT, formatValue } from "@/lib/format";
import {
  CHANGE_COL, FORECAST_CHOICES, HISTORY_CHOICES, LINKS, chartSpan, parseRange, pyramidOptions, pyramidString, rangeString,
  scatterOptions, scatterString, type Action, type Group, type Panel as PanelState, type View,
} from "@/lib/workspace";

export type Value = { entity_id: string; value: number; status: string };

// Where a click happened: on a map (a place) or anywhere else (the screen).
export type At = { lng: number; lat: number } | { clientX: number; clientY: number };
export type ClickMode = "popup" | "select";
// A popup to draw in this panel: on a map at its place, elsewhere at x/y in the
// panel (or stacked in the corner when pinned without a place).
export type PanelPopup = { key: string; entity: string; pinned: boolean; at: At | null; node: React.ReactNode };
// What a click on a country asks for: shift says select, double says the other action.
export type Activate = (entity: string, how: { shift: boolean; double: boolean }, at: At | null) => void;

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
  clickMode: ClickMode;
  onActivate: Activate;
  popups: PanelPopup[];
  sparkline: boolean;
};

const VIEW_LABEL: Record<View, string> = { map: "Map", chart: "Chart", table: "Table", pyramid: "Pyramid", scatter: "Scatter" };

// The panel's year, held inside the indicator's range; unset means the last estimate.
export function effectiveYear(panel: PanelState, ind: Indicator | undefined): number | null {
  if (!ind || ind.first_year === null || ind.last_year === null) return null;
  if (panel.year === null) return ind.main_year ?? ind.last_estimate_year ?? ind.last_year;
  return Math.min(ind.last_year, Math.max(ind.first_year, panel.year));
}

export default function Panel({
  panel, indicators, names, selection, dispatch, canDuplicate, canClose, maximised, style,
  hovered, onHover, scale, onValues, cameraBus, clickMode, onActivate, popups, sparkline,
}: Props) {
  // A pyramid has no indicator of its own; its years follow total population.
  const chosen = indicators.find((i) => i.indicator_id === panel.indicator);
  const indicator = panel.view === "pyramid" ? (indicators.find((i) => i.indicator_id === "pop_total") ?? chosen) : chosen;
  const year = effectiveYear(panel, indicator);
  const set = (patch: Extract<Action, { type: "panel" }>["patch"]) => dispatch({ type: "panel", id: panel.id, patch });
  const playing = usePlay(year, indicator?.first_year ?? null, indicator?.last_year ?? null, (y) => set({ year: y }));
  const domains = useMemo(() => [...new Set(indicators.map((i) => i.domain))], [indicators]);
  const isProjection = indicator && year !== null && indicator.last_estimate_year !== null && year > indicator.last_estimate_year;
  const exporter = useRef<Exporter>({});
  const body = useRef<HTMLDivElement>(null);
  const activate: Activate = (entity, how, at) => onActivate(entity, how, at);
  const clicks = { mode: clickMode, activate };
  // Popups not on a map: the open one where it was clicked, pinned ones stacked in the corner.
  const loose = panel.view === "map" ? [] : popups;
  const place = (p: PanelPopup, i: number): React.CSSProperties => {
    const r = body.current?.getBoundingClientRect();
    if (p.at && "clientX" in p.at && r && !p.pinned) {
      const left = Math.min(Math.max(4, p.at.clientX - r.left + 8), Math.max(4, r.width - 300));
      const top = Math.min(Math.max(4, p.at.clientY - r.top + 8), Math.max(4, r.height - 260));
      return { left, top };
    }
    return { right: 6 + i * 14, top: 6 + i * 26 };
  };

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
        <DownloadMenu exporter={exporter} />
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
      <div className="panel-body" ref={body}>
        {!indicator && <p className="muted">Loading…</p>}
        {indicator && panel.view === "map" && year !== null && (
          <MapView panel={panel} indicator={indicator} year={year} selection={selection}
            hovered={hovered} onHover={onHover} scale={scale} onValues={onValues} cameraBus={cameraBus}
            clicks={clicks} popups={popups} sparkline={sparkline} exporter={exporter} />
        )}
        {indicator && panel.view === "table" && year !== null && (
          <TableView panel={panel} indicator={indicator} indicators={indicators} year={year} names={names} selection={selection} dispatch={dispatch}
            hovered={hovered} onHover={onHover} clicks={clicks} exporter={exporter} />
        )}
        {indicator && panel.view === "chart" && (
          <ChartView panel={panel} indicator={indicator} indicators={indicators} year={year} names={names} selection={selection}
            dispatch={dispatch} hovered={hovered} onHover={onHover} clicks={clicks} exporter={exporter} />
        )}
        {indicator && panel.view === "scatter" && year !== null && (
          <ScatterView panel={panel} indicator={indicator} indicators={indicators} year={year} names={names} selection={selection}
            dispatch={dispatch} hovered={hovered} onHover={onHover} clicks={clicks} exporter={exporter} playing={playing.on} />
        )}
        {indicator && panel.view === "pyramid" && year !== null && (
          <PyramidView panel={panel} year={year} names={names} selection={selection} dispatch={dispatch} exporter={exporter} />
        )}
        {loose.map((p, i) => (
          <div key={p.key} className="panel-popup" style={place(p, i)}>{p.node}</div>
        ))}
      </div>
    </section>
  );
}

// This calendar year, held inside the indicator's range.
function todayIn(ind: Indicator): number {
  return Math.min(ind.last_year!, Math.max(ind.first_year!, new Date().getFullYear()));
}

// Steps the year forward once every PLAY_STEP ms until the indicator's last year.
const PLAY_STEP = 400;
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
    }, PLAY_STEP);
    return () => clearInterval(t);
  }, [on]);
  const toggle = () => {
    // Playing from the end starts again from the indicator's first year.
    if (!on && first !== null && year !== null && last !== null && year >= last) step(first);
    setOn(!on);
  };
  return { on, toggle };
}

type Clicks = { mode: ClickMode; activate: Activate };

// Mouse handlers for a country in a table row or chart. In select mode a single
// click waits a moment, so a double click (which opens the popup) can be told apart.
function useClickHandlers(clicks: Clicks) {
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  return {
    click: (entity: string, e: { shiftKey: boolean; clientX: number; clientY: number }) => {
      const at = { clientX: e.clientX, clientY: e.clientY };
      if (clicks.mode === "popup" || e.shiftKey) return clicks.activate(entity, { shift: e.shiftKey, double: false }, at);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => clicks.activate(entity, { shift: false, double: false }, at), 250);
    },
    double: (entity: string, e: { clientX: number; clientY: number }) => {
      if (clicks.mode !== "select") return;
      clearTimeout(timer.current);
      clicks.activate(entity, { shift: false, double: true }, { clientX: e.clientX, clientY: e.clientY });
    },
  };
}

function useOutsideClose(box: React.RefObject<HTMLDetailsElement | null>) {
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (box.current?.open && !box.current.contains(e.target as Node)) box.current.open = false;
    };
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [box]);
}

// CSV of the panel's data and a PNG picture, from whatever the view registered.
function DownloadMenu({ exporter }: { exporter: React.RefObject<Exporter> }) {
  const box = useRef<HTMLDetailsElement>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useOutsideClose(box);
  const csv = () => {
    const text = exporter.current.csv?.();
    if (text) saveText(text, `${exporter.current.name ?? "worldmodel"}.csv`);
    if (box.current) box.current.open = false;
  };
  const png = async () => {
    try {
      const url = await exporter.current.png?.();
      if (url) saveUrl(url, `${exporter.current.name ?? "worldmodel"}.png`);
      setMsg(null);
      if (box.current) box.current.open = false;
    } catch (e) {
      setMsg(String((e as Error).message || e));
    }
  };
  return (
    <details className="links download" ref={box}>
      <summary title="Download this panel's data or a picture" aria-label="Download">⤓</summary>
      <div className="links-menu">
        <button className="link" onClick={csv}>Data (CSV)</button>
        <button className="link" onClick={png}>Picture (PNG)</button>
        {msg && <p className="caption error">{msg}</p>}
      </div>
    </details>
  );
}

// A picture of an ECharts chart: its SVG drawn onto a canvas under a title.
async function chartPng(chart: ECharts | null, title: string, note: string, footer: Promise<string[]>): Promise<string> {
  if (!chart || chart.isDisposed()) throw new Error("Nothing drawn yet");
  const lines = await footer;
  return titledPng(chart.getDataURL({ type: "svg", excludeComponents: ["dataZoom"] }), chart.getWidth(), chart.getHeight(), title, note, lines);
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

function MapView({ panel, indicator, year, selection, hovered, onHover, scale, onValues, cameraBus, clicks, popups, sparkline, exporter }: {
  panel: PanelState; indicator: Indicator; year: number; selection: string[];
  hovered: string | null; onHover: (e: string | null) => void; scale?: Scale;
  onValues: (id: string, v: Value[] | null) => void; cameraBus: CameraBus;
  clicks: Clicks; popups: PanelPopup[]; sparkline: boolean; exporter: React.RefObject<Exporter>;
}) {
  const { values, error } = useMapValues(indicator.indicator_id, year);
  useEffect(() => { onValues(panel.id, values); }, [panel.id, values, onValues]);
  useEffect(() => () => onValues(panel.id, null), [panel.id, onValues]);
  const range = useRange(sparkline ? indicator.indicator_id : null);
  const spark: Spark | null = useMemo(() => (range ? { years: range.years, rows: range.rows, upTo: year } : null), [range, year]);
  const overlays: Overlay[] = popups.flatMap((p) => (p.at && "lng" in p.at ? [{ key: p.key, lng: p.at.lng, lat: p.at.lat, node: p.node }] : []));
  const map = useRef<maplibregl.Map | null>(null);
  const onMap = useCallback((m: maplibregl.Map | null) => { map.current = m; }, []);
  const title = `${indicator.name}, ${year}`;
  exporter.current = {
    name: fileName(indicator.indicator_id, year),
    csv: () => csvText(["entity_id", "indicator_id", "year", "value", "status"],
      values.map((v) => [v.entity_id, indicator.indicator_id, year, v.value, v.status])),
    png: async () => {
      const footer = await credits(sourcesOf(indicator), ["Borders: Natural Earth (public domain)."]);
      return new Promise((ok, fail) => {
        const m = map.current;
        if (!m) return fail(new Error("The map is not ready yet"));
        // The canvas is only readable during a render, so ask for one and copy it then.
        m.once("render", () => {
          const c = m.getCanvas();
          titledPng(c.toDataURL("image/png"), c.clientWidth, c.clientHeight, title, `${values.length} countries with data.`, footer).then(ok, fail);
        });
        m.triggerRepaint();
      });
    },
  };
  const hint = clicks.mode === "popup" ? "Click a country for its popup; shift-click to select it." : "Click a country to select it; double-click for its popup.";
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
        onPick={(iso, e) => clicks.activate(iso, { shift: e.shift, double: e.double }, { lng: e.lngLat[0], lat: e.lngLat[1] })}
        doubleClick={clicks.mode === "select"}
        scale={scale}
        hovered={hovered}
        onHover={onHover}
        camera={panel.links.camera ? { bus: cameraBus, id: panel.id, group: panel.group } : null}
        overlays={overlays}
        spark={spark}
        onMap={onMap}
      />
      <p className="caption">
        {sourceLine(indicator)}. {values.length} countries with data.{scale ? " Colour scale shared with linked maps." : ""} {hint}
      </p>
    </>
  );
}

// Every country's values over all years, for the hover sparkline; once per indicator.
const rangeCache = new Map<string, Promise<MapRange>>();
function useRange(indicator: string | null): MapRange | null {
  const [range, setRange] = useState<MapRange | null>(null);
  useEffect(() => {
    if (!indicator) { setRange(null); return; }
    let live = true;
    if (!rangeCache.has(indicator)) {
      const p = api.mapRange(indicator);
      p.catch(() => rangeCache.delete(indicator));
      rangeCache.set(indicator, p);
    }
    rangeCache.get(indicator)!.then((r) => live && setRange(r)).catch(() => {});
    return () => { live = false; };
  }, [indicator]);
  return range;
}

// Several indicators for one year, handed over together once all have arrived, so
// a chart built from them never draws one indicator's new year against another's
// old one. The values stay on the previous year until then.
function useYearValues(indicators: string[], year: number) {
  const [state, setState] = useState<{ values: Value[][]; error: string | null }>({ values: indicators.map(() => []), error: null });
  const key = indicators.join("|");
  useEffect(() => {
    let live = true;
    Promise.all(indicators.map((i) => mapValues(i, year)))
      .then((v) => live && setState({ values: v, error: null }))
      .catch((e) => live && setState((s) => ({ ...s, error: String(e.message || e) })));
    return () => { live = false; };
  }, [key, year]); // eslint-disable-line react-hooks/exhaustive-deps
  return state;
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

function TableView({ panel, indicator, indicators, year, names, selection, dispatch, hovered, onHover, clicks, exporter }: {
  panel: PanelState; indicator: Indicator; indicators: Indicator[]; year: number; names: Map<string, string>;
  selection: string[]; dispatch: (a: Action) => void; hovered: string | null; onHover: (e: string | null) => void;
  clicks: Clicks; exporter: React.RefObject<Exporter>;
}) {
  const handlers = useClickHandlers(clicks);
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
  exporter.current = {
    name: fileName(indicator.indicator_id, "table", year),
    csv: () => csvText(["rank", "entity_id", "name", ...columns.flatMap((c) => [c.label, `${c.label} status`])],
      rows.map((id) => [ranks.get(id), id, names.get(id) ?? id,
        ...columns.flatMap((c) => [c.values.get(id)?.value, c.values.get(id)?.status])])),
    png: async () => tablePng(`${indicator.name}, ${year}`, ["Rank", "Country", ...columns.map((c) => c.label)],
      rows.map((id) => [String(ranks.get(id) ?? "–"), names.get(id) ?? id, ...columns.map((c) => fmt(c, c.values.get(id)))]),
      40, await credits(sourcesOf(indicator))),
  };

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
                  onClick={(e) => handlers.click(id, e)} onDoubleClick={(e) => handlers.double(id, e)}
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
        {sourceLine(indicator)}. {rows.length} countries. {clicks.mode === "popup" ? "Click a row for its popup, shift-click to select it" : "Click a row to select it, double-click for its popup"}; click a heading to sort.
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

function ChartView({ panel, indicator, indicators, year, names, selection, dispatch, hovered, onHover, clicks, exporter }: {
  panel: PanelState; indicator: Indicator; indicators: Indicator[]; year: number | null; names: Map<string, string>;
  selection: string[]; dispatch: (a: Action) => void; hovered: string | null; onHover: (e: string | null) => void;
  clicks: Clicks; exporter: React.RefObject<Exporter>;
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
  const chartEvents = useChartEvents(useMemo(() => key.split(",").filter(Boolean), [key]));

  // Years shown: quick choices around today, or a span dragged on the slider under the chart.
  const opts = scatterOptions(panel.xy);
  const range = parseRange(panel.range);
  const [from, to] = chartSpan(panel.range);
  const setRange = (r: string) => dispatch({ type: "panel", id: panel.id, patch: { range: r } });
  const setTrim = (trim: boolean) => dispatch({ type: "panel", id: panel.id, patch: { xy: scatterString({ ...opts, trim }) } });
  const setParty = (party: boolean) => dispatch({ type: "panel", id: panel.id, patch: { xy: scatterString({ ...opts, party }) } });
  const settings = useSettings();
  const oneCountry = entities.length === 1 && shown.length === 1;
  const terms = useGovernments(oneCountry ? entities[0].id : null, opts.party, settings.party_office);
  const extent = useMemo(() => {
    const ys = (rows ?? []).flat().map((r) => +r.period);
    return ys.length ? [Math.min(...ys), Math.max(...ys)] as const : null;
  }, [rows]);
  const span = extent ? [Math.max(extent[0], Math.min(extent[1], from ?? extent[0])), Math.min(extent[1], Math.max(extent[0], to ?? extent[1]))] as const : null;

  const inView = useMemo(() => (extent ? chartEvents.filter((e) => +e.start_date.slice(0, 4) <= extent[1] + 1
    && +(e.end_date ?? e.start_date).slice(0, 4) >= extent[0]) : []), [chartEvents, extent]);
  const option = useCallback(() => {
    const layers = shown.map((i, n) => ({ id: i.indicator_id, name: i.name, unit: i.unit, decimals: i.decimals, rows: rows?.[n] ?? [] }));
    const o = linesOption(layers, entities);
    const series: object[] = (o.series as object[]).map((x) => ({ ...x, triggerLineEvent: true }));
    // A thin rule at the panel's year, so a linked or playing year shows here too.
    if (year !== null) series.push({
      type: "line" as const, id: "year-marker", data: [], silent: true,
      markLine: { symbol: "none", silent: true, animation: false, label: { show: false },
        lineStyle: { color: cssVar("--muted"), type: "solid" as const, width: 1 }, data: [{ xAxis: year }] },
    });
    // Events for the countries shown (up to three; Settings: Events on charts), inside the years with data.
    const shownNames = new Map(entities.map((e) => [e.id, e.name]));
    if (inView.length) series.push(eventMarks(inView, shownNames));
    let yAxis = o.yAxis;
    // Ignore outliers: fit the left axis to most of the values in view; spikes run off the edge.
    if (opts.trim && span) {
      const left = layers.filter((l) => l.unit === layers[0].unit).flatMap((l) => l.rows)
        .filter((r) => +r.period >= span[0] && +r.period <= span[1]).map((r) => r.value);
      const fence = outlierFence(left, false);
      if (fence) {
        const pad = (fence[1] - fence[0]) * 0.05;
        const first = Array.isArray(yAxis) ? yAxis[0] : yAxis;
        const trimmed = { ...(first as object), min: fence[0] - pad, max: fence[1] + pad, scale: true,
          name: `${(first as { name?: string }).name ?? ""} (outliers cut off)` };
        yAxis = (Array.isArray(yAxis) ? [trimmed, ...yAxis.slice(1)] : trimmed) as typeof yAxis;
      }
    }
    const coloured = oneCountry && terms.length ? withParties({ ...o, series } as typeof o, terms, span ? [span[0], span[1]] : null) : { ...o, series };
    return withEventTooltip({
      ...coloured, yAxis,
      grid: { ...(coloured.grid as object), bottom: 40 },
      dataZoom: span ? [{
        type: "slider" as const, xAxisIndex: 0, filterMode: "filter" as const, realtime: false, height: 18, bottom: 6,
        startValue: span[0], endValue: span[1], labelFormatter: (v: number) => String(Math.round(v)), brushSelect: false,
        borderColor: cssVar("--border"), textStyle: { color: cssVar("--muted") },
      }] : undefined,
    } as typeof o, inView, shownNames);
  }, [rows, entities, shown, year, opts.trim, span?.[0], span?.[1], inView, extent, terms, oneCountry]);
  const hasRows = rows?.some((r) => r.length > 0);
  const units = [...new Set(shown.map((i) => i.unit))];

  // Hover in either direction: a linked hover emphasises that line; hovering a line tells the others.
  const chart = useRef<ECharts | null>(null);
  const hoverRef = useRef(onHover);
  hoverRef.current = onHover;
  const handlers = useClickHandlers(clicks);
  const clickRef = useRef(handlers);
  clickRef.current = handlers;
  const rangeRef = useRef(setRange);
  rangeRef.current = setRange;
  const onReady = useCallback((c: ECharts) => {
    chart.current = c;
    const entityOf = (p: { seriesName?: string }) => (p.seriesName && p.seriesName !== "year-marker" ? String(p.seriesName).split("|")[0] : null);
    c.on("mouseover", (p) => { const e = entityOf(p); if (e) hoverRef.current(e); });
    c.on("mouseout", () => hoverRef.current(null));
    c.on("click", (p) => { const e = entityOf(p); const ev = (p.event as { event?: MouseEvent } | undefined)?.event; if (e && ev) clickRef.current.click(e, ev); });
    c.on("dblclick", (p) => { const e = entityOf(p); const ev = (p.event as { event?: MouseEvent } | undefined)?.event; if (e && ev) clickRef.current.double(e, ev); });
    // Dragging the slider sets a span of years, kept with the panel.
    c.on("datazoom", () => {
      const dz = (c.getOption().dataZoom as { startValue?: number; endValue?: number }[] | undefined)?.[0];
      if (dz?.startValue !== undefined && dz.endValue !== undefined) rangeRef.current(`${Math.round(dz.startValue)}-${Math.round(dz.endValue)}`);
    });
  }, []);
  useEffect(() => {
    const c = chart.current;
    if (!c || !hovered || !key.split(",").includes(hovered)) return;
    const seriesId = showKey.split(",").flatMap((ind) => [`${hovered}|${ind}:E`, `${hovered}|${ind}:P`]);
    c.dispatchAction({ type: "highlight", seriesId });
    return () => { if (!c.isDisposed()) c.dispatchAction({ type: "downplay", seriesId }); };
  }, [hovered, key, rows, showKey]);

  const title = `${shown.map((i) => i.name).join(", ")}${span ? `, ${span[0]}–${span[1]}` : ""}`;
  exporter.current = {
    name: fileName(showKey.replace(/,/g, "-"), span?.[0], span?.[1]),
    csv: () => csvText(["entity_id", "name", "indicator_id", "year", "value", "status", "source_id", "vintage"],
      (rows ?? []).flat().filter((r) => !span || (+r.period >= span[0] && +r.period <= span[1]))
        .map((r) => [r.entity_id, names.get(r.entity_id) ?? r.entity_id, r.indicator_id, r.period.slice(0, 4), r.value, r.status, r.source_id, r.vintage])),
    png: () => chartPng(chart.current, title, `${entities.map((e) => e.name).join(", ")}.`,
      credits([...shown.flatMap((i, n) => sourcesOf(i, rows?.[n])), ...inView.map((e) => e.source_id)])),
  };
  const histOn = range.custom ? "" : range.history;
  const foreOn = range.custom ? "" : range.forecast;
  return (
    <>
      {error && <p className="error">{error}</p>}
      <div className="table-tools">
        <ColumnsMenu panel={panel} indicators={indicators} dispatch={dispatch} lines units={units} />
        <div className="range-picker small" role="group" aria-label="Years shown">
          <span className="muted">Back</span>
          <div className="seg">
            {HISTORY_CHOICES.map((h) => (
              <button key={h} className={histOn === h ? "on" : ""} aria-pressed={histOn === h}
                title={h === "a" ? "All history" : `${h} years back from today`}
                onClick={() => setRange(rangeString({ history: h, forecast: range.custom ? "a" : range.forecast }))}>{h === "a" ? "All" : h}</button>
            ))}
          </div>
          <span className="muted">Ahead</span>
          <div className="seg">
            {FORECAST_CHOICES.map((f) => (
              <button key={f} className={foreOn === f ? "on" : ""} aria-pressed={foreOn === f}
                title={f === "a" ? "All projections" : f === "0" ? "No projections" : `${f} years ahead of today`}
                onClick={() => setRange(rangeString({ history: range.custom ? "a" : range.history, forecast: f }))}>{f === "a" ? "All" : f === "0" ? "None" : f}</button>
            ))}
          </div>
          {range.custom && (
            <span className="chip" title="Set by dragging the slider under the chart">
              {range.custom[0]}–{range.custom[1]}
              <button aria-label="Show all years" onClick={() => setRange("")}>×</button>
            </span>
          )}
        </div>
        <label className="small" title="Fit the axis to most of the values; spikes run off the edge">
          <input type="checkbox" checked={opts.trim} onChange={(e) => setTrim(e.target.checked)} /> Ignore outliers
        </label>
        <label className="small" title={oneCountry ? `Colour the line by the party of the head of ${settings.party_office} (Wikidata); change whose in Settings`
          : "For one country and one indicator"}>
          <input type="checkbox" checked={opts.party && oneCountry} disabled={!oneCountry} onChange={(e) => setParty(e.target.checked)} /> Governing party
        </label>
        {opts.party && oneCountry && !terms.length && <span className="small muted">No leaders stored for {entities[0].name}.</span>}
        {units.length > 1 && <span className="small muted">Right axis: {units[1]}</span>}
      </div>
      {rows && !hasRows && <p className="muted">No data for this indicator yet.</p>}
      {rows && hasRows && <div className="chart-fill"><EChart option={option} height="100%" label={`${indicator.name} chart`} onReady={onReady} /></div>}
      <p className="caption">
        {sourceLine(indicator)}. {selection.length ? "Selected countries." : "World shown; select countries on a map or table to compare."}
        {rows?.some((r) => r.some((x) => x.status === "P")) ? " Dashed lines are projections." : ""} Drag the ends of the slider for any span of years.
      </p>
    </>
  );
}

// One dot per country: the panel's indicator across, a second one up, and
// optionally a third as bubble size. Dots can be coloured by region or group
// and labelled. Click a dot to select the country.
function ScatterView({ panel, indicator, indicators, year, names, selection, dispatch, hovered, onHover, clicks, exporter, playing }: {
  panel: PanelState; indicator: Indicator; indicators: Indicator[]; year: number; names: Map<string, string>;
  selection: string[]; dispatch: (a: Action) => void; hovered: string | null; onHover: (e: string | null) => void;
  clicks: Clicks; exporter: React.RefObject<Exporter>; playing: boolean;
}) {
  const opts = scatterOptions(panel.xy);
  const usable = indicators.filter((i) => i.available);
  const yInd = usable.find((i) => i.indicator_id === opts.y && i.indicator_id !== indicator.indicator_id)
    ?? usable.find((i) => i.indicator_id === (indicator.indicator_id === "life_expectancy" ? "tfr" : "life_expectancy"))
    ?? usable.find((i) => i.indicator_id !== indicator.indicator_id) ?? indicator;
  const sizeInd = usable.find((i) => i.indicator_id === opts.size) ?? null;
  const setOpts = (o: Partial<typeof opts>) =>
    dispatch({ type: "panel", id: panel.id, patch: { xy: scatterString({ ...opts, y: yInd.indicator_id, ...o }) } });

  // Across, up, and bubble size (or population when only ranking the "major" countries to label).
  const ids = [indicator.indicator_id, yInd.indicator_id, sizeInd?.indicator_id ?? "pop_total"];
  const { values: [xs = [], ys = [], sizes = []], error } = useYearValues(ids, year);
  // While playing, fetch the next year ahead so each step has its data waiting.
  useEffect(() => {
    if (!playing) return;
    for (const id of ids) mapValues(id, year + 1).catch(() => {});
  }, [playing, year, ids.join("|")]); // eslint-disable-line react-hooks/exhaustive-deps
  const groups = useGroups(opts.colour);
  const points = useMemo(() => {
    const yBy = new Map(ys.map((v) => [v.entity_id, v]));
    const sBy = new Map(sizes.map((v) => [v.entity_id, v]));
    const out: ScatterPoint[] = [];
    for (const v of xs) {
      const w = yBy.get(v.entity_id);
      if (!w || (opts.logX && v.value <= 0) || (opts.logY && w.value <= 0)) continue;
      const z = sizeInd ? sBy.get(v.entity_id) : undefined;
      if (sizeInd && !z) continue;
      out.push({ id: v.entity_id, name: names.get(v.entity_id) ?? v.entity_id, x: v.value, y: w.value, size: z?.value,
        proj: v.status === "P" || w.status === "P", group: groups?.of.get(v.entity_id) });
    }
    return out;
  }, [xs, ys, sizes, sizeInd, opts.logX, opts.logY, names, groups]);
  // "Major": the 12 biggest by bubble size, or by population with plain dots.
  const labelled = useMemo(() => {
    if (opts.labels === "all") return new Set(points.map((p) => p.id));
    if (opts.labels === "selected") return new Set<string>();
    const shown = new Set(points.map((p) => p.id));
    return new Set([...sizes].filter((v) => shown.has(v.entity_id)).sort((a, b) => b.value - a.value)
      .slice(0, 12).map((v) => v.entity_id));
  }, [opts.labels, points, sizes]);

  // While playing, the axes only ever widen, so dots move against still axes
  // instead of everything shifting each year as the range changes.
  const held = useRef<{ x: Extent; y: Extent } | null>(null);
  const hold = useMemo(() => {
    if (!playing) return (held.current = null);
    const now = scatterExtent(points, opts.logX, opts.logY, opts.trim);
    if (!now) return held.current;
    const prev = held.current;
    const grow = (a: Extent, b: Extent): Extent => [Math.min(a[0], b[0]), Math.max(a[1], b[1])];
    return (held.current = prev ? { x: grow(prev.x, now.x), y: grow(prev.y, now.y) } : now);
  }, [playing, points, opts.logX, opts.logY, opts.trim]);

  const option = useCallback(() => scatterOption([...points],
    { name: indicator.name, unit: indicator.unit, decimals: indicator.decimals, log: opts.logX },
    { name: yInd.name, unit: yInd.unit, decimals: yInd.decimals, log: opts.logY },
    sizeInd ? { name: sizeInd.name, unit: sizeInd.unit, decimals: sizeInd.decimals, log: false } : null,
    selection, { grouped: !!groups, labelled, trim: opts.trim, hold, step: playing ? PLAY_STEP : 0 }),
  [points, indicator, yInd, sizeInd, opts.logX, opts.logY, opts.trim, selection, groups, labelled, hold, playing]);

  const hoverRef = useRef(onHover);
  hoverRef.current = onHover;
  const handlers = useClickHandlers(clicks);
  const clickRef = useRef(handlers);
  clickRef.current = handlers;
  const chart = useRef<ECharts | null>(null);
  const onReady = useCallback((c: ECharts) => {
    chart.current = c;
    c.on("mouseover", (p) => { if (p.name && p.seriesId !== "linked") hoverRef.current(String(p.name)); });
    c.on("mouseout", () => hoverRef.current(null));
    const ev = (p: { event?: unknown }) => (p.event as { event?: MouseEvent } | undefined)?.event;
    c.on("click", (p) => { const e = ev(p); if (p.name && e) clickRef.current.click(String(p.name), e); });
    c.on("dblclick", (p) => { const e = ev(p); if (p.name && e) clickRef.current.double(String(p.name), e); });
  }, []);
  // A country hovered in another panel lights up here too, with its name: drawn
  // as a separate one-dot series so label crowding never hides it.
  useEffect(() => {
    const c = chart.current;
    if (!c || !hovered) return;
    type Dot = { name: string; value: number[]; symbolSize?: number; symbol?: string; symbolRotate?: number };
    const opt = c.getOption() as { series?: { id?: string; data?: Dot[] }[] };
    const dot = opt.series?.find((x) => x.id !== "linked")?.data?.find((d) => d.name === hovered);
    if (!dot) return;
    c.dispatchAction({ type: "highlight", seriesIndex: 0, name: hovered });
    // Only the dot's place and shape: its own label and colour settings would hide the name.
    c.setOption({ series: [{
      id: "linked", type: "scatter", silent: true, z: 10, animation: false,
      data: [{ name: dot.name, value: dot.value, symbol: dot.symbol, symbolRotate: dot.symbolRotate, symbolSize: dot.symbolSize,
        itemStyle: { color: "transparent", borderColor: cssVar("--ink"), borderWidth: 2 },
        label: { show: true, formatter: names.get(hovered) ?? hovered, position: "right", color: cssVar("--ink"), fontWeight: "bold",
          fontSize: 12, backgroundColor: cssVar("--surface"), padding: [1, 4], borderRadius: 3 } }],
    }] });
    return () => {
      if (c.isDisposed()) return;
      c.dispatchAction({ type: "downplay", seriesIndex: 0, name: hovered });
      c.setOption({ series: [{ id: "linked", data: [] }] });
    };
  }, [hovered, points, names]);
  exporter.current = {
    name: fileName(indicator.indicator_id, yInd.indicator_id, sizeInd?.indicator_id, year),
    csv: () => csvText(["entity_id", "name", indicator.indicator_id, yInd.indicator_id, ...(sizeInd ? [sizeInd.indicator_id] : []), "year", "projection"],
      points.map((p) => [p.id, p.name, p.x, p.y, ...(sizeInd ? [p.size] : []), year, p.proj ? "yes" : ""])),
    png: () => chartPng(chart.current, `${yInd.name} against ${indicator.name}, ${year}`,
      `${points.length} countries.${sizeInd ? ` Bubble area: ${sizeInd.name.toLowerCase()}.` : ""}`,
      credits([indicator, yInd, sizeInd].flatMap((i) => sourcesOf(i)))),
  };

  const groupList = useGroupList();
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
        <label className="small">
          Colour
          <select value={opts.colour} onChange={(e) => setOpts({ colour: e.target.value })}>
            <option value="">selected countries</option>
            <option value="continent">continent</option>
            <option value="subregion">UN subregion</option>
            <optgroup label="Members of">
              {groupList.map((g) => <option key={g.entity_id} value={g.entity_id}>{g.short_name}</option>)}
            </optgroup>
          </select>
        </label>
        <label className="small">
          Names
          <select value={opts.labels} onChange={(e) => setOpts({ labels: e.target.value as typeof opts.labels })}>
            <option value="selected">selected only</option>
            <option value="major">{sizeInd ? "12 biggest bubbles" : "12 most populous"}</option>
            <option value="all">all (where room)</option>
          </select>
        </label>
        <label className="small"><input type="checkbox" checked={opts.logX} onChange={(e) => setOpts({ logX: e.target.checked })} /> Log across</label>
        <label className="small"><input type="checkbox" checked={opts.logY} onChange={(e) => setOpts({ logY: e.target.checked })} /> Log up</label>
        <label className="small" title="Fit the axes to most countries; the few far outside are drawn as triangles on the edge">
          <input type="checkbox" checked={opts.trim} onChange={(e) => setOpts({ trim: e.target.checked })} /> Ignore outliers
        </label>
      </div>
      {groups && groups.names.length > 0 && (
        <div className="scatter-legend small">
          {groups.names.map((n, i) => (
            <span key={n} className="chip"><span className="swatch" style={{ background: seriesVar(i) }} />{n}</span>
          ))}
          {groups.names.length > 8 && <span className="muted">Colours repeat after eight.</span>}
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {!error && points.length === 0 && <p className="muted">No countries have both values for {year}.</p>}
      {points.length > 0 && (
        <div className="chart-fill">
          <EChart option={option} height="100%" update="merge" label={`${yInd.name} against ${indicator.name}, ${year}`} onReady={onReady} />
        </div>
      )}
      <p className="caption">
        {points.length} countries in {year}.{sizeInd ? ` Bubble area shows ${sizeInd.name.toLowerCase()}.` : ""}
        {points.some((p) => p.proj) ? " Faded dots are projections." : ""} {clicks.mode === "popup" ? "Click a dot for its popup, shift-click to select" : "Click a dot to select, double-click for its popup"}; press ▶ to play through the years.
      </p>
    </>
  );
}

// Which group each country is in, for colouring: every continent or subregion,
// or one bloc's members. Fetched once per choice.
type Groups = { names: string[]; of: Map<string, number> };
const groupsCache = new Map<string, Promise<Groups>>();
function useGroups(colour: string): Groups | null {
  const [groups, setGroups] = useState<Groups | null>(null);
  useEffect(() => {
    if (!colour) { setGroups(null); return; }
    let live = true;
    if (!groupsCache.has(colour)) {
      const byType = colour === "continent" || colour === "subregion";
      const p = api.memberships(byType ? { type: colour } : { group: colour }).then((rows) => {
        const names: string[] = [];
        const of = new Map<string, number>();
        for (const r of rows) {
          if (!names.includes(r.group_name)) names.push(r.group_name);
          if (!of.has(r.member_id)) of.set(r.member_id, names.indexOf(r.group_name));
        }
        return { names, of };
      });
      p.catch(() => groupsCache.delete(colour));
      groupsCache.set(colour, p);
    }
    groupsCache.get(colour)!.then((g) => live && setGroups(g)).catch(() => live && setGroups(null));
    return () => { live = false; };
  }, [colour]);
  return colour ? groups : null;
}

let groupListCache: Promise<Entity[]> | null = null;
function useGroupList(): Entity[] {
  const [list, setList] = useState<Entity[]>([]);
  useEffect(() => {
    groupListCache ??= api.entities("bloc,group,alliance,income_group");
    let live = true;
    groupListCache.then((l) => live && setList(l)).catch(() => { groupListCache = null; });
    return () => { live = false; };
  }, []);
  return list;
}

// One population pyramid, optionally with a second drawn over it as an outline:
// the second selected country in the same year, or the same country in another year.
function PyramidView({ panel, year, names, selection, dispatch, exporter }: {
  panel: PanelState; year: number; names: Map<string, string>; selection: string[]; dispatch: (a: Action) => void;
  exporter: React.RefObject<Exporter>;
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
  const chart = useRef<ECharts | null>(null);
  const onReady = useCallback((c: ECharts) => { chart.current = c; }, []);
  exporter.current = {
    name: fileName("pyramid", a?.entity, a?.year, b?.entity !== a?.entity ? b?.entity : "", b?.year),
    csv: () => csvText(["entity_id", "year", "age", "male", "female"],
      [a, b].flatMap((d) => (d ? d.groups.map((g) => [d.entity, d.year, g.age, g.male, g.female]) : []))),
    png: () => chartPng(chart.current, `Population by age: ${a ? label(a) : ""}${b && b.groups.length ? ` and ${label(b)}` : ""}`,
      `${opts.absolute ? "People" : "Share of each population"}.`, credits(["un_wpp"])),
  };

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
        <div className="chart-fill"><EChart option={option} height="100%" label={`Population pyramid of ${label(a)}`} onReady={onReady} /></div>
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
