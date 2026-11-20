"use client";

import { useMemo, useRef, useState } from "react";
import AskButton from "@/components/AskButton";
import { FACTS } from "@/lib/space";
import { HOSTS, layout, moonList, type Host, type Moon } from "@/lib/moons";

// Every planet (and the dwarf planets with moons) with its moons packed around it, set around the
// Sun, so the counts read at a glance: Saturn and Jupiter swamp the rest. Click any circle for its
// card; scroll to zoom, drag to move.

type Pick = { kind: "host"; host: Host } | { kind: "moon"; moon: Moon; host: Host };
const MOON_KM = 1737.4;

export default function MoonsView({ jpl, fetched }: { jpl: [string, string, number | null][] | null; fetched?: string }) {
  const [scale, setScale] = useState<"readable" | "true">("readable");
  const [unnamed, setUnnamed] = useState(true);
  const [pick, setPick] = useState<Pick | null>({ kind: "host", host: HOSTS.find((h) => h.id === "saturn")! });
  const { moons, from } = useMemo(() => moonList(jpl), [jpl]);
  const { clusters, sun, rings } = useMemo(() => layout(moons, scale, unnamed), [moons, scale, unnamed]);

  // Whole picture in view to start with; zoom and pan move this box.
  const full = useMemo(() => {
    const ext = Math.max(...clusters.map((c) => Math.max(Math.abs(c.x), Math.abs(c.y)) + c.enclose)) + 12;
    return { x: -ext, y: -ext, w: 2 * ext, h: 2 * ext };
  }, [clusters]);
  const [box, setBox] = useState<typeof full | null>(null);
  const vb = box ?? full;
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<{ x: number; y: number; vb: typeof full; moved: boolean } | null>(null);

  const toUnits = (e: { clientX: number; clientY: number }) => {
    const r = svg.current!.getBoundingClientRect(), k = Math.max(vb.w / r.width, vb.h / r.height);
    return { k, x: vb.x + (e.clientX - r.left - (r.width - vb.w / k) / 2) * k, y: vb.y + (e.clientY - r.top - (r.height - vb.h / k) / 2) * k };
  };
  const wheel = (e: React.WheelEvent) => {
    const p = toUnits(e), f = e.deltaY > 0 ? 1.2 : 1 / 1.2;
    const w = Math.min(full.w * 1.2, Math.max(full.w / 25, vb.w * f));
    const z = w / vb.w;
    setBox({ x: p.x - (p.x - vb.x) * z, y: p.y - (p.y - vb.y) * z, w, h: vb.h * z });
  };

  const counts = useMemo(() => HOSTS.map((h) => {
    const mine = moons.filter((m) => m.host === h.id);
    return { host: h, total: mine.length, named: mine.filter((m) => m.named).length };
  }).sort((a, b) => b.total - a.total), [moons]);
  const most = Math.max(1, ...counts.map((c) => c.total));
  const totalMoons = counts.reduce((s, c) => s + c.total, 0);

  const fact = pick ? FACTS.find((f) => f.name === (pick.kind === "host" ? pick.host.name : pick.moon.name)) : undefined;

  return (
    <div className="chips-row" style={{ gap: 14, alignItems: "flex-start", flexWrap: "wrap" }}>
      <div className="card" style={{ flex: "3 1 560px", padding: 6 }}>
        <div className="chips-row small" style={{ gap: 12, flexWrap: "wrap", alignItems: "center", margin: "2px 4px 6px" }}>
          <b>Planets with their moons</b>
          <div className="seg" role="group" aria-label="Sizes">
            <button className={scale === "readable" ? "on" : ""} aria-pressed={scale === "readable"} onClick={() => { setScale("readable"); setBox(null); }}>Easy to read</button>
            <button className={scale === "true" ? "on" : ""} aria-pressed={scale === "true"} onClick={() => { setScale("true"); setBox(null); }}>True sizes</button>
          </div>
          <label><input type="checkbox" checked={unnamed} onChange={(e) => { setUnnamed(e.target.checked); setBox(null); }} /> Moons not named yet</label>
          {box && <button className="link" onClick={() => setBox(null)}>Show all</button>}
        </div>
        <svg ref={svg} viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`} role="img" aria-label="Planets with their moons packed around them"
          style={{ width: "100%", height: 680, display: "block", background: "#0b1020", borderRadius: 6, cursor: drag.current ? "grabbing" : "grab", touchAction: "none" }}
          onWheel={wheel}
          onPointerDown={(e) => { drag.current = { x: e.clientX, y: e.clientY, vb, moved: false }; }}
          onPointerMove={(e) => {
            const d = drag.current;
            if (!d || !svg.current) return;
            const r = svg.current.getBoundingClientRect(), k = Math.max(d.vb.w / r.width, d.vb.h / r.height);
            const dx = (e.clientX - d.x) * k, dy = (e.clientY - d.y) * k;
            if (Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) > 3) d.moved = true;
            if (d.moved) setBox({ ...d.vb, x: d.vb.x - dx, y: d.vb.y - dy });
          }}
          onPointerUp={() => { setTimeout(() => { drag.current = null; }, 0); }}
          onPointerLeave={() => { drag.current = null; }}>
          <defs>
            <radialGradient id="moons-sun"><stop offset="0%" stopColor="#fff6c8" /><stop offset="55%" stopColor="#ffc844" /><stop offset="100%" stopColor="#f07a1a" /></radialGradient>
            <radialGradient id="moons-glow"><stop offset="60%" stopColor="#ffb02e" stopOpacity="0.35" /><stop offset="100%" stopColor="#ffb02e" stopOpacity="0" /></radialGradient>
          </defs>
          {rings.map((r, i) => <circle key={i} cx={0} cy={0} r={r} fill="none" stroke="#ffffff" strokeOpacity={0.09} strokeWidth={Math.max(0.5, vb.w / 1400)} />)}
          <circle r={sun * 1.6} fill="url(#moons-glow)" />
          <circle r={sun} fill="url(#moons-sun)" />
          {clusters.map((c) => (
            <g key={c.host.id} transform={`translate(${c.x} ${c.y})`}>
              {c.moons.map((m) => (
                <g key={m.moon.name} transform={`translate(${m.x} ${m.y})`} style={{ cursor: "pointer" }}
                  onClick={() => { if (!drag.current?.moved) setPick({ kind: "moon", moon: m.moon, host: c.host }); }}>
                  <title>{`${m.moon.name}, moon of ${c.host.name}${m.moon.radius ? `: ${Math.round(m.moon.radius * 2).toLocaleString()} km across` : ""}`}</title>
                  <circle r={m.r} fill={m.moon.named ? moonFill(m.moon.radius) : "#3c4352"}
                    stroke={pick?.kind === "moon" && pick.moon === m.moon ? "#ffd25a" : c.host.colour} strokeOpacity={pick?.kind === "moon" && pick.moon === m.moon ? 1 : 0.55}
                    strokeWidth={pick?.kind === "moon" && pick.moon === m.moon ? Math.max(1.5, m.r * 0.12) : Math.min(1, m.r * 0.15)} />
                  {m.moon.named && <Label name={m.moon.name} r={m.r} />}
                </g>
              ))}
              <g style={{ cursor: "pointer" }} onClick={() => { if (!drag.current?.moved) setPick({ kind: "host", host: c.host }); }}>
                <title>{`${c.host.name}: ${c.moons.length} moons shown`}</title>
                <circle r={c.r} fill={c.host.colour} stroke={pick?.kind === "host" && pick.host === c.host ? "#ffd25a" : "#ffffff"} strokeOpacity={pick?.kind === "host" && pick.host === c.host ? 1 : 0.25} strokeWidth={2} />
                {c.host.id === "saturn" && <ellipse rx={c.r * 1.55} ry={c.r * 0.38} fill="none" stroke="#e8d9a8" strokeOpacity={0.55} strokeWidth={c.r * 0.12} pointerEvents="none" />}
                <text textAnchor="middle" dy="0.35em" fill="#fff" fontWeight={700} pointerEvents="none"
                  style={{ fontSize: Math.max(5, Math.min(c.r * 0.42, 15)), paintOrder: "stroke", stroke: "#0008", strokeWidth: 2 }}>{c.host.name}</text>
              </g>
            </g>
          ))}
        </svg>
        <p className="caption">
          {from === "jpl"
            ? `Moons and their sizes from JPL's planetary satellite table (${fetched?.slice(0, 10) ?? ""}). `
            : "Moons from the built-in list (named moons; sizes of the small outer moons are rounded estimates), until JPL's satellite table downloads. "}
          Grey dots are moons with only a provisional code so far. {scale === "readable" ? "Sizes are squeezed so the smallest moons can still be seen: bigger is bigger, but not to scale." : "Planets and moons to one scale (the Sun is not: it would be ten times as wide as Jupiter). Most moons are specks next to their planet."} Places around the Sun are for show, not where the planets are today (see From above).
        </p>
      </div>
      <div style={{ flex: "1 1 280px", display: "grid", gap: 12 }}>
        {pick && (
          <div className="card">
            <div className="title-row">
              <h3 style={{ marginTop: 0 }}>{pick.kind === "host" ? pick.host.name : pick.moon.name} <span className="muted small">{pick.kind === "host" ? pick.host.kind : `moon of ${pick.host.name}`}</span></h3>
              <AskButton title={pick.kind === "host" ? `${pick.host.name}'s moons` : pick.moon.name} parts={() => [
                { key: "pick", kind: "data", label: pick.kind === "host" ? pick.host.name : pick.moon.name, text: pick.kind === "host"
                  ? `${pick.host.name} (${pick.host.kind}), ${Math.round(pick.host.radius * 2).toLocaleString()} km across, ${counts.find((c) => c.host === pick.host)?.total ?? 0} known moons: ${moons.filter((m) => m.host === pick.host.id && m.named).map((m) => m.name).join(", ")}`
                  : `${pick.moon.name}, moon of ${pick.host.name}${pick.moon.radius ? `, ${Math.round(pick.moon.radius * 2).toLocaleString()} km across` : ""}` },
                ...(fact ? [{ key: "fact", kind: "data" as const, label: "Fact card", text: `${fact.facts.map((f) => f.join(": ")).join("; ")}. ${fact.note}` }] : []),
              ]} />
            </div>
            <table className="small"><tbody>
              {pick.kind === "host" ? (<>
                <tr><td className="muted">Diameter</td><td>{Math.round(pick.host.radius * 2).toLocaleString()} km</td></tr>
                <tr><td className="muted">Known moons</td><td><b>{counts.find((c) => c.host === pick.host)?.total ?? 0}</b> ({counts.find((c) => c.host === pick.host)?.named ?? 0} with names)</td></tr>
                {moons.filter((m) => m.host === pick.host.id && m.radius).slice(0, 1).map((m) => (
                  <tr key="big"><td className="muted">Biggest moon</td><td><button className="link" onClick={() => setPick({ kind: "moon", moon: m, host: pick.host })}>{m.name}</button>, {Math.round(m.radius! * 2).toLocaleString()} km</td></tr>
                ))}
              </>) : (<>
                <tr><td className="muted">Diameter</td><td>{pick.moon.radius ? `${Math.round(pick.moon.radius * 2).toLocaleString()} km` : "not measured"}</td></tr>
                {pick.moon.radius ? <tr><td className="muted">Next to our Moon</td><td>{pctOfMoon(pick.moon.radius)}</td></tr> : null}
                <tr><td className="muted">Planet</td><td><button className="link" onClick={() => setPick({ kind: "host", host: pick.host })}>{pick.host.name}</button></td></tr>
              </>)}
              {fact?.facts.filter(([k]) => k !== "Diameter" && k !== "Moons").map(([k, v]) => <tr key={k}><td className="muted">{k}</td><td>{v}</td></tr>)}
            </tbody></table>
            {fact && <p className="small">{fact.note}</p>}
          </div>
        )}
        <div className="card">
          <div className="title-row">
            <h3 style={{ marginTop: 0 }}>{counts[0]?.host.name} has the most moons: {counts[0]?.total.toLocaleString()}</h3>
            <AskButton title="Moons per planet" parts={() => [{ key: "counts", kind: "data", label: "Known moons", text: counts.map((c) => `${c.host.name}: ${c.total} (${c.named} named)`).join("\n") }]} />
          </div>
          <p className="small muted" style={{ marginTop: 0 }}>{totalMoons.toLocaleString()} known moons of the planets and dwarf planets. Darker part: named.</p>
          <table className="small" style={{ width: "100%" }}><tbody>
            {counts.filter((c) => c.total > 0).map((c) => (
              <tr key={c.host.id} style={{ cursor: "pointer" }} onClick={() => setPick({ kind: "host", host: c.host })}>
                <td style={{ whiteSpace: "nowrap", width: 80 }}>{c.host.name}</td>
                <td>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <div style={{ display: "flex", width: `${Math.max(1.5, (c.total / most) * 78)}%`, height: 12 }}>
                      <div style={{ width: `${(c.named / c.total) * 100}%`, background: c.host.colour }} />
                      <div style={{ flex: 1, background: c.host.colour, opacity: 0.4 }} />
                    </div>
                    <b>{c.total}</b>
                  </div>
                </td>
              </tr>
            ))}
          </tbody></table>
          <p className="caption">Mercury, Venus and Ceres have none. New small moons turn up most years, mostly around Saturn and Jupiter.</p>
        </div>
      </div>
    </div>
  );
}

// Big moons lighter, small ones darker, like the greys in the picture of them.
function moonFill(km: number | null) {
  const t = Math.min(1, Math.log10(1 + (km ?? 1)) / 3.4);
  const v = Math.round(78 + t * 90);
  return `rgb(${v + 6},${v + 2},${v - 4})`;
}

function pctOfMoon(km: number) {
  const p = (km / MOON_KM) * 100;
  return p >= 100 ? `${(km / MOON_KM).toFixed(1)} times as wide` : `${p >= 10 ? Math.round(p) : p.toFixed(1)}% as wide`;
}

// A name inside its circle when it fits: on one line, or split in two like "Kalli / chore".
function Label({ name, r }: { name: string; r: number }) {
  const fs = Math.min(r * 0.5, 11);
  if (fs < 3) return null;
  const width = (s: string) => s.length * fs * 0.56;
  const style = { fontSize: fs, paintOrder: "stroke" as const, stroke: "#0006", strokeWidth: fs * 0.15 };
  if (width(name) <= r * 1.8) return <text textAnchor="middle" dy="0.35em" fill="#fff" pointerEvents="none" style={style}>{name}</text>;
  const cut = Math.ceil(name.length / 2), a = name.slice(0, cut), b = name.slice(cut);
  const fs2 = Math.min(fs, (r * 1.6) / (Math.max(a.length, b.length) * 0.56));
  if (fs2 < 3) return null;
  return (
    <text textAnchor="middle" fill="#fff" pointerEvents="none" style={{ ...style, fontSize: fs2 }}>
      <tspan x={0} dy="-0.15em">{a}</tspan><tspan x={0} dy="1.05em">{b}</tspan>
    </text>
  );
}
