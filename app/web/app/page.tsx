"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import Panel, { effectiveYear, type Activate, type At, type PanelPopup, type Value } from "@/components/Panel";
import PopupCard from "@/components/PopupCard";
import Search from "@/components/Search";
import { makeScale, type Scale } from "@/components/WorldMap";
import { api, type Indicator, type SavedLayout } from "@/lib/api";
import { CameraBus } from "@/lib/camera";
import { DIVERGING, seriesVar } from "@/lib/colors";
import { logHistory } from "@/lib/history";
import { useSettings } from "@/lib/settings";
import {
  LAYOUTS, MAX_PANELS, MAX_PINS, MAX_SELECTION, STARTERS, fromQuery, reducer, selectionOf, toQuery,
  type Action, type Group, type Layout, type Panel as PanelState, type Workspace,
} from "@/lib/workspace";

// Grid areas per layout; the panels fill a, b, c, d in order.
const AREAS: Record<Layout, string> = {
  "1": `"a"`,
  "2h": `"a b"`,
  "2v": `"a" "b"`,
  "3": `"a b" "a c"`,
  "4": `"a b" "c d"`,
};
const HAS_COLS = new Set<Layout>(["2h", "3", "4"]);
const HAS_ROWS = new Set<Layout>(["2v", "3", "4"]);

function ExploreWorkspace() {
  const params = useSearchParams();
  const [ws, dispatch] = useReducer(reducer, params, fromQuery);
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [names, setNames] = useState<Map<string, string>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<{ entity: string; group: Group } | null>(null);
  const [values, setValues] = useState<Record<string, Value[]>>({});
  const cameraBus = useMemo(() => new CameraBus(), []);
  const settings = useSettings();
  // The popup open now (one at a time); pinned ones live in the workspace.
  const [open, setOpen] = useState<{ entity: string; panel: string; at: At | null } | null>(null);

  const onValues = useCallback((id: string, v: Value[] | null) => {
    setValues((cur) => {
      if (v === null) {
        if (!(id in cur)) return cur;
        const { [id]: _gone, ...rest } = cur;
        return rest;
      }
      return cur[id] === v ? cur : { ...cur, [id]: v };
    });
  }, []);

  // One colour scale per group and indicator, built from every linked map showing it,
  // so the same colour means the same value across years.
  const scales = useMemo(() => {
    const pools = new Map<string, { ids: string[]; vals: number[]; indicator: string }>();
    for (const p of ws.panels) {
      if (p.view !== "map" || !p.links.scale || !values[p.id]) continue;
      const key = `${p.group}|${p.indicator}`;
      const pool = pools.get(key) ?? { ids: [], vals: [], indicator: p.indicator };
      pool.ids.push(p.id);
      pool.vals.push(...values[p.id].map((v) => v.value));
      pools.set(key, pool);
    }
    const out = new Map<string, Scale>();
    for (const pool of pools.values()) {
      if (pool.ids.length < 2) continue;
      const scale = makeScale(pool.vals, DIVERGING.has(pool.indicator));
      for (const id of pool.ids) out.set(id, scale);
    }
    return out;
  }, [ws.panels, values]);

  useEffect(() => {
    api.indicators()
      .then((list) => setIndicators(list.filter((i) => i.available && !i.breakdowns)))
      .catch((e) => setError(String(e.message || e)));
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(null); };
    window.addEventListener("keydown", esc);
    api.entities().then((list) => setNames(new Map(list.map((e) => [e.entity_id, e.short_name])))).catch(() => {});
    return () => window.removeEventListener("keydown", esc);
  }, []);

  // Panel menus offer the indicators switched on in the Indicators page, plus any a panel already shows.
  const inUse = new Set(ws.panels.flatMap((p) => [p.indicator, ...p.cols]));
  const menu = useMemo(() => indicators.filter((i) => i.enabled || inUse.has(i.indicator_id)), [indicators, [...inUse].join(",")]);
  const byId = useMemo(() => new Map(indicators.map((i) => [i.indicator_id, i])), [indicators]);

  // Click a country: a popup or a selection, as set in Settings.
  const activate = (panel: PanelState): Activate => (entity, how, at) => {
    const popupFirst = settings.click_mode === "popup";
    const wantsPopup = popupFirst ? !how.shift : how.double;
    if (!wantsPopup) return dispatch({ type: "toggleSelect", entity, panel: panel.id });
    setOpen((o) => (o && o.entity === entity && o.panel === panel.id && !how.double ? null : { entity, panel: panel.id, at }));
  };

  // Every indicator the panels show, for the popup tabs.
  const tabs = settings.popup_tabs ? [...new Set(ws.panels.map((p) => p.indicator))].map((id) => byId.get(id)).filter((i): i is Indicator => !!i) : [];
  const popupsFor = (p: PanelState): PanelPopup[] => {
    const ind = p.view === "pyramid" ? byId.get("pop_total") : byId.get(p.indicator);
    if (!ind) return [];
    const year = effectiveYear(p, ind);
    const sel = selectionOf(ws, p);
    const card = (entity: string, pinned: boolean, at: At | null) => (
      <PopupCard entity={entity} indicator={ind} year={year} tabs={tabs} pinned={pinned} selected={sel.includes(entity)}
        onClose={() => (pinned ? dispatch({ type: "unpin", entity, panel: p.id }) : setOpen(null))}
        onPin={() => {
          if (pinned) return dispatch({ type: "unpin", entity, panel: p.id });
          dispatch({ type: "pin", pin: { entity, panel: p.id, ...(at && "lng" in at ? { lng: at.lng, lat: at.lat } : {}) } });
          setOpen(null);
          logHistory({ kind: "pin", title: `Pinned ${names.get(entity) ?? entity}`, entity, indicator: ind.indicator_id });
        }}
        onSelect={() => dispatch({ type: "toggleSelect", entity, panel: p.id })}
        onBoard={settings.side_panel ? (indicator) => dispatch({ type: "board", item: { entity, indicator }, on: true }) : undefined} />
    );
    const out: PanelPopup[] = ws.pins.filter((x) => x.panel === p.id).map((x) => {
      const at = x.lng !== undefined && x.lat !== undefined ? { lng: x.lng, lat: x.lat } : null;
      return { key: `pin:${x.entity}`, entity: x.entity, pinned: true, at, node: card(x.entity, true, at) };
    });
    if (open && open.panel === p.id && !out.some((x) => x.entity === open.entity))
      out.push({ key: `open:${open.entity}`, entity: open.entity, pinned: false, at: open.at, node: card(open.entity, false, open.at) });
    return out;
  };

  // The history log gets each workspace once it has been looked at for a few seconds.
  useEffect(() => {
    if (!indicators.length) return;
    const t = setTimeout(() => {
      const ind = (id: string) => byId.get(id)?.name ?? id;
      const parts = ws.panels.map((p) => `${p.view[0].toUpperCase()}${p.view.slice(1)}: ${p.view === "pyramid" ? "population by age" : ind(p.indicator)}${p.year ? ` ${p.year}` : ""}`);
      const sel = ws.selection.map((id) => names.get(id) ?? id);
      logHistory({ kind: "view", title: parts.join(" · ") + (sel.length ? ` (${sel.join(", ")})` : ""), url: `/?${toQuery(ws)}`,
        indicator: ws.panels[0]?.indicator, entity: ws.selection.length === 1 ? ws.selection[0] : undefined });
    }, 5000);
    return () => clearTimeout(t);
  }, [ws, indicators.length]);

  // Keep the URL in step without a navigation, so the view can be bookmarked.
  useEffect(() => {
    const q = toQuery(ws);
    if (q !== window.location.search.slice(1)) window.history.replaceState(null, "", `?${q}`);
  }, [ws]);

  return (
    <div className="workspace-page">
      <div className="controls ws-bar">
        <h1 className="ws-title">World map</h1>
        <LayoutPicker layout={ws.layout} onPick={(layout) => dispatch({ type: "layout", layout })} />
        <LayoutsMenu ws={ws} onLoad={(query) => dispatch({ type: "load", ws: fromQuery(new URLSearchParams(query)) })} />
        <SelectionBar ws={ws} names={names} dispatch={dispatch} />
        {settings.side_panel && (
          <button className={`small side-toggle${ws.side ? " on" : ""}`} aria-pressed={ws.side} onClick={() => dispatch({ type: "side", on: !ws.side })}
            title="Cards kept beside the panels; send one from any popup">
            Pinboard{ws.board.length ? ` (${ws.board.length})` : ""}
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {ws.pins.length >= MAX_PINS && open && <p className="caption">Up to {MAX_PINS} popups stay pinned; pinning another unpins the oldest.</p>}
      <div className={`ws-row${settings.side_panel && ws.side ? " with-side" : ""}`}>
      <Grid ws={ws} dispatch={dispatch}>
        {(ws.maximised ? ws.panels.filter((p) => p.id === ws.maximised) : ws.panels).map((p, i) => (
          <Panel
            key={p.id}
            panel={p}
            indicators={menu}
            names={names}
            dispatch={dispatch}
            canDuplicate={ws.panels.length < MAX_PANELS}
            canClose={ws.panels.length > 1}
            maximised={ws.maximised === p.id}
            style={{ gridArea: ws.maximised ? "a" : "abcd"[i] }}
            selection={selectionOf(ws, p)}
            hovered={p.links.hover && hover?.group === p.group ? hover.entity : null}
            onHover={(entity) => {
              if (!p.links.hover) return;
              setHover((h) => (entity === null ? (h?.group === p.group ? null : h) : { entity, group: p.group }));
            }}
            scale={scales.get(p.id)}
            onValues={onValues}
            cameraBus={cameraBus}
            clickMode={settings.click_mode}
            onActivate={activate(p)}
            popups={popupsFor(p)}
            sparkline={settings.hover_sparkline}
          />
        ))}
      </Grid>
      {settings.side_panel && ws.side && <Pinboard ws={ws} byId={byId} dispatch={dispatch} />}
      </div>
    </div>
  );
}

// The side panel: cards sent from popups, kept with the layout (and in the URL).
function Pinboard({ ws, byId, dispatch }: { ws: Workspace; byId: Map<string, Indicator>; dispatch: (a: Action) => void }) {
  return (
    <aside className="pinboard" aria-label="Pinboard">
      <div className="pinboard-head">
        <b>Pinboard</b>
        <span className="spacer" />
        {ws.board.length > 0 && <button className="small link" onClick={() => dispatch({ type: "clearBoard" })}>Clear</button>}
        <button className="x" aria-label="Hide the pinboard" onClick={() => dispatch({ type: "side", on: false })}>×</button>
      </div>
      {ws.board.length === 0 && (
        <p className="caption">Open a country&apos;s popup and press &quot;To side panel&quot; to keep its card here. Cards are saved with the layout.</p>
      )}
      {ws.board.map((b) => {
        const ind = byId.get(b.indicator);
        if (!ind) return null;
        return (
          <PopupCard key={`${b.entity}:${b.indicator}`} variant="board" entity={b.entity} indicator={ind} year={null}
            onClose={() => dispatch({ type: "board", item: b, on: false })} />
        );
      })}
    </aside>
  );
}

function Grid({ ws, dispatch, children }: { ws: Workspace; dispatch: (a: { type: "split"; split: [number, number] }) => void; children: React.ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const layout = ws.maximised ? "1" : ws.layout;
  const [c, r] = ws.split;
  const cols = HAS_COLS.has(layout) ? `${c}fr ${1 - c}fr` : "1fr";
  const rows = HAS_ROWS.has(layout) ? `${r}fr ${1 - r}fr` : "1fr";

  // Dragging a divider moves the split; kept between 20% and 80% so no panel vanishes.
  const drag = (axis: 0 | 1) => (e: React.PointerEvent) => {
    e.preventDefault();
    const rect = box.current!.getBoundingClientRect();
    const move = (ev: PointerEvent) => {
      const f = axis === 0 ? (ev.clientX - rect.left) / rect.width : (ev.clientY - rect.top) / rect.height;
      const next: [number, number] = [...ws.split];
      next[axis] = Math.min(0.8, Math.max(0.2, Math.round(f * 100) / 100));
      dispatch({ type: "split", split: next });
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div ref={box} className="ws-grid" style={{ gridTemplateAreas: AREAS[layout], gridTemplateColumns: cols, gridTemplateRows: rows }}>
      {children}
      {HAS_COLS.has(layout) && (
        <div className="divider col" style={{ left: `calc(${c * 100}% - 6px)` }} onPointerDown={drag(0)}
          role="separator" aria-orientation="vertical" aria-label="Resize columns" />
      )}
      {HAS_ROWS.has(layout) && (
        <div className="divider row" onPointerDown={drag(1)} role="separator" aria-orientation="horizontal" aria-label="Resize rows"
          style={{ top: `calc(${r * 100}% - 6px)`, left: layout === "3" ? `calc(${c * 100}% + 6px)` : 0 }} />
      )}
    </div>
  );
}

function LayoutIcon({ layout }: { layout: Layout }) {
  const cells: Record<Layout, [number, number, number, number][]> = {
    "1": [[0, 0, 16, 12]],
    "2h": [[0, 0, 7.5, 12], [8.5, 0, 7.5, 12]],
    "2v": [[0, 0, 16, 5.5], [0, 6.5, 16, 5.5]],
    "3": [[0, 0, 7.5, 12], [8.5, 0, 7.5, 5.5], [8.5, 6.5, 7.5, 5.5]],
    "4": [[0, 0, 7.5, 5.5], [8.5, 0, 7.5, 5.5], [0, 6.5, 7.5, 5.5], [8.5, 6.5, 7.5, 5.5]],
  };
  return (
    <svg width="16" height="12" viewBox="0 0 16 12" aria-hidden="true">
      {cells[layout].map(([x, y, w, h], i) => <rect key={i} x={x} y={y} width={w} height={h} rx="1" fill="currentColor" />)}
    </svg>
  );
}

function LayoutPicker({ layout, onPick }: { layout: Layout; onPick: (l: Layout) => void }) {
  return (
    <div className="seg" role="group" aria-label="Layout">
      {LAYOUTS.map((l) => (
        <button key={l.id} className={l.id === layout ? "on" : ""} aria-pressed={l.id === layout} title={l.label} aria-label={l.label}
          onClick={() => onPick(l.id)}>
          <LayoutIcon layout={l.id} />
        </button>
      ))}
    </div>
  );
}

function SelectionBar({ ws, names, dispatch }: { ws: Workspace; names: Map<string, string>; dispatch: (a: import("@/lib/workspace").Action) => void }) {
  const full = ws.selection.length >= MAX_SELECTION;
  const compare = useMemo(() => `/compare?ids=${ws.selection.join(",")}&indicator=${ws.panels[0]?.indicator ?? "tfr"}`, [ws]);
  return (
    <div className="selection">
      {ws.selection.map((id, i) => (
        <span className="chip" key={id}>
          <span className="swatch" style={{ background: seriesVar(i) }} />
          <Link href={`/entity/${id}`}>{names.get(id) ?? id}</Link>
          <button aria-label={`Remove ${names.get(id) ?? id}`} onClick={() => dispatch({ type: "toggleSelect", entity: id })}>×</button>
        </span>
      ))}
      <div style={{ width: 220 }}>
        <Search
          placeholder={full ? `Up to ${MAX_SELECTION} selected` : "Select a country, region or bloc"}
          kinds={["entity"]}
          onPick={(h) => !ws.selection.includes(h.id) && dispatch({ type: "toggleSelect", entity: h.id })}
        />
      </div>
      {ws.selection.length > 0 && (
        <>
          <Link href={compare} className="small">Compare these</Link>
          <button className="small" onClick={() => dispatch({ type: "select", selection: [] })}>Clear</button>
        </>
      )}
    </div>
  );
}

export default function ExplorePage() {
  return (
    <Suspense fallback={<p className="muted">Loading…</p>}>
      <ExploreWorkspace />
    </Suspense>
  );
}

// Save the whole workspace under a name, and load saved ones or a starter.
// Saved layouts are kept by the API in a user folder beside the data.
function LayoutsMenu({ ws, onLoad }: { ws: Workspace; onLoad: (query: string) => void }) {
  const box = useRef<HTMLDetailsElement>(null);
  const [saved, setSaved] = useState<SavedLayout[]>([]);
  const [name, setName] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const refresh = () => api.layouts().then(setSaved).catch((e) => setMsg(String(e.message || e)));

  useEffect(() => {
    refresh();
    const close = (e: MouseEvent) => {
      if (box.current?.open && !box.current.contains(e.target as Node)) box.current.open = false;
    };
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, []);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    const n = name.trim();
    if (!n) return;
    if (saved.some((l) => l.name === n) && !window.confirm(`Replace the saved layout "${n}"?`)) return;
    try {
      await api.saveLayout(n, toQuery(ws));
      setName("");
      setMsg(`Saved "${n}".`);
      refresh();
    } catch (err) {
      setMsg(String((err as Error).message || err));
    }
  };
  const remove = async (n: string) => {
    if (!window.confirm(`Delete the saved layout "${n}"?`)) return;
    await api.deleteLayout(n).catch((err) => setMsg(String(err.message || err)));
    refresh();
  };
  const load = (query: string) => {
    onLoad(query);
    if (box.current) box.current.open = false;
  };

  return (
    <details className="links layouts" ref={box}>
      <summary>Layouts</summary>
      <div className="links-menu">
        <form onSubmit={save} className="row">
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name this layout" maxLength={60}
            aria-label="Layout name" />
          <button type="submit" disabled={!name.trim()}>Save</button>
        </form>
        {msg && <p className="caption">{msg}</p>}
        <div className="menu-head">Saved</div>
        {saved.length === 0 && <p className="caption">Nothing saved yet.</p>}
        {saved.map((l) => (
          <div className="row layout-row" key={l.name}>
            <button className="link" onClick={() => load(l.query)} title={`Saved ${l.saved_at.slice(0, 10)}`}>{l.name}</button>
            <button className="x" aria-label={`Delete ${l.name}`} onClick={() => remove(l.name)}>×</button>
          </div>
        ))}
        <div className="menu-head">Starters</div>
        {STARTERS.map((l) => (
          <button className="link" key={l.name} onClick={() => load(l.query)}>{l.name}</button>
        ))}
      </div>
    </details>
  );
}
