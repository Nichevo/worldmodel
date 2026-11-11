"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import CardAsk from "@/components/CardAsk";
import WorldMap, { type MapPoint } from "@/components/WorldMap";
import { openAsk } from "@/lib/ai";
import { get } from "@/lib/api";
import { people } from "@/lib/cities";
import { cssVar } from "@/lib/colors";
import { clusterRadius, packCluster, placeClusters, type Circ } from "@/lib/pack";

// The world's largest cities, sized by people in the chosen year and coloured by how much they grew
// since the start year: as clusters by continent, or on the map. Years run on to the projections.
type City = { city_id: string; name: string; country_id: string; country: string | null; lat: number | null; lon: number | null;
  continent: string | null; pts: [number, number, boolean][] };
type Largest = { rows: City[]; measure: string | null; source?: string; years?: number[]; first_projection?: number | null; note: string | null;
  measures?: Record<string, number> };

const W = 1000, H = 640;
const ANCHOR: Record<string, [number, number]> = { Americas: [210, 360], Europe: [540, 150], Africa: [560, 440], Asia: [810, 330], Oceania: [930, 590] };
export const GROWTH = [
  { key: "smaller", label: "smaller", color: "#3b5ba5", test: (g: number) => g < 1 },
  { key: "x2", label: "up to ×2", color: "#e3b5ae", test: (g: number) => g < 2 },
  { key: "x4", label: "×2 to ×4", color: "#c0675b", test: (g: number) => g < 4 },
  { key: "more", label: "more than ×4", color: "#8e2a1c", test: () => true },
];
const NEW = "#a9a9a9";

export function valueAt(pts: [number, number, boolean][], y: number): number | null {
  if (!pts.length || y < pts[0][0] || y > pts[pts.length - 1][0]) return null;
  for (let i = 0; i < pts.length; i++) {
    if (pts[i][0] === y) return pts[i][1];
    if (pts[i][0] > y) {
      const [y0, v0] = pts[i - 1], [y1, v1] = pts[i];
      return v0 + ((v1 - v0) * (y - y0)) / (y1 - y0);
    }
  }
  return null;
}
const colourOf = (g: number | null) => (g === null ? NEW : GROWTH.find((c) => c.test(g))!.color);
const times = (g: number | null) => (g === null ? "new" : g >= 10 ? `×${Math.round(g)}` : `×${g.toFixed(1)}`);

export default function LargestCities() {
  const router = useRouter();
  const [d, setD] = useState<Largest | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [view, setView] = useState<"clusters" | "map">("clusters");
  const [count, setCount] = useState(500);
  const [from, setFrom] = useState(1975);
  const [to, setTo] = useState(2025);
  const [playing, setPlaying] = useState(false);
  const [tip, setTip] = useState<{ c: City; x: number; y: number; w: number } | null>(null);
  const prev = useRef(new Map<string, { x: number; y: number }>());

  useEffect(() => {
    let on = true;
    get<Largest>("/cities/largest", { limit: 1500, year: 2025 }).then((x) => {
      if (!on) return;
      setD(x);
      const ys = x.years ?? [];
      if (ys.length) {
        setFrom((f) => (ys.includes(f) ? f : ys[0]));
        const now = new Date().getFullYear();
        setTo((t) => (ys.includes(t) ? t : ys.filter((y) => y <= now).pop() ?? ys[ys.length - 1]));
      }
    }).catch((e) => on && setErr(String(e.message || e)));
    return () => { on = false; };
  }, []);
  const years = d?.years ?? [];
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => setTo((y) => {
      const i = years.indexOf(y);
      if (i < 0 || i >= years.length - 1) { setPlaying(false); return y; }
      return years[i + 1];
    }), 900);
    return () => clearInterval(t);
  }, [playing, years]);

  // the chosen year's largest, each with its size then and its growth since the start year
  const cities = useMemo(() => (d?.rows ?? []).map((c) => {
    const now = valueAt(c.pts, to), then = valueAt(c.pts, from);
    return { c, now, then, g: now !== null && then ? now / then : null };
  }).filter((x): x is { c: City; now: number; then: number | null; g: number | null } => x.now !== null && x.now > 0)
    .sort((a, b) => b.now - a.now).slice(0, count), [d, from, to, count]);
  // one scale for every year (the biggest any city gets), so growth shows as growing circles
  const top = useMemo(() => Math.max(1, ...(d?.rows ?? []).flatMap((c) => c.pts.map((p) => p[1]))), [d]);
  const totalMax = useMemo(() => Math.max(1, ...years.map((y) => (d?.rows ?? []).map((c) => valueAt(c.pts, y) ?? 0).sort((a, b) => b - a).slice(0, count).reduce((s, v) => s + v, 0))), [d, years, count]);

  const layout = useMemo(() => {
    if (view !== "clusters" || !cities.length) return null;
    const k = Math.sqrt((W * H * 0.3) / (Math.PI * totalMax)); // the busiest year fills about 30% of the picture
    const groups = new Map<string, { id: string; r: number }[]>();
    for (const x of cities) {
      const g = x.c.continent ?? "Other";
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g)!.push({ id: x.c.city_id, r: Math.max(1.2, k * Math.sqrt(x.now)) });
    }
    const packed = new Map<string, Circ[]>();
    for (const [g, items] of groups) {
      const old = new Map<string, { x: number; y: number }>();
      for (const it of items) { const p = prev.current.get(`${g}:${it.id}`); if (p) old.set(it.id, p); }
      packed.set(g, packCluster(items, old.size > items.length / 2 ? old : undefined));
    }
    const at = placeClusters([...packed].map(([g, cs]) => ({ key: g, r: clusterRadius(cs), ax: (ANCHOR[g] ?? [W / 2, H - 40])[0], ay: (ANCHOR[g] ?? [W / 2, H - 40])[1] })), 50);
    const out: (Circ & { g: string })[] = [];
    for (const [g, cs] of packed) for (const c of cs) {
      prev.current.set(`${g}:${c.id}`, { x: c.x, y: c.y });
      out.push({ ...c, x: c.x + at[g].x, y: c.y + at[g].y, g });
    }
    const labels = [...packed].map(([g, cs]) => ({ g, x: at[g].x, y: at[g].y, r: clusterRadius(cs) }));
    const xs = out.flatMap((c) => [c.x - c.r, c.x + c.r]), ys = [...out.flatMap((c) => [c.y - c.r, c.y + c.r]), ...labels.map((l) => l.y - l.r - 40)];
    const pad = 20;
    const box = [Math.min(...xs) - pad, Math.min(...ys) - pad, Math.max(...xs) - Math.min(...xs) + 2 * pad, Math.max(...ys) - Math.min(...ys) + 2 * pad];
    return { circles: out, labels, box };
  }, [cities, view, totalMax]);

  const byId = useMemo(() => new Map(cities.map((x) => [x.c.city_id, x])), [cities]);
  const points: MapPoint[] = useMemo(() => cities.filter((x) => x.c.lat !== null && x.c.lon !== null).map((x) => ({
    id: x.c.city_id, name: x.c.name, lng: x.c.lon as number, lat: x.c.lat as number, size: x.now, color: colourOf(x.g),
    text: `${people(x.now)} in ${to}${x.then ? `, ${people(x.then)} in ${from} (${times(x.g)})` : `, none counted in ${from}`}`,
  })), [cities, from, to]);

  if (err) return <p className="error">{err}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  if (d.note || !d.rows.length) return <div className="card"><h3>Largest cities</h3><p className="muted small">{d.note ?? "No city sizes through the years yet."}</p></div>;

  const proj = d.first_projection ?? null;
  const isProj = (y: number) => proj !== null && y >= proj;
  const ask = () => openAsk({ title: `Largest cities ${from} to ${to}`, parts: [{
    key: "cities", kind: "data" as const, label: `The ${cities.length} largest cities in ${to}, with ${from} (${d.source})`,
    text: ["City\tCountry\tContinent\t" + `${to}\t${from}\tGrowth`, ...cities.slice(0, 300).map((x) => `${x.c.name}\t${x.c.country ?? x.c.country_id}\t${x.c.continent ?? ""}\t${Math.round(x.now)}\t${x.then ? Math.round(x.then) : ""}\t${times(x.g)}`)].join("\n"),
  }] });
  const counts = GROWTH.map((gr) => cities.filter((x) => x.g !== null && colourOf(x.g) === gr.color).length);
  const spark = (c: City) => {
    const ys = c.pts.map((p) => p[0]), vs = c.pts.map((p) => p[1]);
    const x0 = Math.min(...ys), x1 = Math.max(...ys), v1 = Math.max(...vs);
    const sx = (y: number) => ((y - x0) / Math.max(1, x1 - x0)) * 180, sy = (v: number) => 46 - (v / v1) * 42;
    const est = c.pts.filter((p) => !p[2]), pr = c.pts.filter((p, i) => p[2] || (c.pts[i + 1]?.[2] ?? false));
    const line = (ps: [number, number, boolean][]) => ps.map((p, i) => `${i ? "L" : "M"}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join("");
    return (
      <svg width={180} height={50} aria-hidden>
        {est.length > 1 && <path d={`${line(est)}L${sx(est[est.length - 1][0])},48L${sx(est[0][0])},48Z`} fill={cssVar("--muted")} opacity={0.25} />}
        <path d={line(est)} fill="none" stroke={cssVar("--ink-2")} strokeWidth={1.5} />
        {pr.length > 1 && <path d={line(pr)} fill="none" stroke={cssVar("--ink-2")} strokeWidth={1.2} strokeDasharray="3 3" />}
        <line x1={sx(to)} x2={sx(to)} y1={0} y2={50} stroke="#b5891b" />
      </svg>
    );
  };

  return (
    <div className="card" id="largest-cities">
      <div className="card-head">
        <h3>Largest cities, {from === to ? to : `${from} to ${to}`}</h3>
        <span className="card-actions">
          <span className="seg small" role="group" aria-label="View">
            {(["clusters", "map"] as const).map((v) => <button key={v} className={view === v ? "on" : ""} aria-pressed={view === v} onClick={() => setView(v)}>{v === "clusters" ? "Clusters" : "Map"}</button>)}
          </span>
          <select className="small" value={count} onChange={(e) => setCount(Number(e.target.value))} aria-label="How many cities">
            {[100, 250, 500, 1000].map((n) => <option key={n} value={n}>Top {n}</option>)}
          </select>
          <CardAsk onAsk={ask} />
        </span>
      </div>
      <div className="chips-row small" style={{ gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        {GROWTH.map((g, i) => <span key={g.key}><span className="swatch round" style={{ background: g.color }} /> {g.label} ({counts[i]})</span>)}
        <span><span className="swatch round" style={{ background: NEW }} /> not counted in {from}</span>
      </div>
      <div style={{ position: "relative" }} onMouseLeave={() => setTip(null)}>
        {view === "clusters" && layout && (
          <svg viewBox={layout.box.join(" ")} width="100%" style={{ maxHeight: 720, display: "block" }} role="img" aria-label={`The ${cities.length} largest cities in ${to} by continent`}>
            {layout.labels.map((l) => <text key={l.g} x={l.x} y={l.y - l.r - 10} textAnchor="middle" fontSize={26}
              fontFamily="Georgia, serif" fill={cssVar("--muted")}>{l.g}</text>)}
            {layout.circles.map((c) => {
              const x = byId.get(c.id)!;
              return (
                <g key={c.id} className="lc-city" style={{ transform: `translate(${c.x}px, ${c.y}px)` }}
                  onMouseMove={(e) => { const box = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect(); setTip({ c: x.c, x: e.clientX - box.left, y: e.clientY - box.top, w: box.width }); }}
                  onClick={() => router.push(`/city/${c.id}`)}>
                  <circle r={c.r} fill={colourOf(x.g)} stroke="#fff" strokeOpacity={0.8} strokeWidth={Math.min(1, c.r / 4)} />
                  {c.r > 19 && <text textAnchor="middle" y={c.r > 26 ? -2 : 3} fontSize={Math.min(15, c.r / 3.2)} fontWeight={600} fill={x.g !== null && x.g >= 2 ? "#fff" : "#2b2b2b"} pointerEvents="none">{x.c.name.length > 14 ? `${x.c.name.slice(0, 12)}…` : x.c.name}</text>}
                  {c.r > 26 && <text textAnchor="middle" y={Math.min(15, c.r / 3.2) + 1} fontSize={Math.min(12, c.r / 4)} fill={x.g !== null && x.g >= 2 ? "#fff" : "#2b2b2b"} fontFamily="ui-monospace, monospace" pointerEvents="none">{from === to ? people(x.now) : times(x.g)}</text>}
                </g>
              );
            })}
          </svg>
        )}
        {view === "map" && (
          <div className="city-map" style={{ height: 560 }}>
            <WorldMap fill values={[]} unit="" decimals={0} diverging={false} points={points} pointsTop={top} onPick={() => undefined} />
          </div>
        )}
        {tip && view === "clusters" && (() => {
          const x = byId.get(tip.c.city_id);
          return (
            <div className="lc-tip" style={{ left: tip.x > tip.w - 240 ? tip.x - 224 : tip.x + 14, top: tip.y + 14 }}>
              <b>{tip.c.name}</b> <span className="muted">{tip.c.country ?? tip.c.country_id}</span>
              <div className="mono">{people(x?.now)} in {to}{isProj(to) ? " (projection)" : ""}</div>
              {x?.then ? <div className="small muted">{people(x.then)} in {from}: {times(x.g)}</div> : <div className="small muted">not counted in {from}</div>}
              {spark(tip.c)}
            </div>
          );
        })()}
      </div>
      <div className="chips-row small lc-years">
        <label>From <select value={from} onChange={(e) => setFrom(Number(e.target.value))}>{years.filter((y) => y <= to).map((y) => <option key={y} value={y}>{y}</option>)}</select></label>
        <button className="link" onClick={() => { if (!playing && to === years[years.length - 1]) setTo(years[Math.min(years.length - 1, years.indexOf(from) + 1)]); setPlaying(!playing); }}>{playing ? "Pause" : "Play"}</button>
        <input type="range" min={0} max={years.length - 1} step={1} value={Math.max(0, years.indexOf(to))} aria-label="Year"
          onChange={(e) => { setPlaying(false); const y = years[Number(e.target.value)]; setTo(y); if (from > y) setFrom(y); }} />
        <b>{to}</b> <span className="muted">{isProj(to) ? "UN projection" : "estimate"}</span>
      </div>
      <p className="caption">
        Circles sized by people in {to}, on one scale for every year, so cities grow as the years move on; colour is the growth since {from}.
        {proj ? ` From ${proj} on the figures are projections.` : ""} Click a city for its page. Data: {d.source}
        {d.measure === "ghsl_population" ? " (cities as the built-up area seen from space, the way the UN's 2025 edition counts them)" : ""}.
        {" "}{d.measures && Object.keys(d.measures).length > 1 ? <>Both city counts are loaded; the UN&apos;s is used.</> : <>The UN&apos;s World Urbanization Prospects file can be saved by hand in <code>var\manual\un_wup</code>; see <Link href="/sources">Sources</Link>.</>}
      </p>
    </div>
  );
}
