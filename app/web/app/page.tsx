"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import Panel, { type Value } from "@/components/Panel";
import Search from "@/components/Search";
import { makeScale, type Scale } from "@/components/WorldMap";
import { api, type Indicator, type SavedLayout } from "@/lib/api";
import { CameraBus } from "@/lib/camera";
import { DIVERGING, seriesVar } from "@/lib/colors";
import {
  LAYOUTS, MAX_PANELS, MAX_SELECTION, STARTERS, fromQuery, reducer, selectionOf, toQuery, type Group, type Layout, type Workspace,
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
    api.entities().then((list) => setNames(new Map(list.map((e) => [e.entity_id, e.short_name])))).catch(() => {});
  }, []);

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
      </div>
      {error && <p className="error">{error}</p>}
      <Grid ws={ws} dispatch={dispatch}>
        {(ws.maximised ? ws.panels.filter((p) => p.id === ws.maximised) : ws.panels).map((p, i) => (
          <Panel
            key={p.id}
            panel={p}
            indicators={indicators}
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
          />
        ))}
      </Grid>
    </div>
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
