"use client";

import * as maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import CardAsk from "@/components/CardAsk";
import WorldMap from "@/components/WorldMap";
import { openAsk } from "@/lib/ai";
import { get } from "@/lib/api";
import { countryCentres } from "@/lib/geo";

// The electricity mix on the map: zoomed out, the world's bars; further in, each continent's; then each
// country as a dot in the colour of its main source, and once zoomed in further (or for the biggest
// producers) its own bars. Each source has two bars: the latest year, and ten years before (faded).
export type Mix = { id: string; name: string; level: "world" | "continent" | "country"; year: number; twh: number;
  share: Record<string, number>; before_year: number | null; before: Record<string, number> | null; top: string };
export type MixData = { world: Mix | null; rows: Mix[]; kinds: string[]; back: number; source: string };

export const ELEC_KINDS: Record<string, { label: string; long: string; color: string }> = {
  coal: { label: "Coal", long: "Coal", color: "#262626" },
  gas: { label: "Gas", long: "Gas", color: "#7b4a2b" },
  oil: { label: "Fossil", long: "Oil and other fossil", color: "#b5482f" },
  nuclear: { label: "Nuclear", long: "Nuclear", color: "#7a3b8f" },
  hydro: { label: "Hydro", long: "Hydropower", color: "#2c4f9e" },
  wind: { label: "Wind", long: "Wind", color: "#5b9fd8" },
  solar: { label: "Solar", long: "Solar", color: "#d6a21c" },
  bio: { label: "Bio", long: "Bioenergy", color: "#4f8a35" },
  other: { label: "Other", long: "Geothermal and other", color: "#2f7d63" },
};
export const CONTINENT_AT: Record<string, [number, number]> = {
  africa: [20, 2], americas: [-88, 22], asia: [92, 38], europe: [18, 54], oceania: [140, -26],
};
const BIG_TWH = 250; // producers this big get bars as soon as countries show

function Bars({ m, scale, compact = false }: { m: Mix; scale: number; compact?: boolean }) {
  const kinds = Object.keys(ELEC_KINDS).filter((k) => (m.share[k] ?? 0) >= 0.05 || (m.before?.[k] ?? 0) >= 0.05)
    .sort((a, b) => (m.share[b] ?? 0) - (m.share[a] ?? 0));
  const bw = compact ? 9 : 14;
  return (
    <div className={`em-bars ${compact ? "compact" : ""}`}>
      <div className="em-cols">
        {kinds.map((k) => {
          const now = m.share[k] ?? 0, then = m.before?.[k] ?? null;
          const c = ELEC_KINDS[k].color;
          return (
            <div key={k} className="em-col" title={`${ELEC_KINDS[k].long}: ${now.toFixed(1)}% in ${m.year}${then !== null ? `, ${then.toFixed(1)}% in ${m.before_year}` : ""}`}>
              <div className="em-pair">
                <div className="em-bar" style={{ height: Math.max(1, now * scale), width: bw, background: c }}>{!compact || now >= 8 ? <span>{now.toFixed(1)}</span> : null}</div>
                {then !== null && <div className="em-bar then" style={{ height: Math.max(1, then * scale), width: bw, background: c }}>{!compact ? <span>{then.toFixed(1)}</span> : null}</div>}
              </div>
              <div className="em-lab">{ELEC_KINDS[k].label}</div>
            </div>
          );
        })}
      </div>
      <div className="em-name">{m.name} · {m.year}{m.before_year ? ` vs ${m.before_year}` : ""}</div>
    </div>
  );
}

export default function ElectricityMap() {
  const [d, setD] = useState<MixData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [map, setMap] = useState<maplibregl.Map | null>(null);
  const [zoom, setZoom] = useState(1);
  const [z0, setZ0] = useState<number | null>(null); // the zoom the map opened at (whole world in view)
  const [bounds, setBounds] = useState<maplibregl.LngLatBounds | null>(null);
  const [centres, setCentres] = useState<Record<string, [number, number]>>({});
  const [els, setEls] = useState<Map<string, HTMLDivElement>>(new Map());
  const markers = useRef(new Map<string, maplibregl.Marker>());

  useEffect(() => {
    get<MixData>("/energy/electricity-mix").then(setD).catch((e) => setErr(String(e.message || e)));
    countryCentres().then(setCentres).catch(() => undefined);
  }, []);
  useEffect(() => {
    if (!map) return;
    const upd = () => { setZoom(map.getZoom()); setBounds(map.getBounds()); };
    upd();
    setZ0(map.getZoom());
    map.on("zoomend", upd); map.on("moveend", upd);
    return () => { map.off("zoomend", upd); map.off("moveend", upd); };
  }, [map]);

  const rel = zoom - (z0 ?? zoom); // zoom steps in from the opening view
  const level = rel < 0.6 ? "world" : rel < 1.6 ? "continent" : "country";
  // what to draw: [key, where, item, bars?]
  const shown = useMemo(() => {
    if (!d) return [] as { key: string; at: [number, number]; m: Mix; bars: boolean }[];
    if (level === "continent") return d.rows.filter((r) => r.level === "continent" && CONTINENT_AT[r.id]).map((m) => ({ key: m.id, at: CONTINENT_AT[m.id], m, bars: true }));
    if (level === "country") {
      const placed: { x0: number; x1: number; y0: number; y1: number }[] = [];
      return d.rows.filter((r) => r.level === "country" && centres[r.id]).filter((r) => {
        if (!bounds) return true;
        const [lng, lat] = centres[r.id];
        return bounds.contains([lng, lat]) || bounds.contains([lng + 360, lat]) || bounds.contains([lng - 360, lat]);
      }).sort((a, b) => b.twh - a.twh).map((m) => {
        // bars for big producers (all when zoomed well in), unless they would cover a bigger one's bars
        let bars = rel >= 3 || m.twh >= BIG_TWH * Math.pow(3, 2.2 - rel);
        if (bars && map) {
          const pt = map.project(centres[m.id]);
          const n = Object.keys(ELEC_KINDS).filter((k) => (m.share[k] ?? 0) >= 0.05 || (m.before?.[k] ?? 0) >= 0.05).length;
          const compact = rel < 3.5, sc = rel >= 3.5 ? 2 : 1.3;
          const w = n * (compact ? 22 : 35), h = Math.max(...Object.values(m.share)) * sc + 34;
          const r = { x0: pt.x - w / 2, x1: pt.x + w / 2, y0: pt.y + 18 - h, y1: pt.y + 18 };
          if (placed.some((q) => r.x0 < q.x1 && r.x1 > q.x0 && r.y0 < q.y1 && r.y1 > q.y0)) bars = false;
          else placed.push(r);
        }
        return { key: m.id, at: centres[m.id], m, bars };
      });
    }
    return [];
  }, [d, level, centres, bounds, rel, map]);

  // one MapLibre marker per item, React drawing into it
  const shownKey = shown.map((s) => `${s.key}:${s.bars ? 1 : 0}`).join(",");
  useEffect(() => {
    if (!map) return;
    const want = new Map(shown.map((s) => [s.key, s]));
    let changed = false;
    for (const [k, mk] of markers.current) if (!want.has(k) || (mk.getElement().dataset.bars === "1") !== want.get(k)!.bars) { mk.remove(); markers.current.delete(k); changed = true; }
    for (const s of shown) {
      if (markers.current.has(s.key)) continue;
      const el = document.createElement("div");
      el.className = "em-marker";
      el.dataset.bars = s.bars ? "1" : "0";
      markers.current.set(s.key, new maplibregl.Marker({ element: el, anchor: s.bars ? "bottom" : "left", offset: s.bars ? [0, 18] : [-6, 0] }).setLngLat(s.at).addTo(map));
      changed = true;
    }
    if (changed) setEls(new Map([...markers.current].map(([k, mk]) => [k, mk.getElement() as HTMLDivElement])));
  }, [map, shownKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { for (const mk of markers.current.values()) mk.remove(); markers.current.clear(); }, []);

  const ask = () => d && openAsk({ title: "The world's electricity mix", parts: [{
    key: "mix", kind: "data" as const, label: `Share of electricity generation by source (%), latest year and ${d.back} years before`,
    text: ["Place\tYear\tTWh\t" + Object.keys(ELEC_KINDS).map((k) => ELEC_KINDS[k].long).join("\t"),
      ...[d.world, ...d.rows].filter((m): m is Mix => !!m).map((m) => `${m.name}\t${m.year}\t${m.twh}\t${Object.keys(ELEC_KINDS).map((k) => `${m.share[k]}${m.before ? ` (${m.before[k]})` : ""}`).join("\t")}`)].join("\n"),
  }] });

  return (
    <section className="card" id="electricity-map">
      <div className="card-head">
        <h3>The world&apos;s electricity mix</h3>
        <span className="card-actions"><span className="small muted">Zoom in for continents, then countries</span><CardAsk onAsk={ask} /></span>
      </div>
      {err && <p className="error">{err}</p>}
      {d && !d.world && !d.rows.length && <p className="muted small">No electricity figures yet: <code>.\refresh.bat</code> loads them (Our World in Data energy).</p>}
      <div className="em-map">
        <WorldMap fill values={[]} unit="" decimals={0} diverging={false} onPick={() => undefined} onMap={setMap} />
        {level === "world" && d?.world && <div className="em-world"><Bars m={d.world} scale={7} /></div>}
        <div className="em-legend">
          <i>{d?.world?.before_year ? `Change over ${d.back} years:` : "Electricity mix"}</i> <span className="em-key now" /> latest year <span className="em-key then" /> {d?.back ?? 10} years earlier
          <div className="em-legend-kinds">{Object.entries(ELEC_KINDS).map(([k, v]) => <span key={k}><span className="swatch" style={{ background: v.color }} /> {v.long}</span>)}</div>
        </div>
      </div>
      {shown.map((s) => {
        const el = els.get(s.key);
        if (!el) return null;
        return createPortal(s.bars
          ? <Bars m={s.m} scale={s.m.level === "continent" ? 2.4 : rel >= 3.5 ? 2 : 1.3} compact={s.m.level === "country" && rel < 3.5} />
          : <div className="em-dot" title={`${s.m.name}: mostly ${ELEC_KINDS[s.m.top].long.toLowerCase()} (${s.m.share[s.m.top].toFixed(0)}%), ${s.m.year}`}>
              <span style={{ background: ELEC_KINDS[s.m.top].color }} />{rel >= 2.2 ? ELEC_KINDS[s.m.top].label : null}</div>, el, s.key);
      })}
      <p className="caption">
        Share of electricity generated by each source, in each place&apos;s latest year with figures, with the same {d?.back ?? 10} years before
        (faded). Continents add up their countries. A dot shows a country&apos;s main source; zoom in for its bars. Data: {d?.source ?? "Our World in Data"}.
      </p>
    </section>
  );
}
