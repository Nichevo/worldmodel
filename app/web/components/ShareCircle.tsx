"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Indicator, Ranking, RankingRow } from "@/lib/api";
import { cssVar } from "@/lib/colors";
import { csvText, type Exporter } from "@/lib/download";
import { useFlagCodes, flagUrl } from "@/lib/flags";
import { formatValue } from "@/lib/format";
import { shortValue } from "@/lib/look";
import { useSettings } from "@/lib/settings";
import { KEY_COUNTRIES } from "@/lib/topics";
import { lightness, mix, svgPng, useBoxSize } from "@/lib/svgpic";
import { circlePoly, labelSpot, polyArea, voronoiTreemap, type Poly, type Pt } from "@/lib/voronoi";

// Share of the world as one circle: cut into continents, then each continent into its
// countries, every cell's area in proportion to its figure (a Voronoi treemap). Small
// countries are gathered into "Rest of …". A ring round the edge names each continent with
// its share. Only for figures that add up across countries (people, land, emissions...).
// Click a country's cell for the country.

type Cont = { name: string; colour: string; angle: number | null };
const CONTINENTS: { name: string; v: string; angle: number }[] = [
  // where each continent starts, as an angle round the circle (0 = right, 90 = bottom)
  { name: "North America", v: "--cont-americas", angle: -105 },
  { name: "Oceania", v: "--cont-oceania", angle: -35 },
  { name: "Africa", v: "--cont-africa", angle: 20 },
  { name: "South America", v: "", angle: 100 },
  { name: "Europe", v: "--cont-europe", angle: 155 },
  { name: "Asia", v: "--cont-asia", angle: -160 },
];
const DETAIL = { fewer: 0.012, auto: 0.005, more: 0.0018 } as const;
type Detail = keyof typeof DETAIL;
const KEY = new Set(KEY_COUNTRIES.map((k) => k.id));

// Figures that can be split into shares of a world total.
export function addsUp(ind: Indicator): boolean {
  return ind.agg_method === "sum" || ind.type === "count";
}

type Cell = { id: string; name: string; value: number; rest: number; poly: Poly; fill: string; cont: string; row?: RankingRow };
type Arc = { name: string; colour: string; share: number; a1: number; a2: number };

export default function ShareCircle({ indicator, ranking, onPick, exporter, fill = false, maxSize = 760 }: {
  indicator: Indicator; ranking: Ranking | null; onPick: (id: string, e: React.MouseEvent) => void;
  exporter?: React.RefObject<Exporter>; fill?: boolean; maxSize?: number;
}) {
  const [detail, setDetail] = useState<Detail>("auto");
  const [box, size] = useBoxSize<HTMLDivElement>();
  const svg = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<string | null>(null);
  const flags = useFlagCodes(useSettings().flags_on);
  const S = Math.max(320, Math.min(maxSize, size.w || maxSize, fill && size.h ? size.h : Infinity));
  const ring = 34, R = S / 2 - ring - 6, C = S / 2;

  const rows = useMemo(() => (ranking?.rows ?? []).filter((r) => r.value > 0 && Number.isFinite(r.value)), [ranking]);
  const total = rows.reduce((s, r) => s + r.value, 0);
  const left = (ranking?.rows ?? []).length - rows.length; // zero or below: not in the circle

  // The layout in a unit circle (radius 1, centre 0), scaled when drawn; worked out again only
  // when the figures or the detail change.
  const layout = useMemo(() => {
    if (!rows.length || !(total > 0)) return null;
    const amer = cssVar("--cont-americas") || "#c2413a";
    const conts: Cont[] = CONTINENTS.map((c) => ({ name: c.name, colour: c.v ? cssVar(c.v) || "#888" : mix(amer, "#3a1020", 0.62), angle: c.angle }));
    const groups = new Map<string, RankingRow[]>();
    for (const r of rows) {
      const g = r.continent && conts.some((c) => c.name === r.continent) ? r.continent : "Other";
      groups.set(g, [...(groups.get(g) ?? []), r]);
    }
    if (groups.has("Other")) conts.push({ name: "Other", colour: cssVar("--muted") || "#888", angle: null });
    const used = conts.filter((c) => groups.has(c.name));
    const sums = used.map((c) => groups.get(c.name)!.reduce((s, r) => s + r.value, 0));
    const unit = circlePoly(0, 0, 1, 144);
    const start = used.map((c) => (c.angle === null ? null : [0.55 * Math.cos((c.angle * Math.PI) / 180), 0.55 * Math.sin((c.angle * Math.PI) / 180)] as Pt));
    const contCells = voronoiTreemap(unit, sums, { start, seed: 11 });
    const min = DETAIL[detail] * total;
    const cells: Cell[] = [];
    const arcs: Arc[] = [];
    used.forEach((c, ci) => {
      const list = groups.get(c.name)!.slice().sort((a, b) => b.value - a.value);
      const shown = list.filter((r, i) => i < 28 && (r.value >= min || (KEY.has(r.entity_id) && r.value >= total * 0.0002)));
      let rest = list.filter((r) => !shown.includes(r));
      if (rest.length === 1) { shown.push(rest[0]); rest = []; }
      if (!shown.length && rest.length) { shown.push(rest.shift()!); }
      const restSum = rest.reduce((s, r) => s + r.value, 0);
      const items = [...shown.map((r) => ({ id: r.entity_id, name: r.name, value: r.value, rest: 0, row: r as RankingRow | undefined })),
        ...(restSum > 0 ? [{ id: `rest:${c.name}`, name: `Rest of ${c.name}`, value: restSum, rest: rest.length, row: undefined }] : [])];
      const polys = voronoiTreemap(contCells[ci], items.map((x) => x.value), { seed: 31 + ci * 7 });
      items.forEach((x, k) => {
        const shade = [0, 0.1, -0.09, 0.17, -0.15, 0.05, -0.04, 0.13][k % 8];
        const fillC = x.rest ? mix(c.colour, cssVar("--surface") || "#fff", 0.42)
          : mix(c.colour, shade > 0 ? "#ffffff" : "#000000", 1 - Math.abs(shade));
        cells.push({ ...x, poly: polys[k] ?? [], fill: fillC, cont: c.name });
      });
      // the stretch of the rim this continent covers, for its label on the ring
      const angs = contCells[ci].filter((p) => Math.hypot(p[0], p[1]) > 0.995).map((p) => Math.atan2(p[1], p[0])).sort((a, b) => a - b);
      if (angs.length >= 2) {
        let gapAt = angs.length - 1, gap = angs[0] + 2 * Math.PI - angs[angs.length - 1];
        for (let i = 0; i < angs.length - 1; i++) if (angs[i + 1] - angs[i] > gap) { gap = angs[i + 1] - angs[i]; gapAt = i; }
        const a1 = angs[(gapAt + 1) % angs.length];
        let a2 = angs[gapAt];
        if (a2 <= a1) a2 += 2 * Math.PI;
        arcs.push({ name: c.name, colour: c.colour, share: sums[ci] / total, a1, a2 });
      }
    });
    return { cells, contCells, used, arcs, sums };
  }, [rows, total, detail]); // eslint-disable-line react-hooks/exhaustive-deps

  const year = ranking?.year;
  useEffect(() => {
    if (!exporter || !layout) return;
    exporter.current = {
      name: `${indicator.indicator_id}-shares-${year ?? ""}`,
      csv: () => csvText(["continent", "entity_id", "name", `value (${indicator.unit})`, "share of total (%)"],
        rows.map((r) => [r.continent ?? "", r.entity_id, r.name, r.value, +((r.value / total) * 100).toFixed(3)])),
      png: () => svgPng(svg.current!, `${indicator.name}${year ? `, ${year}` : ""}`, `Share of the countries' total, ${formatValue(total, indicator.unit, indicator.decimals)}`),
    };
  }, [exporter, layout, indicator, year, rows, total]);

  if (!ranking) return <p className="muted">Loading…</p>;
  if (!addsUp(indicator)) {
    return <p className="muted">Shares of the world only work for figures that add up across countries, such as population,
      farmland or emissions. {indicator.name} is a rate or average, so try Bands instead.</p>;
  }
  if (!layout) return <p className="muted">No country figures above zero for this year.</p>;

  const surface = cssVar("--surface") || "#fff", ink = cssVar("--ink") || "#111";
  const P = (p: Pt) => `${(C + p[0] * R).toFixed(1)},${(C + p[1] * R).toFixed(1)}`;
  const path = (poly: Poly) => (poly.length ? `M${poly.map(P).join("L")}Z` : "");
  const fmt = (v: number) => shortValue(v, indicator.unit, indicator.decimals);
  const pct = (v: number) => `${(v * 100).toFixed(v >= 0.1 ? 1 : v >= 0.01 ? 1 : 2)}%`;

  return (
    <div className="pic-wrap" style={fill ? { flex: 1, minHeight: 0, display: "flex", flexDirection: "column" } : undefined}>
      <div className="pic-bar">
        <span className="small muted">
          Countries&apos; total <b style={{ color: "var(--ink)" }}>{formatValue(total, indicator.unit, indicator.decimals)}</b>{year ? ` in ${year}` : ""}
          {ranking.world ? ` (world figure ${formatValue(ranking.world.value, indicator.unit, indicator.decimals)})` : ""}.
          {left > 0 ? ` ${left} at zero or below left out.` : ""} Area is share.
        </span>
        <span className="seg small" role="group" aria-label="How many countries">
          {(["fewer", "auto", "more"] as const).map((d) => (
            <button key={d} className={detail === d ? "on" : ""} onClick={() => setDetail(d)}>{d === "auto" ? "Usual" : d === "fewer" ? "Fewer countries" : "More countries"}</button>
          ))}
        </span>
      </div>
      <div ref={box} className="pic-scroll" style={{ display: "flex", justifyContent: "center", ...(fill ? { flex: 1, minHeight: 0 } : {}) }}>
        <svg ref={svg} className="share-pic" viewBox={`0 0 ${S} ${S}`} width={S} height={S} role="img"
          aria-label={`${indicator.name}: each country's share of the total, by continent`}>
          <defs>
            {layout.arcs.map((a, i) => {
              const mid = (a.a1 + a.a2) / 2;
              const lower = Math.sin(mid) > 0.05; // text on the lower half runs the other way, to stay upright
              const r = R + ring / 2 + 2;
              const p1: Pt = [C + r * Math.cos(a.a1), C + r * Math.sin(a.a1)], p2: Pt = [C + r * Math.cos(a.a2), C + r * Math.sin(a.a2)];
              const large = a.a2 - a.a1 > Math.PI ? 1 : 0;
              const d = lower ? `M${p2.join(",")} A${r},${r} 0 ${large} 0 ${p1.join(",")}` : `M${p1.join(",")} A${r},${r} 0 ${large} 1 ${p2.join(",")}`;
              return <path key={i} id={`share-arc-${indicator.indicator_id}-${i}`} d={d} fill="none" />;
            })}
          </defs>
          {/* the ring: one band per continent with its name and share */}
          {layout.arcs.map((a, i) => {
            const g = 0.012, r1 = R + 5, r2 = R + ring - 2;
            const b1 = a.a1 + g, b2 = a.a2 - g;
            if (b2 <= b1) return null;
            const large = b2 - b1 > Math.PI ? 1 : 0;
            const pt = (r: number, t: number) => `${(C + r * Math.cos(t)).toFixed(1)},${(C + r * Math.sin(t)).toFixed(1)}`;
            const len = (a.a2 - a.a1) * (R + ring / 2);
            const full = `${a.name.toUpperCase()}  ${pct(a.share)}`;
            const label = full.length * 8.2 < len ? full : pct(a.share).length * 7.5 < len ? pct(a.share) : "";
            return (
              <g key={a.name}>
                <path d={`M${pt(r2, b1)} A${r2},${r2} 0 ${large} 1 ${pt(r2, b2)} L${pt(r1, b2)} A${r1},${r1} 0 ${large} 0 ${pt(r1, b1)} Z`}
                  fill={mix(a.colour, surface, 0.16)} stroke={mix(a.colour, surface, 0.4)} strokeWidth={1} />
                {label && (
                  <text fontSize={12.5} fontWeight={700} letterSpacing={1.6} fill={lightness(a.colour) > 0.7 ? ink : a.colour} dominantBaseline="middle">
                    <textPath href={`#share-arc-${indicator.indicator_id}-${i}`} startOffset="50%" textAnchor="middle">{label}</textPath>
                  </text>
                )}
              </g>
            );
          })}
          <circle cx={C} cy={C} r={R + 2} fill={surface} />
          {layout.cells.map((c) => {
            const isCountry = !c.rest;
            const on = hover === c.id;
            return (
              <path key={c.id} d={path(c.poly)} fill={on && isCountry ? mix(c.fill, "#ffffff", 0.82) : c.fill} stroke={surface} strokeWidth={1.3}
                strokeLinejoin="round" style={{ cursor: isCountry ? "pointer" : "default" }}
                onClick={isCountry ? (e) => onPick(c.id, e) : undefined}
                onMouseEnter={() => setHover(c.id)} onMouseLeave={() => setHover(null)}>
                <title>{c.rest ? `${c.name} (${c.rest} countries): ${fmt(c.value)}, ${pct(c.value / total)} of the total`
                  : `${c.name}: ${fmt(c.value)}, ${pct(c.value / total)} of the total`}</title>
              </path>
            );
          })}
          {/* continents' outlines, heavier than the countries' */}
          {layout.contCells.map((poly, i) => (
            <path key={i} d={path(poly)} fill="none" stroke={surface} strokeWidth={3.5} strokeLinejoin="round" pointerEvents="none" />
          ))}
          <circle cx={C} cy={C} r={R} fill="none" stroke={surface} strokeWidth={3} pointerEvents="none" />
          {layout.cells.map((c) => <Label key={c.id} c={c} R={R} C={C} flag={c.rest ? undefined : flags.get(c.id)} value={fmt(c.value)}
            keyCountry={KEY.has(c.id)} />)}
        </svg>
      </div>
    </div>
  );
}

// A cell's flag, name and value, as large as fits in the cell.
function Label({ c, R, C, flag, value, keyCountry }: { c: Cell; R: number; C: number; flag?: string; value: string; keyCountry: boolean }) {
  if (c.poly.length < 3 || polyArea(c.poly) <= 0) return null;
  const spot = labelSpot(c.poly);
  const r = spot.r * R;
  const x = C + spot.at[0] * R, y = C + spot.at[1] * R;
  const wide = 1.85 * r;
  let name = c.name;
  let fs = Math.min(30, r * 0.5, wide / (0.58 * name.length));
  if (fs < 8.5 && !c.rest) { name = c.id; fs = Math.min(r * 0.55, wide / (0.66 * name.length)); }
  if (c.rest && fs < 8) { name = "Rest"; fs = Math.min(r * 0.5, wide / (0.6 * 4)); }
  if (fs < 6.5) return null;
  let vs = Math.min(fs * 0.86, wide / (0.6 * value.length));
  if (vs < 6.5) vs = 0;
  const fh = flag && fs >= 11 ? Math.min(fs * 1.05, r * 0.4) : 0;
  const H = (fh ? fh + 4 : 0) + fs + (vs ? vs + 2 : 0);
  let top = y - H / 2;
  const light = lightness(c.fill) > 0.6;
  const colour = c.rest ? cssVar("--ink-2") || "#555" : light ? "#161616" : "#ffffff";
  const halo = c.rest ? "none" : light ? "rgba(255,255,255,0.35)" : "rgba(0,0,0,0.28)";
  const out: React.ReactNode[] = [];
  if (fh) {
    out.push(<image key="f" href={flagUrl(flag!)} x={x - (fh * 4) / 3 / 2} y={top} width={(fh * 4) / 3} height={fh} preserveAspectRatio="xMidYMid slice" />);
    top += fh + 4;
  }
  out.push(<text key="n" x={x} y={top + fs * 0.82} textAnchor="middle" fontSize={fs} fontWeight={keyCountry || fs >= 14 ? 700 : 600}
    fill={colour} stroke={halo} strokeWidth={fs >= 12 ? 2.4 : 1.4} paintOrder="stroke" fontFamily={fs >= 16 ? cssVar("--serif") || "Georgia, serif" : undefined}>{name}</text>);
  top += fs + 2;
  if (vs) out.push(<text key="v" x={x} y={top + vs * 0.82} textAnchor="middle" fontSize={vs} fill={colour} opacity={0.92}
    stroke={halo} strokeWidth={1.2} paintOrder="stroke" style={{ fontVariantNumeric: "tabular-nums" }}>{value}</text>);
  return <g pointerEvents="none">{out}</g>;
}
