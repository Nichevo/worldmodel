"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import AskButton from "@/components/AskButton";
import { get } from "@/lib/api";
import { cssVar } from "@/lib/colors";
import { logHistory } from "@/lib/history";
import { useSettings } from "@/lib/settings";
import {
  asteroidAt, dateOf, FACTS, jd, orbit, PLANETS, planetAt, planetElements, TYPE_INFO, type AsteroidRow, type Fact,
} from "@/lib/space";

// The solar system from above: planets on their orbits for any date from 1957 to 2050, the
// asteroids by what they are made of, the paths of spacecraft that left Earth, and a fact
// card for each planet and big moon. A tilt slider turns it to show how orbits lean.

type Mission = { id: string; name: string; start: string; stop: string; country: string | null; agency: string; what: string };
type Have = { fetched: string; count: number; bytes: number } | null;
type SpaceStatus = {
  job: { state: string; step?: string; error?: string; skipped?: string[] }; on: boolean; values_on: boolean; missions: Mission[];
  asteroids_have: Have; missions_have: Have; values_have: Have;
};
type View = "inner" | "jupiter" | "outer" | "far";
const SPAN: Record<View, number> = { inner: 2.2, jupiter: 6, outer: 33, far: 160 };
const VIEW_TEXT: [View, string][] = [["inner", "Inner planets"], ["jupiter", "Out to Jupiter"], ["outer", "Out to Neptune"], ["far", "The Voyagers"]];
const MISSION_COLOURS = ["--series-1", "--series-2", "--series-3", "--series-4", "--series-6", "--series-7", "--series-5"];
const START = jd(new Date("1957-10-04")); // Sputnik
const END = jd(new Date("2050-12-31"));

export default function SpacePage() {
  const s = useSettings();
  const [st, setSt] = useState<SpaceStatus | null>(null);
  const [asteroids, setAsteroids] = useState<AsteroidRow[]>([]);
  const [paths, setPaths] = useState<Record<string, [number, number, number, number][]>>({});
  const [values, setValues] = useState<[string, number, string | null][]>([]);
  const [day, setDay] = useState(() => Math.round(jd(new Date())));
  const [playing, setPlaying] = useState(false);
  const [view, setView] = useState<View>("jupiter");
  const [log, setLog] = useState(false);
  const [tilt, setTilt] = useState(0);
  const [show, setShow] = useState({ asteroids: true, neo: true, trojans: true, missions: true });
  const [fact, setFact] = useState<Fact | null>(FACTS.find((f) => f.id === "earth") ?? null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const spots = useRef<{ id: string; x: number; y: number }[]>([]);

  const status = () => get<SpaceStatus>("/space").then(setSt).catch(() => setSt(null));
  useEffect(() => { status(); logHistory({ kind: "page", title: "Solar system", url: "/space", detail: "page" }); }, []);
  useEffect(() => {
    if (st?.job.state !== "running") return;
    const t = setInterval(status, 4000);
    return () => clearInterval(t);
  }, [st?.job.state]);
  useEffect(() => {
    if (st?.asteroids_have) get<{ rows: AsteroidRow[] }>("/space/asteroids").then((d) => setAsteroids(d.rows)).catch(() => undefined);
    if (st?.missions_have) get<{ rows: Record<string, [number, number, number, number][]> }>("/space/missions").then((d) => setPaths(d.rows)).catch(() => undefined);
    if (st?.values_have && s.space_values) get<{ rows: [string, number, string | null][] }>("/space/values").then((d) => setValues(d.rows)).catch(() => undefined);
  }, [st?.asteroids_have?.fetched, st?.missions_have?.fetched, st?.values_have?.fetched, s.space_values]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => setDay((d) => (d + 20 > END ? (setPlaying(false), d) : d + 20)), 60);
    return () => clearInterval(t);
  }, [playing]);

  const missions = st?.missions ?? [];
  const orbits = useMemo(() => PLANETS.map((p) => { const k = planetElements(p, day); return orbit(k.a, k.e, k.I, k.node, k.peri); }),
    [Math.round(day / 3650)]); // eslint-disable-line react-hooks/exhaustive-deps

  // Draw.
  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const w = c.clientWidth, h = c.clientHeight, dpr = window.devicePixelRatio || 1;
    c.width = w * dpr; c.height = h * dpr;
    const g = c.getContext("2d")!;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const dark = matchMedia("(prefers-color-scheme: dark)").matches;
    g.fillStyle = dark ? "#05070d" : "#0b1020";
    g.fillRect(0, 0, w, h);
    const span = SPAN[view], R = Math.min(w, h) / 2 - 12;
    const ct = Math.cos(tilt * Math.PI / 180), stt = Math.sin(tilt * Math.PI / 180);
    const radius = (r: number) => (log ? (Math.log10(1 + r / 0.25) / Math.log10(1 + span / 0.25)) * R : (r / span) * R);
    const xy = ([x, y, z]: [number, number, number]): [number, number] => {
      const r = Math.hypot(x, y, z);
      const k = r ? radius(r) / r : 0;
      return [w / 2 + x * k, h / 2 - (y * ct - z * stt) * k];
    };
    // Orbits
    g.lineWidth = 1;
    PLANETS.forEach((p, i) => {
      g.strokeStyle = `${p.colour}66`;
      g.beginPath();
      orbits[i].forEach((pt, k) => { const [x, y] = xy(pt); if (k) g.lineTo(x, y); else g.moveTo(x, y); });
      g.stroke();
    });
    // Asteroids
    if (show.asteroids || show.neo || show.trojans) {
      for (const r of asteroids) {
        const group = r[13];
        if ((group === "main belt" && !show.asteroids) || (group === "near Earth" && !show.neo) || (group === "Jupiter Trojans" && !show.trojans)) continue;
        const [x, y] = xy(asteroidAt(r, day));
        if (x < 0 || y < 0 || x > w || y > h) continue;
        g.fillStyle = r[10] ? "#ff9f43" : r[8] ? TYPE_INFO[r[8]]?.colour ?? "#777" : "#555c66";
        g.globalAlpha = r[9] ? 0.95 : 0.55;
        g.fillRect(x, y, r[10] ? 1.8 : 1.2, r[10] ? 1.8 : 1.2);
      }
      g.globalAlpha = 1;
    }
    // Sun
    g.fillStyle = "#ffd25a";
    g.beginPath(); g.arc(w / 2, h / 2, 5, 0, Math.PI * 2); g.fill();
    // Mission paths up to the date
    const now = day;
    spots.current = [{ id: "sun", x: w / 2, y: h / 2 }];
    if (show.missions) {
      missions.forEach((m, i) => {
        const rows = paths[m.id];
        if (!rows?.length || rows[0][0] > now) return;
        const colour = cssVar(MISSION_COLOURS[i % MISSION_COLOURS.length]) || "#7cc";
        g.strokeStyle = colour; g.lineWidth = 1.3; g.globalAlpha = 0.85;
        g.beginPath();
        let last: [number, number] | null = null;
        for (const r of rows) {
          if (r[0] > now) break;
          const p = xy([r[1], r[2], r[3]]);
          if (last) g.lineTo(p[0], p[1]); else g.moveTo(p[0], p[1]);
          last = p;
        }
        g.stroke(); g.globalAlpha = 1;
        if (last && rows[rows.length - 1][0] >= now - 20) { // still flying at this date
          g.fillStyle = colour; g.beginPath(); g.arc(last[0], last[1], 3, 0, Math.PI * 2); g.fill();
          g.font = "11px system-ui"; g.fillText(m.name, last[0] + 5, last[1] - 4);
          spots.current.push({ id: `m:${m.id}`, x: last[0], y: last[1] });
        }
      });
    }
    // Planets
    g.font = "12px system-ui";
    PLANETS.forEach((p) => {
      const [x, y] = xy(planetAt(p, day));
      g.fillStyle = p.colour;
      g.beginPath(); g.arc(x, y, p.id === "jupiter" || p.id === "saturn" ? 5 : 3.5, 0, Math.PI * 2); g.fill();
      if (x > 0 && x < w && y > 0 && y < h) { g.fillStyle = "#dfe6f0"; g.fillText(p.name, x + 6, y + 4); }
      spots.current.push({ id: p.id, x, y });
    });
    // Scale
    g.fillStyle = "#9aa4b2"; g.font = "11px system-ui";
    g.fillText(log ? "Distances squeezed (log scale) so the inner and outer planets both show" : `Width: ${(span * 2).toFixed(0)} AU (1 AU = Earth to Sun, 150 million km)`, 10, h - 10);
  }, [day, view, log, tilt, show, asteroids, paths, missions, orbits]);

  const click = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    const hit = spots.current.map((p) => ({ ...p, d: Math.hypot(p.x - x, p.y - y) })).sort((a, b) => a.d - b.d)[0];
    if (!hit || hit.d > 14) return;
    if (hit.id.startsWith("m:")) {
      const m = missions.find((mm) => mm.id === hit.id.slice(2));
      if (m) setFact({ id: hit.id, name: m.name, kind: "spacecraft", facts: [["Launched", m.start], ["Agency", m.agency], ["Path shown to", m.stop]], note: m.what });
      return;
    }
    setFact(FACTS.find((f) => f.id === hit.id) ?? null);
  };

  const date = dateOf(day).toISOString().slice(0, 10);
  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const r of asteroids) out[r[8] ?? "?"] = (out[r[8] ?? "?"] ?? 0) + 1;
    return out;
  }, [asteroids]);
  const byCountry = useMemo(() => {
    const out: Record<string, Mission[]> = {};
    for (const m of missions) (out[m.agency.split(",")[0]] ??= []).push(m);
    return Object.entries(out).sort((a, b) => b[1].length - a[1].length);
  }, [missions]);

  return (
    <div className="grid sector-page">
      <div className="title-row"><h1>Solar system</h1>
        <AskButton title="The solar system" parts={() => [
          { key: "date", kind: "description", label: "Date shown", text: date },
          { key: "missions", kind: "data", label: "Missions", text: missions.map((m) => `${m.name} (${m.agency}, launched ${m.start}): ${m.what}`).join("\n") },
          ...(fact ? [{ key: "fact", kind: "data" as const, label: fact.name, text: `${fact.facts.map((f) => f.join(": ")).join("; ")}. ${fact.note}` }] : []),
        ]} /></div>
      <p className="ink-2" style={{ marginTop: 0, maxWidth: 860 }}>
        The planets from above on any date since Sputnik, the asteroids coloured by what they are made of, and where spacecraft have flown. Click a planet or a spacecraft for its card.
        Part of <Link href="/zones">Beyond borders</Link>; launches and satellites by country are on <Link href="/sectors/space">Sectors &gt; Space</Link>.
      </p>
      <div className="chips-row" style={{ gap: 10, flexWrap: "wrap", alignItems: "center" }}>
        <div className="seg" role="group" aria-label="How far out">
          {VIEW_TEXT.map(([v, t]) => <button key={v} className={view === v ? "on" : ""} aria-pressed={view === v} onClick={() => setView(v)}>{t}</button>)}
        </div>
        <label className="small"><input type="checkbox" checked={log} onChange={(e) => setLog(e.target.checked)} /> Squeeze distances (log)</label>
        <label className="small">Tilt <input type="range" min={0} max={80} value={tilt} onChange={(e) => setTilt(Number(e.target.value))} /></label>
      </div>
      <div className="chips-row" style={{ gap: 10, flexWrap: "wrap", alignItems: "center" }}>
        <label className="small" style={{ flex: "1 1 320px" }}>Date <b>{date}</b>
          <input type="range" min={START} max={END} value={day} onChange={(e) => setDay(Number(e.target.value))} style={{ width: "100%" }} />
        </label>
        <button onClick={() => setPlaying(!playing)}>{playing ? "Pause" : "Play"}</button>
        <button className="link" onClick={() => setDay(Math.round(jd(new Date())))}>Today</button>
        {[["1977-09-05", "Voyager 1 leaves"], ["1989-08-25", "Voyager 2 at Neptune"], ["2015-07-14", "New Horizons at Pluto"]].map(([d, t]) =>
          <button key={d} className="link small" onClick={() => setDay(Math.round(jd(new Date(d))))}>{t}</button>)}
      </div>
      <div className="chips-row" style={{ gap: 14, alignItems: "flex-start", flexWrap: "wrap" }}>
        <div className="card" style={{ flex: "3 1 560px", padding: 6 }}>
          <canvas ref={canvas} onClick={click} style={{ width: "100%", height: 620, display: "block", cursor: "pointer" }} aria-label="Map of the solar system" />
          <div className="chips-row small" style={{ gap: 12, flexWrap: "wrap", marginTop: 6 }}>
            <label><input type="checkbox" checked={show.asteroids} onChange={(e) => setShow({ ...show, asteroids: e.target.checked })} /> Asteroid belt</label>
            <label><input type="checkbox" checked={show.neo} onChange={(e) => setShow({ ...show, neo: e.target.checked })} /> <span className="swatch" style={{ background: "#ff9f43" }} /> Near Earth</label>
            <label><input type="checkbox" checked={show.trojans} onChange={(e) => setShow({ ...show, trojans: e.target.checked })} /> Jupiter Trojans</label>
            <label><input type="checkbox" checked={show.missions} onChange={(e) => setShow({ ...show, missions: e.target.checked })} /> Spacecraft</label>
            {Object.entries(TYPE_INFO).map(([k, t]) => <span key={k}><span className="swatch" style={{ background: t.colour }} /> {t.label}</span>)}
          </div>
          {!s.space_fetch && <p className="small muted">Asteroids and spacecraft are off (Settings &gt; Maps &gt; Solar system downloads).</p>}
          {st?.job.state === "running" && <p className="small"><b>Downloading:</b> {st.job.step}. The planets already show; the rest appears when it is in.</p>}
          {st?.job.state === "failed" && <p className="small warn-text">Not downloaded: {st.job.error} <button className="link" onClick={() => fetch("/api/v1/space/fetch", { method: "POST" }).then(status)}>Try again</button></p>}
          {!!st?.job.skipped?.length && <p className="small muted">Horizons gave no path for: {st.job.skipped.join("; ")}.</p>}
          <p className="caption">
            Planets from JPL&apos;s orbital elements (good from 1800 to 2050). {asteroids.length ? `${asteroids.length.toLocaleString()} asteroids from JPL's Small-Body Database (${st?.asteroids_have?.fetched.slice(0, 10)}); bright dots have a measured type, faint ones are guessed from how much light they reflect.` : ""}
            {" "}Spacecraft paths from JPL Horizons. Sizes of dots are not to scale.
          </p>
        </div>
        <div style={{ flex: "1 1 280px", display: "grid", gap: 12 }}>
          {fact && (
            <div className="card">
              <h3 style={{ marginTop: 0 }}>{fact.name} <span className="muted small">{fact.kind}{fact.of ? ` of ${fact.of}` : ""}</span></h3>
              <table className="small"><tbody>{fact.facts.map(([k, v]) => <tr key={k}><td className="muted">{k}</td><td>{v}</td></tr>)}</tbody></table>
              <p className="small">{fact.note}</p>
              {fact.kind === "planet" && FACTS.some((f) => f.of === fact.name) && (
                <p className="small">Moons: {FACTS.filter((f) => f.of === fact.name).map((f, i) => <span key={f.id}>{i ? ", " : ""}<button className="link" onClick={() => setFact(f)}>{f.name}</button></span>)}</p>
              )}
            </div>
          )}
          <div className="card">
            <h3 style={{ marginTop: 0 }}>What is out there to mine</h3>
            <ul className="small" style={{ paddingLeft: 18 }}>
              {Object.entries(TYPE_INFO).map(([k, t]) => <li key={k}><b>{t.label}</b>{counts[k] ? ` (${counts[k].toLocaleString()} here)` : ""}: {t.holds}.</li>)}
              <li><b>The Moon:</b> water ice at the poles, for drinking, air and rocket fuel; helium-3 in the soil.</li>
              <li><b>Mars:</b> ice under the surface, and clays and salts left by old water.</li>
            </ul>
            {s.space_values && values.length > 0 && (
              <>
                <h4>Asterank&apos;s guessed values</h4>
                <table className="small"><tbody>{values.slice(0, 12).map(([n, v, t]) => <tr key={n}><td>{n}</td><td className="muted">{t ?? ""}</td><td className="num">${v >= 1e12 ? `${(v / 1e12).toFixed(0)} trillion` : `${(v / 1e9).toFixed(0)} billion`}</td></tr>)}</tbody></table>
                <p className="caption">Rough guesses from type and size at today&apos;s metal prices; nobody could sell that much.</p>
              </>
            )}
          </div>
          <div className="card">
            <h3 style={{ marginTop: 0 }}>Missions by agency</h3>
            <table className="small"><tbody>{byCountry.map(([a, ms]) => (
              <tr key={a}><td>{a}</td><td>{ms.map((m, i) => <span key={m.id}>{i ? ", " : ""}<button className="link" onClick={() => setFact({ id: m.id, name: m.name, kind: "spacecraft", facts: [["Launched", m.start], ["Agency", m.agency]], note: m.what })}>{m.name}</button></span>)}</td></tr>
            ))}</tbody></table>
          </div>
        </div>
      </div>
    </div>
  );
}
