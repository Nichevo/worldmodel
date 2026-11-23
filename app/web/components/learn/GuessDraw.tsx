"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api, type GuessChart, type GuessResult } from "@/lib/api";
import { formatValue } from "@/lib/format";
import { short } from "@/lib/sectors";

// Draw your guess: the real line up to a year, then a blank area you draw the rest into with the
// mouse or a finger (one point a year, drag across). "Show me" draws the real line over yours and
// gives a score out of 100. Plain SVG so drawing feels direct; colours from the page's own palette.
const W = 720, H = 320, L = 56, R = 16, T = 16, B = 30;

export default function GuessDraw({ entity, indicator, hideFrom, ask, onScored }: {
  entity: string; indicator: string; hideFrom: number; ask?: string; onScored?: () => void;
}) {
  const [g, setG] = useState<GuessChart | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mine, setMine] = useState<Record<number, number>>({});
  const [result, setResult] = useState<GuessResult | null>(null);
  const [busy, setBusy] = useState(false);
  const svg = useRef<SVGSVGElement>(null);
  const drawing = useRef(false);
  const last = useRef<[number, number] | null>(null);

  useEffect(() => {
    let live = true;
    setG(null); setMine({}); setResult(null); setError(null);
    api.guess(entity, indicator, hideFrom).then((x) => live && setG(x)).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [entity, indicator, hideFrom]);

  const scale = useMemo(() => {
    if (!g) return null;
    const x = (y: number) => L + ((y - g.first) / (g.last - g.first || 1)) * (W - L - R);
    const y = (v: number) => T + (1 - (v - g.y_min) / (g.y_max - g.y_min || 1)) * (H - T - B);
    const toYear = (px: number) => g.first + ((px - L) / (W - L - R)) * (g.last - g.first);
    const toValue = (py: number) => g.y_min + (1 - (py - T) / (H - T - B)) * (g.y_max - g.y_min);
    return { x, y, toYear, toValue };
  }, [g]);

  if (error) return <p className="error">{error}</p>;
  if (!g || !scale) return <p className="muted small">Loading…</p>;
  const dec = g.decimals ?? 1;
  const fmt = (v: number) => formatValue(v, g.unit, dec);
  const start = g.shown[g.shown.length - 1];

  const put = (e: React.PointerEvent) => {
    if (result) return;
    const box = svg.current!.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W, py = ((e.clientY - box.top) / box.height) * H;
    const yr = Math.round(scale.toYear(px));
    const v = Math.min(g.y_max, Math.max(g.y_min, scale.toValue(py)));
    if (yr <= g.hide_from || yr > g.last) return;
    setMine((m) => {
      const out = { ...m, [yr]: v };
      const prev = last.current; // fill the years skipped by a quick drag
      if (prev && Math.abs(prev[0] - yr) > 1) {
        const [y0, v0] = prev, step = yr > y0 ? 1 : -1;
        for (let k = y0 + step; k !== yr; k += step) if (k > g.hide_from) out[k] = v0 + ((v - v0) * (k - y0)) / (yr - y0);
      }
      last.current = [yr, v];
      return out;
    });
  };

  const drawn = Object.entries(mine).map(([y, v]) => [Number(y), v] as [number, number]).sort((a, b) => a[0] - b[0]);
  const path = (pts: [number, number][]) => pts.map(([y, v], i) => `${i ? "L" : "M"}${scale.x(y).toFixed(1)},${scale.y(v).toFixed(1)}`).join(" ");
  const covered = drawn.length / Math.max(1, g.last - g.hide_from);
  const check = () => {
    setBusy(true);
    api.guessCheck(entity, indicator, g.hide_from, drawn).then((r) => { setResult(r); onScored?.(); }).catch((e) => setError(String(e.message || e))).finally(() => setBusy(false));
  };
  const ticks = Array.from({ length: 5 }, (_, i) => g.y_min + ((g.y_max - g.y_min) * i) / 4);
  const yearTicks = (() => {
    const span = g.last - g.first, step = span > 60 ? 20 : span > 30 ? 10 : 5;
    const out: number[] = [];
    for (let y = Math.ceil(g.first / step) * step; y <= g.last; y += step) out.push(y);
    return out;
  })();
  const end = result?.actual[result.actual.length - 1];

  return (
    <div>
      <h3 style={{ margin: "0 0 2px" }}>{ask || `${g.indicator}, ${g.name}: draw the rest`}</h3>
      <p className="small muted" style={{ marginTop: 0 }}>{g.indicator} ({g.unit || "number"}), {g.name}. The line stops in {g.hide_from}:
        drag across the shaded part to draw what you think happened up to {g.last}.</p>
      <svg ref={svg} viewBox={`0 0 ${W} ${H}`} className="guess-svg" role="img" aria-label={`Draw your guess: ${g.indicator}, ${g.name}`}
        onPointerDown={(e) => { drawing.current = true; last.current = null; (e.target as Element).setPointerCapture?.(e.pointerId); put(e); }}
        onPointerMove={(e) => drawing.current && put(e)} onPointerUp={() => { drawing.current = false; }} onPointerLeave={() => { drawing.current = false; }}>
        <rect x={scale.x(g.hide_from)} y={T} width={W - R - scale.x(g.hide_from)} height={H - T - B} className="guess-zone" />
        {ticks.map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={scale.y(v)} y2={scale.y(v)} className="guess-grid" />
            <text x={L - 6} y={scale.y(v) + 4} textAnchor="end" className="guess-axis">{short(v)}</text>
          </g>
        ))}
        {yearTicks.map((y) => <text key={y} x={scale.x(y)} y={H - 10} textAnchor="middle" className="guess-axis">{y}</text>)}
        <path d={path(g.shown)} className="guess-real" />
        <circle cx={scale.x(start[0])} cy={scale.y(start[1])} r={4} className="guess-dot" />
        <text x={scale.x(start[0]) - 6} y={scale.y(start[1]) - 8} textAnchor="end" className="guess-label">{fmt(start[1])}</text>
        {drawn.length > 0 && <path d={path([start, ...drawn])} className="guess-mine" />}
        {result && <path d={path([start, ...result.actual])} className="guess-real reveal" />}
        {result && end && <text x={scale.x(end[0]) - 4} y={scale.y(end[1]) - 8} textAnchor="end" className="guess-label">{end[0]}: {fmt(end[1])}</text>}
        {!drawn.length && !result && <text x={(scale.x(g.hide_from) + W - R) / 2} y={H / 2} textAnchor="middle" className="guess-hint">Draw here</text>}
      </svg>
      <div className="chips-row small" style={{ marginTop: 6 }}>
        {!result && <button disabled={busy || covered < 0.5} onClick={check}
          title={covered < 0.5 ? "Draw at least half of the missing years first" : ""}>Show me</button>}
        {!result && drawn.length > 0 && <button className="link small" onClick={() => { setMine({}); last.current = null; }}>Start again</button>}
        {result && <>
          <b className={result.score >= 70 ? "good" : result.score < 40 ? "bad" : ""}>Your score: {result.score} out of 100</b>
          <span className="muted">
            {result.gap != null ? `Your line was ${fmt(result.gap)} away from the real one on average.` : ""}
            {end ? ` The real figure in ${end[0]}: ${fmt(end[1])}` : ""}
            {end && mine[end[0]] != null ? `; you drew ${fmt(mine[end[0]])}.` : "."}
          </span>
          <button className="link small" onClick={() => { setMine({}); setResult(null); last.current = null; }}>Try again</button>
        </>}
      </div>
      <p className="caption">Source: {g.source_id}. Only actual figures, not projections.</p>
    </div>
  );
}
