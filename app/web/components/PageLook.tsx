"use client";

import { useCallback, useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import { openAsk } from "@/lib/ai";
import { api, type Chokepoint, type CountryPorts, type HeadTileData, type LandCover, type LandMix, type Ranked, type Recovery, type SeriesRow } from "@/lib/api";
import { cardLinesOption, linesOption } from "@/lib/charts";
import { formatValue } from "@/lib/format";
import { entityVar, sparkPath } from "@/lib/look";
import { useSettings } from "@/lib/settings";

// Pieces the Transport, Tourism, Land, Pollution and Nature pages lead with: a headline strip,
// cards titled by what the figures say, labelled bars, small multiples and target tiles.

export const useKeys = () => useSettings().discover_key_countries || "NZL,AUS,GBR,USA";
const ask = (title: string, label: string, text: string) => openAsk({ title, parts: [{ key: title, kind: "data", label, text }] });
const fmt = (v: number, unit: string, d: number) => formatValue(v, unit, d);

export function HeadStrip({ heads, onGo }: { heads: HeadTileData[] | null; onGo?: (tab: string) => void }) {
  if (!heads?.length) return null;
  return (
    <div className="climate-strip">
      {heads.map((h) => (
        <button key={h.id} className="card tile htile climate-head" onClick={() => onGo?.(h.tab)} title={onGo ? `${h.label}: open its tab` : h.label}>
          <span className="label">{h.label}</span>
          <span className="value">{h.value}</span>
          <span className={`meta tone-${h.tone}`}>{h.note}</span>
        </button>
      ))}
    </div>
  );
}

// Chokepoints as labelled bars with the change against a year before; click one for its chart.
export function ChokeBars({ rows, finding, picked, onPick }: { rows: Chokepoint[]; finding: string; picked: string | null; onPick: (id: string) => void }) {
  const top = Math.max(...rows.map((r) => r.now ?? 0), 1);
  return (
    <div className="card">
      <div className="card-head"><span className="small ink-2">Chokepoints, ships a day, last 30 days</span>
        <CardAsk onAsk={() => ask("Chokepoints", "Ships a day, last 30 days, and change on a year before",
          rows.map((c) => `${c.name}\t${c.now ?? ""}\t${c.change ?? ""}%`).join("\n"))} /></div>
      {finding && <h3 className="finding">{finding}</h3>}
      <div className="lbars">
        {rows.map((c) => (
          <button key={c.id} className={`lbar${c.id === picked ? " on" : ""}`} onClick={() => onPick(c.id)} title={`${c.name}: open its chart`}>
            <span className="lbar-name">{c.name}</span>
            <span className="lbar-track"><span style={{ width: `${Math.max(1, ((c.now ?? 0) / top) * 100)}%` }} /></span>
            <span className="mono">{c.now == null ? "" : c.now >= 10 ? Math.round(c.now) : c.now}</span>
            <span className={`mono small ${c.change == null ? "" : c.change >= 0 ? "tone-good" : "tone-bad"}`}>
              {c.change == null ? "" : `${c.change >= 0 ? "▲" : "▼"} ${Math.abs(c.change).toFixed(0)}%`}</span>
          </button>
        ))}
      </div>
      {rows[0] && <p className="caption">Last 30 days to {rows[0].as_of} against the same days a year before (IMF PortWatch). Click one for its chart.</p>}
    </div>
  );
}

// A country's busiest ports, one small chart each on its own scale.
export function PortMultiples({ entity, name }: { entity: string; name: string }) {
  const [d, setD] = useState<CountryPorts | null>(null);
  useEffect(() => { api.countryPorts(entity).then(setD).catch(() => setD(null)); }, [entity]);
  if (!d?.ports.length) return null;
  const W = 120, H = 40;
  return (
    <div className="card">
      <div className="card-head"><span className="small ink-2">{name}&apos;s ports, ship calls a month</span>
        <CardAsk onAsk={() => ask(`${name}'s ports`, "Ship calls a month", d.ports.map((p) => `${p.name}\t${p.months.map((m) => `${m[0]}:${m[1]}`).join(" ")}`).join("\n"))} /></div>
      {d.finding && <h3 className="finding">{d.finding}</h3>}
      <div className="port-grid">
        {d.ports.map((p) => (
          <div key={p.port_id} className="port-tile">
            <b className="small">{p.name}</b>
            <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-label={`${p.name}: ship calls a month`}>
              <path d={sparkPath(p.months.map((m, i) => [i, m[1]] as [number, number]), W, H)} fill="none" stroke="var(--ink)" strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
            </svg>
            <span className="mono small">{Math.round(p.calls_12m / 12).toLocaleString()} a month{" "}
              {p.change != null && <span className={p.change >= 0 ? "tone-good" : "tone-bad"}>{p.change >= 0 ? "▲" : "▼"}{Math.abs(p.change).toFixed(0)}%</span>}</span>
          </div>
        ))}
      </div>
      <p className="caption">Three years to {d.to}, each on its own scale so the smaller ports read. Change: the last 12 months against the 12 before. IMF PortWatch.</p>
    </div>
  );
}

// Where a country sits on a figure among all countries: a dot per key country, the world and the
// ends of the range, with a guideline or target line, and the home country's line under it.
export function RankedCard({ indicator, keys, title }: { indicator: string; keys: string; title?: string }) {
  const [r, setR] = useState<Ranked | null | undefined>(undefined);
  useEffect(() => { api.ranked(indicator, keys).then(setR).catch(() => setR(null)); }, [indicator, keys]);
  if (!r) return null;
  const hi = Math.max(r.max, r.guide?.value ?? 0) * 1.02;
  const lo = Math.min(0, r.min);
  const at = (v: number) => `${((v - lo) / (hi - lo || 1)) * 100}%`;
  const keyIds = keys.split(",");
  const finding = r.guide && r.guide.meeting != null
    ? `${r.guide.meeting} of ${r.of} countries ${r.lower_better ? "at or under" : "at or above"} ${r.guide.label.split(" (")[0].replace(/^WHO guideline /, "the WHO guideline of ")}`
    : r.line;
  return (
    <div className="card">
      <div className="card-head"><span className="small ink-2">{title ?? r.name.replace(/\s*\([^)]*\)$/, "")}, {r.unit}, {r.year}</span>
        <CardAsk onAsk={() => ask(r.name, `${r.name} (${r.unit}), ${r.year}`, [r.line, ...r.rows.map((x) => `${x.name}\t${x.value}${x.rank ? `\t#${x.rank}` : ""}`)].join("\n"))} /></div>
      <h3 className="finding">{finding}</h3>
      <div className="rk">
        {r.guide && <span className="rk-guide" style={{ left: `calc(130px + (100% - 190px) * ${(r.guide.value - lo) / (hi - lo || 1)})` }} title={r.guide.label} />}
        {r.rows.map((x) => {
          const i = keyIds.indexOf(x.entity_id);
          const color = x.entity_id === "world" ? "var(--c-world)" : i >= 0 ? entityVar(x.entity_id, i) : "var(--muted)";
          return (
            <div key={x.entity_id} className={`rk-row${x.key ? "" : " far"}`}>
              <span className={i === 0 ? "strong" : ""}>{x.name}</span>
              <span className="rk-line"><i style={{ left: at(x.value), background: color }} /></span>
              <span className="mono small">{fmt(x.value, "", r.decimals)}</span>
            </div>
          );
        })}
      </div>
      <p className="small rk-home">{r.line ? <><b>{r.line.split(":")[0]}:</b>{r.line.slice(r.line.indexOf(":") + 1)}</> : null}</p>
      {r.guide && <p className="caption">Dashed line: {r.guide.label}.{r.lower_better ? " Lower is better." : ""} Grey: the best and worst countries.</p>}
    </div>
  );
}

// Target tiles: the home country's figure, the world's, and a bar with the target marked.
export function TargetTiles({ ids, keys }: { ids: string[]; keys: string }) {
  const [rs, setRs] = useState<Ranked[]>([]);
  useEffect(() => {
    Promise.all(ids.map((i) => api.ranked(i, keys).catch(() => null))).then((l) => setRs(l.filter((x): x is Ranked => !!x)));
  }, [ids.join(","), keys]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!rs.length) return null;
  const home = keys.split(",")[0];
  return (
    <div className="target-tiles">
      {rs.map((r) => {
        const h = r.rows.find((x) => x.entity_id === home);
        const w = r.rows.find((x) => x.entity_id === "world");
        const top = Math.max(100, r.guide?.value ?? 0);
        return (
          <div key={r.indicator} className="card tile htile">
            <span className="label">{r.name}</span>
            <span className="value">{h ? `${fmt(h.value, "", r.decimals)}${r.unit.includes("%") ? "%" : ` ${r.unit}`}` : "–"}</span>
            <span className="tt-bar"><span style={{ width: `${Math.min(100, ((h?.value ?? 0) / top) * 100)}%` }} />
              {r.guide && <i style={{ left: `${(r.guide.value / top) * 100}%` }} title={r.guide.label} />}</span>
            <span className="meta">{h?.name ?? home}{w ? ` · world ${fmt(w.value, r.unit, r.decimals)}` : ""}{r.guide ? ` · goal ${r.guide.label.split(" (")[0]}` : ""}</span>
          </div>
        );
      })}
    </div>
  );
}

// Key countries since 2000 with end labels, titled by how far each is back to its 2019 level.
export function RecoveryCard({ indicator, keys, label }: { indicator: string; keys: string; label: string }) {
  const [r, setR] = useState<Recovery | null>(null);
  useEffect(() => { api.recovery(indicator, keys).then(setR).catch(() => setR(null)); }, [indicator, keys]);
  const opt = useCallback(() => {
    const rows: SeriesRow[] = (r?.lines ?? []).flatMap((l) => l.points.map(([y, v]) => ({ entity_id: l.id, indicator_id: indicator, period: String(y), value: v,
      status: "E" as const, source_id: "", vintage: "", is_aggregate: false, coverage: null })));
    return linesOption([{ id: indicator, name: label, unit: "", decimals: 1, rows }], (r?.lines ?? []).map((l) => ({ id: l.id, name: l.name })));
  }, [r, indicator, label]);
  if (!r?.lines.length) return null;
  return (
    <div className="card">
      <div className="card-head"><span className="small ink-2">{label}</span>
        <CardAsk onAsk={() => ask(label, label, r.lines.map((l) => `${l.name}\t${l.points.map((p) => `${p[0]}:${p[1]}`).join(" ")}`).join("\n"))} /></div>
      <h3 className="finding">{r.finding || label}</h3>
      <EChart option={opt} height={260} label={label} />
      <p className="caption">Your key countries (Settings: Discover). The figure: each country&apos;s latest year against {r.base}, the last year before COVID-19.</p>
    </div>
  );
}

const LAND_COLOURS: Record<string, string> = { pasture: "#6fae4f", natural: "#2c5e3f", planted: "#8a6d3b", forest: "#2c7a4b", crops: "#d29a00", other: "var(--surface-2)" };

export function LandMixBar({ entity }: { entity: string }) {
  const [m, setM] = useState<LandMix | undefined>(undefined);
  useEffect(() => { api.landMix(entity).then(setM).catch(() => setM(null)); }, [entity]);
  if (!m) return null;
  const name = m.name;
  return (
    <div className="card">
      <div className="card-head"><span className="small ink-2">What the land is used for, {name}, {m.year}</span>
        <CardAsk onAsk={() => ask(`Land use in ${name}`, "Share of land area, change since " + m.since, m.parts.map((p) => `${p.label}\t${p.share}%\t${p.change ?? ""}`).join("\n"))} /></div>
      {m.finding && <h3 className="finding">{m.finding}</h3>}
      <div className="lm-bar" role="img" aria-label={m.parts.map((p) => `${p.label} ${p.share}%`).join(", ")}>
        {m.parts.filter((p) => p.share > 0).map((p) => (
          <span key={p.id} style={{ width: `${p.share}%`, background: LAND_COLOURS[p.id] }} className={p.id === "other" ? "other" : ""}
            title={`${p.label}: ${p.share}% of the land${p.change != null ? `, ${p.change > 0 ? "+" : ""}${p.change}% since ${m.since}` : ""}`}>
            {p.share >= 9 ? `${p.label.split(" (")[0]} ${p.share.toFixed(0)}%` : ""}
          </span>
        ))}
      </div>
      <p className="small ink-2">{m.parts.filter((p) => p.share < 9).map((p) => `${p.label.split(" (")[0]} ${p.share}%`).join(" · ")}</p>
      <p className="caption">Share of land area (FAOSTAT). Other is what is left: scrub, tussock, bare ground, towns and inland water.</p>
    </div>
  );
}

// Land cover by year (ESA satellite maps via FAOSTAT) as stacked bands, titled by the biggest moves,
// with chips for the key countries.
const COVER_COLOURS: Record<string, string> = { trees: "#1b5e20", shrub: "#8aa66b", grass: "#a9d18e", crops: "#d29a00", built: "#c0392b",
  bare: "#cfc6a8", snow: "#dfe7ec", water: "#4a90c2" };

export function LandCoverCard({ entity }: { entity: string }) {
  const keys = useKeys().split(",").filter(Boolean);
  const [who, setWho] = useState(entity);
  useEffect(() => setWho(entity), [entity]);
  const [c, setC] = useState<LandCover | null>(null);
  useEffect(() => { api.landCover(who).then(setC).catch(() => setC(null)); }, [who]);
  const opt = useCallback(() => cardLinesOption((c?.parts ?? []).map((p) => ({ key: p.id, label: p.label, color: COVER_COLOURS[p.id] ?? "#999",
    points: p.points.map(([y, v]) => [y, v, "E"] as [number, number, string]) })), { unit: "%", decimals: 1, stack: true, max: 100 }), [c]);
  if (!c?.parts.length && who === entity) return null;
  const chips = [...new Set([entity, ...keys])];
  return (
    <div className="card">
      <div className="card-head"><span className="small ink-2">Land cover seen from space{c?.first ? `, ${c.first} to ${c.last}` : ""}</span>
        <CardAsk onAsk={() => ask(`Land cover in ${c?.name ?? who}`, "Share of land by year", (c?.parts ?? []).map((p) => `${p.label}\t${p.points.map((x) => `${x[0]}:${x[1]}`).join(" ")}`).join("\n"))} /></div>
      <h3 className="finding">{c?.finding ?? "No land cover figures for this country yet"}</h3>
      <div className="chips-row small" role="group" aria-label="Country">
        {chips.map((e) => <button key={e} className={`chip-btn${who === e ? " on" : ""}`} aria-pressed={who === e} onClick={() => setWho(e)}>{e}</button>)}
      </div>
      {c?.parts.length ? <EChart option={opt} height={260} label="Land cover by year" /> : null}
      <p className="caption">Share of land and inland water in each kind of cover, from ESA&apos;s yearly 300 m satellite maps as FAOSTAT adds them up by
        country. Satellite classes differ from land use above (grazed tussock counts as grassland, young plantations as shrubs). The Map&apos;s Land cover
        picture shows the same at 10 m for 2020 and 2021.</p>
    </div>
  );
}
