"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Indicator, Ranking } from "@/lib/api";
import { bandOf, makeBands, type BandDetail } from "@/lib/bands";
import { useCss } from "@/lib/colors";
import { csvText, type Exporter } from "@/lib/download";
import { useFlagCodes, flagUrl } from "@/lib/flags";
import { FIXED_ENTITY, shortValue } from "@/lib/look";
import { useSettings } from "@/lib/settings";
import { mix, svgPng, textWidth, useBoxSize } from "@/lib/svgpic";

// Every country as a small tile (flag, name, value), stacked in columns by value band:
// lowest band on the left, highest in each column at the top. The columns' heights make
// a bar chart of how many countries fall in each band; the world figure sits over its band.
// Click a tile for the country.

const TILE_H = 21, TILE_GAP = 3, COL_GAP = 7, HEAD = 40, FOOT = 46, MIN_COL = 112;

export default function CountryBands({ indicator, ranking, onPick, selection = [], exporter, fill = false }: {
  indicator: Indicator; ranking: Ranking | null; onPick: (id: string, e: React.MouseEvent) => void;
  selection?: string[]; exporter?: React.RefObject<Exporter>; fill?: boolean;
}) {
  const settings = useSettings();
  const flags = useFlagCodes(settings.flags_on);
  const [detail, setDetail] = useState<BandDetail>("auto");
  const [box, size] = useBoxSize<HTMLDivElement>();
  const svg = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<string | null>(null);
  const rows = useMemo(() => (ranking?.rows ?? []).filter((r) => Number.isFinite(r.value)), [ranking]);

  const cssVar = useCss();
  const model = useMemo(() => {
    if (!rows.length) return null;
    const bands = makeBands(rows.map((r) => r.value), indicator.unit, detail);
    const cols = bands.map(() => [] as typeof rows);
    for (const r of rows) cols[bandOf(bands, r.value)].push(r);
    cols.forEach((c) => c.sort((a, b) => b.value - a.value));
    // colours: reds for bands below zero, then a light-to-deep ramp
    const neg = bands.filter((b) => b.neg).length, pos = bands.length - neg;
    const negRamp = ["--div-neg-1", "--div-neg-2", "--div-neg-3"].map(cssVar);
    const seq = [2, 3, 4, 5, 6, 7].map((i) => cssVar(`--seq-${i}`));
    const colours = bands.map((b, i) => {
      if (b.neg) return negRamp[Math.min(2, Math.max(0, 2 - Math.round(((i) / Math.max(1, neg - 1)) * 2)))] || "#c0392b";
      const k = i - neg;
      return seq[pos <= 1 ? 3 : Math.round((k / (pos - 1)) * (seq.length - 1))] || "#1d8bbf";
    });
    const worldBand = ranking?.world ? bandOf(bands, ranking.world.value) : null;
    return { bands, cols, colours, worldBand };
  }, [rows, indicator.unit, detail, ranking?.world, cssVar]); // eslint-disable-line react-hooks/exhaustive-deps

  const surface = cssVar("--surface") || "#fff", ink = cssVar("--ink") || "#111", muted = cssVar("--muted") || "#888";
  const nCols = model?.bands.length ?? 1;
  const colW = Math.max(MIN_COL, Math.floor(((size.w || 900) - COL_GAP * (nCols - 1)) / nCols));
  const tallest = model ? Math.max(...model.cols.map((c) => c.length)) : 0;
  const width = nCols * colW + (nCols - 1) * COL_GAP;
  const base = HEAD + tallest * (TILE_H + TILE_GAP);
  const height = base + FOOT;
  const fmt = (v: number) => shortValue(v, indicator.unit, indicator.decimals);
  const year = ranking?.year;

  useEffect(() => {
    if (!exporter || !model) return;
    exporter.current = {
      name: `${indicator.indicator_id}-bands-${year ?? ""}`,
      csv: () => csvText(["band", "rank", "entity_id", "name", `value (${indicator.unit})`],
        model.cols.flatMap((c, i) => c.map((r) => [model.bands[i].label, r.rank, r.entity_id, r.name, r.value]))),
      png: () => svgPng(svg.current!, `${indicator.name}${year ? `, ${year}` : ""}`, `Every country by value band (${indicator.unit})`),
    };
  }, [exporter, model, indicator, year]);

  if (!ranking) return <p className="muted">Loading…</p>;
  if (!model) return <p className="muted">No country figures for this year.</p>;
  return (
    <div className="pic-wrap" style={fill ? { flex: 1, minHeight: 0, display: "flex", flexDirection: "column" } : undefined}>
      <div className="pic-bar">
        <span className="small muted">{rows.length} countries{year ? `, ${year}` : ""} in {model.bands.length} bands. Click a tile for the country.</span>
        <span className="seg small" role="group" aria-label="How many bands">
          {(["fewer", "auto", "more"] as const).map((d) => (
            <button key={d} className={detail === d ? "on" : ""} onClick={() => setDetail(d)}>{d === "auto" ? "Usual" : d === "fewer" ? "Fewer bands" : "More bands"}</button>
          ))}
        </span>
      </div>
      <div ref={box} className="pic-scroll" style={fill ? { flex: 1, minHeight: 0 } : undefined}>
        <svg ref={svg} className="bands-pic" viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img"
          aria-label={`${indicator.name}: countries in ${model.bands.length} value bands`}>
          <defs>
            <filter id="band-lift" x="-10%" y="-30%" width="120%" height="160%">
              <feDropShadow dx="0" dy="1" stdDeviation="1.2" floodOpacity="0.25" />
            </filter>
          </defs>
          {model.cols.map((col, ci) => {
            const x = ci * (colW + COL_GAP);
            const colour = model.colours[ci];
            const tint = mix(colour, surface, 0.26);
            const band = model.bands[ci];
            return (
              <g key={ci}>
                {/* a faint column behind the tiles, the full height, so empty space still reads as a band */}
                <rect x={x} y={HEAD - 4} width={colW} height={base - HEAD + 4} rx={6} fill={mix(colour, surface, 0.05)} />
                {col.map((r, k) => {
                  const y = base - (col.length - k) * (TILE_H + TILE_GAP);
                  const fixed = FIXED_ENTITY[r.entity_id];
                  const picked = selection.includes(r.entity_id);
                  const ring = fixed ? cssVar(fixed) : picked ? cssVar("--accent") : null;
                  const code = flags.get(r.entity_id);
                  const val = fmt(r.value);
                  const nameX = code ? 27 : 9;
                  const room = colW - nameX - textWidth(val, 11, 700) - 12;
                  const name = fitName(r.name, room, fixed || picked ? 700 : 400);
                  const on = hover === r.entity_id;
                  return (
                    <g key={r.entity_id} className="band-tile" transform={`translate(${x},${y})`} style={{ cursor: "pointer" }}
                      onClick={(e) => onPick(r.entity_id, e)} onMouseEnter={() => setHover(r.entity_id)} onMouseLeave={() => setHover(null)}
                      filter={on ? "url(#band-lift)" : undefined}>
                      <title>{`${r.name}: ${val}${r.status === "P" ? " (projection)" : ""}, ${r.rank} of ${rows.length}`}</title>
                      <rect width={colW} height={TILE_H} rx={4} fill={on ? mix(colour, surface, 0.45) : tint}
                        stroke={ring ?? "none"} strokeWidth={ring ? 2 : 0} />
                      <rect width={4} height={TILE_H} rx={2} fill={colour} />
                      {code && <image href={flagUrl(code)} x={9} y={(TILE_H - 11) / 2} width={14} height={11} preserveAspectRatio="xMidYMid slice" />}
                      <text x={nameX} y={TILE_H / 2 + 4} fontSize={11} fill={ink} fontWeight={fixed || picked ? 700 : 400}>{name}</text>
                      <text x={colW - 6} y={TILE_H / 2 + 4} fontSize={11} fill={ink} fontWeight={700} textAnchor="end"
                        style={{ fontVariantNumeric: "tabular-nums" }}>{val}</text>
                    </g>
                  );
                })}
                {/* the band's name and count under the column */}
                <text x={x + colW / 2} y={base + 19} textAnchor="middle" fontSize={13} fontWeight={700}
                  fill={band.neg ? cssVar("--bad") || colour : mix(colour, ink, 0.62)}>{band.label}</text>
                <text x={x + colW / 2} y={base + 35} textAnchor="middle" fontSize={11} fill={muted}>
                  {col.length} {col.length === 1 ? "country" : "countries"}</text>
              </g>
            );
          })}
          <line x1={0} x2={width} y1={base + 2} y2={base + 2} stroke={cssVar("--axis") || muted} strokeWidth={1} />
          {model.worldBand !== null && ranking.world && (() => {
            const ci = model.worldBand;
            const cx = ci * (colW + COL_GAP) + colW / 2;
            const top = base - model.cols[ci].length * (TILE_H + TILE_GAP) - 10;
            const text = `World ${fmt(ranking.world.value)}`;
            const w = text.length * 6.6 + 18;
            return (
              <g transform={`translate(${cx},${Math.max(16, top)})`}>
                <rect x={-w / 2} y={-20} width={w} height={20} rx={10} fill={ink} />
                <path d="M -5 0 L 5 0 L 0 6 Z" fill={ink} />
                <text y={-6} textAnchor="middle" fontSize={11} fontWeight={700} fill={surface} letterSpacing={0.4}>{text}</text>
              </g>
            );
          })()}
        </svg>
      </div>
    </div>
  );
}

// A name cut short with an ellipsis so it fits the room left beside the value.
function fitName(name: string, room: number, weight: number): string {
  if (textWidth(name, 11, weight) <= room) return name;
  let n = name.length - 1;
  while (n > 2 && textWidth(`${name.slice(0, n).trimEnd()}…`, 11, weight) > room) n--;
  return `${name.slice(0, n).trimEnd()}…`;
}
