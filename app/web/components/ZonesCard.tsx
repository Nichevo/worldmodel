"use client";

import Link from "next/link";
import type * as echarts from "echarts";
import { useCallback, useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import { api, type ZonesCountry } from "@/lib/api";
import { openAsk } from "@/lib/ai";
import { cssVar } from "@/lib/colors";
import { useSettings } from "@/lib/settings";

// A country's Köppen-Geiger climate zones over six 30-year periods (two of them ahead, on the
// emissions path chosen), the share of its city dwellers in each zone today, and each big
// city's rough climate twin: a city whose zone today is the one it is heading for.

export const PERIOD_OF: Record<string, string> = { 1916: "1901-1930", 1946: "1931-1960", 1976: "1961-1990", 2006: "1991-2020",
  2056: "2041-2070", 2085: "2071-2099" };
export const PATHS: { id: string; variant: string; label: string }[] = [
  { id: "ssp126", variant: "low", label: "Low emissions (SSP1-2.6)" },
  { id: "ssp245", variant: "central", label: "Middle (SSP2-4.5)" },
  { id: "ssp585", variant: "high", label: "Very high (SSP5-8.5)" },
];

export default function ZonesCard({ entity, name, showLink = true }: { entity: string; name: string; showLink?: boolean }) {
  const s = useSettings();
  const [path, setPath] = useState(s.zones_scenario || "ssp245");
  const [d, setD] = useState<ZonesCountry | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [full, setFull] = useState(false);
  useEffect(() => { setPath(s.zones_scenario || "ssp245"); }, [s.zones_scenario]);
  useEffect(() => {
    let live = true;
    api.climateZonesCountry(entity, path).then((r) => live && setD(r)).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [entity, path]);
  const variant = PATHS.find((p) => p.id === path)?.variant ?? "central";
  // Past periods are stored as central estimates; future ones under each path's variant.
  const years = Object.keys(PERIOD_OF).filter((y) => (+y < 2021 ? d?.groups.central?.[y] : d?.groups[variant]?.[y]));
  const at = (kind: "groups" | "zones", y: string) => (+y < 2021 ? d?.[kind].central?.[y] : d?.[kind][variant]?.[y]) ?? {};
  const chart = useCallback(() => {
    const groups = d?.legend.groups ?? [];
    const zones = d?.legend.zones ?? [];
    const list = full ? zones.map((z) => ({ key: z.code, name: `${z.code} ${z.name}`, colour: z.colour }))
      : groups.map((g) => ({ key: g.code, name: g.name, colour: g.colour }));
    return {
      tooltip: { trigger: "axis", valueFormatter: (v: unknown) => (typeof v === "number" ? `${v.toFixed(1)}%` : "") },
      legend: { type: "scroll", top: 0, textStyle: { color: cssVar("--ink-2") } },
      grid: { left: 44, right: 12, top: 34, bottom: 28 },
      xAxis: { type: "category", data: years.map((y) => `${PERIOD_OF[y]}${+y > 2020 ? " *" : ""}`), axisLabel: { color: cssVar("--ink-2") } },
      yAxis: { type: "value", max: 100, axisLabel: { formatter: "{value}%", color: cssVar("--ink-2") } },
      series: list.map((g) => ({ type: "bar", stack: "z", name: g.name, itemStyle: { color: g.colour },
        data: years.map((y) => {
          const v = at(full ? "zones" : "groups", y)[g.key] ?? 0;
          return { value: Math.round(v * 10) / 10, itemStyle: +y > 2020 ? { color: g.colour, opacity: 0.7 } : undefined };
        }) })).filter((sr) => sr.data.some((x) => x.value > 0)),
    } as echarts.EChartsOption;
  }, [d, full, variant, years.join()]); // eslint-disable-line react-hooks/exhaustive-deps
  if (error) return <div className="card"><h3>Climate zones</h3><p className="error">{error}</p></div>;
  if (!d) return null;
  if (!years.length) {
    return showLink ? null : (
      <div className="card"><h3>Climate zones</h3>
        <p className="small">No climate zones stored yet. They come with <code>.\refresh.bat</code> (one download of about 1 GB, read once; switch in <Link href="/settings#nature">Settings: Nature and pollution</Link>).</p></div>
    );
  }
  const zname = new Map(d.legend.zones.map((z) => [z.code, z.name]));
  const now = at("zones", "2006"), later = at("zones", "2085");
  const codes = [...new Set([...Object.keys(now), ...Object.keys(later)])].sort((a, b) => (later[b] ?? 0) + (now[b] ?? 0) - (later[a] ?? 0) - (now[a] ?? 0)).slice(0, 8);
  const ask = () => openAsk({ title: `${name}: climate zones`, entity, parts: [{ key: "data", kind: "data", label: "Land in each climate zone",
    text: codes.map((c) => `${c} ${zname.get(c)}: ${(now[c] ?? 0).toFixed(1)}% in 1991-2020, ${(later[c] ?? 0).toFixed(1)}% in 2071-2099 (${PATHS.find((p) => p.id === path)?.label})`).join("\n")
      + "\n\nCity twins:\n" + d.twins.map((t) => `${t.name}: ${t.now} now, ${t.later} by 2071-2099${t.twin ? `, like ${t.twin.name} today` : ""}`).join("\n") }] });
  return (
    <div className="card" id="zones-card">
      <div className="card-head"><h3>Climate zones</h3>
        <span><CardAsk onAsk={ask} />{showLink ? <> <Link className="small" href={`/climate?tab=zones&country=${entity}`}>Zones map</Link></> : null}</span></div>
      <div className="chips-row small">
        <div className="seg small" role="group" aria-label="Emissions path">{PATHS.map((p) =>
          <button key={p.id} className={path === p.id ? "on" : ""} aria-pressed={path === p.id} onClick={() => setPath(p.id)}>{p.label}</button>)}</div>
        <label><input type="checkbox" checked={full} onChange={(e) => setFull(e.target.checked)} /> All 30 zones</label>
      </div>
      <EChart option={chart} height={260} label={`${name} land by climate zone`} />
      <p className="caption">Share of the country&apos;s land in each Köppen-Geiger zone, by 30-year period. * Projected for the emissions path chosen (paler bars).
        Beck et al. 2023, 0.1° grids.</p>
      <div className="grid two">
        <div>
          <h4>Biggest zones, now and by 2071-2099</h4>
          <table className="small"><thead><tr><th>Zone</th><th className="num">1991-2020</th><th className="num">2071-2099</th></tr></thead>
            <tbody>{codes.map((c) => <tr key={c}><td><b>{c}</b> {zname.get(c)}</td><td className="num">{(now[c] ?? 0).toFixed(1)}%</td>
              <td className="num">{(later[c] ?? 0).toFixed(1)}%</td></tr>)}</tbody></table>
          {Object.keys(d.people).length ? <p className="small"><b>Where people live now:</b> {Object.entries(d.people).slice(0, 4).map(([c, v]) => `${c} ${zname.get(c) ?? ""} ${v}%`).join("; ")}.
            <span className="muted"> {d.people_note}</span></p> : null}
        </div>
        <div>
          <h4>City climate twins by 2071-2099</h4>
          {d.twins.length ? (
            <table className="small"><thead><tr><th>City</th><th>Now</th><th>Heading for</th><th>Like … today</th></tr></thead>
              <tbody>{d.twins.map((t) => <tr key={t.city_id}><td><Link href={`/city/${t.city_id}`}>{t.name}</Link></td><td title={zname.get(t.now ?? "")}>{t.now ?? "—"}</td>
                <td title={zname.get(t.later ?? "")}>{!t.later ? "—" : t.later === t.now ? "same" : t.later}</td>
                <td>{t.twin ? <Link href={`/city/${t.twin.city_id}`}>{t.twin.name} ({t.twin.country_id})</Link> : !t.later ? "" : t.later === t.now ? "stays in its zone" : "no big city in that zone"}</td></tr>)}</tbody></table>
          ) : <p className="small muted">Cities come with GeoNames during a refresh.</p>}
          <p className="caption">Rough twins: a city of 300,000 or more whose zone today is the one this city is heading for, at a similar distance from the equator.
            Only the zone is compared, not every measure of climate (Bastin et al. 2019 did that for 520 cities), so read it as a hint.</p>
        </div>
      </div>
    </div>
  );
}
