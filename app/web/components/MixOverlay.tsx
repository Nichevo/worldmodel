"use client";

import Link from "next/link";
import * as maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CONTINENT_AT, ELEC_KINDS, type Mix, type MixData } from "@/components/ElectricityMap";
import type { Scale } from "@/components/WorldMap";
import { get } from "@/lib/api";
import { countryCentres } from "@/lib/geo";

// The electricity mix as a map layer: a pie for each place, sized by how much electricity it makes.
// Zoomed out: one pie per continent; zoomed in: one per country. Or a dot in the colour of each
// country's main source, or the countries shaded by the share of one source (click it in the key).

export type MixMode = "pies" | "dots" | "share";
export type MixShade = { values: { entity_id: string; value: number; status: string }[]; scale: Scale; label: string } | null;

const LOW = ["nuclear", "hydro", "wind", "solar", "bio", "other"];
const SHADE_COLORS = ["#d9f0d3", "#a8ddb5", "#7bccc4", "#43a2ca", "#0868ac"];
export const SHADE_SCALE: Scale = { breaks: [20, 40, 60, 80], colors: SHADE_COLORS };
const HOME = "NZL";

const lowCarbon = (m: Mix) => LOW.reduce((t, k) => t + (m.share[k] ?? 0), 0);
const shareOf = (m: Mix, kind: string) => (kind === "low" ? lowCarbon(m) : m.share[kind] ?? 0);
const kindName = (kind: string) => (kind === "low" ? "Low-carbon (all but coal, gas and oil)" : ELEC_KINDS[kind]?.long ?? kind);

// SVG arcs, clockwise from 12 o'clock.
function Pie({ m, r }: { m: Mix; r: number }) {
  const parts = Object.keys(ELEC_KINDS).map((k) => [k, m.share[k] ?? 0] as const).filter(([, v]) => v > 0.2);
  const total = parts.reduce((t, [, v]) => t + v, 0) || 1;
  let a = -Math.PI / 2;
  const d = 2 * r + 4;
  return (
    <svg width={d} height={d} viewBox={`${-r - 2} ${-r - 2} ${d} ${d}`} aria-hidden="true">
      <circle r={r + 1} fill="#fff" />
      {parts.length === 1 ? <circle r={r} fill={ELEC_KINDS[parts[0][0]].color} /> : parts.map(([k, v]) => {
        const b = a + (v / total) * 2 * Math.PI;
        const big = b - a > Math.PI ? 1 : 0;
        const p = `M0 0 L${(r * Math.cos(a)).toFixed(2)} ${(r * Math.sin(a)).toFixed(2)} A${r} ${r} 0 ${big} 1 ${(r * Math.cos(b)).toFixed(2)} ${(r * Math.sin(b)).toFixed(2)} Z`;
        a = b;
        return <path key={k} d={p} fill={ELEC_KINDS[k].color} stroke="#fff" strokeWidth={r > 14 ? 0.8 : 0.4} />;
      })}
    </svg>
  );
}

export default function MixOverlay({ map, onShade }: { map: maplibregl.Map | null; onShade: (s: MixShade) => void }) {
  const [d, setD] = useState<MixData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<MixMode>("pies");
  const [kind, setKind] = useState("low");
  const [bySize, setBySize] = useState(true);
  const [open, setOpen] = useState(true);
  const [hover, setHover] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [z0, setZ0] = useState<number | null>(null);
  const [bounds, setBounds] = useState<maplibregl.LngLatBounds | null>(null);
  const [centres, setCentres] = useState<Record<string, [number, number]>>({});
  const [els, setEls] = useState<Map<string, HTMLDivElement>>(new Map());
  const markers = useRef(new Map<string, maplibregl.Marker>());
  const [box, setBox] = useState<HTMLElement | null>(null);

  useEffect(() => {
    get<MixData>("/energy/electricity-mix").then(setD).catch((e) => setErr(String(e.message || e)));
    countryCentres().then(setCentres).catch(() => undefined);
  }, []);
  useEffect(() => {
    if (!map) return;
    setBox(map.getContainer());
    const upd = () => { setZoom(map.getZoom()); setBounds(map.getBounds()); };
    upd();
    setZ0(Math.min(map.getZoom(), 2));
    map.on("zoomend", upd); map.on("moveend", upd);
    return () => { map.off("zoomend", upd); map.off("moveend", upd); };
  }, [map]);

  const countries = useMemo(() => (d?.rows ?? []).filter((r) => r.level === "country"), [d]);
  const byId = useMemo(() => new Map([...(d?.rows ?? []), ...(d?.world ? [d.world] : [])].map((m) => [m.id, m])), [d]);
  // low-carbon rank among countries, for the hover card
  const lowRank = useMemo(() => new Map([...countries].sort((a, b) => lowCarbon(b) - lowCarbon(a)).map((m, i) => [m.id, i + 1])), [countries]);

  // the shaded map for "one source"
  useEffect(() => {
    if (mode !== "share" || !countries.length) { onShade(null); return; }
    onShade({ values: countries.map((m) => ({ entity_id: m.id, value: Math.round(shareOf(m, kind) * 10) / 10, status: "E" })), scale: SHADE_SCALE,
      label: `${kindName(kind)}, % of electricity` });
  }, [mode, kind, countries, onShade]);
  useEffect(() => () => onShade(null), [onShade]);

  const level = zoom < (z0 ?? 1.5) + 1.1 ? "continent" : "country";
  const shown = useMemo(() => {
    if (!d || mode === "share") return [] as { key: string; at: [number, number]; m: Mix; r: number }[];
    if (mode === "pies" && level === "continent") {
      return d.rows.filter((r) => r.level === "continent" && CONTINENT_AT[r.id])
        .map((m) => ({ key: m.id, at: CONTINENT_AT[m.id], m, r: bySize ? Math.min(46, 12 + Math.sqrt(m.twh) / 4) : 22 }));
    }
    const grow = Math.max(1, 1 + (zoom - (z0 ?? 1.5) - 1.1) * 0.35);
    return countries.filter((r) => centres[r.id]).filter((r) => {
      if (!bounds) return true;
      const [lng, lat] = centres[r.id];
      return bounds.contains([lng, lat]) || bounds.contains([lng + 360, lat]) || bounds.contains([lng - 360, lat]);
    }).map((m) => ({ key: m.id, at: centres[m.id], m,
      r: mode === "dots" ? 5 : Math.min(60, (bySize ? 3 + Math.sqrt(m.twh) / 3.2 : 9) * grow) }));
  }, [d, mode, level, countries, centres, bounds, bySize, zoom, z0]);

  // one MapLibre marker per pie, React drawing into it; smaller pies sit on top of bigger ones
  const shownKey = shown.map((s) => s.key).join(",");
  useEffect(() => {
    if (!map) return;
    const want = new Set(shown.map((s) => s.key));
    let changed = false;
    for (const [k, mk] of markers.current) if (!want.has(k)) { mk.remove(); markers.current.delete(k); changed = true; }
    for (const s of shown) {
      if (markers.current.has(s.key)) continue;
      const el = document.createElement("div");
      el.className = "mix-marker";
      el.style.zIndex = String(Math.max(1, 400 - Math.round(Math.sqrt(s.m.twh))));
      markers.current.set(s.key, new maplibregl.Marker({ element: el, anchor: "center" }).setLngLat(s.at).addTo(map));
      changed = true;
    }
    if (changed) setEls(new Map([...markers.current].map(([k, mk]) => [k, mk.getElement() as HTMLDivElement])));
  }, [map, shownKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { for (const mk of markers.current.values()) mk.remove(); markers.current.clear(); }, []);

  const card = byId.get(pinned ?? hover ?? "");
  const world = d?.world;
  const home = byId.get(HOME);
  const twh = (v: number) => (v >= 100 ? Math.round(v) : v).toLocaleString();
  const pct = (v: number) => `${v < 10 ? v.toFixed(1) : v.toFixed(0)}%`;
  const at = (v: number) => `${Math.max(0, Math.min(100, v))}%`;

  const key = box ? createPortal(
    <div className={`mix-key${open ? "" : " shut"}`} onMouseDown={(e) => e.stopPropagation()} onWheel={(e) => e.stopPropagation()}>
      <div className="mix-key-head">
        <b>Electricity mix</b>
        <button className="small" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "Hide key" : "Key"}</button>
      </div>
      {open && <>
        <div className="seg small" role="group" aria-label="Show the electricity mix as">
          {([["pies", "Pies"], ["dots", "Dots"], ["share", "Shade"]] as [MixMode, string][]).map(([m, l]) =>
            <button key={m} className={mode === m ? "on" : ""} aria-pressed={mode === m} onClick={() => setMode(m)}>{l}</button>)}
        </div>
        {err && <p className="error small">{err}</p>}
        {d && !d.rows.length && <p className="small muted">No electricity figures yet: a refresh loads them (Our World in Data energy).</p>}
        <p className="caption">{mode === "share" ? "Countries shaded by the share of the source picked below. Click another to switch."
          : mode === "dots" ? "A dot in the colour of each country's main source. Click a source to shade the map by it."
          : `Each pie is a place's electricity by source${level === "continent" ? ": continents now, zoom in for countries" : ""}. Click a source to shade the map by it.`}</p>
        <div className="mix-kinds">
          {[...Object.keys(ELEC_KINDS), "low"].map((k) => (
            <button key={k} className={`mix-kind${mode === "share" && kind === k ? " on" : ""}`} onClick={() => { setKind(k); setMode("share"); }}
              title={`Shade the map by ${kindName(k).toLowerCase()}`}>
              <span className="mix-sw" style={{ background: k === "low" ? "linear-gradient(90deg, #2c4f9e, #5b9fd8, #d6a21c)" : ELEC_KINDS[k].color }} />
              <span>{k === "low" ? "Low-carbon, all" : ELEC_KINDS[k].long}</span>
              <span className="mono small muted">{world ? pct(shareOf(world, k)) : ""}</span>
            </button>
          ))}
        </div>
        <p className="caption">Right: the world&apos;s share{world ? `, ${world.year}` : ""}.{mode === "pies" ? " Pie size: total electricity (bigger = more TWh)." : ""}</p>
        {mode === "pies" && <label className="small"><input type="checkbox" checked={bySize} onChange={(e) => setBySize(e.target.checked)} /> Size pies by total electricity</label>}
        {mode === "share" && (
          <div className="mix-steps">
            <b className="small">{kindName(kind)}, % of electricity</b>
            <div className="mix-ramp">{SHADE_COLORS.map((c) => <span key={c} style={{ background: c }} />)}
              {home && <i className="mix-mark home" style={{ left: at(shareOf(home, kind)) }} title={`${home.name} ${pct(shareOf(home, kind))}`} />}
              {world && <i className="mix-mark world" style={{ left: at(shareOf(world, kind)) }} title={`World ${pct(shareOf(world, kind))}`} />}
            </div>
            <div className="mix-edges mono">{[0, 20, 40, 60, 80, 100].map((v) => <span key={v} style={{ left: `${v}%` }}>{v}</span>)}</div>
            <span className="small">{home ? <><i className="mix-tri home" /> {home.name} {pct(shareOf(home, kind))}</> : null}
              {world ? <> · <i className="mix-tri world" /> World {pct(shareOf(world, kind))}</> : null}</span>
          </div>
        )}
      </>}
    </div>, box) : null;

  const hoverCard = box && card ? createPortal(
    <div className="mix-card" onMouseDown={(e) => e.stopPropagation()}>
      <div className="mix-key-head"><b>{card.name}, {card.year}</b>{pinned && <button className="small" onClick={() => setPinned(null)} aria-label="Close">×</button>}</div>
      <span className="small">{Object.keys(ELEC_KINDS).filter((k) => (card.share[k] ?? 0) >= 0.5).sort((a, b) => card.share[b] - card.share[a])
        .map((k) => `${ELEC_KINDS[k].label} ${pct(card.share[k])}`).join(" · ")}</span>
      <span className="small muted">Low-carbon {pct(lowCarbon(card))}{card.level === "country" && lowRank.get(card.id) ? `, ${ordinal(lowRank.get(card.id)!)} of ${countries.length}` : ""} · {twh(card.twh)} TWh
        {card.before && card.before_year ? ` · ${pct(lowCarbon({ ...card, share: card.before }))} in ${card.before_year}` : ""}</span>
      {card.level === "country" && <Link className="small" href={`/entity/${card.id}#energy`}>Open {card.name}&apos;s energy card</Link>}
    </div>, box) : null;

  return (
    <>
      {key}
      {hoverCard}
      {shown.map((s) => {
        const el = els.get(s.key);
        if (!el) return null;
        const label = `${s.m.name}: ${ELEC_KINDS[s.m.top]?.long ?? s.m.top} ${pct(s.m.share[s.m.top] ?? 0)}, ${twh(s.m.twh)} TWh (${s.m.year})`;
        return createPortal(
          <button className={`mix-pie${mode === "dots" ? " dot" : ""}`} aria-label={label}
            onMouseEnter={() => setHover(s.key)} onMouseLeave={() => setHover((h) => (h === s.key ? null : h))}
            onClick={(e) => { e.stopPropagation(); setPinned(pinned === s.key ? null : s.key); }}>
            {mode === "dots" ? <span style={{ background: ELEC_KINDS[s.m.top]?.color, width: 2 * s.r, height: 2 * s.r }} /> : <Pie m={s.m} r={s.r} />}
            {mode === "pies" && s.m.level === "continent" ? <em>{s.m.name}</em> : null}
          </button>, el, s.key);
      })}
    </>
  );
}

function ordinal(n: number) {
  const s = n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] ?? "th";
  return `${n}${s}`;
}
